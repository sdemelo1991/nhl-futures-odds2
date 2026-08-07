r"""Kambi / Northstar Bets (Ontario) NHL futures scraper (LOCAL).

Odds API (via inspect_har): the Kambi listView
  eu.offering-api.kambicdn.com/offering/v2018/torstarcaon/listView/ice_hockey/nhl/all/all/competitions.json
Public GET (brand "torstarcaon"). Structure: top-level "events" -> each has
  event{name,id} + betOffers[] -> each betOffer has criterion{label} (market)
  + outcomes[] -> {label / participant, oddsAmerican, odds(milli-decimal), line}.

Phase 1 — catalog (default): parse the captured HAR and print every event +
betOffer criterion + outcomes so Claude can build the routing.

    python scrapers/kambi.py                 # from scrapers/.cache/kambi*.har
    python scrapers/kambi.py --file <path>

Phase 2 — --write (added once routing confirmed). Kambi is likely direct-
fetchable too, so it may become a one-command refresh.
"""
import argparse
import base64
import glob
import json
import os
import re
import sys
from collections import defaultdict

import requests

from common import (CACHE_DIR, load, save, set_to_win, set_award, set_playoff,
                    set_team_points, classify_special, set_special)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

BOOK = "kambi"
# Public Kambi listView (brand torstarcaon = Northstar Ontario) — direct-fetchable.
LISTVIEW_URL = ("https://eu.offering-api.kambicdn.com/offering/v2018/torstarcaon/"
                "listView/ice_hockey/nhl/all/all/competitions.json"
                "?lang=en_CA&market=CA-ON&client_id=200&channel_id=3")
# Per-team "<Team> Markets" events carry the To-reach-Playoffs + Season-Points
# betOffers, which the competitions listView returns empty. Fetch each by id.
EVENT_URL = ("https://eu.offering-api.kambicdn.com/offering/v2018/torstarcaon/"
             "betoffer/event/{}.json?lang=en_CA&market=CA-ON&client_id=200&channel_id=3")
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "application/json"}
AWARD_KW = {"calder": "calder", "norris": "norris", "vezina": "vezina", "hart": "hart",
            "jack adams": "jack_adams", "art ross": "art_ross",
            "rocket richard": "rocket_richard", "selke": "selke"}


def har_payloads(fp):
    with open(fp, encoding="utf-8") as f:
        raw = json.load(f)
    entries = (raw.get("log", {}) or {}).get("entries") if isinstance(raw, dict) else None
    if entries is None:
        return [raw]
    out = []
    for e in entries:
        url = e.get("request", {}).get("url", "")
        if "kambicdn" not in url or "listView" not in url:
            continue
        content = (e.get("response", {}) or {}).get("content", {}) or {}
        body = content.get("text")
        if not body:
            continue
        if content.get("encoding") == "base64":
            try:
                body = base64.b64decode(body).decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                continue
        try:
            obj = json.loads(body)
        except (ValueError, TypeError):
            continue
        if isinstance(obj, dict) and obj.get("events") is not None:
            out.append(obj)
    return out


def am(o):
    v = o.get("oddsAmerican")
    if v not in (None, "", "0"):
        return v
    d = o.get("odds")  # milli-decimal, e.g. 36000 -> 36.0
    if d:
        dec = d / 1000.0
        return round((dec - 1) * 100) if dec >= 2 else round(-100 / (dec - 1))
    return None


def line_of(o):
    ln = o.get("line")
    return ln / 1000.0 if isinstance(ln, (int, float)) and ln else None


def catalog(payloads):
    seen = set()
    n = 0
    for obj in payloads:
        for ev in obj.get("events", []) or []:
            e = ev.get("event", {}) or {}
            ename = e.get("name") or ev.get("name") or "?"
            for bo in ev.get("betOffers", []) or []:
                crit = (bo.get("criterion", {}) or {}).get("label", "?")
                boid = bo.get("id")
                if boid in seen:
                    continue
                seen.add(boid)
                outs = bo.get("outcomes", []) or []
                n += 1
                print(f"\n• event={ename!r}  criterion={crit!r}  ({len(outs)} outcomes)")
                for o in outs[:8]:
                    lab = o.get("label") or o.get("participant") or "?"
                    ln = line_of(o)
                    ln_s = f"  line={ln:g}" if ln else ""
                    print(f"     {lab!r}: {am(o)}{ln_s}")
                if len(outs) > 8:
                    print(f"     ... +{len(outs)-8} more")
    print(f"\n=== {n} distinct betOffers ===")
    print("Paste this catalog back to Claude to build the Kambi routing.")


def kam_int(o):
    v = o.get("oddsAmerican")
    if v not in (None, "", "0"):
        try:
            return int(str(v).replace("−", "-").replace("+", "").strip())
        except (TypeError, ValueError):
            pass
    d = o.get("odds")  # milli-decimal fallback
    if d:
        dec = d / 1000.0
        return round((dec - 1) * 100) if dec >= 2 else round(-100 / (dec - 1))
    return None


def _teams(doc, market, outs, counts):
    for o in outs:
        nm = o.get("label") or o.get("participant")
        od = kam_int(o)
        if nm and od is not None:
            set_to_win(doc, market, nm, BOOK, od); counts[market] += 1


