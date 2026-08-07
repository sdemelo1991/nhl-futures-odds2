r"""Kalshi exchange NHL futures scraper (LOCAL, direct REST API).

Kalshi lists only a few NHL futures markets; we bring in the ones that exist and
apply two dashboard-specific treatments the desk asked for:

  (a) Price = best available YES ask (the cost to *back* a team/player), chosen
      as the price at which at least $LIQ_MIN of liquidity is available, then
      converted from an implied % to American odds. Walking to the depth where
      $LIQ_MIN fills gives the price you could realistically get down, not a
      one-lot top-of-book quote.
  (b) Liquidity ($) available at that quoted price is stored per selection and
      shown in the dashboard where other books show "updated <date>".

  Quality gate — a lone YES ask on a thin, one-sided book is misleading: with
  almost no No-side interest, yes_ask = 1 - best_no_bid comes out artificially
  SHORT (a 1%-shot quotes like a 30% favorite). So a selection is only priced
  when the market is genuinely two-sided: a real YES bid AND ask, a top-of-book
  spread <= MAX_SPREAD, and >= $LIQ_MIN of ask depth. Everything else is skipped.

Markets pulled (2026-27):
  cup         event KXNHL-27         (Stanley Cup)      -> to_win.cup
  conference  events KXNHLWEST-27 / KXNHLEAST-27        -> to_win.conference
  hart        event KXNHLHART-27     (Hart Trophy)      -> awards.hart

Usage:
  python scrapers/kalshi.py            # dry-run: print discovered prices/liq
  python scrapers/kalshi.py --write    # route into data/odds.json as "kalshi"
  python scrapers/kalshi.py --write --min-liq 500
"""
import argparse
import json
import os
import sys

import requests

from common import load, save, set_award, set_liq, set_to_win, stamp_book

# teams import for a pre-check so unknown names are reported, not silently set
sys.path.insert(0, __import__("os").path.dirname(
    __import__("os").path.dirname(__import__("os").path.abspath(__file__))))
from teams import normalize_team  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

BOOK = "kalshi"
API_BASE = "https://api.elections.kalshi.com/trade-api/v2"


def _load_api_key():
    """Kalshi key from env KALSHI_API_KEY, else scrapers/.secrets.json {"kalshi": "..."}.
    Kept OUT of source so it's never committed. Rotate the key in the Kalshi
    dashboard, then put the new value in scrapers/.secrets.json (git-ignored)."""
    k = os.environ.get("KALSHI_API_KEY")
    if k:
        return k.strip()
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".secrets.json")
    if os.path.exists(p):
        try:
            return (json.load(open(p, encoding="utf-8")).get("kalshi") or "").strip()
        except (ValueError, OSError):
            pass
    return ""


API_KEY = _load_api_key()
LIQ_MIN = 300.0  # dollars — minimum liquidity required at the quoted price
MAX_SPREAD = 0.12  # max top-of-book YES bid/ask spread (12c) to trust a market
MAX_OVERROUND = 2.0  # drop a market whose YES-ask field sums past this (200%)

# (event_ticker, section, kind). section is the table the price/liq annotate:
# to-win markets use their market name; awards use the category key.
MARKETS = [
    ("KXNHL-27", "cup", "team"),
    ("KXNHLWEST-27", "conference", "team"),
    ("KXNHLEAST-27", "conference", "team"),
    ("KXNHLHART-27", "hart", "player"),
]


def _headers():
    return {"Authorization": API_KEY}


def get_markets(event_ticker):
    r = requests.get(f"{API_BASE}/markets", headers=_headers(),
                     params={"event_ticker": event_ticker, "limit": 500}, timeout=20)
    r.raise_for_status()
    return r.json().get("markets", []) or []


def get_orderbook(ticker):
    r = requests.get(f"{API_BASE}/markets/{ticker}/orderbook", headers=_headers(), timeout=15)
    if r.status_code == 200:
        return (r.json() or {}).get("orderbook_fp", {}) or {}
    return {}


def prob_to_american(p):
    """Implied probability (0-1) -> American odds."""
    if p is None or p <= 0 or p >= 1:
        return None
    return round((1 - p) / p * 100) if p < 0.5 else round(-100 * p / (1 - p))


def _levels(ob, side):
    """Return [(price, dollars), ...] for a side of the book (price ascending)."""
    out = []
    for row in ob.get(side) or []:
        try:
            out.append((float(row[0]), float(row[1])))
        except (TypeError, ValueError, IndexError):
            continue
    return out


def quote(ob, min_liq):
    """Assess a market's YES side. Returns a dict with:
      top_bid  best (highest) YES bid price, or None
      top_ask  best (lowest) YES ask price (= 1 - highest No bid), or None
      spread   top_ask - top_bid, or None
      ask      YES ask price at >= min_liq of depth (the actionable back price)
      liq      dollars available up to that quoted ask level

    YES asks are the mirror of resting NO bids: yes_ask = 1 - no_bid_price, with
    the No bid's dollar size the liquidity available to take."""
    yes_bids = sorted(_levels(ob, "yes_dollars"), key=lambda x: x[0], reverse=True)
    yes_asks = sorted(((1.0 - p, q) for p, q in _levels(ob, "no_dollars")), key=lambda x: x[0])
    top_bid = yes_bids[0][0] if yes_bids else None
    top_ask = yes_asks[0][0] if yes_asks else None
    spread = (top_ask - top_bid) if (top_bid is not None and top_ask is not None) else None
    cum, ask = 0.0, None
    for price, qty in yes_asks:
        cum += qty
        if cum >= min_liq:
            ask = price
            break
    return {"top_bid": top_bid, "top_ask": top_ask, "spread": spread,
            "ask": ask, "liq": cum}


