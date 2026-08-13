r"""Apply a manual (paste-sourced) book's odds into odds.json.

Manual books (Bookmaker, Caesars, ...) have no scraper — Claude transcribes
your paste into scrapers/<book>_data.json, and this applies it. Supports any
subset of: cup / conference / division (team->odds), playoffs
(team->{yes,no}), team_points (team->{line,over,under}), awards
(category->{player->odds}).

    python scrapers/apply_manual.py bookmaker
    python scrapers/apply_manual.py caesars
"""
import json
import os
import sys

from common import (load, save, set_to_win, set_playoff, set_team_points, set_award,
                    set_player_prop, stamp_book, set_special)

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
    for market in ("cup", "conference", "division", "presidents", "worst"):
        for team, odds in (data.get(market) or {}).items():
            set_to_win(doc, market, team, book, odds); n += 1
    for team, sides in (data.get("playoffs") or {}).items():
        for side in ("yes", "no"):
            if sides.get(side) is not None:
                set_playoff(doc, team, book, side, sides[side]); n += 1
    for team, q in (data.get("team_points") or {}).items():
        set_team_points(doc, team, book, q.get("line"), q.get("over"), q.get("under")); n += 1
    for cat, players in (data.get("awards") or {}).items():
        for player, odds in players.items():
            set_award(doc, cat, player, "", book, odds); n += 1
    for cat, players in (data.get("player_markets") or {}).items():
        for player, q in players.items():
            set_player_prop(doc, cat, player, "", book, line=q.get("line"),
                            over=q.get("over"), under=q.get("under")); n += 1
    # Cup Specials: champion's conference / division / state
    for kind in ("conf", "div", "state"):
        for label, odds in (data.get("specials", {}).get(kind) or {}).items():
            set_special(doc, kind, label, book, odds); n += 1

    stamp_book(doc, book, data.get("updated"))
    # Per-market freshness overrides: {"award:rocket_richard": "2026-08-13", ...} lets a
    # single market read fresh in the dashboard while the rest of the book keeps its date.
    for mk, when in (data.get("updated_markets") or {}).items():
        doc.setdefault("meta", {}).setdefault("book_market_updated", {}) \
            .setdefault(book, {})[mk] = when
    print(f"  applied {n} {book} prices from {os.path.basename(path)} "
          f"[updated {data.get('updated', '?')}]")
    if n:
        save(doc)


if __name__ == "__main__":
    main()
