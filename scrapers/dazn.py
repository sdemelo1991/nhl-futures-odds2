r"""DAZN Bet (Ontario) NHL futures scraper (LOCAL, direct API).

DAZN Bet runs on the Altenar platform. Outright futures come from one public
widget call (no auth), so this is DIRECT-FETCHABLE with a HAR fallback:

  https://sb2frontend-altenar2.biahosted.com/api/widget/GetOutrightEvents
      ?culture=en-CA&integration=daznbet.on&champIds=3232   (3232 = NHL)

Response: markets[] {id, name, oddIds[]} + odds[] {id, name (competitor),
price (DECIMAL)}. Route by market name; each oddId -> a competitor + decimal
price -> American. DAZN offers Cup, Regular-Season Winner (=presidents),
Conference, Division, and per-team Make-Playoffs (Yes/No). No awards/points.

  python scrapers/dazn.py             # catalog from direct fetch (or dazn*.har)
  python scrapers/dazn.py --write     # route into odds.json
"""
import argparse
import base64
import glob
import json
import os
import sys
from collections import defaultdict

import requests
import time

from common import (CACHE_DIR, load, save, set_playoff, set_to_win, stamp_book,
                    classify_special, set_special)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from teams import normalize_team  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

BOOK = "dazn"
_Q = ("culture=en-CA&timezoneOffset=240&integration=daznbet.on&deviceType=1"
      "&numFormat=en-GB&countryCode=CA&stateCode=ON")
URL = ("https://sb2frontend-altenar2.biahosted.com/api/widget/GetOutrightEvents"
       "?" + _Q + "&eventCount=0&sportId=0&champIds=3232")
# GetOutrightEvents truncates each "win" market to the top 5 (the collapsed
# preview). The full participant list for one event comes from GetEventDetails.
EVENT_DETAILS_URL = ("https://sb2frontend-altenar2.biahosted.com/api/widget/"
                     "GetEventDetails?" + _Q + "&eventId={}")
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "application/json",
           "Cache-Control": "no-cache", "Pragma": "no-cache"}


def _cb():
    return f"&_={int(time.time() * 1000)}"  # cache-buster; both URLs already carry a query string
SKIP = ("winning conference", "winning division", "winning nationality")


def dec_to_am(dec):
    dec = float(dec)
    if dec <= 1.0:
        return None
    return round((dec - 1) * 100) if dec >= 2 else round(-100 / (dec - 1))


def har_payloads(fp):
    with open(fp, encoding="utf-8") as f:
        raw = json.load(f)
    out = []
    for e in (raw.get("log", {}) or {}).get("entries", []) or []:
        if "GetOutrightEvents" not in e.get("request", {}).get("url", ""):
            continue
        content = (e.get("response", {}) or {}).get("content", {}) or {}
        b = content.get("text")
        if b and content.get("encoding") == "base64":
            try:
                b = base64.b64decode(b).decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                continue
        try:
            obj = json.loads(b)
        except (ValueError, TypeError):
            continue
        if isinstance(obj, dict) and obj.get("markets") is not None:
            out.append(obj)
    return out


def fetch_direct():
    try:
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        pass
    r = requests.get(URL + _cb(), headers=HEADERS, timeout=25)
    r.raise_for_status()
    return [r.json()]


def market_type(name):
    nl = name.lower()
    if any(k in nl for k in SKIP):
        return None
    if "stanley cup winner" in nl:
        return "cup"
    if "winner (regular season)" in nl:
        return "presidents"
    if "conference winner" in nl:
        return "conference"
    if "division - winner" in nl:
        return "division"
    if "to reach the playoffs" in nl:
        return "playoffs"
    return None


def fetch_event_odds(eid):
    """Full participant list for one outright event (un-truncated)."""
    try:
        j = requests.get(EVENT_DETAILS_URL.format(eid) + _cb(), headers=HEADERS, timeout=20).json()
        return [o for o in j.get("odds", []) or [] if o.get("price")]
    except Exception:  # noqa: BLE001
        return None


