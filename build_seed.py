"""Generate a fresh data/odds.json skeleton with every team wired in and empty
price maps for each book. Re-runnable: pass --keep to merge existing prices in
(so you don't wipe entered odds when the schema changes).

    uv run python build_seed.py            # write a blank skeleton (with samples)
    uv run python build_seed.py --keep     # preserve existing prices, add gaps

Sample prices are included for a few teams/players so the UI and the arb /
middle finders render something on first run. They are clearly flagged in
meta.notes; replace them with real odds.
"""
import argparse
import json
import os

from teams import TEAMS
from awards import AWARD_CATEGORIES
from player_props import PROP_CATEGORIES
from books import BOOKS

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "odds.json")

# --- sample data (demonstrates best-price, arb, and middle finders) ---------
SAMPLE_CUP = {
    "Colorado Avalanche": {"pinnacle": 650, "fanduel": 700, "draftkings": 650, "betmgm": 680, "caesars": 750},
    "Florida Panthers": {"pinnacle": 750, "fanduel": 700, "draftkings": 800, "betmgm": 720},
    "Edmonton Oilers": {"pinnacle": 800, "fanduel": 850, "draftkings": 750, "betmgm": 900},
    "Vegas Golden Knights": {"pinnacle": 1100, "fanduel": 1200, "draftkings": 1000},
}
# Playoffs sample includes a deliberate arb (Buffalo yes/no across books).
SAMPLE_PLAYOFFS = {
    "Colorado Avalanche": {"yes": {"pinnacle": -900, "fanduel": -1000, "draftkings": -850},
                            "no": {"pinnacle": 600, "fanduel": 650, "betmgm": 700}},
    "Buffalo Sabres": {"yes": {"fanduel": 180, "draftkings": 200, "betmgm": 175},
                        "no": {"pinnacle": -180, "caesars": -170, "betano": 105}},
}
# Team points sample includes a same-index arb and a cross-index middle.
SAMPLE_POINTS = {
    "Colorado Avalanche": {
        "pinnacle": {"line": 108.5, "over": -110, "under": -110},
        "fanduel": {"line": 108.5, "over": 105, "under": -125},   # over side pairs for arb
        "draftkings": {"line": 106.5, "over": -115, "under": -105},  # lower line -> middle
        "betmgm": {"line": 109.5, "over": -105, "under": -115},      # higher line -> middle
    },
    "Chicago Blackhawks": {
        "pinnacle": {"line": 74.5, "over": -110, "under": -110},
        "fanduel": {"line": 76.5, "over": -108, "under": -112},
        "draftkings": {"line": 74.5, "over": -105, "under": -115},   # best over @ 74.5
        "betmgm": {"line": 74.5, "over": -120, "under": 110},        # best under @ 74.5 -> same-line arb
    },
}
SAMPLE_AWARDS = {
    "hart": {
        "Nathan MacKinnon": {"team": "Colorado Avalanche", "prices": {"pinnacle": 550, "fanduel": 600, "draftkings": 500}},
        "Connor McDavid": {"team": "Edmonton Oilers", "prices": {"pinnacle": 450, "fanduel": 400, "draftkings": 450}},
    },
    "vezina": {
        "Connor Hellebuck": {"team": "Winnipeg Jets", "prices": {"pinnacle": 300, "fanduel": 275, "draftkings": 320}},
    },
}
# Player props sample: mixes O/U lines and X+ milestones, incl. a cross-form
# middle (McDavid: back 120+ @ over 119.5 vs Under 126.5) so the section renders.
SAMPLE_PROPS = {
    "points": {
        "Connor McDavid": {
            "team": "Edmonton Oilers",
            "ou": {"fanduel": {"line": 124.5, "over": -110, "under": -110},
                   "draftkings": {"line": 126.5, "over": -105, "under": -115},
                   "betmgm": {"line": 123.5, "over": -108, "under": -112}},
            "plus": {"120": {"fanduel": -140, "caesars": -130}},
        },
        "Nathan MacKinnon": {
            "team": "Colorado Avalanche",
            "ou": {"fanduel": {"line": 116.5, "over": 100, "under": -122},
                   "draftkings": {"line": 116.5, "over": 105, "under": -125}},
            "plus": {"110": {"betmgm": -160}},
        },
    },
    "goals": {
        "Auston Matthews": {
            "team": "Toronto Maple Leafs",
            "ou": {"fanduel": {"line": 44.5, "over": -120, "under": 100},
                   "draftkings": {"line": 45.5, "over": -110, "under": -110}},
            "plus": {"50": {"betmgm": 180, "caesars": 200}},
        },
    },
}


def empty_book_map():
    return {}


def build(existing=None, blank=False):
    existing = existing or {}
    prev = existing

    doc = {
        "meta": {
            "season": "2026-27",
            "last_updated": None,
            "books": BOOKS,
            "notes": ("" if blank else
                      "SAMPLE prices seeded for a few teams/players to demo the "
                      "arb + middle finders. Replace with real odds."),
        },
        "books": BOOKS,
        "to_win": {"cup": {}, "conference": {}, "division": {},
                   "presidents": {}, "worst": {}},
        "playoffs": {},
        "team_points": {},
        "awards": {cat: {} for cat in AWARD_CATEGORIES},
        "player_markets": {cat: {} for cat in PROP_CATEGORIES},
    }

    for team in TEAMS:
        for market in ("cup", "conference", "division", "presidents", "worst"):
            seed = SAMPLE_CUP.get(team, {}) if (market == "cup" and not blank) else {}
            doc["to_win"][market][team] = dict(seed)
        doc["playoffs"][team] = ({"yes": {}, "no": {}} if blank
                                 else SAMPLE_PLAYOFFS.get(team, {"yes": {}, "no": {}}))
        doc["team_points"][team] = {} if blank else SAMPLE_POINTS.get(team, {})

    for cat in AWARD_CATEGORIES:
        doc["awards"][cat] = {} if blank else SAMPLE_AWARDS.get(cat, {})

    for cat in PROP_CATEGORIES:
        doc["player_markets"][cat] = {} if blank else SAMPLE_PROPS.get(cat, {})

    # merge previously-entered prices back in
    if prev:
        _merge(doc, prev)
    return doc


def _merge(doc, prev):
    for market in ("cup", "conference", "division", "presidents", "worst"):
        for team, prices in prev.get("to_win", {}).get(market, {}).items():
            if prices:
                doc["to_win"].setdefault(market, {}).setdefault(team, {}).update(prices)
    for team, sides in prev.get("playoffs", {}).items():
        if sides.get("yes") or sides.get("no"):
            doc["playoffs"][team] = sides
    for team, lines in prev.get("team_points", {}).items():
        if lines:
            doc["team_points"][team] = lines
    for cat, players in prev.get("awards", {}).items():
        if players:
            doc["awards"].setdefault(cat, {}).update(players)
    for cat, players in prev.get("player_markets", {}).items():
        if players:
            doc.setdefault("player_markets", {}).setdefault(cat, {}).update(players)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true", help="merge existing prices")
    ap.add_argument("--blank", action="store_true",
                    help="clean slate: no demo samples (for real-only rollout)")
    args = ap.parse_args()

    existing = None
    if args.keep and os.path.exists(DATA_PATH):
        with open(DATA_PATH, encoding="utf-8") as f:
            existing = json.load(f)

    doc = build(existing, blank=args.blank)
    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
    print(f"Wrote {DATA_PATH}")


if __name__ == "__main__":
    main()
