# WFFL League Hub

Live standings, playoff odds, matchups that matter, rooting guide, trades and more for the WFFL Yahoo fantasy league.

- `index.html` – the site (reads `data.json` on load)
- `data.json` – league data, refreshed automatically from Yahoo
- `scraper.js` – produces `data.json` when run in a signed-in Yahoo tab
- `template.html` + `build.py` – source for `index.html` (embeds a fallback copy of the data)
