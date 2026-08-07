r"""BetOnline NHL futures scraper (LOCAL, capture-based).

Odds API (via inspect_har): api-offering.betonline.ag .../get-contests-by-contest-type2
Structure:
  ContestOfferings.ContestType2  -> market group ("Conference Futures", ...)
  ContestOfferings.DateGroup[].DescriptionGroup[].TimeGroup[].ContestExtended
    .Description   -> market name ("Eastern Conference Champion 2026/27",
                      "<Team> Regular Season Points", "Vezina Trophy ...")
    .ContestGroupLine[].Contestants[] -> outcomes
        .Name (team / player / "Over"/"Under"/"Yes"/"No")
        .ThresholdLine (e.g. 95.5 for points totals)
        .Line.MoneyLine.Line -> American odds (int)

Capture the futures page as a HAR (F12 -> Network -> reload + click futures tabs
-> Save all as HAR with content -> scrapers/.cache/betonline.har), then:

    python scrapers/betonline.py            # catalog (desc + contestants)
    python scrapers/betonline.py --write     # route into odds.json
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

from common import (CACHE_DIR, load, save, set_to_win, set_playoff,
                    set_team_points, set_award, classify_special, set_special)
from teams import TEAMS, normalize_team

# Direct-fetch: POST each futures contest the page requests (static gsetting, no
# auth/cookies). HAR is the fallback if BetOnline ever gates these.
_ENDPOINT = "https://api-offering.betonline.ag/api/offering/Sports/get-contests-by-contest-type2"
_QUERIES = [
    ("nhl-futures", "stanley-cup"),
    ("nhl-futures", "conference-futures"),
    ("nhl-futures", "division-futures"),
    ("nhl-futures", "specials"),
    ("nhl-player-futures", "hart-memorial-trophy"),
    ("nhl-player-futures", "vezina-trophy"),
    ("nhl-player-futures", "james-norris-memorial-trophy"),
    ("nhl-player-futures", "calder-memorial-trophy"),
    ("nhl-team-points", "regular-season-points"),
    ("nhl-playoff-specials", "to-make-the-playoffs"),
]
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Origin": "https://www.betonline.ag",
    "Referer": "https://www.betonline.ag/",
    "gsetting": "bolsassite",
    "utc-offset": "240",
}


def fetch_direct():
    """POST each futures contest directly. Returns [payload,...] with
    ContestOfferings; [] on failure so the caller falls back to a saved HAR."""
    try:
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        pass
    out = []
    for ct, ct2 in _QUERIES:
        try:
            r = requests.post(_ENDPOINT, headers=_HEADERS, timeout=25,
                              json={"ContestType": ct, "ContestType2": ct2, "filterTime": 0})
        except Exception as e:  # noqa: BLE001
            print(f"  {ct2}: fetch error {e}")
            continue
        if r.status_code != 200:
            print(f"  {ct2}: HTTP {r.status_code}")
            continue
        try:
            obj = r.json()
        except ValueError:
            print(f"  {ct2}: non-JSON response")
            continue
        if isinstance(obj, dict) and obj.get("ContestOfferings"):
            out.append(obj)
        else:
            print(f"  {ct2}: 200 but no ContestOfferings")
    return out

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

BOOK = "betonline"
AWARD_KW = {"hart": "hart", "norris": "norris", "vezina": "vezina", "calder": "calder",
            "jack adams": "jack_adams", "art ross": "art_ross",
            "rocket richard": "rocket_richard", "richard": "rocket_richard", "selke": "selke"}
_DIV = ("atlantic", "metropolitan", "central", "pacific")


def har_payloads(fp):
    with open(fp, encoding="utf-8") as f:
        raw = json.load(f)
    entries = (raw.get("log", {}) or {}).get("entries") if isinstance(raw, dict) else None
    if entries is None:
        return [raw]
    out = []
    for e in entries:
        if "get-contests" not in e.get("request", {}).get("url", ""):
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
        if isinstance(obj, dict) and obj.get("ContestOfferings"):
            out.append(obj)
    return out


def markets_from(payload):
    """Flatten to [{id, desc, group, ct2, conts:[{name, american, threshold}]}]."""
    co = payload.get("ContestOfferings") or {}
    ct2 = co.get("ContestType2") or co.get("ContestType") or ""
    out = []
    for dg in co.get("DateGroup", []) or []:
        for grp in dg.get("DescriptionGroup", []) or []:
            for tg in grp.get("TimeGroup", []) or []:
                ce = tg.get("ContestExtended") or {}
                desc = ce.get("Description") or grp.get("Description") or ""
                conts = []
                for gl in ce.get("ContestGroupLine", []) or []:
                    for c in gl.get("Contestants", []) or []:
                        ml = (c.get("Line", {}) or {}).get("MoneyLine", {}) or {}
                        if ml.get("Line") is None:
                            continue
                        conts.append({"name": c.get("Name", ""), "american": ml.get("Line"),
                                      "threshold": c.get("ThresholdLine")})
                if conts:
                    out.append({"id": ce.get("ID"), "desc": desc, "group": ce.get("Group", ""),
                                "ct2": ct2, "conts": conts})
    return out


def team_in_text(text):
    low = " " + text.lower() + " "
    for t in TEAMS:
        if t.lower() in low:
            return t
    for t in TEAMS:
        if f" {t.split()[-1].lower()} " in low:  # nickname
            return t
    return None


def route(markets, doc, counts, unmatched, seen):
    for m in markets:
        if m["id"] in seen:
            continue
        seen.add(m["id"])
        conts, desc = m["conts"], m["desc"]
        nl = f"{desc} {m['group']} {m['ct2']}".lower()
        names = {c["name"] for c in conts}
        team_conts = [(normalize_team(c["name"]), c) for c in conts
                      if normalize_team(c["name"]) in TEAMS]

        # 0) Cup Specials — champion's conference/division/state (outcomes are
        # conference/state names, not teams, so the team-outright logic misses them)
        sp = classify_special(nl)
        if sp:
            for c in conts:
                if c["name"] not in ("Yes", "No", "Over", "Under") and c.get("american") is not None:
                    set_special(doc, sp, c["name"], BOOK, c["american"]); counts[f"special:{sp}"] += 1
        # 1) team-points Over/Under
        elif names & {"Over", "Under"}:
            team = team_in_text(desc)
            line = next((c["threshold"] for c in conts if c["threshold"]), None)
            over = next((c["american"] for c in conts if c["name"] == "Over"), None)
            under = next((c["american"] for c in conts if c["name"] == "Under"), None)
            if team and line:
                set_team_points(doc, team, BOOK, line, over, under); counts["points"] += 1
            else:
                unmatched.append(f"[O/U] {desc}  (team={team} line={line})")
        # 2) playoffs — per-team Yes/No (set BOTH sides), or make/miss team-lists
        elif "playoff" in nl:
            team = team_in_text(desc)
            if names & {"Yes", "No"}:
                yp = next((c["american"] for c in conts if c["name"] == "Yes"), None)
                np = next((c["american"] for c in conts if c["name"] == "No"), None)
                # a "to miss" market flips which side is make vs miss
                make = np if "miss" in nl else yp
                miss = yp if "miss" in nl else np
                if team and make is not None:
                    set_playoff(doc, team, BOOK, "yes", make); counts["po_yes"] += 1
                if team and miss is not None:
                    set_playoff(doc, team, BOOK, "no", miss); counts["po_no"] += 1
                if not team:
                    unmatched.append(f"[PO Yes/No] {desc}")
            elif team_conts:  # e.g. "Make/Miss Playoffs - Western Conference" (team list)
                side = "no" if "miss" in nl else "yes"
                for t, c in team_conts:
                    set_playoff(doc, t, BOOK, side, c["american"]); counts[f"po_{side}"] += 1
            else:
                unmatched.append(f"[PO] {desc}")
        # 2b) other Yes/No props (to-win-conference etc.) — covered by outrights, skip
        elif names & {"Yes", "No"}:
            continue
        # 3) team outrights (cup / conference / division)
        elif len(team_conts) >= 6:
            if "president" in nl:
                market = "presidents"
            elif "worst" in nl or "fewest" in nl or "least" in nl:
                market = "worst"
            elif "stanley cup" in nl or len(team_conts) >= 24:
                market = "cup"
            elif "conference" in nl:
                market = "conference"
            elif "division" in nl or any(d in nl for d in _DIV) or len(team_conts) <= 8:
                market = "division"
            else:
                market = {32: "cup", 16: "conference", 8: "division"}.get(len(team_conts))
            if market:
                for t, c in team_conts:
                    set_to_win(doc, market, t, BOOK, c["american"]); counts[market] += 1
            else:
                unmatched.append(f"[teams x{len(team_conts)}] {desc}")
        # 4) awards (players)
        elif any(k in nl for k in AWARD_KW):
            cat = next(c for k, c in AWARD_KW.items() if k in nl)
            for c in conts:
                if c["name"] not in ("Yes", "No", "Over", "Under"):
                    set_award(doc, cat, c["name"], "", BOOK, c["american"]); counts[f"award:{cat}"] += 1
        else:
            unmatched.append(f"{desc}  | contestants: {sorted(names)[:4]}")


def catalog(all_markets):
    seen = set()
    for m in all_markets:
        if m["id"] in seen:
            continue
        seen.add(m["id"])
        print(f"\n• [{m['ct2']}] {m['desc']}   ({len(m['conts'])} outcomes)")
        for c in m["conts"][:6]:
            thr = f"  thr={c['threshold']}" if c["threshold"] else ""
            print(f"     {c['name']!r}: {c['american']}{thr}")
        if len(m["conts"]) > 6:
            print(f"     ... +{len(m['conts'])-6} more")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=None)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--har", action="store_true", help="skip direct fetch, use saved HAR only")
    args = ap.parse_args()

    payloads = []
    if args.file:
        payloads = har_payloads(args.file)
    elif args.har:
        for fp in sorted(glob.glob(os.path.join(CACHE_DIR, "betonline*.har"))):
            payloads += har_payloads(fp)
    else:
        payloads = fetch_direct()  # direct API first
        if payloads:
            print(f"  (direct fetch: {len(payloads)} contest payloads)")
        else:
            print("  direct fetch returned nothing — falling back to saved HAR")
            for fp in sorted(glob.glob(os.path.join(CACHE_DIR, "betonline*.har"))):
                payloads += har_payloads(fp)

    all_markets = []
    for payload in payloads:
        all_markets += markets_from(payload)
    print(f"markets found: {len(all_markets)}")
    if not all_markets:
        print(f"  No data. Direct fetch failed and no HAR at {CACHE_DIR}\\betonline.har")
        return

    if args.write:
        doc = load()
        counts, unmatched, seen = defaultdict(int), [], set()
        route(all_markets, doc, counts, unmatched, seen)
        print("  wrote BetOnline:", dict(counts))
        if unmatched:
            print("  UNMATCHED (paste to Claude):")
            for u in sorted(set(unmatched)):
                print(f"     - {u}")
        if sum(counts.values()):
            save(doc)
    else:
        catalog(all_markets)
        print("\nPaste the catalog back to Claude if anything looks misrouted.")


if __name__ == "__main__":
    main()
