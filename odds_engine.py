"""Odds math and market analytics: American<->decimal conversion, best-price
selection, two-way arbitrage detection, and index-gap (middle) ranking.

All book prices are stored and passed around as American odds (int), e.g.
+550 or -120. A missing price is represented as None.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Conversions
# ---------------------------------------------------------------------------

def american_to_decimal(odds) -> float | None:
    if odds is None:
        return None
    odds = float(odds)
    if odds > 0:
        return 1.0 + odds / 100.0
    if odds < 0:
        return 1.0 + 100.0 / abs(odds)
    return None


def american_to_prob(odds) -> float | None:
    """No-vig-agnostic implied probability of a single American price."""
    dec = american_to_decimal(odds)
    return None if dec is None else 1.0 / dec


def decimal_to_american(dec: float) -> int | None:
    if dec is None or dec <= 1.0:
        return None
    if dec >= 2.0:
        return round((dec - 1.0) * 100)
    return round(-100.0 / (dec - 1.0))


def fmt_american(odds) -> str:
    if odds is None:
        return "—"
    odds = int(round(float(odds)))
    return f"+{odds}" if odds > 0 else str(odds)


# ---------------------------------------------------------------------------
# Best price across books
# ---------------------------------------------------------------------------

def best_price(prices: dict) -> tuple[str | None, int | None]:
    """Given {book: american_odds}, return (best_book, best_odds) where "best"
    is the highest payout (largest decimal). Ignores None entries."""
    best_book, best_dec, best_odds = None, None, None
    for book, odds in prices.items():
        dec = american_to_decimal(odds)
        if dec is None:
            continue
        if best_dec is None or dec > best_dec:
            best_book, best_dec, best_odds = book, dec, odds
    return best_book, best_odds


# ---------------------------------------------------------------------------
# Two-way arbitrage (Yes/No, Over/Under)
# ---------------------------------------------------------------------------

def two_way_arb(side_a: dict, side_b: dict) -> dict | None:
    """side_a / side_b are {book: american_odds} for the two opposite outcomes.
    Uses the best price on each side. Returns an arb dict if the combined
    implied probability is < 1 (guaranteed profit), else None.

    Returned dict:
      a_book, a_odds, b_book, b_odds, margin (profit fraction on total stake),
      stake_a_pct, stake_b_pct (stake split that locks equal profit).
    """
    a_book, a_odds = best_price(side_a)
    b_book, b_odds = best_price(side_b)
    pa, pb = american_to_prob(a_odds), american_to_prob(b_odds)
    if pa is None or pb is None:
        return None
    total = pa + pb
    margin = 1.0 - total
    # Reject break-even / float-noise "0% arbs" (e.g. +900 vs -900 = exactly
    # 100%): only a real, positive edge counts.
    if margin <= 1e-6:
        return None
    return {
        "a_book": a_book, "a_odds": a_odds,
        "b_book": b_book, "b_odds": b_odds,
        "margin": margin,               # profit as fraction of total staked
        "stake_a_pct": pa / total,
        "stake_b_pct": pb / total,
    }


def two_way_arb_with_book(side_a: dict, side_b: dict, book: str) -> dict | None:
    """Best two-way arb in which `book` is one of the two legs.

    two_way_arb() only ever considers each side's single best price, so a book's
    real arb is hidden whenever another book edges it out on one side. The
    FanDuel Desk must instead surface *every* arb where FanDuel is actually a
    leg, so this forces `book` onto one side and pairs it with the best price
    from a *different* book on the opposite side (trying `book` on each side).
    a_* is always the side_a leg and b_* the side_b leg, mirroring two_way_arb.
    Returns the higher-margin orientation, or None if neither clears an edge."""
    candidates = []
    if book in side_a:                                  # book supplies the side_a leg
        bb, bo = best_price({k: v for k, v in side_b.items() if k != book})
        candidates.append((book, side_a[book], bb, bo))
    if book in side_b:                                  # book supplies the side_b leg
        ab, ao = best_price({k: v for k, v in side_a.items() if k != book})
        candidates.append((ab, ao, book, side_b[book]))
    best = None
    for a_book, a_odds, b_book, b_odds in candidates:
        pa, pb = american_to_prob(a_odds), american_to_prob(b_odds)
        if pa is None or pb is None:
            continue
        margin = 1.0 - (pa + pb)
        if margin <= 1e-6:
            continue
        if best is None or margin > best["margin"]:
            total = pa + pb
            best = {"a_book": a_book, "a_odds": a_odds, "b_book": b_book, "b_odds": b_odds,
                    "margin": margin, "stake_a_pct": pa / total, "stake_b_pct": pb / total}
    return best


# ---------------------------------------------------------------------------
# Team-points: same-index arb + cross-index middles
# ---------------------------------------------------------------------------

def _points_by_line(book_lines: dict) -> dict:
    """{line: {"over": {book: odds}, "under": {book: odds}}} from book_lines."""
    by_line: dict[float, dict] = {}
    for book, q in book_lines.items():
        line = q.get("line")
        if line is None:
            continue
        by_line.setdefault(line, {"over": {}, "under": {}})
        if q.get("over") is not None:
            by_line[line]["over"][book] = q["over"]
        if q.get("under") is not None:
            by_line[line]["under"][book] = q["under"]
    return by_line


def points_same_index_arb(book_lines: dict) -> list[dict]:
    """book_lines: {book: {"line": float, "over": odds, "under": odds}}.
    For each distinct line value, look for an over/under arb across books that
    both post that exact line. Returns a list of arb dicts (one per line that
    arbs), each including the line.
    """
    arbs = []
    for line, sides in _points_by_line(book_lines).items():
        arb = two_way_arb(sides["over"], sides["under"])
        if arb:
            arbs.append({"line": line, **arb})
    return arbs


def points_same_index_arb_with_book(book_lines: dict, book: str) -> list[dict]:
    """Like points_same_index_arb, but only arbs where `book` is a leg — forced
    onto one side (see two_way_arb_with_book). For the FanDuel Desk, which must
    surface every FD-leg arb even when another book wins the line's best pair."""
    arbs = []
    for line, sides in _points_by_line(book_lines).items():
        arb = two_way_arb_with_book(sides["over"], sides["under"], book)
        if arb:
            arbs.append({"line": line, **arb})
    return arbs


