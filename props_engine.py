"""Player-prop analytics — the O/U <-> X+ unification.

Books post player totals two ways:
  * O/U line: {"line": 44.5, "over": -120, "under": +100}
  * X+ milestone: "50+ goals" at some yes price (a one-sided OVER)

The trick that makes both comparable (and lets us reuse odds_engine's arb /
middle math unchanged) is to normalize every "N+" into an OVER at line N-0.5:
  "50+ goals" @ +180   ==   over 49.5 @ +180

Once everything is an (book, line, side, odds) quote on one shared line axis:
  * best price per line/side falls out of odds_engine.best_price
  * a same-line over/under pair is a two_way_arb
  * the lowest over-line vs the highest under-line is a middle — and because
    milestones live on the same axis, cross-form middles (back 50+ vs Under
    52.5 -> win on 50 or 51) are found for free.

A player entry in odds.json looks like:
  {
    "team": "Toronto Maple Leafs",
    "ou":   {book: {"line": 44.5, "over": -120, "under": 100}, ...},
    "plus": {"50": {book: 180, ...}, "55": {book: 320, ...}}
  }
"""
from __future__ import annotations

from odds_engine import (american_to_decimal, american_to_prob, best_price,
                         two_way_arb, two_way_arb_with_book)


def unify_quotes(entry: dict) -> list[dict]:
    """Flatten a player entry into normalized quotes:
    {book, line, side ('over'|'under'), odds, form ('ou'|'plus'), threshold?}."""
    quotes: list[dict] = []
    for book, q in (entry.get("ou") or {}).items():
        line = q.get("line")
        if line is None:
            continue
        line = float(line)
        if q.get("over") is not None:
            quotes.append({"book": book, "line": line, "side": "over",
                           "odds": q["over"], "form": "ou"})
        if q.get("under") is not None:
            quotes.append({"book": book, "line": line, "side": "under",
                           "odds": q["under"], "form": "ou"})
    for thr, books in (entry.get("plus") or {}).items():
        line = float(thr) - 0.5  # "N+" == over @ (N-0.5)
        for book, odds in (books or {}).items():
            if odds is not None:
                quotes.append({"book": book, "line": line, "side": "over",
                               "odds": odds, "form": "plus", "threshold": int(float(thr))})
    return quotes


def line_grid(quotes: list[dict]) -> dict:
    """{line: {"over": {book: odds}, "under": {book: odds}}}, lines ascending.
    If a book quotes the same line/side twice (e.g. an O/U over and an
    equivalent milestone), keep the better price."""
    grid: dict[float, dict] = {}
    for q in quotes:
        side = grid.setdefault(q["line"], {"over": {}, "under": {}})[q["side"]]
        cur = side.get(q["book"])
        if cur is None or (american_to_decimal(q["odds"]) or 0) > (american_to_decimal(cur) or 0):
            side[q["book"]] = q["odds"]
    return dict(sorted(grid.items()))


def prop_arbs(quotes: list[dict]) -> list[dict]:
    """Same-line over/under arbs across books (one per line that arbs)."""
    arbs = []
    for line, sides in line_grid(quotes).items():
        arb = two_way_arb(sides["over"], sides["under"])
        if arb:
            arbs.append({"line": line, **arb})
    return arbs


def prop_arbs_with_book(quotes: list[dict], book: str) -> list[dict]:
    """Like prop_arbs, but only arbs where `book` is a leg — forced onto one
    side (see two_way_arb_with_book). For the FanDuel Desk, which must surface
    every FD-leg arb even when another book wins the line's best pairing."""
    arbs = []
    for line, sides in line_grid(quotes).items():
        arb = two_way_arb_with_book(sides["over"], sides["under"], book)
        if arb:
            arbs.append({"line": line, **arb})
    return arbs


def prop_middles(quotes: list[dict], min_gap: float = 1.0,
                 max_gap: float | None = None) -> list[dict]:
    """Best cross-line (and cross-form) middle: back the OVER at some line, the
    UNDER at a higher line; any result strictly between wins both. Rather than
    the widest span (which pairs distant, non-comparable lines), scan all valid
    over/under pairs whose gap is within [min_gap, max_gap] and return the
    single most valuable one (lowest combined implied, tightest gap on ties).
    max_gap=None means no upper bound. Returns [] if none qualify."""
    grid = line_grid(quotes)
    overs = [(ln, best_price(s["over"])) for ln, s in grid.items() if s["over"]]
    unders = [(ln, best_price(s["under"])) for ln, s in grid.items() if s["under"]]
    best = None
    for lo, (ob, oo) in overs:
        for hi, (ub, uo) in unders:
            gap = round(hi - lo, 1)
            if gap < min_gap or (max_gap is not None and gap > max_gap):
                continue
            p_o = american_to_prob(oo) or 0
            p_u = american_to_prob(uo) or 0
            cand = {
                "gap": gap,
                "over_book": ob, "over_line": lo, "over_odds": oo,
                "under_book": ub, "under_line": hi, "under_odds": uo,
                "combined_implied": round(p_o + p_u, 4),
                "is_free_middle": (p_o + p_u) < 1.0,
            }
            if best is None or (cand["combined_implied"], cand["gap"]) < \
                    (best["combined_implied"], best["gap"]):
                best = cand
    return [best] if best else []


def primary_line(entry: dict):
    """The representative O/U line for a player (median of posted O/U lines),
    for the summary row. None if the player has only milestones."""
    lines = sorted(float(q["line"]) for q in (entry.get("ou") or {}).values()
                   if q.get("line") is not None)
    if not lines:
        return None
    return lines[len(lines) // 2]
