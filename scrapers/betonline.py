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

from common import (CACHE_DIR, load, save, set_to_win, set_playoff,
                    set_team_points, set_award, classify_special, set_special)
from teams import TEAMS, normalize_team

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
    args = ap.parse_args()
    files = [args.file] if args.file else sorted(glob.glob(os.path.join(CACHE_DIR, "betonline*.har")))
    if not files:
        print(f"No capture. Save the HAR as {CACHE_DIR}\\betonline.har")
        return

    all_markets = []
    for fp in files:
        for payload in har_payloads(fp):
            all_markets += markets_from(payload)
    print(f"markets found: {len(all_markets)}")

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
