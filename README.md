# NHL Futures — Comparable Odds Tool (2026-27)

Line-shopping + arbitrage/middle finder across sportsbooks for NHL season-long
futures. Streamlit UI, JSON-backed, deploy to Streamlit Cloud (display-only)
with local refresh — same pattern as the Kalshi apps.

## Sections

| Section | What it shows |
|---|---|
| **To Win** | Stanley Cup / Conference / Division "to win" prices per book, with **Best Price** + **Best Book** columns. |
| **Playoffs** | Make-playoffs **Yes/No** per book, plus an **arbitrage finder** (best Yes book vs best No book, combined implied < 100%). |
| **Team Points** | Regular-season point total **Over/Under**. Books can post different lines ("indexes") per team. Includes a **same-line arbitrage** finder and a **cross-index middle** finder ranked by line gap. |
| **Awards** | Player award prices per category (Hart, Norris, Vezina, Calder, Rocket Richard, Art Ross, Selke, …), with Best Price + Best Book. |

## Books tracked

pinnacle · circa · fanduel · bookmaker (manual) · betonline · draftkings ·
caesars (manual) · betmgm · kambi (northstar) · bet99 · betano

## Quick start

```bash
uv run python build_seed.py     # generate data/odds.json (with demo samples)
uv run streamlit run app.py
```

Toggle books in the sidebar; switch sections with the radio at the top.

## Data model (`data/odds.json`)

American odds (int) throughout; `null`/missing = book doesn't offer it.

```jsonc
{
  "to_win": {
    "cup":        { "Colorado Avalanche": { "pinnacle": 650, "fanduel": 700 } },
    "conference": { "Colorado Avalanche": { "pinnacle": 260 } },
    "division":   { "Colorado Avalanche": { "pinnacle": 160 } }
  },
  "playoffs": {
    "Buffalo Sabres": { "yes": { "fanduel": 180 }, "no": { "pinnacle": -180 } }
  },
  "team_points": {
    "Colorado Avalanche": {
      "pinnacle": { "line": 108.5, "over": -110, "under": -110 }
    }
  },
  "awards": {
    "hart": { "Nathan MacKinnon": { "team": "Colorado Avalanche",
                                     "prices": { "pinnacle": 550 } } }
  }
}
```

Team names are canonical (see `teams.py`); scraper/paste labels are routed
through `normalize_team()` so books line up.

## Manual entry (paste-to-Claude workflow)

For **bookmaker** and **caesars** (and any scraper gaps): paste the raw odds
into the chat and I'll parse them into `data/odds.json`. Include the book,
section, and — for team points — the line. Screenshots or copied text both work.
Then hit **↻ Reload data** in the app.

## Adding a scraper

Drop a `scrapers/<book>.py` that returns the odds dict for its book and merges
into `data/odds.json`. Model it on the MLB app's `fetch_competitor_odds` (capture
network calls / fixture ids, prefer the site's JSON API over DOM scraping). Wire
a refresh script + Task Scheduler job once ≥1 scraper is live.

## Deploy (Streamlit Cloud)

Commit `data/odds.json` (cloud is display-only — no scraping there). Set Python
**3.13** in Advanced Settings. Refresh odds locally, then commit + push.
