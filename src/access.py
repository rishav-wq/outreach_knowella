"""Who may do what. One place, deny by default.

Every API route has an entry in POLICY, keyed by (method, path template). On every
request auth.require_auth looks the matched route up and refuses anything without an
entry (403 "this endpoint has no access rule"), so a new endpoint cannot ship open by
accident: until it is given a rule here, nobody can call it.

Route rules:
  PUBLIC  no sign-in: webhooks that carry their own secret, email-footer pages, images
          referenced by sent mail, the static frontend.
  ANY     any signed-in, active user.
  a role set, e.g. SALES = {admin, sales}.

On top of the route rule, campaign work is scoped by ownership (campaign_visible):
admins see every campaign, sales users see the campaigns they own, marketing users see
none. A campaign outside your scope answers 404, exactly like one that doesn't exist.

Roles (decision #3 in docs/knowcrm-requirements-audit.md): admin, sales, marketing.
Admins are named in the ADMIN_EMAILS environment variable and can also be promoted from
the Users screen. Everyone else who signs in starts as sales.
"""
from __future__ import annotations

import contextvars
import os

ROLES = ("admin", "sales", "marketing")

PUBLIC = "public"
ANY = "any"
ADMIN = frozenset({"admin"})
SALES = frozenset({"admin", "sales"})
MKT = frozenset({"admin", "marketing"})
STAFF = frozenset(ROLES)

# The ASGI scope of the HTTP request being served, set by ScopeMiddleware. FastAPI runs a
# request's sync code on worker threads that inherit it. The app's own background threads
# (pipeline runs, blast sends) don't, so they run as trusted internal code.
_SCOPE: contextvars.ContextVar = contextvars.ContextVar("kn_scope", default=None)

# Used when Clerk isn't configured (local dev): the API stays fully open, as it always was.
LOCAL_ADMIN = {"_id": "local", "id": "local", "email": "local@localhost", "name": "Local dev",
               "role": "admin", "active": True}
# Capture tokens issued before tokens had owners. Only admins used the app then.
LEGACY_TOKEN_USER = {"_id": "legacy-capture-token", "id": "legacy-capture-token",
                     "email": "", "name": "Capture token (issued before per-user tokens)",
                     "role": "admin", "active": True}


