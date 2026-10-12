"""The BDR training playbook inside the app, and the Target board's shared table.

Design (docs/bdr-playbook-crm-plan.md §3, docs/knowcrm-requirements-audit.md §11.2):

- The playbook is a single HTML file written by Sid. An admin uploads it (Team page);
  versions live in `training_content`. It never touches git: the repo is public and the
  file holds pricing, contract terms and scripts.
- The browser shows it in a SANDBOXED iframe (no allow-same-origin), so the file's own
  script can't reach the app or the user's session.
- At serve time the file's `localStorage.` calls are swapped for `KNStore.`, an in-page
  store pre-filled with this user's saved state. Each save is posted to the parent page,
  which writes it to `training_state` with a version check.
- The file's Target board expects claude.ai's shared-data API (window.claude). We inject a
  stand-in that relays reads and writes to the parent, and the server applies the claim
  rules atomically. Without it the board would silently become private per user.
"""
from __future__ import annotations

import hashlib
import html as _html
import json
import re
from datetime import datetime, timezone

MAX_HTML_BYTES = 5 * 1024 * 1024
MAX_VALUE_BYTES = 256 * 1024
MAX_EVENTS_PER_SAVE = 100                 # a real save changes a handful of things
BOARD_KEY = "knowella_board_v1"          # the board's browser fallback; never stored per user
ORG = "knowella"                          # every record carries its org (multi-org later)

_KEY_RE = re.compile(r'"(knowella_[a-z0-9_]+)"')
_STORAGE_RE = re.compile(r"localStorage")
_STORAGE_OK_RE = re.compile(r"localStorage\.(?:getItem|setItem)\(")
_MODULE_RE = re.compile(r'<article class="page" id="((?:found|craft|safety|ops|scl)-m\d+)"')
_MODULE_TITLE_RE = re.compile(r'<article class="page" id="((?:found|craft|safety|ops|scl)-m\d+)" data-title="([^"]*)"')
_SIGNOFF_RE = re.compile(r'\{id:"([a-z0-9_]+)",t:"Manager sign-off')
_SIGNOFF_LABEL_RE = re.compile(r'\{id:"([a-z0-9_]+)",t:"Manager sign-off: ([^"]*)"')
_TRACK_RE = re.compile(r'\{id:"([a-z]+)",name:"([^"]+)",color:')
_CERT_BLOCK_RE = re.compile(r"var CERT=\[(.*?)\];", re.S)
_CERT_ITEM_RE = re.compile(r'\{id:"([a-z0-9_]+)",t:"([^"]*)"')
_HEAD_RE = re.compile(r"<head[^>]*>", re.I)

# Small, exact edits made to the file at serve time. Each one applies only where its
# text is found exactly once; a reworded file just keeps its own text (the page still
# works), and the upload result lists any edit that didn't apply.
TEXT_SWAPS = [
    # Lines that stop being true once progress is saved to the account (must-fix #10).
    ("progress-banner", "<b>Progress saves in this browser</b>", "<b>Progress saves to your account</b>"),
    ("progress-faq",
     "In your browser on this device: modules completed, live quiz scores, schedule checkmarks, "
     "activity log, Industry and Persona choices. Use the same browser each day.",
     "In your Outreach account: modules completed, live quiz scores, schedule checkmarks, "
     "activity log, Industry and Persona choices. It follows you to any browser or device."),
    ("self-rating", "Rate yourself (private, saves in this browser)",
     "Rate yourself (private, saves to your account)"),
    # The Target board's failure messages assume a browser-only fallback. Here a refused
    # write is followed by a fresh board from the server, and the board key is never
    # stored per user, so say what actually happened. (Inside JS strings: no quotes.)
    ("board-toast",
     """knToast("Couldn't save to the shared board ("+(e&&e.code||"error")+"). Saved in this browser only.");""",
     """knToast("Not saved: "+(e&&e.code||"the shared board did not answer")+". The board now shows the latest.");"""),
    ("board-banner",
     """'<span class="warn">Saved in this browser only.</span> Shared tracking works on the published playbook """
     """link when your team has Contributor access. In your CRM, a developer connects it to a shared table.'""",
     """'<span class="warn">Connecting to the shared board.</span> If this message stays, reload the page. """
     """Changes made before it connects are not saved.'"""),
    # Manager sign-off items are ticked by the manager on the Team page. Lock their
    # checkboxes here and say so, rather than letting a tick vanish on the next load.
    ("signoff-lock",
     """+(c.auto?"disabled ":"")+'data-c="'+c.id+'"><span>'+c.t+(c.auto?' <span class="pill">auto</span>':'')+'</span></label>';""",
     """+((c.auto||window.KN_LOCKED(c.id))?"disabled ":"")+'data-c="'+c.id+'"><span>'+c.t+(c.auto?' <span class="pill">auto</span>':(window.KN_LOCKED(c.id)?' <span class="pill">your manager ticks this</span>':''))+'</span></label>';"""),
]


