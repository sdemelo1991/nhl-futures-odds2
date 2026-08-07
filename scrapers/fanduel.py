"""FanDuel NHL futures scraper (LOCAL) — via the public sportsbook content API.

FanDuel models a league hub as a "content-managed-page" whose `attachments`
carry events + markets; each market runner has americanDisplayOdds.americanOdds.

Discovery (default):
    python scrapers/fanduel.py
      Tries the Ontario content API for the NHL hub, dumps raw JSON to
      scrapers/.cache/, and prints a CATALOG of every market + runner odds it
      finds. Paste the catalog back to Claude to build the section mapping.

If the auto-guess returns nothing (region/page id differs), CAPTURE the real
request and pass it straight through:
    1. Open https://on.sportsbook.fanduel.ca/navigation/nhl?tab=futures
    2. F12 → Network → filter "content-managed-page" (or "sbapi")
    3. Right-click the request → Copy → Copy URL
    4. python scrapers/fanduel.py --url "<PASTE URL>"
  The scraper will fetch that exact URL and print the same catalog.

Flags: --host <base>, --page <customPageId>, --url <full url>, --insecure.
"""
import argparse
import re
import sys
from collections import defaultdict

import requests

from common import (dump_raw, load, save, set_to_win, set_playoff, set_team_points,
                    set_award, set_player_prop, classify_special, set_special, stamp_book)

_VERIFY = True
HOST = "https://sbapi.on.sportsbook.fanduel.ca"
API_KEY = "FhMFpcPWXMeyZxOx"  # public web client key
BOOK = "fanduel"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept": "application/json",
    "Referer": "https://on.sportsbook.fanduel.ca/",
    "X-Requested-With": "XMLHttpRequest",
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


def build_url(host, page):
    return (f"{host}/api/content-managed-page?page=CUSTOM&customPageId={page}"
            f"&pbHorizontal=false&_ak={API_KEY}&timezone=America%2FNew_York")


def fetch(url):
    print(f"GET {url}")
    r = requests.get(url, headers=HEADERS, timeout=25, verify=_VERIFY)
    if r.status_code != 200:
        print(f"  !! HTTP {r.status_code}\n{r.text[:400]}")
        r.raise_for_status()
    return r.json()


def american(runner):
    try:
        return int(runner["winRunnerOdds"]["americanDisplayOdds"]["americanOdds"])
    except (KeyError, TypeError, ValueError):
        return None


def catalog(payload):
    att = payload.get("attachments", {}) or {}
    markets = att.get("markets", {}) or {}
    events = att.get("events", {}) or {}
    print("\n================== FANDUEL NHL FUTURES CATALOG ==================")
    print(f"(events: {len(events)}, markets: {len(markets)})")
    if not markets:
        print("\nNo markets in attachments. The page id / region is likely different.")
        print("Capture the real request (see header docstring) and re-run with --url.")
        return
    # group markets by event for readability
    for mid, mk in markets.items():
        name = mk.get("marketName", "?")
        ev = events.get(str(mk.get("eventId")), {}) or {}
        ev_name = ev.get("name", "")
        runners = mk.get("runners", []) or []
        print(f"\n• {name}   [{ev_name}]   ({len(runners)} runners)")
        for r in runners[:6]:
            od = american(r)
            print(f"     {r.get('runnerName', '?')}: {od:+d}" if od is not None
                  else f"     {r.get('runnerName', '?')}: (no price)")
        if len(runners) > 6:
            print(f"     ... +{len(runners)-6} more")
    print("\n===============================================================")
    print("Paste the catalog (and/or scrapers/.cache/fanduel_page.json) back to Claude.")


# --- market -> section routing --------------------------------------------
AWARD_MAP = {
    "hart trophy winner": "hart", "norris trophy winner": "norris",
    "vezina trophy winner": "vezina", "calder trophy winner": "calder",
    "jack adams award winner": "jack_adams", "art ross trophy winner": "art_ross",
    "rocket richard trophy winner": "rocket_richard", "selke trophy winner": "selke",
}
_LINE_RE = re.compile(r"(Over|Under)\s+(\d+(?:\.\d+)?)", re.I)
_XPLUS_RE = re.compile(r"(\d+)\+")
# marketType -> player-prop category (O/U line form vs X+ milestone form)
PROP_OU = {"PLAYER_REGULAR_SEASON_POINTS": "points", "PLAYER_REGULAR_SEASON_GOALS": "goals"}
PROP_XPLUS = {"PLAYER_SEASON_X+_POINTS": "points", "PLAYER_SEASON_X+_GOALS": "goals"}


def prop_player(name):
    """'Connor McDavid 2026-27 Regular Season Points' -> 'Connor McDavid'."""
    return re.split(r"\s+20\d\d", name, maxsplit=1)[0].strip()


