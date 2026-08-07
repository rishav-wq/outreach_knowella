"""Signals — the monitoring inbox.

Nothing here is scraped. Every signal arrives because a platform *pushed* it to us,
through one of two channels:

  email  Postmark inbound. Forward the notification mail LinkedIn / G2 / Capterra /
         Trustpilot / Google Alerts already send us, and it lands here as a named
         person who did something. This is the only automatic PERSON-level signal
         available, and it only fires where we have a presence — our page, our
         posts, our listing. See docs/monitoring-sources.md.
  rss    Publisher feeds, polled. A Google Alert set to "Deliver to → RSS feed"
         becomes a pollable URL too. TOPIC-level: tells you the subject is live,
         not that a person asked something.

House rule: a signal we cannot parse is still a signal. Unrecognised mail is filed
under its subject line rather than dropped, so a changed notification format costs
us the labelling and never the lead.
"""
from __future__ import annotations

import hashlib
import html
import re
import time
from datetime import datetime, timezone
from functools import lru_cache

import httpx

POLL_SECONDS = 30 * 60          # feeds are hourly-ish news; twice an hour is plenty
_MAX_TEXT = 1200                # keep enough to judge a signal, not the whole email


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _strip_html(s: str) -> str:
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s or "")
    s = re.sub(r"(?i)<br\s*/?>|</p>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"[ \t]+", " ", s).strip()


def _clip(s: str, n: int = _MAX_TEXT) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[:n].rstrip() + "…"


def dedupe_key(platform: str, url: str, title: str, person: str = "") -> str:
    """Stable identity for a signal. URL when we have one (the same LinkedIn post
    notified twice is one signal); otherwise the person+subject pair."""
    basis = (url or "").split("?")[0].strip().lower() or f"{person}|{title}".lower()
    return hashlib.sha1(f"{platform}|{basis}".encode()).hexdigest()[:16]


# --- inbound notification email ----------------------------------------------

# Match on the sending domain, not the display name — display names get localised.
_SENDERS = (
    ("linkedin", ("linkedin.com",)),
    ("g2", ("g2.com", "g2crowd.com")),
    ("capterra", ("capterra.com", "softwareadvice.com", "getapp.com", "gartner.com")),
    ("trustpilot", ("trustpilot.com",)),
    ("google_alert", ("googlealerts-noreply@google.com", "google.com")),
)

# "Rishav Kumar commented on your post", "Dana Ruiz replied to your comment", …
_LI_ACTION = re.compile(
    r"^(?P<name>[^:<>]{2,60}?)\s+(?P<verb>commented on|replied to|mentioned you|"
    r"reacted to|responded to|liked|shared|asked)\b", re.I)
_VERB_KIND = {
    "commented on": "comment", "replied to": "comment", "responded to": "comment",
    "mentioned you": "mention", "reacted to": "reaction", "liked": "reaction",
    "shared": "mention", "asked": "question",
}
_QUESTION_WORDS = re.compile(
    r"\b(how do|how does|how can|what is|what are|anyone (?:know|using|tried)|"
    r"looking for|recommend|advice|struggling with|does anyone|which .{0,20}\?)", re.I)
# The first URL that points at the thing itself, not at a footer/unsubscribe link.
_LINK = re.compile(r"https?://[^\s<>\"')]+", re.I)
_LINK_NOISE = re.compile(
    r"(unsubscrib|email[-_]?settings|/preferences|/help|/legal|/privacy|"
    r"manage.{0,12}notification|opt.?out)", re.I)


def platform_of(sender: str) -> str:
    s = (sender or "").lower()
    for name, needles in _SENDERS:
        if any(n in s for n in needles):
            return name
    return "other"


def _unwrap(u: str) -> str:
    """Google Alerts hand out redirector links (google.com/url?…&url=REAL). Keep the
    destination — it's what a human needs to click and what dedupe should key on."""
    m = re.search(r"[?&]url=([^&]+)", u)
    if m and "google.com/url" in u.lower():
        from urllib.parse import unquote
        return unquote(m.group(1))
    return u


def _best_link(raw: str, platform: str) -> str:
    """Scan the RAW body — stripping HTML first would throw away every href."""
    for m in _LINK.finditer(html.unescape(raw or "")):
        u = _unwrap(m.group(0).rstrip(".,)”\"'"))
        if _LINK_NOISE.search(u):
            continue
        if platform == "linkedin" and "linkedin.com" not in u.lower():
            continue
        return u
    return ""


def _is_question(*parts: str) -> bool:
    blob = " ".join(p or "" for p in parts)
    return "?" in blob or bool(_QUESTION_WORDS.search(blob))


def parse_email(sender: str, subject: str, text: str, html_body: str = "") -> dict:
    """A Postmark inbound payload → one signal. Always returns a signal: when the
    format is unrecognised we keep the subject and the raw body, which is enough
    for a human to act on and enough for us to write a parser later."""
    subject = (subject or "").strip()
    body = _strip_html(text or "") or _strip_html(html_body or "")
    platform = platform_of(sender)
    person, kind, title = "", "mention", subject

    if platform == "linkedin":
        m = _LI_ACTION.match(subject)
        if m:
            person = m.group("name").strip()
            kind = _VERB_KIND.get(m.group("verb").lower(), "comment")
            title = subject
        elif re.search(r"\bnew (comments?|posts?|discussions?)\b", subject, re.I):
            kind = "comment"
    elif platform in ("g2", "capterra", "trustpilot"):
        kind = "question" if re.search(r"question|ask", subject, re.I) else "review"
    elif platform == "google_alert":
        kind = "article"
        title = re.sub(r"^google alert\s*[-–]\s*", "", subject, flags=re.I) or subject

    # A comment that reads like a question is the highest-value signal there is:
    # someone stated a problem in public and is waiting for an answer.
    if kind in ("comment", "mention") and _is_question(subject, body[:400]):
        kind = "question"

    url = _best_link(text, platform) or _best_link(html_body, platform)
    return {"channel": "email", "platform": platform, "kind": kind, "person": person,
            "title": _clip(title, 240) or "(no subject)", "text": _clip(body),
            "url": url, "dedupe": dedupe_key(platform, url, title, person)}


# --- RSS / Atom ---------------------------------------------------------------

def _tag(el) -> str:
    return el.tag.split("}")[-1].lower()


def _child(el, *names: str) -> str:
    for c in el:
        if _tag(c) in names:
            if _tag(c) == "link" and not (c.text or "").strip():
                return (c.attrib.get("href") or "").strip()
            return (c.text or "").strip()
    return ""


# Live feeds are routinely a little malformed — a stray control byte or unescaped
# ampersand in one item shouldn't cost us the other twenty-four. FreightWaves' feed
# is a real example: valid RSS 2.0, one invalid token, strict parsers return nothing.
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_ITEM_BLOCK = re.compile(r"(?is)<(item|entry)\b[^>]*>(.*?)</\1\s*>")
_HREF = re.compile(r"""(?is)<link\b[^>]*\bhref\s*=\s*["']([^"']+)["']""")


def _field(blob: str, *names: str) -> str:
    for n in names:
        m = re.search(rf"(?is)<{n}\b[^>]*>(.*?)</{n}\s*>", blob)
        if m:
            v = re.sub(r"(?is)^\s*<!\[CDATA\[(.*?)\]\]>\s*$", r"\1", m.group(1)).strip()
            if v:
                return v
    return ""


def _rows_by_regex(xml_text: str, limit: int) -> list[dict]:
    out = []
    for _, blob in _ITEM_BLOCK.findall(xml_text)[:limit]:
        link = _field(blob, "link")
        if not link:
            m = _HREF.search(blob)
            link = m.group(1) if m else _field(blob, "guid", "id")
        out.append({"title": _strip_html(_field(blob, "title")), "url": (link or "").strip(),
                    "summary": _strip_html(_field(blob, "description", "summary", "content:encoded")),
                    "published": _field(blob, "pubDate", "published", "updated")})
    return out


def parse_feed(xml_text: str | bytes, limit: int = 25) -> list[dict]:
    """RSS 2.0 and Atom, stdlib only — a feed is a list, not a document model, and
    the fields we need carry the same names either way. Strict parse first; on a
    malformed document fall back to scanning the item blocks, which survives the
    one bad byte that would otherwise throw away the whole feed."""
    from xml.etree import ElementTree as ET
    if isinstance(xml_text, bytes):
        # Honour the document's own declaration — several trucking feeds are
        # windows-1252, and decoding those as UTF-8 turns every apostrophe into "�".
        m = re.search(rb'encoding=["\']([\w\-]+)["\']', xml_text[:200], re.I)
        enc = (m.group(1).decode("ascii", "ignore") if m else "utf-8") or "utf-8"
        try:
            xml_text = xml_text.decode(enc, "replace")
        except LookupError:
            xml_text = xml_text.decode("utf-8", "replace")
    xml_text = _CTRL.sub("", xml_text)
    rows: list[dict] = []
    try:
        root = ET.fromstring(xml_text)
        for el in [e for e in root.iter() if _tag(e) in ("item", "entry")][:limit]:
            rows.append({"title": _strip_html(_child(el, "title")),
                         "url": _child(el, "link") or _child(el, "id", "guid"),
                         "summary": _strip_html(_child(el, "description", "summary", "content")),
                         "published": _child(el, "pubdate", "published", "updated")})
    except ET.ParseError:
        rows = _rows_by_regex(xml_text, limit)
    if not rows:
        raise ValueError("no items found — is this an RSS or Atom feed?")
    return [{"title": r["title"] or _clip(r["summary"], 120), "url": r["url"],
             "text": _clip(r["summary"]), "published": r["published"]}
            for r in rows if r["title"] or r["summary"]]


def fetch_feed(url: str, timeout: float = 20.0) -> list[dict]:
    # Some publishers 403 an unrecognised agent, so identify as a normal reader.
    r = httpx.get(url, timeout=timeout, follow_redirects=True, headers={
        "User-Agent": "Mozilla/5.0 (compatible; KnowellaOutreach/1.0; +https://outreach.knowella.com)",
        "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8"})
    r.raise_for_status()
    return parse_feed(r.content)


@lru_cache(maxsize=512)
def _kw_re(keyword: str):
    """Whole words only, plural tolerated, hyphens and spaces interchangeable.

    Whole words because a bare substring test lets three-letter industry acronyms
    match anything: 'eld' hits held/welding/fields (a story about factory job cuts
    got through that way) and 'csa' hits inside 'FMCSA'. The trailing s? keeps 'ELD'
    matching 'ELDs'. The separator class is what makes 'hours of service' find
    "Companies seek hours-of-service exemptions" — publications write these terms
    both ways and the hyphenated form is the more common one in headlines."""
    parts = [re.escape(p) for p in re.split(r"[\s\-]+", keyword.strip()) if p]
    return re.compile(r"\b" + r"[\s\-]+".join(parts) + r"s?\b", re.I)


def _matches(item: dict, keywords: list[str]) -> bool:
    if not keywords:
        return True
    blob = f"{item.get('title','')} {item.get('text','')}"
    return any(_kw_re(k.strip().lower()).search(blob) for k in keywords if k.strip())


def poll_feed(store, feed: dict) -> int:
    """One feed → new signals. Returns how many were new (upserts are keyed on the
    item URL, so re-polling the same feed is free)."""
    items = fetch_feed(feed["url"])
    plat = "google_alert" if "google.com/alerts" in feed["url"].lower() else "rss"
    kws = feed.get("keywords") or []
    new = 0
    for it in items:
        if not _matches(it, kws):
            continue
        sig = {"channel": "rss", "platform": plat, "kind": "article", "person": "",
               "title": it["title"], "text": it["text"], "url": it["url"],
               "source_id": feed.get("source_id", ""), "feed": feed.get("name") or feed["url"],
               "dedupe": dedupe_key(plat, it["url"], it["title"])}
        if store.add_signal(sig):
            new += 1
    return new


def poll_all(store) -> dict:
    """Every enabled feed, one pass. Failures are per-feed: a dead URL records its
    error on the feed row and never stops the others."""
    total, errors = 0, 0
    for f in store.list_feeds():
        if not f.get("enabled", True):
            continue
        try:
            n = poll_feed(store, f)
            store.mark_feed_polled(f["_id"], ok=True, note=f"{n} new")
            total += n
        except Exception as e:                       # network, XML, HTTP status
            errors += 1
            store.mark_feed_polled(f["_id"], ok=False, note=str(e)[:160])
    return {"new": total, "errors": errors, "at": _now()}


_poller_started = False


def start_poller(open_store, extra=None) -> None:
    """Background loop, started once per process. Single uvicorn process (see the
    Dockerfile), so there is exactly one poller; even so every write is an idempotent
    upsert on the dedupe key, which keeps a restart or a second process harmless."""
    global _poller_started
    if _poller_started:
        return
    _poller_started = True
    import threading

    def loop():
        time.sleep(20)          # let the app finish coming up before the first poll
        while True:
            store = None
            try:
                store = open_store()
                if store.list_feeds():
                    res = poll_all(store)
                    if res["new"] or res["errors"]:
                        print(f"[signals] polled feeds: {res['new']} new, {res['errors']} error(s)")
            except Exception as e:
                print(f"[signals] poll cycle failed: {e}")
            # Sources that aren't plain feeds (OSHA citations) are injected by the
            # caller rather than imported here — they import this module, and a poller
            # that only ran feeds would leave citations arriving only on a manual click.
            for fn in (extra or []):
                try:
                    n = fn(store or open_store())
                    if n:
                        print(f"[signals] {fn.__module__.split('.')[-1]}: {n} new")
                except Exception as e:
                    print(f"[signals] {getattr(fn, '__module__', '?')} poll failed: {e}")
            time.sleep(POLL_SECONDS)

    threading.Thread(target=loop, daemon=True, name="signal-poller").start()
