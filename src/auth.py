"""Clerk authentication for the API.

Auth is OPT-IN: it activates only when Clerk env is configured. With nothing set
— e.g. local dev — the dependency is a no-op and the app runs without login. In
production (Render) set CLERK_SECRET_KEY + CLERK_PUBLISHABLE_KEY (or CLERK_ISSUER)
and every /api route then requires a valid, signed Clerk session token.

Verification is done against Clerk's public JWKS (no secret needed to verify a
token's signature), so the frontend just sends `Authorization: Bearer <token>`
where the token is `window.Clerk.session.getToken()`.
"""
from __future__ import annotations

import base64
import os

from fastapi import HTTPException, Request

_jwks_client = None  # cached PyJWKClient (network fetch of Clerk's public keys)

# Which routes are public, which need which role, and which accept the browser
# extension's capture token instead of a session: all in access.POLICY and
# access.CAPTURE_ROUTES. The public ones and why:
# - /api/health: platform probes.
# - /api/postmark/events, /api/signals/inbound: Postmark webhooks (no Clerk session);
#   each authenticates itself with its shared-secret token in the URL.
# - /api/subscribe (+ confirm): a subscribe form behind a login is not a subscribe form.
# - /api/unsubscribe*, /api/preferences: reached from an email footer, so they carry no
#   session. The signed token IS the authentication: it names one address and nothing
#   else, and the handlers refuse outright when it fails to verify.
# - /api/asset/{h}: images inside sent mail, fetched by Gmail's proxy without a session.
# A capture token is validated HERE (capture_token_user) and acts as its owner; until
# 12 Oct 2026 the check was left to each endpoint, and POST /api/sources never made it,
# so any request carrying the header could write without signing in.


def _issuer() -> str | None:
    """The Clerk token issuer URL, from CLERK_ISSUER or derived from the publishable key.

    A Clerk publishable key is `pk_<env>_<base64(frontend_api_domain + '$')>`, and
    the session-token issuer is exactly `https://<frontend_api_domain>`.
    """
    iss = os.environ.get("CLERK_ISSUER")
    if iss:
        return iss.rstrip("/")
    pk = (os.environ.get("CLERK_PUBLISHABLE_KEY")
          or os.environ.get("VITE_CLERK_PUBLISHABLE_KEY")
          or os.environ.get("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY"))  # tolerate the Next.js name
    if pk and "_" in pk:
        try:
            b64 = pk.split("_", 2)[-1]
            domain = base64.b64decode(b64 + "===").decode().rstrip("$")
            if domain:
                return f"https://{domain}"
        except Exception:
            return None
    return None


def enabled() -> bool:
    """True when Clerk is configured; when False the API is open (local dev)."""
    return bool(os.environ.get("CLERK_SECRET_KEY") or _issuer())


_email_cache: dict[str, str] = {}  # clerk user id -> primary email (per process)
_name_cache: dict[str, str] = {}   # clerk user id -> display name (per process)


def _allowlist() -> tuple[set[str], set[str]]:
    """(allowed emails, allowed domains) from env. Empty => anyone signed in is allowed."""
    emails = {e.strip().lower() for e in os.environ.get("ALLOWED_EMAILS", "").split(",") if e.strip()}
    domains = {d.strip().lower().lstrip("@") for d in os.environ.get("ALLOWED_EMAIL_DOMAINS", "").split(",") if d.strip()}
    return emails, domains


def _user_email(sub: str) -> str:
    """The user's primary email, fetched from Clerk's API (cached). '' if unavailable."""
    if sub in _email_cache:
        return _email_cache[sub]
    key = os.environ.get("CLERK_SECRET_KEY")
    email = ""
    if key and sub:
        try:
            import httpx
            r = httpx.get(f"https://api.clerk.com/v1/users/{sub}",
                          headers={"Authorization": f"Bearer {key}"}, timeout=15)
            if r.status_code < 400:
                d = r.json()
                email = verified_email(d)
                _name_cache[sub] = " ".join(x for x in (d.get("first_name"), d.get("last_name")) if x)
        except Exception:
            email = ""
    if email:   # never cache a failed lookup: the next request should try again
        _email_cache[sub] = email
    return email


def verified_email(d: dict) -> str:
    """The Clerk user's primary email if Clerk has verified it, else another verified
    one, else ''. An unverified address proves nothing (anyone can type
    sid@knowella.com into a profile), and this address decides the allowlist and
    ADMIN_EMAILS."""
    addrs = [a for a in (d.get("email_addresses") or [])
             if isinstance(a, dict) and (a.get("verification") or {}).get("status") == "verified"]
    pid = d.get("primary_email_address_id")
    pick = next((a for a in addrs if a.get("id") == pid), addrs[0] if addrs else {})
    return (pick.get("email_address") or "").strip()


def _user_name(sub: str) -> str:
    _user_email(sub)            # fills the name cache on the same Clerk call
    return _name_cache.get(sub, "")


def _check_allowed(claims: dict) -> None:
    """Enforce the email/domain allowlist. No-op when no allowlist is configured."""
    emails, domains = _allowlist()
    if not emails and not domains:
        return  # open to any signed-in user (new accounts then start switched off)
    email = _user_email(claims.get("sub", "")).lower()
    dom = email.rsplit("@", 1)[-1] if "@" in email else ""
    if email in emails or (dom and dom in domains):
        return
    raise HTTPException(status_code=403, detail="this account is not authorized for this app")


