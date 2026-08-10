"""Signals — the monitoring inbox.

Nothing here is scraped. Every signal arrives because a platform *pushed* it to us,
through one of two channels:

  email  Postmark inbound, and now the only intake that matters. Forward the mail
         LinkedIn / G2 / Trustpilot / Google Alerts / F5Bot already send, and it
         lands here — a named person for the first three, a page mention for the
         last two. Digests are split: one Google Alert becomes eight signals.
  poll   Named sources only, e.g. OSHA citations (src/integrations/osha.py). Trade
         RSS feeds were removed: an article is never someone you can email, and
         they buried the signals that were.

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
    ("f5bot", ("f5bot.com",)),
    ("google_alert", ("googlealerts-noreply@google.com", "google.com")),
)
# Senders that mail a DIGEST — one message carrying many separate finds. Treating
# those as a single signal keeps the first result and silently discards the rest,
# which is what the first version did.
_DIGEST = {"google_alert", "f5bot"}
_ANCHOR = re.compile(r"""(?is)<a\b[^>]*\bhref\s*=\s*["']([^"']+)["'][^>]*>(.*?)</a>""")

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


# Signals arrive by forwarded mail, and Outlook's "forward" action replaces the
# envelope sender with the forwarding mailbox — which files an F5Bot digest under
# 'other' and stops it being split, turning eight Reddit finds into one signal
# titled "Fwd: F5Bot Alert". Silent, and exactly the failure the digest split
# exists to prevent. The original sender survives in the forwarded body, so we look
# there before giving up. Only unambiguous needles: a body mentioning 'google.com'
# is not a Google Alert, whereas one mentioning 'f5bot.com' is an F5Bot digest.
_FWD_HINTS = (
    ("f5bot", "f5bot.com"),
    ("google_alert", "googlealerts-noreply@google.com"),
    ("linkedin", "notifications-noreply@linkedin.com"),
    ("g2", "@g2.com"),
    ("capterra", "@capterra.com"),
    ("trustpilot", "@trustpilot.com"),
)


def platform_of(sender: str, subject: str = "", body: str = "") -> str:
    s = (sender or "").lower()
    for name, needles in _SENDERS:
        if any(n in s for n in needles):
            return name
    hay = f"{subject} {body}".lower()[:4000]
    for name, needle in _FWD_HINTS:
        if needle in hay:
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


def _digest_items(platform: str, subject: str, text: str, html_body: str) -> list[dict]:
    """Split a digest into its individual finds.

    Google Alerts and F5Bot both mail a batch: one message, eight results. The
    anchors in the HTML body are the reliable structure — each result is a link
    whose text is the headline — so items are read from those, with the plain-text
    body as the fallback when a message arrives text-only.
    """
    seen: set[str] = set()
    items: list[dict] = []
    for href, label in _ANCHOR.findall(html_body or ""):
        url = _unwrap(html.unescape(href.strip()))
        title = _strip_html(label)
        if not title or len(title) < 12 or _LINK_NOISE.search(url) or not url.startswith("http"):
            continue
        if "google.com/alerts" in url or url in seen:
            continue                     # the "edit this alert" footer link
        seen.add(url)
        items.append({"title": title, "url": url})
    if not items:                        # text-only digest: a URL per line, title above it
        lines = [ln.strip() for ln in _strip_html(text or "").splitlines() if ln.strip()]
        for i, ln in enumerate(lines):
            m = _LINK.search(ln)
            if not m:
                continue
            url = _unwrap(m.group(0).rstrip(".,)"))
            if _LINK_NOISE.search(url) or url in seen:
                continue
            seen.add(url)
            title = ln.replace(m.group(0), "").strip(" -–—:") or (lines[i - 1] if i else "")
            items.append({"title": title[:200] or url, "url": url})
    label = re.sub(r"^google alert\s*[-–]\s*", "", subject, flags=re.I).strip()
    out = []
    for it in items:
        out.append({"channel": "email", "platform": platform, "kind": "mention",
                    "person": "", "title": _clip(it["title"], 240),
                    "text": f"matched “{label}”" if label else "",
                    "url": it["url"], "topic": label,
                    "dedupe": dedupe_key(platform, it["url"], it["title"])})
    return out


def parse_email(sender: str, subject: str, text: str, html_body: str = "") -> dict:
    """A Postmark inbound payload → one signal. Always returns a signal: when the
    format is unrecognised we keep the subject and the raw body, which is enough
    for a human to act on and enough for us to write a parser later."""
    subject = (subject or "").strip()
    body = _strip_html(text or "") or _strip_html(html_body or "")
    platform = platform_of(sender, subject, body)
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


def parse_inbound(sender: str, subject: str, text: str, html_body: str = "") -> list[dict]:
    """A Postmark inbound payload → one or more signals.

    One message is usually one event ("Dana Ruiz commented on your post"), but the
    keyword services batch — a Google Alert carries every page it found that day.
    Returning a list lets a digest become eight signals instead of one, and a digest
    we fail to split still degrades to the single-signal path rather than vanishing.
    """
    platform = platform_of(sender, subject, f"{text or ''} {html_body or ''}")
    if platform in _DIGEST:
        items = _digest_items(platform, subject, text, html_body)
        if items:
            return items
    return [parse_email(sender, subject, text, html_body)]


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




_poller_started = False


def start_poller(open_store, extra=None) -> None:
    """Background loop, started once per process.

    There are no user-configurable feeds any more — a trade publication produces
    articles, and an article is never someone you can email. What remains are named
    sources (OSHA citations), passed in as `extra` because they import this module.
    Single uvicorn process (see the Dockerfile), so there is exactly one poller; even
    so every write is an idempotent upsert on the dedupe key, which keeps a restart
    or a second process harmless.
    """
    global _poller_started
    if _poller_started:
        return
    _poller_started = True
    import threading

    def loop():
        time.sleep(20)          # let the app finish coming up before the first poll
        while True:
            for fn in (extra or []):
                try:
                    n = fn(open_store())
                    if n:
                        print(f"[signals] {fn.__module__.split('.')[-1]}: {n} new")
                except Exception as e:
                    print(f"[signals] {getattr(fn, '__module__', '?')} poll failed: {e}")
            time.sleep(POLL_SECONDS)

    threading.Thread(target=loop, daemon=True, name="signal-poller").start()
