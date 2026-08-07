r"""DraftKings NHL futures scraper (LOCAL).

DraftKings shields its API with Akamai bot protection, so direct requests get a
403 "Access Denied" — we can't fetch it server-side like Pinnacle/FanDuel.
Instead we parse a response your BROWSER already fetched (it passes Akamai).

=== HOW TO GET DK DATA ===
1. Open your DK NHL futures page in Chrome.
2. F12 → Network tab → filter box: type  sportscontent  (or  eventgroup ).
3. Reload the page. Click requests until the Response tab shows team names +
   odds (JSON). Good ones usually have "leagues", "categories", "eventgroup",
   or "sportscontent" in the URL.
4. Right-click that request → Copy → "Copy response".
5. Paste it into a file:  scrapers\.cache\dk_capture.json
6. Run:  python scrapers\draftkings.py --file scrapers\.cache\dk_capture.json

The scanner auto-detects DK's JSON shape (classic eventGroup OR modern
selections/markets) and prints a catalog. Paste that catalog back to Claude.

(Direct fetch modes --url / eventgroup are kept for the rare case Akamai lets a
captured URL through, but --file is the reliable path.)
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

from common import (dump_raw, load, save, set_to_win, set_playoff,
                    set_team_points, set_award, set_player_prop, CACHE_DIR,
                    classify_special, set_special)
from teams import TEAMS, normalize_team

try:  # PowerShell's cp1252 console crashes on unicode (−, •) — force UTF-8
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

_VERIFY = True
HOST = "https://sportsbook.draftkings.com"
SITE = "US-SB"
EG = 42133
BOOK = "draftkings"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept": "application/json", "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://sportsbook.draftkings.com/leagues/hockey/nhl",
    "sec-ch-ua": '"Chromium";v="126", "Not.A/Brand";v="24"',
    "sec-fetch-dest": "empty", "sec-fetch-mode": "cors", "sec-fetch-site": "same-origin",
}


def configure_tls(insecure):
    global _VERIFY
    if insecure:
        _VERIFY = False
        import urllib3
        urllib3.disable_warnings()
        print("  (TLS verification DISABLED via --insecure)")
        return
    try:
        import truststore
        truststore.inject_into_ssl()
        print("  (using OS trust store via truststore)")
    except ImportError:
        print("  (truststore not installed — run: pip install truststore)")


def get(url):
    print(f"GET {url}")
    r = requests.get(url, headers=HEADERS, timeout=25, verify=_VERIFY)
    if r.status_code != 200:
        print(f"  !! HTTP {r.status_code}\n{r.text[:300]}")
        r.raise_for_status()
    return r.json()


# --- catalog printers (shape auto-detect) ----------------------------------
def _classic(payload):
    eg = payload.get("eventGroup", {}) or {}
    cats = eg.get("offerCategories", []) or []
    print(f"\n--- categories ({len(cats)}) ---")
    for c in cats:
        print(f"   [{c.get('offerCategoryId')}] {c.get('name')}")
    for c in cats:
        for d in c.get("offerSubcategoryDescriptors", []) or []:
            sub = d.get("offerSubcategory") or {}
            outs = []
            for group in sub.get("offers") or []:
                for offer in group or []:
                    for o in offer.get("outcomes", []) or []:
                        outs.append((o.get("label", "?"), o.get("oddsAmerican", "?")))
            if outs:
                print(f"\n• {c.get('name')} › {d.get('name')}   ({len(outs)} outcomes)")
                for lab, od in outs[:8]:
                    print(f"     {lab}: {od}")
                if len(outs) > 8:
                    print(f"     ... +{len(outs)-8} more")


def _american(sel):
    dd = sel.get("displayOdds") or sel.get("odds") or {}
    if isinstance(dd, dict):
        return dd.get("american") or dd.get("americanOdds") or dd.get("value")
    return sel.get("americanOdds") or sel.get("oddsAmerican")


def _modern(payload):
    markets = payload.get("markets") or []
    selections = payload.get("selections") or []
    events = payload.get("events") or []
    mkt_name = {m.get("id"): m.get("name", "?") for m in markets}
    ev_name = {e.get("id"): e.get("name", "") for e in events}
    mkt_event = {m.get("id"): m.get("eventId") for m in markets}
    by_mkt = {}
    for s in selections:
        by_mkt.setdefault(s.get("marketId"), []).append(s)
    print(f"\n--- markets: {len(markets)}, selections: {len(selections)} ---")
    for mid, sels in by_mkt.items():
        name = mkt_name.get(mid, "?")
        ev = ev_name.get(mkt_event.get(mid), "")
        print(f"\n• {name}   [{ev}]   ({len(sels)} selections)")
        for s in sels[:8]:
            print(f"     {s.get('label', '?')}: {_american(s)}")
        if len(sels) > 8:
            print(f"     ... +{len(sels)-8} more")


def catalog_from(payload):
    if "eventGroup" in payload:
        _classic(payload)
    elif "selections" in payload or "markets" in payload:
        _modern(payload)
    else:
        print("\nUnrecognized JSON shape. Top-level keys:", list(payload.keys())[:20])
        print("Paste this file (or its top-level structure) to Claude to build the parser.")


# --- write: route captured markets into odds.json --------------------------
_LINE_RE = re.compile(r"(Over|Under)\s+(\d+(?:\.\d+)?)", re.I)
_DIV_RE = re.compile(r"(atlantic|metropolitan|central|pacific)")
# player X+ props: market = "Player to Record 40+ Regular Season Goals", selections = players
_PROP_RE = re.compile(r"player to record (\d+)\+ regular season (points|goals)", re.I)
# single player-named milestone, e.g. "Connor McDavid to Record 154+ Regular Season Points" (Yes)
_PLAYER_MS_RE = re.compile(r"^(.+?) to record (\d+)\+ regular season (points|goals)$", re.I)
AWARD_MAP = {"hart": "hart", "norris": "norris", "vezina": "vezina", "calder": "calder",
             "jack adams": "jack_adams", "art ross": "art_ross",
             "rocket richard": "rocket_richard", "richard": "rocket_richard", "selke": "selke"}


def dk_team(label):
    """DK labels teams like 'FLA Panthers' / 'UTA Mammoth' / 'NY Rangers'.
    Normalize via the full label, then the nickname (drop the short code)."""
    t = normalize_team(label)
    if t in TEAMS:
        return t
    parts = label.split(" ", 1)
    if len(parts) == 2:
        t2 = normalize_team(parts[1])
        if t2 in TEAMS:
            return t2
    return None  # not a real team (e.g. DK's "Field" / "Original Six" exotics)


def to_int(am):
    # DK encodes odds as strings with a unicode minus ("−"), not ASCII "-".
    try:
        s = str(am)
        for ch in ("−", "–", "—"):  # minus, en-dash, em-dash
            s = s.replace(ch, "-")
        return int(s.replace("+", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def sel_odds(s):
    return to_int(_american(s))


def route(payload, doc, counts, unmatched, seen):
    markets = {m.get("id"): m for m in payload.get("markets", []) or []}
    by_mkt = defaultdict(list)
    for s in payload.get("selections", []) or []:
        by_mkt[s.get("marketId")].append(s)

    for mid, sels in by_mkt.items():
        if mid in seen:  # same market re-fired across tabs in the HAR
            continue
        seen.add(mid)
        name = (markets.get(mid, {}) or {}).get("name", "") or ""
        low = name.lower()
        exotic = any(x in low for x in ("exact", "matchup", "first ", "not ", " of ",
                                        "state", "province", "series", "margin"))

        sp = classify_special(name)
        if sp:  # champion's conference/division/state (DK tags these as 'exotic' by title)
            for s in sels:
                od, label = sel_odds(s), s.get("label", "")
                if label and od is not None:
                    set_special(doc, sp, label, BOOK, od); counts[f"special:{sp}"] += 1
            continue

        if "stanley cup" in low and ("champion" in low or "winner" in low) and not exotic:
            for s in sels:
                od, t = sel_odds(s), dk_team(s.get("label", ""))
                if od is not None and t:  # skip "Field" / "Original Six" exotics
                    set_to_win(doc, "cup", t, BOOK, od); counts["cup"] += 1
        elif "conference" in low and ("champion" in low or "winner" in low) and not exotic:
            for s in sels:
                od, t = sel_odds(s), dk_team(s.get("label", ""))
                if od is not None and t:
                    set_to_win(doc, "conference", t, BOOK, od); counts["conf"] += 1
        elif _DIV_RE.search(low) and "division" in low and ("champion" in low or "winner" in low) and not exotic:
            for s in sels:
                od, t = sel_odds(s), dk_team(s.get("label", ""))
                if od is not None and t:
                    set_to_win(doc, "division", t, BOOK, od); counts["div"] += 1
        elif "president" in low and not exotic:
            for s in sels:
                od, t = sel_odds(s), dk_team(s.get("label", ""))
                if od is not None and t:
                    set_to_win(doc, "presidents", t, BOOK, od); counts["presidents"] += 1
        elif ("worst" in low or "fewest" in low) and not exotic:
            for s in sels:
                od, t = sel_odds(s), dk_team(s.get("label", ""))
                if od is not None and t:
                    set_to_win(doc, "worst", t, BOOK, od); counts["worst"] += 1
        elif _PROP_RE.search(low):  # player X+ milestone (each selection is a player)
            m = _PROP_RE.search(low)
            cat, thr = m.group(2), int(m.group(1))
            for s in sels:
                od, player = sel_odds(s), s.get("label", "")
                if player and od is not None:
                    set_player_prop(doc, cat, player, "", BOOK, plus=thr, yes=od)
                    counts[f"prop_x+:{cat}"] += 1
        elif _PLAYER_MS_RE.match(name) and not low.startswith("team "):
            m = _PLAYER_MS_RE.match(name)  # single named-player milestone (Yes side)
            player, thr, cat = m.group(1).strip(), int(m.group(2)), m.group(3).lower()
            yes = next((sel_odds(s) for s in sels
                        if (s.get("label", "") or "").strip().lower() == "yes"), None)
            if yes is None and sels:
                yes = sel_odds(sels[0])
            if player and yes is not None:
                set_player_prop(doc, cat, player, "", BOOK, plus=thr, yes=yes)
                counts[f"prop_x+:{cat}"] += 1
        elif "regular season points" in low and len(sels) == 2 and \
                any("over" in (s.get("label", "").lower()) for s in sels):
            team = dk_team(re.sub(r"(?i)regular season points|o/u|total|-", "", name).strip())
            line = over = under = None
            for s in sels:
                mm = _LINE_RE.search(s.get("label", ""))
                if mm:
                    line = float(mm.group(2))
                    if mm.group(1).lower() == "over":
                        over = sel_odds(s)
                    else:
                        under = sel_odds(s)
            if team in TEAMS and line is not None:
                set_team_points(doc, team, BOOK, line, over, under); counts["points"] += 1
            else:
                unmatched.append(f"{name}  (points parse failed: team={team!r} line={line})")
        elif ("make" in low or "miss" in low) and not exotic:
            # DK splits playoffs into conference lists: East/West - Make, East/West - Miss.
            # "make" -> Yes side, "miss" -> No side (each a 16-team list).
            side = "no" if "miss" in low else "yes"
            for s in sels:
                od = sel_odds(s)
                if od is not None:
                    set_playoff(doc, dk_team(s.get("label", "")), BOOK, side, od); counts[f"po_{side}"] += 1
        else:
            cat = next((c for k, c in AWARD_MAP.items() if k in low and ("trophy" in low or "winner" in low)), None)
            if cat:
                for s in sels:
                    od = sel_odds(s)
                    if od is not None:
                        set_award(doc, cat, s.get("label", ""), "", BOOK, od); counts[f"award:{cat}"] += 1
            else:
                unmatched.append(name)


def load_payloads(fp):
    """Return a list of DK JSON payloads from a file. Handles a raw captured
    response (single payload) OR a .har export (many payloads — every recorded
    'markets' response across all the tabs you clicked)."""
    with open(fp, encoding="utf-8") as f:
        raw = json.load(f)
    entries = (raw.get("log", {}) or {}).get("entries") if isinstance(raw, dict) else None
    if not entries:
        return [raw]  # plain captured response
    out = []
    for e in entries:
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
        if isinstance(obj, dict) and ("selections" in obj or "markets" in obj):
            out.append(obj)
    return out


def write_all(files):
    doc = load()
    counts, unmatched, seen = defaultdict(int), [], set()
    for fp in files:
        payloads = load_payloads(fp)
        for payload in payloads:
            route(payload, doc, counts, unmatched, seen)
        print(f"  parsed {os.path.basename(fp)}  ({len(payloads)} market payload(s))")
    print("\n  wrote DraftKings:", dict(counts))
    if unmatched:
        print("  UNMATCHED markets (paste these to Claude to add routing):")
        for u in sorted(set(unmatched)):
            print(f"     - {u}")
    if sum(counts.values()):
        save(doc)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=None, help="parse/catalog a saved browser response")
    ap.add_argument("--write", action="store_true",
                    help="route all scrapers/.cache/dk_*.json (or --file) into odds.json")
    ap.add_argument("--url", default=None, help="fetch an exact captured URL (often Akamai-blocked)")
    ap.add_argument("--host", default=HOST)
    ap.add_argument("--site", default=SITE)
    ap.add_argument("--eg", type=int, default=EG)
    ap.add_argument("--insecure", action="store_true")
    args = ap.parse_args()

    if args.write:
        files = ([args.file] if args.file else
                 sorted(glob.glob(os.path.join(CACHE_DIR, "dk*.json"))) +
                 sorted(glob.glob(os.path.join(CACHE_DIR, "dk*.har"))))
        if not files:
            print(f"No captures. Save a DK response as {CACHE_DIR}\\dk_<name>.json "
                  f"or a HAR export as {CACHE_DIR}\\dk.har first.")
            return
        write_all(files)
        return

    if args.file:
        for payload in load_payloads(args.file):
            print(f"\nParsing payload from {os.path.basename(args.file)}")
            catalog_from(payload)
        print("\nPaste the catalog above back to Claude to build the DK mapping.")
        return

    configure_tls(args.insecure)
    url = args.url or f"{args.host}/sites/{args.site}/api/v5/eventgroups/{args.eg}?format=json"
    try:
        payload = get(url)
    except Exception as e:  # noqa: BLE001
        print(f"\nFETCH FAILED: {e}\nDK is Akamai-protected — use the --file capture route "
              f"(see the docstring at the top of this script).")
        sys.exit(1)
    dump_raw("dk_capture", payload)
    catalog_from(payload)
    print("\nPaste the catalog above back to Claude.")


if __name__ == "__main__":
    main()