class PlaybookError(ValueError):
    """An uploaded file we can't serve safely. The message is shown to the admin."""


def inspect_html(html: str) -> dict:
    """Validate an uploaded playbook and describe it. Raises PlaybookError.

    The serve-time swap is only exact if every storage use is a plain getItem/setItem
    call: anything else (a bare `localStorage`, removeItem, iteration) would either reach
    the sandbox's real storage, which throws, or silently not save."""
    if not html or len(html.encode("utf-8")) > MAX_HTML_BYTES:
        raise PlaybookError("the file is empty or bigger than 5 MB")
    if not re.search(r"<html", html, re.I) or not _HEAD_RE.search(html):
        raise PlaybookError("this doesn't look like the playbook HTML file (no <html> and <head>)")
    total = len(_STORAGE_RE.findall(html))
    plain = len(_STORAGE_OK_RE.findall(html))
    if total != plain:
        raise PlaybookError(f"the file uses browser storage in {total - plain} way(s) other than "
                            "getItem/setItem, so progress saving can't be wired safely")
    keys = sorted(set(_KEY_RE.findall(html)))
    if not keys:
        raise PlaybookError("no saved-progress keys (\"knowella_…\") found: is this the playbook?")
    modules = sorted(set(_MODULE_RE.findall(html)))
    return {"keys": keys, "state_keys": [k for k in keys if k != BOARD_KEY],
            "modules": modules, "signoff_ids": sorted(set(_SIGNOFF_RE.findall(html))),
            "has_board": BOARD_KEY in keys and "window.claude" in html,
            "storage_calls": plain, "sha256": hashlib.sha256(html.encode("utf-8")).hexdigest(),
            "bytes": len(html.encode("utf-8")),
            "swaps_missing": [name for name, old, _ in TEXT_SWAPS if html.count(old) != 1],
            # Labels for the manager's view, read from the file so none of its content
            # lives in this (public) repo. Missing ones fall back to the ids.
            "module_titles": {m: _html.unescape(t) for m, t in _MODULE_TITLE_RE.findall(html)},
            "signoff_labels": {k: _html.unescape(t) for k, t in _SIGNOFF_LABEL_RE.findall(html)},
            "tracks": [{"id": k, "name": _html.unescape(n)} for k, n in _TRACK_RE.findall(html)],
            "cert_labels": _cert_labels(html)}


def _cert_labels(html: str) -> dict:
    m = _CERT_BLOCK_RE.search(html)
    return {k: _html.unescape(t) for k, t in _CERT_ITEM_RE.findall(m.group(1))} if m else {}


def _js_literal(obj) -> str:
    """JSON safe to drop inside a <script> element: no </script>, no <!--, no HTML."""
    return (json.dumps(obj, ensure_ascii=True)
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))


# Content-Security-Policy for the frame. The file only needs its inline script and style,
# Google Fonts, and its inline data: logo. No network calls of any kind.
CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline' "
       "https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src data:; "
       "connect-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none'")

