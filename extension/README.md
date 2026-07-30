# Knowella Outreach — LinkedIn Capture (side panel)

Captures the **commenters of a LinkedIn post you're viewing** into a Knowella
Outreach campaign. People who comment on a relevant post are the warmest leads —
they self-selected into the topic.

The panel docks on the right (like Gemini in Chrome). LinkedIn is used **only as
a pointer** (name + profile URL + headline); all contact data comes from Apollo's
database, and captured people land as normal `new` leads for the usual
review → approve → send flow. Nothing is emailed without review.

## Risk posture (why it's built this way)

- **No content scripts, no host permissions, no background access.** The page is
  read only at the moment you click **Scan** (`activeTab` + `scripting`).
- **No automation.** It never scrolls, never clicks "Load more", never visits
  profiles. You load the comments yourself; it reads what's on screen.
- **Keep usage human-paced.** A few posts here and there — this is a capture aid,
  not a crawler. Automated collection violates LinkedIn's User Agreement; this
  design minimizes (but cannot zero) the account risk.

## Install (unpacked)

1. Chrome/Edge → `chrome://extensions` → enable **Developer mode**.
2. **Load unpacked** → select this `extension/` folder.
3. In the Outreach app: **Settings → LinkedIn capture extension → Generate token**.
4. Click the extension's toolbar icon (pin it) — the panel opens. Open ⚙, paste
   the **App URL** (`https://outreach.knowella.com`) and the **token**, Save.

## Use

1. Open a LinkedIn **post** (the post page itself, not the feed) and expand its
   comments.
2. Click the toolbar icon → panel opens. Pick the **target campaign** — you know
   what the post is about, so you know which offer fits.
3. Click **Scan visible comments**. Scroll / click "Load more comments" yourself,
   then **Scan** again — the list accumulates, deduped by profile URL.
4. **Send N to campaign.** The app enriches each person via Apollo (~1 credit per
   match), skips anyone already captured or suppressed, and reports
   `added · with email · without email`.
5. In the app: run the pipeline, review the drafts, approve, send — as always.

Notes
- If Scan says it needs a fresh grant, click the toolbar icon once on that tab
  (Chrome's `activeTab` permission is per-click), then Scan again.
- "No comment blocks found" on a real post usually means LinkedIn changed its
  markup — the selectors in `popup.js` (`scrapeComments`) need a touch-up.
- Commenters without a match keep name/title/company from their headline and are
  parked without an email (never sent to blindly).