def sel_name(m):
    """Team/player label for a market (Kalshi puts it in the yes sub-title)."""
    return (m.get("yes_sub_title") or m.get("subtitle") or m.get("title")
            or m.get("ticker") or "").strip()


def purge_book(doc):
    """Drop every existing Kalshi price/liq in the sections we manage, so a
    re-run reflects exactly the current (gated) set. Without this, a selection
    that used to price but now fails the quality gate would keep its stale
    number forever, since set_* only ever writes."""
    tw_sections = {sec for _, sec, kind in MARKETS if kind == "team"}
    aw_sections = {sec for _, sec, kind in MARKETS if kind == "player"}
    for sec in tw_sections:
        for prices in (doc.get("to_win", {}).get(sec) or {}).values():
            prices.pop(BOOK, None)
    for sec in aw_sections:
        for entry in (doc.get("awards", {}).get(sec) or {}).values():
            (entry.get("prices") or {}).pop(BOOK, None)
    for sec in tw_sections | aw_sections:
        for m in (doc.get("liq", {}).get(sec) or {}).values():
            m.pop(BOOK, None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="route into odds.json")
    ap.add_argument("--min-liq", type=float, default=LIQ_MIN)
    ap.add_argument("--max-spread", type=float, default=MAX_SPREAD,
                    help="max top-of-book YES bid/ask spread to trust (e.g. 0.12 = 12c)")
    ap.add_argument("--max-overround", type=float, default=MAX_OVERROUND,
                    help="drop a whole market whose YES-ask field sums past this "
                         "(e.g. 2.0 = 200%%) — it isn't price-discovering")
    args = ap.parse_args()

    if not API_KEY:
        print("No Kalshi API key. Set env KALSHI_API_KEY or create "
              "scrapers/.secrets.json with {\"kalshi\": \"<your-key>\"}.")
        return

    try:
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        pass

    doc = load() if args.write else None
    if args.write:
        purge_book(doc)  # clear our prior prices so a re-run reflects the current set

    counts, skipped, unknown, dropped = {}, [], [], []

    for event_ticker, section, kind in MARKETS:
        try:
            markets = get_markets(event_ticker)
        except Exception as e:  # noqa: BLE001
            print(f"  {event_ticker}: fetch failed ({e})")
            continue

        # pass 1 — per-selection quality gate (two-sided, tight, deep enough)
        cands = []  # (name, ask, liq, spread)
        for m in markets:
            name = sel_name(m)
            q = quote(get_orderbook(m.get("ticker", "")), args.min_liq)
            if q["ask"] is None:
                skipped.append(f"{event_ticker}:{name} (ask depth ${q['liq']:,.0f} < ${args.min_liq:,.0f})")
            elif q["top_bid"] is None:
                skipped.append(f"{event_ticker}:{name} (one-sided — no YES bid)")
            elif q["spread"] is not None and q["spread"] > args.max_spread:
                skipped.append(f"{event_ticker}:{name} (spread {q['spread']*100:.0f}c "
                               f"> {args.max_spread*100:.0f}c)")
            elif kind == "team" and not normalize_team(name):
                unknown.append(f"{event_ticker}: {name!r}")
            else:
                cands.append((name, q["ask"], q["liq"], q["spread"]))

        # pass 2 — market-quality gate. A field whose YES asks sum far past 100%
        # isn't price-discovering (Hart: a nobody prices shorter than McDavid,
        # 624% overround). Drop the entire market rather than trust any of it.
        orr = sum(a for _, a, _, _ in cands)
        status = "kept"
        if cands and orr > args.max_overround:
            dropped.append(f"{event_ticker} — overround {orr*100:.0f}% "
                           f"> {args.max_overround*100:.0f}% ({len(cands)} selections)")
            status = "DROPPED"
        print(f"  [{event_ticker}] overround {orr*100:.0f}%  "
              f"({len(cands)} pass per-selection gate)  ->  {status}")
        if status == "DROPPED":
            counts[event_ticker] = 0
            continue

        # pass 3 — emit the survivors
        n = 0
        for name, ask, liq, spread in cands:
            odds = prob_to_american(ask)
            if odds is None:
                skipped.append(f"{event_ticker}:{name} (bad price {ask:.3f})")
                continue
            if not args.write:
                sp = f"{spread*100:4.0f}c" if spread is not None else "  — "
                print(f"    {section:11} {name:30} {ask*100:5.1f}c  {odds:+6d}  "
                      f"${liq:,.0f}  spread {sp}")
            elif kind == "team":
                set_to_win(doc, section, name, BOOK, odds)
                set_liq(doc, section, name, BOOK, liq, is_player=False)
            else:
                set_award(doc, section, name, "", BOOK, odds)
                set_liq(doc, section, name, BOOK, liq, is_player=True)
            n += 1
        counts[event_ticker] = n

    print("  Kalshi selections priced:", counts)
    if dropped:
        print("  MARKETS DROPPED (overround too high — not price-discovering):")
        for d in dropped:
            print(f"     - {d}")
    if unknown:
        print("  UNKNOWN TEAM NAMES (tell Claude to add aliases):")
        for u in sorted(set(unknown)):
            print(f"     - {u}")
    if skipped:
        print(f"  skipped {len(skipped)} selections (per-selection gate):")
        for s in sorted(set(skipped))[:40]:
            print(f"     - {s}")

    if args.write:
        stamp_book(doc, BOOK)
        save(doc)  # always save — purge must persist even if a market was dropped


if __name__ == "__main__":
    main()