# Runs first in the frame. Everything it says to the app goes over a private
# MessageChannel port, which the app hands over once, when this document has loaded. A
# page the frame might later navigate to never gets the port, so it can't save progress
# or touch the board as this person, and the app never posts to an unknown window.
_BOOT = r"""<meta http-equiv="Content-Security-Policy" content="__CSP__">
<script>
(function () {
  "use strict";
  var STATE = __KN_STATE__;          // this user's saved values, by key
  var ME = __KN_ME__;                // {id, name}
  var LOCKED = __KN_LOCKED__;        // manager sign-off item ids
  window.KN_LOCKED = function (id) { return LOCKED.indexOf(id) >= 0; };
  var port = null, outbox = [];      // messages wait here until the app's port arrives
  function post(msg) { if (port) port.postMessage(msg); else outbox.push(msg); }
  // The playbook's saved progress, backed by the account instead of the browser.
  window.KNStore = {
    getItem: function (k) { return Object.prototype.hasOwnProperty.call(STATE, k) ? STATE[k] : null; },
    setItem: function (k, v) { v = String(v); STATE[k] = v; post({ kn: "save", key: k, value: v }); }
  };
  // RPC to the parent page for the shared Target board.
  var seq = 0, waiting = {}, listeners = [], last = { docs: {}, names: {} };
  function call(method, args) {
    return new Promise(function (resolve, reject) {
      var id = ++seq; waiting[id] = { resolve: resolve, reject: reject };
      post({ kn: "rpc", id: id, method: method, args: args || {} });
      setTimeout(function () {
        if (waiting[id]) { delete waiting[id]; var e = new Error("timed out"); e.code = "timeout"; reject(e); }
      }, 20000);
    });
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function snapshotOf(docs) {
    return { docs: Object.keys(docs).map(function (id) {
      var d = docs[id]; return { id: id, exists: true, data: function () { return JSON.parse(JSON.stringify(d)); } };
    }) };
  }
  function onPort(ev) {
    var m = ev.data || {};
    if (m.kn === "rpc-result" && waiting[m.id]) {
      var w = waiting[m.id]; delete waiting[m.id];
      if (m.ok) w.resolve(m.result);
      else { var e = new Error(m.error || "failed"); e.code = m.code || "error"; w.reject(e); }
    } else if (m.kn === "board-snapshot") {
      last = { docs: m.docs || {}, names: m.names || {} };
      listeners.forEach(function (cb) { try { cb(snapshotOf(last.docs)); } catch (e) {} });
    }
  }
  window.addEventListener("message", function onInit(ev) {
    var m = ev.data || {};
    if (port || ev.source !== window.parent || m.kn !== "init" || !ev.ports || !ev.ports[0]) return;
    port = ev.ports[0];
    port.onmessage = onPort;
    window.removeEventListener("message", onInit);
    outbox.splice(0).forEach(function (msg) { port.postMessage(msg); });
  });
  var userApi = {
    id: function () { return Promise.resolve(ME.id); },
    // Names go into the page as HTML (innerHTML), so they're escaped here.
    profiles: function (ids) {
      var out = {};
      (ids || []).forEach(function (i) { out[i] = { name: esc(last.names[i] || "A teammate") }; });
      return Promise.resolve(out);
    }
  };
  var dbApi = {
    collection: function (name) {
      if (name !== "board") throw new Error("unknown collection");
      return {
        doc: function (id) {
          return {
            get: function () {
              return call("board.get", { id: id }).then(function (d) {
                return { exists: !!d, data: function () { return d ? JSON.parse(JSON.stringify(d)) : undefined; } };
              });
            },
            set: function (next) { return call("board.set", { id: id, next: next }); }
          };
        },
        onSnapshot: function (cb, onErr) {
          listeners.push(cb);
          call("board.subscribe", {}).catch(function (e) { if (onErr) onErr(e); });
          return function () { listeners = listeners.filter(function (x) { return x !== cb; }); };
        }
      };
    }
  };
  window.claude = { use: function (what) {
    if (what === "user") return Promise.resolve(userApi);
    if (what === "db") return Promise.resolve(dbApi);
    return Promise.reject(new Error("not available here"));
  } };
})();
</script>"""