def points_middles(book_lines: dict, min_gap: float = 1.0) -> list[dict]:
    """Find cross-index middle opportunities: buy the OVER at the book with the
    lowest posted line and the UNDER at the book with the highest posted line.
    Any final points total landing strictly between the two lines wins both.

    Returns a list of middle dicts sorted by gap (largest first). A middle is
    reported when (high_line - low_line) >= min_gap.
    """
    overs = []   # (line, book, odds)
    unders = []
    for book, q in book_lines.items():
        line = q.get("line")
        if line is None:
            continue
        if q.get("over") is not None:
            overs.append((line, book, q["over"]))
        if q.get("under") is not None:
            unders.append((line, book, q["under"]))
    if not overs or not unders:
        return []

    # Best middle = lowest over line vs highest under line.
    low_over = min(overs, key=lambda x: x[0])
    high_under = max(unders, key=lambda x: x[0])
    gap = high_under[0] - low_over[0]
    if gap < min_gap:
        return []

    # Combined cost of the two legs; a middle can still be profitable even if
    # combined implied > 1 because the middle band pays both.
    p_over = american_to_prob(low_over[2]) or 0
    p_under = american_to_prob(high_under[2]) or 0
    return [{
        "gap": round(gap, 1),
        "over_book": low_over[1], "over_line": low_over[0], "over_odds": low_over[2],
        "under_book": high_under[1], "under_line": high_under[0], "under_odds": high_under[2],
        "combined_implied": round(p_over + p_under, 4),
        "is_free_middle": (p_over + p_under) < 1.0,  # arb + middle: can't lose
    }]


def line_spread(book_lines: dict) -> dict:
    """Summary of how far apart the posted lines are across books for one team.
    Returns {min_line, max_line, spread, n_books, distinct_lines}."""
    lines = [q["line"] for q in book_lines.values() if q.get("line") is not None]
    if not lines:
        return {"min_line": None, "max_line": None, "spread": 0.0,
                "n_books": 0, "distinct_lines": 0}
    return {
        "min_line": min(lines),
        "max_line": max(lines),
        "spread": round(max(lines) - min(lines), 1),
        "n_books": len(lines),
        "distinct_lines": len(set(lines)),
    }
