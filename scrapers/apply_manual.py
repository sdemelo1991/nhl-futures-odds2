r"""Apply a manual (paste-sourced) book's odds into odds.json.

Manual books (Bookmaker, Caesars, ...) have no scraper — Claude transcribes
your paste into scrapers/<book>_data.json, and this applies it. Supports any
subset of: cup / conference / division (team->odds), playoffs
(team->{yes,no}), team_points (team->{line,over,under}), awards
(category->{player->odds}).

Each <book>_data.json is treated as that book's CURRENT complete snapshot,
not an incremental delta — so after applying, any tracked section that is
NOT present in the file this run gets pruned from odds.json for this book
(same prune_stale() used by the live scrapers). This is what keeps a market
Steven didn't re-check in his latest screenshot/video (e.g. Bookmaker's
awards, dropped from the file months ago when the site stopped posting them)
from permanently sitting around as misleadingly-dated stale data — once a
market isn't in the file anymore, the book stops showing it at all.

    python scrapers/apply_manual.py bookmaker
    python scrapers/apply_manual.py caesars
"""
import json
import os
import sys

from common import (load, save, set_to_win, set_playoff, set_team_points, set_award,
                    set_player_prop, stamp_book, set_special, prune_stale)
from awards import AWARD_CATEGORIES

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    if len(sys.argv) < 2:
        print("usage: python scrapers/apply_manual.py <book>")
        return
    book = sys.argv[1].lower()
    path = os.path.join(HERE, f"{book}_data.json")
    if not os.path.exists(path):
        print(f"No data file: {path}")
        return
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    doc = load()
    n = 0
    seen = {
        "to_win": {m: set() for m in ("cup", "conference", "division", "presidents", "worst")},
        "playoffs_yes": set(), "playoffs_no": set(),
        "team_points": set(),
        "awards": {cat: set() for cat in AWARD_CATEGORIES},
        "cup_specials": {"conf": set(), "div": set(), "state": set()},
    }
    for market in ("cup", "conference", "division", "presidents", "worst"):
        for team, odds in (data.get(market) or {}).items():
            key = set_to_win(doc, market, team, book, odds); n += 1
            seen["to_win"][market].add(key)
    for team, sides in (data.get("playoffs") or {}).items():
        for side in ("yes", "no"):
            if sides.get(side) is not None:
                key = set_playoff(doc, team, book, side, sides[side]); n += 1
                seen[f"playoffs_{side}"].add(key)
    for team, q in (data.get("team_points") or {}).items():
        key = set_team_points(doc, team, book, q.get("line"), q.get("over"), q.get("under")); n += 1
        seen["team_points"].add(key)
    for cat, players in (data.get("awards") or {}).items():
        for player, odds in players.items():
            key = set_award(doc, cat, player, "", book, odds)
            if key is not None:
                n += 1
                seen["awards"].setdefault(cat, set()).add(key)
    for cat, players in (data.get("player_markets") or {}).items():
        for player, q in players.items():
            set_player_prop(doc, cat, player, "", book, line=q.get("line"),
                            over=q.get("over"), under=q.get("under")); n += 1
    # Cup Specials: champion's conference / division / state
    for kind in ("conf", "div", "state"):
        for label, odds in (data.get("specials", {}).get(kind) or {}).items():
            key = set_special(doc, kind, label, book, odds); n += 1
            seen["cup_specials"][kind].add(key)

    pruned = prune_stale(doc, book, seen)
    stamp_book(doc, book, data.get("updated"))
    # Per-market freshness overrides: {"award:rocket_richard": "2026-08-13", ...} lets a
    # single market read fresh in the dashboard while the rest of the book keeps its date.
    # Replaced wholesale (not merged) each apply, so a market dropped from this file's
    # updated_markets - because the whole book, including that market, was re-verified -
    # doesn't keep shadowing the fresh book-level date with a stale override forever.
    doc.setdefault("meta", {})["book_market_updated"] = \
        doc.get("meta", {}).get("book_market_updated") or {}
    doc["meta"]["book_market_updated"][book] = dict(data.get("updated_markets") or {})
    print(f"  applied {n} {book} prices from {os.path.basename(path)} "
          f"[updated {data.get('updated', '?')}]")
    if n or pruned:
        save(doc)


if __name__ == "__main__":
    main()