def route(payloads, doc, counts, unmatched, seen, live=False):
    for j in payloads:
        odds_by_id = {o["id"]: o for o in j.get("odds", []) or []}
        ev_of_market = {mid: e.get("id") for e in j.get("events", []) or []
                        for mid in e.get("marketIds", []) or []}
        for m in j.get("markets", []) or []:
            mid = m.get("id")
            if mid in seen:
                continue
            seen.add(mid)
            name = m.get("name", "") or ""
            summary_ods = [o for o in (odds_by_id.get(i) for i in m.get("oddIds", []) or []) if o]
            sp = classify_special(name)
            if sp:  # champion's conference/division/state — fetch full list like a win market
                ods = None
                if live and ev_of_market.get(mid):
                    ods = fetch_event_odds(ev_of_market[mid])
                for o in (ods or summary_ods):
                    am = dec_to_am(o.get("price"))
                    if o.get("name") and am is not None:
                        set_special(doc, sp, o["name"], BOOK, am); counts[f"special:{sp}"] += 1
                continue
            mt = market_type(name)
            if mt is None:
                if summary_ods:
                    unmatched.append(name)
                continue
            if mt == "playoffs":  # 2-way, never truncated
                team = name.split("To Reach The Playoffs - ")[-1].strip()
                for o in summary_ods:
                    side = (o.get("name") or "").strip().lower()
                    am = dec_to_am(o["price"])
                    if side in ("yes", "no") and am is not None:
                        set_playoff(doc, team, BOOK, side, am)
                        counts["playoffs"] += 1
                continue
            # win markets are truncated to 5 in the summary — fetch the full list
            ods = None
            if live and ev_of_market.get(mid):
                ods = fetch_event_odds(ev_of_market[mid])
            if not ods:
                ods = summary_ods  # HAR / offline fallback (top 5 only)
            for o in ods:
                am = dec_to_am(o.get("price"))
                if o.get("name") and am is not None:
                    set_to_win(doc, mt, o["name"], BOOK, am)
                    counts[mt] += 1


def catalog(payloads):
    for j in payloads:
        odds_by_id = {o["id"]: o for o in j.get("odds", []) or []}
        for m in j.get("markets", []) or []:
            ods = [odds_by_id.get(i) for i in m.get("oddIds", []) or []]
            ods = [o for o in ods if o]
            tag = market_type(m.get("name", "")) or "—skip—"
            print(f"* [{tag}] {m.get('name')}  ({len(ods)} odds)")
            for o in ods[:4]:
                print(f"     {o.get('price'):>7}  {o.get('name')}")


def get_payloads(args):
    if not args.file:
        try:
            print("  fetching DAZN outrights directly...")
            return fetch_direct()
        except Exception as e:  # noqa: BLE001
            print(f"  direct fetch failed ({e}); falling back to HAR")
    files = [args.file] if args.file else sorted(glob.glob(os.path.join(CACHE_DIR, "dazn*.har")))
    return [p for fp in files for p in har_payloads(fp)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=None, help="a dazn HAR (else direct fetch / .cache/dazn*.har)")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    payloads = get_payloads(args)
    if not payloads:
        print(f"No data. Save a capture as {CACHE_DIR}\\dazn.har or check connectivity.")
        return

    if not args.write:
        catalog(payloads)
        print("\n(run with --write to route into odds.json)")
        return

    doc = load()
    counts, unmatched, seen = defaultdict(int), [], set()
    route(payloads, doc, counts, unmatched, seen, live=not args.file)  # per-event full lists
    print("  wrote DAZN:", dict(counts))
    if unmatched:
        print("  UNMATCHED (skipped):")
        for u in sorted(set(unmatched)):
            print(f"     - {u}")
    if sum(counts.values()):
        stamp_book(doc, BOOK)
        save(doc)


if __name__ == "__main__":
    main()