def adapt(html: str, state: dict, me: dict, locked: list[str] | None = None) -> str:
    """The uploaded file, made to run inside the app's sandboxed frame for this user.
    The file itself is never changed in storage; this runs on every serve."""
    fill = {"__CSP__": CSP, "__KN_STATE__": _js_literal(state),
            "__KN_ME__": _js_literal({"id": me.get("id", ""), "name": me.get("name", "")}),
            "__KN_LOCKED__": _js_literal(list(locked or []))}
    # One pass: a saved value that happens to contain "__KN_ME__" stays text.
    boot = re.sub(r"__CSP__|__KN_STATE__|__KN_ME__|__KN_LOCKED__", lambda m: fill[m.group(0)], _BOOT)
    out = _STORAGE_RE.sub("KNStore", html)        # every use is .getItem(/.setItem( (checked on upload)
    for _, old, new in TEXT_SWAPS:
        if out.count(old) == 1:
            out = out.replace(old, new)
    m = _HEAD_RE.search(out)
    return out[:m.end()] + boot + out[m.end():]


# --- saved progress --------------------------------------------------------------------
def training_events(old_raw: str | None, new_raw: str) -> list[dict]:
    """What changed in the main progress key, as events for the manager's timeline:
    modules newly done or undone, new live quiz attempts, checklist changes. Dates come
    from the server, because the file records none for modules."""
    def parse(raw):
        try:
            d = json.loads(raw) if raw else {}
            return d if isinstance(d, dict) else {}
        except (ValueError, TypeError):
            return {}
    a, b = parse(old_raw), parse(new_raw)
    ev = []
    da, db = a.get("done") or {}, b.get("done") or {}
    for m in sorted(set(db) - {k for k, v in da.items() if v}):
        if db.get(m):
            ev.append({"type": "module_done", "ref": m})
    for m in sorted(k for k, v in da.items() if v and not db.get(k)):
        ev.append({"type": "module_undone", "ref": m})
    qa, qb = a.get("qhist") or {}, b.get("qhist") or {}
    for q, hist in qb.items():
        for att in (hist or [])[len(qa.get(q) or []):]:
            ev.append({"type": "quiz_attempt", "ref": q, "score": (att or {}).get("s")})
    ca, cb = a.get("cert") or {}, b.get("cert") or {}
    for k in sorted(set(ca) | set(cb)):
        if bool(ca.get(k)) != bool(cb.get(k)):
            ev.append({"type": "cert", "ref": k, "value": bool(cb.get(k))})
    return ev


def is_progress_object(raw: str) -> bool:
    """True when the value parses as a JSON object, as the playbook's own save always
    does. Anything else (including numbers too long for Python's parser) is refused,
    since sign-off protection can only work on what it can read."""
    try:
        return isinstance(json.loads(raw), dict)
    except (ValueError, TypeError, RecursionError):
        return False


def clean_note(note: str) -> str:
    """A board note as plain text: no angle brackets or double quotes. v3 escapes notes
    itself, but they reach every teammate's frame, so the server keeps them inert in
    case a later version of the file doesn't."""
    return str(note).replace("<", "‹").replace(">", "›").replace('"', "”")[:NOTE_MAX]


def apply_signoffs(raw: str | None, signoffs: dict, signoff_ids: list[str]) -> str | None:
    """The progress value with its manager sign-off items set from `signoffs` (the
    training_signoffs collection), the only place they come from: a person's own save
    can't tick them, and a manager's tick shows on their next page load. Anything
    unparseable is left alone (the file wrote it; its next good save gets fixed)."""
    if not signoff_ids:
        return raw
    if not raw:
        if not any(signoffs.get(k) for k in signoff_ids):
            return raw
        new: dict = {}            # the page fills in the rest of its state from defaults
    else:
        try:
            new = json.loads(raw)
        except (ValueError, TypeError):
            return raw
        if not isinstance(new, dict):
            return raw
    cert = dict(new["cert"]) if isinstance(new.get("cert"), dict) else {}
    for k in signoff_ids:
        if signoffs.get(k):
            cert[k] = True
        else:
            cert.pop(k, None)
    new["cert"] = cert
    return json.dumps(new, separators=(",", ":"))


