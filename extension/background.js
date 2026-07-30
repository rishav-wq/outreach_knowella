// Clicking the toolbar icon opens the side panel (Gemini-style, docked right).
// The click also grants activeTab on the current tab — which is what lets the
// panel's "Scan" read the comments there. No other background behavior.
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {})