def route(payloads, doc, counts, unmatched, seen):
    for obj in payloads:
        for ev in obj.get("events", []) or []:
            ename = (ev.get("event", {}) or {}).get("name", "") or ""
            el = ename.lower()
            for bo in ev.get("betOffers", []) or []:
                boid = bo.get("id")
                if boid in seen:
                    continue
                seen.add(boid)
                crit = (bo.get("criterion", {}) or {}).get("label", "") or ""
                cl = crit.lower()
                outs = bo.get("outcomes", []) or []
                if " @ " in ename or any(k in cl for k in
                                         ("moneyline", "puck line", "total goals", "handicap")):
                    continue  # game markets
                sp = classify_special(crit) or classify_special(ename)
                if sp:  # champion's conference/division/state (attribute market)
                    for o in outs:
                        nm, od = o.get("label") or o.get("participant"), kam_int(o)
                        if nm and od is not None:
                            set_special(doc, sp, nm, BOOK, od); counts[f"special:{sp}"] += 1
                    continue
                if "winner - including playoffs" in cl or ("championship" in el and "winner" in cl):
                    _teams(doc, "cup", outs, counts)
                elif "conference winner" in cl:
                    _teams(doc, "conference", outs, counts)
                elif "division winner" in cl:
                    _teams(doc, "division", outs, counts)
                elif "presidents" in cl or "presidents" in el:
                    _teams(doc, "presidents", outs, counts)
                else:
                    cat = next((c for k, c in AWARD_KW.items() if k in cl or k in el), None)
                    if cat:
                        for o in outs:
                            nm, od = o.get("label") or o.get("participant"), kam_int(o)
                            if nm and od is not None:
                                set_award(doc, cat, nm, "", BOOK, od); counts[f"award:{cat}"] += 1
                    elif outs:
                        unmatched.append(f"{ename} | {crit}")


def fetch_direct():
    try:
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        pass
    r = requests.get(LISTVIEW_URL, headers=HEADERS, timeout=25)
    r.raise_for_status()
    return [r.json()]


def route_team_markets(payloads, doc, counts):
    """Fetch each '<Team> Markets' event and route its To-reach-Playoffs (Yes/No)
    and Team-Total-Points (Over/Under) betOffers. These aren't in the listView."""
    team_events = {}
    for obj in payloads:
        for ev in obj.get("events", []) or []:
            e = ev.get("event", {}) or {}
            nm = e.get("name", "") or ""
            if "Markets" in nm and e.get("id"):
                team = re.sub(r"\s*Markets\b.*$", "", nm).strip()
                team_events[team] = e["id"]
    for team, eid in team_events.items():
        try:
            data = requests.get(EVENT_URL.format(eid), headers=HEADERS, timeout=20).json()
        except Exception:  # noqa: BLE001
            continue
        for bo in data.get("betOffers", []) or []:
            cl = ((bo.get("criterion", {}) or {}).get("label", "") or "").lower()
            outs = bo.get("outcomes", []) or []
            if "reach the playoffs" in cl:
                for o in outs:
                    side = (o.get("label") or "").strip().lower()
                    od = kam_int(o)
                    if side in ("yes", "no") and od is not None:
                        set_playoff(doc, team, BOOK, side, od); counts["playoffs"] += 1
            elif "total points" in cl and "regular season" in cl:
                line = over = under = None
                for o in outs:
                    lab = (o.get("label") or "").strip().lower()
                    od, ln = kam_int(o), line_of(o)
                    if lab == "over":
                        over, line = od, ln or line
                    elif lab == "under":
                        under, line = od, ln or line
                if line is not None and (over is not None or under is not None):
                    set_team_points(doc, team, BOOK, line, over, under); counts["team_points"] += 1


def write_all(payloads):
    doc = load()
    counts, unmatched, seen = defaultdict(int), [], set()
    route(payloads, doc, counts, unmatched, seen)
    try:
        route_team_markets(payloads, doc, counts)
    except Exception as e:  # noqa: BLE001
        print(f"  (team-markets fetch skipped: {e})")
    print("  wrote Kambi:", dict(counts))
    if unmatched:
        print("  UNMATCHED (skipped):")
        for u in sorted(set(unmatched)):
            print(f"     - {u}")
    if sum(counts.values()):
        save(doc)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=None)
    ap.add_argument("--write", action="store_true", help="route into odds.json (direct fetch, HAR fallback)")
    args = ap.parse_args()

    if args.write:
        try:
            payloads = fetch_direct()
            print("  fetched Kambi listView directly")
        except Exception as e:  # noqa: BLE001
            print(f"  direct fetch failed ({e}); falling back to HAR")
            files = sorted(glob.glob(os.path.join(CACHE_DIR, "kambi*.har")))
            payloads = [p for fp in files for p in har_payloads(fp)]
        write_all(payloads)
        return

    files = [args.file] if args.file else sorted(glob.glob(os.path.join(CACHE_DIR, "kambi*.har")))
    if not files:
        print(f"No capture. Save the HAR as {CACHE_DIR}\\kambi.har")
        return
    payloads = []
    for fp in files:
        payloads += har_payloads(fp)
    print(f"listView payloads: {len(payloads)}")
    catalog(payloads)


if __name__ == "__main__":
    main()