def _jwks():
    global _jwks_client
    if _jwks_client is None:
        import jwt  # PyJWT[crypto]
        iss = _issuer()
        if not iss:
            raise RuntimeError("Clerk auth is enabled but no issuer/publishable key is configured")
        _jwks_client = jwt.PyJWKClient(f"{iss}/.well-known/jwks.json")
    return _jwks_client


def verify_token(token: str) -> dict:
    """Verify a Clerk session JWT's signature + issuer + expiry. Raises on failure.

    leeway: Clerk session tokens live ~60s; a few seconds of clock skew between this
    machine and Clerk otherwise causes intermittent 'token not yet valid / expired'.
    """
    import jwt
    signing_key = _jwks().get_signing_key_from_jwt(token).key
    return jwt.decode(
        token, signing_key, algorithms=["RS256"],
        issuer=_issuer(), options={"verify_aud": False}, leeway=15,
    )


def require_auth(request: Request):
    """FastAPI dependency applied to every route: who is this, and may they call it?

    Every route must have an entry in access.POLICY. A route without one is refused,
    so a new endpoint can't ship open by accident. Public routes pass straight through;
    everything else needs a signed-in, active user whose role the rule allows. The user
    is left on request.state.kn_user, where access.current_user() finds it.

    With Clerk unconfigured (local dev) the caller is a local admin, so the API stays
    fully open there, as it always was.

    Plain def on purpose: FastAPI runs it in the threadpool. A cache miss fetches
    Clerk's signing keys and the user's email over the network (blocking HTTP), and
    as an async def that stalled every request in flight while it waited."""
    from . import access
    if request.method == "OPTIONS":
        return None
    route = request.scope.get("route")
    path_t = getattr(route, "path", None)
    rule = access.rule_for(request.method, path_t)
    if rule is None:   # deny by default: this route was never given a rule
        raise HTTPException(status_code=403, detail="this endpoint has no access rule")
    if rule == access.PUBLIC:
        return None
    if not enabled():
        user = access.LOCAL_ADMIN
        claims = None
    elif (request.method, path_t) in access.CAPTURE_ROUTES and request.headers.get("x-capture-token"):
        # The browser extension: the token stands in for a session, acting as its owner.
        user = capture_token_user(request.headers["x-capture-token"])
        claims = None
    else:
        import logging
        log = logging.getLogger("uvicorn.error")
        path = request.url.path
        authz = request.headers.get("authorization") or ""
        if not authz.lower().startswith("bearer "):
            log.warning("[auth] 401 %s — no Authorization header (frontend sent no token; signed out or Clerk not loaded)", path)
            raise HTTPException(status_code=401, detail="missing bearer token")
        token = authz.split(" ", 1)[1].strip()
        try:
            claims = verify_token(token)
        except Exception as e:  # signature/expiry/issuer mismatch → unauthenticated
            log.warning("[auth] 401 %s — token rejected: %s", path, e)
            raise HTTPException(status_code=401, detail=f"invalid session: {e}")
        _check_allowed(claims)  # 403 if an allowlist is set and this user isn't on it
        user = resolve_user(claims.get("sub", ""))
    if not user.get("active", True):
        raise HTTPException(status_code=403, detail="this account isn't switched on — ask an admin (Team page)")
    if not access.allowed(rule, user):
        raise HTTPException(status_code=403, detail="your role doesn't have access to this")
    request.state.user = user.get("id")
    request.state.kn_user = user
    return claims


def resolve_user(sub: str) -> dict:
    """The app's user record for a Clerk user id, created on first sign-in.

    New users start as sales; anyone named in ADMIN_EMAILS is always an admin (so the
    admins can never be locked out by the Users screen). With no allowlist configured
    (ALLOWED_EMAILS / ALLOWED_EMAIL_DOMAINS), anyone able to sign up could get in, so new
    users then start switched off until an admin turns them on. Fails closed when the
    email can't be confirmed: an unknown address can't be checked against ADMIN_EMAILS."""
    from . import access
    from .store import open_store
    if not sub:
        raise HTTPException(status_code=401, detail="invalid session: no user id")
    store = open_store()
    u = store.get_user(sub)
    email = (u or {}).get("email") or _user_email(sub)
    if not email:
        raise HTTPException(status_code=503, detail="couldn't confirm your account email with Clerk — try again")
    email = email.strip().lower()
    admins = access.admin_emails()
    if u is None:
        allow_emails, allow_domains = _allowlist()
        gated = bool(allow_emails or allow_domains)
        u = store.ensure_user(sub, email, _user_name(sub), "admin" if email in admins else "sales",
                              active=gated or email in admins)
    if email in admins and u.get("role") != "admin":
        u = store.update_user(sub, {"role": "admin"})
    store.touch_user(sub)
    return {**u, "id": u["_id"], "pinned_admin": email in admins}


def capture_token_user(token: str) -> dict:
    """The user a browser-extension capture token acts as. 401 for an unknown token.
    Tokens made before tokens had owners act as an admin (only admins used the app)."""
    import hashlib
    import hmac
    from . import access
    from .store import open_store
    store = open_store()
    h = hashlib.sha256((token or "").encode()).hexdigest()
    t = store.find_capture_token(h)
    if t is None:
        legacy = store.get_setting("linkedin_capture_token_sha256")
        if legacy and hmac.compare_digest(h, legacy):
            return dict(access.LEGACY_TOKEN_USER)
        raise HTTPException(status_code=401, detail="invalid capture token — generate one in Settings and paste it into the extension")
    if not t.get("owner"):
        return dict(access.LEGACY_TOKEN_USER)
    u = store.get_user(t["owner"])
    if u is None:
        raise HTTPException(status_code=401, detail="this capture token's owner no longer exists")
    return {**u, "id": u["_id"]}