def runner_odds(mk):
    for r in mk.get("runners", []) or []:
        yield r.get("runnerName", ""), american(r)


def write(doc, payload):
    markets = (payload.get("attachments", {}) or {}).get("markets", {}) or {}
    n = defaultdict(int)
    for mk in markets.values():
        name = mk.get("marketName", "") or ""
        low = name.lower()
        mtype = mk.get("marketType", "") or ""

        # --- player props (route by marketType so they never collide with team markets) ---
        if mtype in PROP_OU:
            cat, player = PROP_OU[mtype], prop_player(name)
            line = over = under = None
            for rn, od in runner_odds(mk):
                m = _LINE_RE.search(rn)
                if not m:
                    continue
                line = float(m.group(2))
                if m.group(1).lower() == "over":
                    over = od
                else:
                    under = od
            if line is not None:
                set_player_prop(doc, cat, player, "", BOOK, line=line, over=over, under=under)
                n[f"prop_ou:{cat}"] += 1
            continue
        if mtype in PROP_XPLUS:
            cat, player = PROP_XPLUS[mtype], prop_player(name)
            for rn, od in runner_odds(mk):
                m = _XPLUS_RE.search(rn)
                if m and od is not None:
                    set_player_prop(doc, cat, player, "", BOOK, plus=int(m.group(1)), yes=od)
                    n[f"prop_x+:{cat}"] += 1
            continue

        sp = classify_special(name)
        if sp:  # Conference/Division/State-Province OF WINNER (champion's attribute)
            for label, od in runner_odds(mk):
                if od is not None:
                    set_special(doc, sp, label, BOOK, od); n[f"special:{sp}"] += 1
            continue

        if low.endswith("stanley cup - winner"):
            for team, od in runner_odds(mk):
                if od is not None:
                    set_to_win(doc, "cup", team, BOOK, od); n["cup"] += 1
        elif "eastern conference - winner" in low or "western conference - winner" in low:
            for team, od in runner_odds(mk):
                if od is not None:
                    set_to_win(doc, "conference", team, BOOK, od); n["conf"] += 1
        elif re.search(r"(atlantic|metropolitan|central|pacific) division - winner", low):
            for team, od in runner_odds(mk):
                if od is not None:
                    set_to_win(doc, "division", team, BOOK, od); n["div"] += 1
        elif "presidents" in low and "winner" in low:
            for team, od in runner_odds(mk):
                if od is not None:
                    set_to_win(doc, "presidents", team, BOOK, od); n["presidents"] += 1
        elif "worst record" in low or ("fewest" in low and "points" in low):
            for team, od in runner_odds(mk):
                if od is not None:
                    set_to_win(doc, "worst", team, BOOK, od); n["worst"] += 1
        elif low.endswith("team to make playoffs"):
            for team, od in runner_odds(mk):
                if od is not None:
                    set_playoff(doc, team, BOOK, "yes", od); n["po_yes"] += 1
        elif low.endswith("team to miss playoffs"):
            for team, od in runner_odds(mk):
                if od is not None:
                    set_playoff(doc, team, BOOK, "no", od); n["po_no"] += 1
        elif "- o/u regular season points" in low:
            team = name.split(" - ")[0]
            line = over = under = None
            for rn, od in runner_odds(mk):
                m = _LINE_RE.search(rn)
                if not m:
                    continue
                line = float(m.group(2))
                if m.group(1).lower() == "over":
                    over = od
                else:
                    under = od
            if line is not None:
                set_team_points(doc, team, BOOK, line, over, under); n["points"] += 1
        else:
            for suffix, cat in AWARD_MAP.items():
                if low.endswith(suffix):
                    for player, od in runner_odds(mk):
                        if od is not None:
                            set_award(doc, cat, player, "", BOOK, od); n[f"award:{cat}"] += 1
                    break

    if sum(n.values()):
        stamp_book(doc, BOOK)  # record freshness (meta.book_updated.fanduel)
    print("  wrote FanDuel:", dict(n))
    return sum(n.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=HOST)
    ap.add_argument("--page", default="nhl", help="customPageId (try: nhl, nhl-futures)")
    ap.add_argument("--url", default=None, help="fetch an exact captured URL")
    ap.add_argument("--write", action="store_true", help="map + write into odds.json")
    ap.add_argument("--insecure", action="store_true")
    args = ap.parse_args()
    configure_tls(args.insecure)

    url = args.url or build_url(args.host, args.page)
    try:
        payload = fetch(url)
    except Exception as e:  # noqa: BLE001
        print(f"\nFETCH FAILED: {e}\nIf this is 404/empty, capture the real request URL "
              f"from devtools and pass it with --url (see docstring).")
        sys.exit(1)

    dump_raw("fanduel_page", payload)
    if args.write:
        doc = load()
        if write(doc, payload):
            save(doc)
    else:
        catalog(payload)


if __name__ == "__main__":
    main()