# --- the Target board ------------------------------------------------------------------
SEGMENT_ID_RE = re.compile(r"^[a-z0-9]{1,24}__[a-z0-9]{1,32}$")
STATUSES = ("grey", "yellow", "green", "red")
NOTE_MAX = 300


class BoardRefused(Exception):
    """A board change the rules don't allow. `code` reaches the page's error toast."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def plan_change(cur: dict | None, nxt: dict, user: dict) -> dict:
    """Decide what a board write means and whether this user may make it.

    The page sends the whole next state; the server works out the action from the
    difference and applies the rules (audit §11.2). Returns {"action", "set", "unset",
    "expect"}: `expect` is the state the write is conditional on, so two people acting
    at once can't both succeed. Raises BoardRefused."""
    cur = cur or {}
    uid = user.get("id")
    admin = user.get("role") == "admin"
    cs = cur.get("status") or "grey"
    owner = cur.get("owner") or ""
    mine = bool(owner) and owner == uid
    ns = nxt.get("status") or "grey"
    if ns not in STATUSES:
        raise BoardRefused("bad-status", "unknown status")
    note = clean_note(nxt.get("note") if nxt.get("note") is not None else (cur.get("note") or ""))
    try:
        mt_new, mt_old = int(nxt.get("mtgs") or 0), int(cur.get("mtgs") or 0)
    except (TypeError, ValueError):
        raise BoardRefused("bad-meetings", "meetings must be a number")
    expect = {"status": cur.get("status"), "owner": cur.get("owner")}
    s: dict = {"at": today()}
    unset: dict = {}

    if ns == "yellow" and cs != "yellow":
        if cs == "green" and not (mine or admin):
            raise BoardRefused("not-owner", "only the person working it can move it back")
        s.update({"status": "yellow", "owner": uid, "owner_email": user.get("email", ""),
                  "claimed_at": today()})
        return {"action": "claim" if cs != "green" else "resume", "set": s, "unset": unset, "expect": expect}
    if ns == "yellow" and cs == "yellow" and not mine:
        # The page sends the owner it expects. A different one means its claim lost a
        # race (or its view is stale): refuse, admins too, so nobody believes they hold
        # a pair they don't.
        if owner and (not admin or (nxt.get("owner") and nxt.get("owner") != owner)):
            raise BoardRefused("already-claimed", "someone else claimed it first")
    if ns == "grey" and cs != "grey":
        if cs == "red":
            action = "reopen"                      # anyone, with a new trigger
        elif mine or admin:
            action = "release"
        else:
            raise BoardRefused("not-owner", "only the person working it or an admin can release it")
        unset = {"owner": "", "owner_email": "", "claimed_at": ""}
        s.update({"status": "grey"})
        return {"action": action, "set": s, "unset": unset, "expect": expect}
    if ns in ("green", "red") and ns != cs:
        if not (mine or admin):
            raise BoardRefused("not-owner", "only the person working it or an admin can change it")
        s["status"] = ns
        return {"action": "productive" if ns == "green" else "exhausted", "set": s, "unset": unset, "expect": expect}
    # same status: a meeting logged and/or a note edited
    changes = []
    if mt_new != mt_old:
        if not (mine or admin):
            raise BoardRefused("not-owner", "only the person working it can log meetings")
        if mt_new != mt_old + 1 and not admin:
            raise BoardRefused("bad-meetings", "meetings go up one at a time")
        if mt_new < 0:
            raise BoardRefused("bad-meetings", "meetings can't go below zero")
        s["mtgs"] = mt_new
        changes.append("meeting")
    if note != (cur.get("note") or ""):
        if owner and not (mine or admin):
            raise BoardRefused("not-owner", "only the person working it can edit its note")
        s["note"] = note
        changes.append("note")
    if not changes:
        return {"action": "none", "set": {}, "unset": {}, "expect": expect}
    return {"action": "+".join(changes), "set": s, "unset": unset, "expect": expect}


def public_segment(d: dict) -> dict:
    """The shape the playbook's board reads: {status, owner, mtgs, note, at}."""
    out = {"status": d.get("status") or "grey"}
    for k in ("owner", "mtgs", "note", "at"):
        if d.get(k) not in (None, ""):
            out[k] = d[k]
    return out