class ScopeMiddleware:
    """Pure ASGI: remembers the current request's scope so code with no Request in hand
    (api._load and friends) can ask who is signed in."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        token = _SCOPE.set(scope)
        try:
            await self.app(scope, receive, send)
        finally:
            _SCOPE.reset(token)


def in_request() -> bool:
    return _SCOPE.get() is not None


def current_user() -> dict | None:
    """The signed-in user of the request being served, or None for internal code
    (a background thread or the CLI), which is trusted."""
    sc = _SCOPE.get()
    if sc is None:
        return None
    return (sc.get("state") or {}).get("kn_user")


def require_user() -> dict:
    """The signed-in user. Inside a request there is always one (require_auth sets it);
    internal code calling this is a bug, so it fails closed."""
    u = current_user()
    if u is None:
        from fastapi import HTTPException
        raise HTTPException(401, "not signed in")
    return u


def admin_emails() -> set[str]:
    return {e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()}


def is_admin(user: dict | None) -> bool:
    return bool(user) and user.get("role") == "admin"


def allowed(rule, user: dict | None) -> bool:
    if rule == PUBLIC:
        return True
    if not user or not user.get("active", True):
        return False
    if rule == ANY:
        return True
    return user.get("role") in rule


def campaign_visible(user: dict | None, owner: str | None) -> bool:
    """May this user work in a campaign owned by `owner`? None user = internal code."""
    if user is None:
        return True
    role = user.get("role")
    if role == "admin":
        return True
    if role == "sales":
        return bool(owner) and owner == user.get("id")
    return False


# --- the route table ------------------------------------------------------------------
# Routes the browser extension calls with an X-Capture-Token instead of a session.
CAPTURE_ROUTES = {("GET", "/api/linkedin/campaigns"), ("POST", "/api/linkedin/capture"),
                  ("GET", "/api/sources"), ("POST", "/api/sources")}

POLICY: dict[tuple[str, str], object] = {
    # public: no session possible or needed
    ("GET", "/api/health"): PUBLIC,
    ("POST", "/api/subscribe"): PUBLIC,
    ("GET", "/api/subscribe/confirm"): PUBLIC,
    ("GET", "/api/unsubscribe"): PUBLIC,
    ("POST", "/api/unsubscribe/confirm"): PUBLIC,
    ("POST", "/api/unsubscribe"): PUBLIC,
    ("GET", "/api/preferences"): PUBLIC,
    ("POST", "/api/preferences"): PUBLIC,
    ("POST", "/api/postmark/events"): PUBLIC,        # checks POSTMARK_WEBHOOK_TOKEN itself
    ("POST", "/api/signals/inbound"): PUBLIC,        # checks SIGNALS_WEBHOOK_TOKEN itself
    ("GET", "/api/asset/{h}"): PUBLIC,               # images inside sent email
    ("GET", "/{full_path:path}"): PUBLIC,            # the static frontend

    # who am I, and the things every signed-in person has
    ("GET", "/api/me"): ANY,
    ("GET", "/api/campaigns"): ANY,                  # filtered to what you may see
    ("GET", "/api/suppression"): ANY,
    ("POST", "/api/suppression"): ANY,               # adding a do-not-contact is always safe
    ("POST", "/api/suppression/remove"): ADMIN,
    ("GET", "/api/capture_token"): ANY,              # your own tokens (admins: all)
    ("POST", "/api/capture_token"): ANY,
    ("DELETE", "/api/capture_token/{tid}"): ANY,     # your own (admins: any)
    ("DELETE", "/api/capture_token"): ADMIN,         # the old shared token

    # users (admin)
    ("GET", "/api/users"): ADMIN,
    ("PATCH", "/api/users/{uid}"): ADMIN,
    ("GET", "/api/campaigns/owners"): ADMIN,         # who owns which campaign
    ("POST", "/api/campaign/owner"): ADMIN,          # give a campaign to someone

    # training: everyone can read the playbook and save their own progress
    ("GET", "/api/training/page"): ANY,
    ("PUT", "/api/training/state/{key}"): ANY,
    ("POST", "/api/training/content"): ADMIN,        # upload a new playbook version
    ("GET", "/api/training/content"): ADMIN,
    ("GET", "/api/training/team"): ADMIN,            # everyone's ramp
    ("GET", "/api/training/team/{uid}/events"): ADMIN,
    ("PUT", "/api/training/signoff"): ADMIN,         # manager sign-off checklist items
    # the Target board: everyone sees it; sales and admins work it
    ("GET", "/api/segments"): ANY,
    ("GET", "/api/segments/{sid}"): ANY,
    ("PUT", "/api/segments/{sid}"): SALES,

    # all leads and companies (src/crm_api.py; scoped per person and company inside)
    ("GET", "/api/crm/meta"): SALES,
    ("GET", "/api/people"): SALES,
    ("POST", "/api/people"): SALES,
    ("GET", "/api/people/{pid}"): SALES,
    ("PATCH", "/api/people/{pid}"): SALES,
    ("DELETE", "/api/people/{pid}"): SALES,
    ("POST", "/api/people/{pid}/notes"): SALES,
    ("POST", "/api/people/enroll"): SALES,
    ("PATCH", "/api/notes/{aid}"): SALES,
    ("DELETE", "/api/notes/{aid}"): SALES,
    ("GET", "/api/companies"): SALES,
    ("GET", "/api/companies/{cid}"): SALES,
    ("PATCH", "/api/companies/{cid}"): SALES,
    ("POST", "/api/companies/{cid}/notes"): SALES,
    ("GET", "/api/replies/sync"): ADMIN,             # the Apollo reply sync: status
    ("POST", "/api/replies/sync"): ADMIN,            # ...and a run now (Apollo calls)
    ("GET", "/api/customers"): SALES,                # existing customers: everyone in sales sees the list
    ("POST", "/api/customers"): ADMIN,
    ("DELETE", "/api/customers/{domain}"): ADMIN,

    # sales: campaigns (ownership is checked per campaign)
    ("POST", "/api/campaigns"): SALES,
    ("GET", "/api/campaign/config"): SALES,
    ("POST", "/api/campaign/rename"): SALES,
    ("POST", "/api/campaign/update"): SALES,
    ("POST", "/api/campaign/delete"): SALES,
    ("POST", "/api/campaign/lookalike"): SALES,
    ("POST", "/api/campaign/mailbox"): ADMIN,        # which mailbox a campaign sends from
    ("GET", "/api/health/sending"): SALES,
    ("GET", "/api/mailboxes"): SALES,
    ("GET", "/api/sequences"): SALES,
    ("POST", "/api/sequences/create"): ADMIN,
    ("GET", "/api/status"): SALES,
    ("GET", "/api/leads"): SALES,
    ("GET", "/api/board"): SALES,
    ("GET", "/api/lead"): SALES,
    ("GET", "/api/review"): SALES,
    ("GET", "/api/inbox"): SALES,
    ("GET", "/api/inbox/thread"): SALES,
    ("GET", "/api/analytics"): SALES,
    ("GET", "/api/ab"): SALES,
    ("POST", "/api/lead/meeting"): SALES,
    ("POST", "/api/lead/email"): SALES,
    ("POST", "/api/review/decision"): SALES,
    ("POST", "/api/review/approve_all"): SALES,
    ("POST", "/api/review/exclude"): SALES,
    ("POST", "/api/review/edit"): SALES,
    ("POST", "/api/review/edit_followup"): SALES,
    ("POST", "/api/review/refine"): SALES,
    ("POST", "/api/leads/exclude"): SALES,
    ("POST", "/api/leads/delete"): SALES,
    ("GET", "/api/leads/all"): SALES,                # filtered to your campaigns
    ("POST", "/api/library/promote"): SALES,
    ("POST", "/api/pull"): SALES,                    # CSV import, no credits
    ("POST", "/api/pull/apollo"): SALES,             # spends Apollo credits: sales within a daily allowance
    ("GET", "/api/pull/allowance"): SALES,           # what you have left today (admins: the team's usage)
    ("PUT", "/api/pull/allowance"): ADMIN,           # set the sales allowance
    ("POST", "/api/preview/apollo"): SALES,          # free count
    ("GET", "/api/apollo/schools"): SALES,
    ("POST", "/api/run"): SALES,
    ("GET", "/api/run/status"): SALES,
    ("GET", "/api/routing"): SALES,
    ("GET", "/api/linkedin/campaigns"): SALES,
    ("POST", "/api/linkedin/capture"): ADMIN,        # matches people in Apollo: spends credits

    # signals, sources, backlog: shared inboxes
    ("GET", "/api/signals"): STAFF,
    ("POST", "/api/signals"): STAFF,
    ("POST", "/api/signals/{sid}/status"): STAFF,
    ("DELETE", "/api/signals/{sid}"): ADMIN,
    ("POST", "/api/signals/clear"): ADMIN,
    ("POST", "/api/signals/poll"): STAFF,
    ("POST", "/api/signals/import-ita"): ADMIN,
    ("POST", "/api/signals/{sid}/resolve"): SALES,   # free lookup
    ("POST", "/api/signals/{sid}/promote"): ADMIN,   # spends Apollo credits
    ("GET", "/api/sources"): STAFF,
    ("POST", "/api/sources"): STAFF,
    ("PUT", "/api/sources/{sid}/notes"): STAFF,
    ("DELETE", "/api/sources/{sid}"): ADMIN,
    ("GET", "/api/backlog"): STAFF,
    ("POST", "/api/backlog"): STAFF,
    ("POST", "/api/backlog/{bid}/status"): STAFF,
    ("DELETE", "/api/backlog/{bid}"): MKT,

    # marketing
    ("GET", "/api/subscribers"): MKT,
    ("GET", "/api/audiences"): MKT,
    ("POST", "/api/audiences"): MKT,
    ("DELETE", "/api/audiences/{aid}"): MKT,
    ("GET", "/api/marketing/status"): MKT,
    ("POST", "/api/marketing/test"): MKT,
    ("GET", "/api/marketing/meta"): MKT,
    ("GET", "/api/marketing/template"): MKT,
    ("PUT", "/api/marketing/template"): MKT,
    ("POST", "/api/marketing/preview"): MKT,
    ("POST", "/api/blasts/format"): MKT,
    ("POST", "/api/blasts/host-images"): MKT,
    ("POST", "/api/blasts/render"): MKT,
    ("POST", "/api/blasts/generate"): MKT,
    ("POST", "/api/blasts/questions"): MKT,
    ("POST", "/api/assets/upload"): MKT,
    ("GET", "/api/assets"): MKT,
    ("GET", "/api/publications"): MKT,
    ("POST", "/api/publications"): MKT,
    ("PUT", "/api/publications/{pid}"): MKT,
    ("DELETE", "/api/publications/{pid}"): MKT,
    ("GET", "/api/blasts"): MKT,
    ("POST", "/api/blasts"): MKT,
    ("GET", "/api/blasts/{bid}"): MKT,
    ("PUT", "/api/blasts/{bid}"): MKT,
    ("DELETE", "/api/blasts/{bid}"): MKT,
    ("POST", "/api/blasts/{bid}/test"): MKT,
    ("POST", "/api/blasts/{bid}/send"): MKT,
}


def rule_for(method: str, path_template: str | None):
    """The rule for a matched route, or None when the route has no entry (deny)."""
    if not path_template:
        return None
    m = "GET" if method == "HEAD" else method
    return POLICY.get((m, path_template))
