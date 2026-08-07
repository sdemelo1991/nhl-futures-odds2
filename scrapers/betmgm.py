r"""BetMGM (Ontario) NHL futures scraper (LOCAL, capture-based).

Odds API (via inspect_har): on.betmgm.ca/en/sports/api/widget/widgetdata
(Entain/bwin platform). One CompetitionLobby payload holds ~all NHL futures.
Structure: top-level "widgets" -> nested fixtures/games -> options with
  {"name": {"value": "Bruins"}, "americanOdds": 5500, "odds": <decimal>, ...}
Teams arrive as NICKNAMES ("Bruins"), handled by normalize_team.

Capture the futures page as a HAR (F12 -> Network -> reload + click futures
tabs -> Save all as HAR with content -> scrapers/.cache/betmgm.har), then:

    python scrapers/betmgm.py            # catalog: market titles + options
    python scrapers/betmgm.py --write     # (added once routing is confirmed)
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
                    set_team_points, set_award, set_player_prop,
                    classify_special, set_special)

# Direct-fetch: the same two widget calls the page makes (from the captured HAR).
# No auth/cookies needed, so this works server-side like DAZN/Kambi — HAR is the
# fallback if BetMGM ever starts gating these.
_WIDGET_BASE = ("https://www.on.betmgm.ca/en/sports/api/widget/widgetdata"
                "?layoutSize=Small&page=CompetitionLobby&sportId=12&regionId=9"
                "&competitionId=34&compoundCompetitionId=1:34")
WIDGET_URLS = [
    _WIDGET_BASE + "&widgetId=/mobilesports-v1.0/layout/layout_us/modules/competition/"
                   "nhldefaultcontainer-events-futures-specials-no-header&shouldIncludePayload=true",
    _WIDGET_BASE + "&widgetId=/mobilesports-v1.0/layout/layout_us/modules/topevents-new/"
                   "nhl/nhl-dailyprops/nhl-dailyprops&useAggregateMatchList=true&shouldIncludePayload=true",
]
_NHL_PAGE = "https://www.on.betmgm.ca/en/sports/hockey-12/betting/usa-9/nhl-34"
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": _NHL_PAGE,
    # These bwin/Entain headers are what make the widget return its payload;
    # without Sports-Api-Version the endpoint answers 200 with an empty shell.
    "Sports-Api-Version": "SportsAPIv2",
    "X-Bwin-Sports-Api": "prod",
    "X-From-Product": "host-app",
    "X-Device-Type": "desktop_Windows 11",
    "X-Bwin-Browser-Url": _NHL_PAGE,
    "X-Requested-With": "XMLHttpRequest",
}


def fetch_direct():
    """GET the two widget payloads directly (truststore for the corporate MITM).
    Returns [] on any failure so the caller can fall back to a saved HAR."""
    try:
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        pass
    out = []
    for u in WIDGET_URLS:
        try:
            r = requests.get(u, headers=_HEADERS, timeout=25)
        except Exception as e:  # noqa: BLE001
            print(f"  direct fetch error: {e}")
            continue
        if r.status_code != 200:
            print(f"  HTTP {r.status_code} on {u[:80]}...")
            continue
        try:
            obj = r.json()
        except ValueError:
            print(f"  non-JSON response ({len(r.content):,}B)")
            continue
        if isinstance(obj, dict) and obj.get("widgets") is not None:
            out.append(obj)
        else:
            keys = list(obj.keys())[:10] if isinstance(obj, dict) else type(obj).__name__
            print(f"  200 but no 'widgets'; top keys={keys}")
    return out

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

BOOK = "betmgm"


def har_payloads(fp):
    with open(fp, encoding="utf-8") as f:
        raw = json.load(f)
    entries = (raw.get("log", {}) or {}).get("entries") if isinstance(raw, dict) else None
    if entries is None:
        return [raw]
    out = []
    for e in entries:
        if "widgetdata" not in e.get("request", {}).get("url", ""):
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
        if isinstance(obj, dict) and obj.get("widgets") is not None:
            out.append(obj)
    return out


def name_of(d):
    n = d.get("name") if isinstance(d, dict) else None
    if isinstance(n, dict):
        return n.get("value")
    if isinstance(n, str):
        return n
    for k in ("title", "label", "shortName"):
        v = d.get(k) if isinstance(d, dict) else None
        if isinstance(v, dict):
            v = v.get("value")
        if isinstance(v, str):
            return v
    return None


def is_option(o):
    return isinstance(o, dict) and "americanOdds" in o


def find_markets(node, parent, out):
    """A 'market' = a dict holding a list of option objects. Record (parent
    label, market label, options, extra attrs)."""
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, list) and any(is_option(x) for x in v):
                out.append({
                    "parent": parent,
                    "market": name_of(node),
                    "attr": node.get("attribute") or node.get("handicap") or node.get("line"),
                    "options": [x for x in v if is_option(x)],
                })
        pn = name_of(node) or parent
        for v in node.values():
            find_markets(v, pn, out)
    elif isinstance(node, list):
        for x in node:
            find_markets(x, parent, out)


def catalog(payloads):
    seen = set()
    n = 0
    for obj in payloads:
        markets = []
        find_markets(obj, None, markets)
        for m in markets:
            onames = tuple(name_of(o) for o in m["options"])
            sig = (m["parent"], m["market"], onames)
            if sig in seen:
                continue
            seen.add(sig)
            n += 1
            attr = f"  attr={m['attr']}" if m["attr"] else ""
            print(f"\n• parent={m['parent']!r}  market={m['market']!r}  "
                  f"({len(m['options'])} options){attr}")
            for o in m["options"][:6]:
                print(f"     {name_of(o)!r}: {o.get('americanOdds')}")
            if len(m["options"]) > 6:
                print(f"     ... +{len(m['options'])-6} more")
    print(f"\n=== {n} distinct markets ===")
    print("Paste this catalog back to Claude to build the BetMGM routing.")


AWARD_KW = {"hart": "hart", "norris": "norris", "vezina": "vezina", "calder": "calder",
            "jack adams": "jack_adams", "art ross": "art_ross",
            "rocket richard": "rocket_richard", "selke": "selke"}
_LINE = re.compile(r"(\d+[.,]\d+)")
# player X+ milestone markets: name = threshold, results = players
_XPLUS = re.compile(r"to (?:record|score) (\d+)\+ (points|goals)", re.I)
_SKIP = ("exact outcome", "name the finalists", "top 3", "stage of elimination",
         "winning division", "winning country", "winning state", "winning conference",
         "original six", "new champion", "nation of", "state/province")


def _teams(doc, market, opts, counts):
    for o in opts:
        od, nm = o.get("americanOdds"), name_of(o)
        if od is not None and nm:
            set_to_win(doc, market, nm, BOOK, od); counts[market] += 1


def route(markets, doc, counts, unmatched, seen):
    for m in markets:
        mk = m["market"] or ""
        low = mk.lower()
        parent = (m["parent"] or "").lower()
        opts = m["options"]
        key = (m["parent"], mk, tuple(name_of(o) for o in opts))
        if key in seen:
            continue
        seen.add(key)

        # player X+ props: market = "To record 50+ points..." / options = players
        xm = _XPLUS.search(low)
        if xm:
            cat, thr = xm.group(2), int(xm.group(1))
            for o in opts:
                player, od = name_of(o), o.get("americanOdds")
                if player and od is not None:
                    set_player_prop(doc, cat, player, "", BOOK, plus=thr, yes=od)
                    counts[f"prop_x+:{cat}"] += 1
            continue

        sp = classify_special(mk)
        if sp:  # champion's conference/division/state (attribute market)
            for o in opts:
                label, od = name_of(o), o.get("americanOdds")
                if label and od is not None:
                    set_special(doc, sp, label, BOOK, od); counts[f"special:{sp}"] += 1
            continue

        if "player futures" in parent or any(x in low for x in _SKIP):
            continue

        if "stanley cup" in low and "winner" in low and "conference" not in low and "division" not in low:
            _teams(doc, "cup", opts, counts)
        elif "conference winner" in low:
            _teams(doc, "conference", opts, counts)
        elif "division winner" in low:
            _teams(doc, "division", opts, counts)
        elif "presidents" in low:
            _teams(doc, "presidents", opts, counts)
        elif "fewest" in low and "points" in low:
            _teams(doc, "worst", opts, counts)
        elif "to make the playoffs" in low:
            team = mk[:low.index(" to make")]
            y = next((o.get("americanOdds") for o in opts if name_of(o) == "Yes"), None)
            n = next((o.get("americanOdds") for o in opts if name_of(o) == "No"), None)
            if y is not None:
                set_playoff(doc, team, BOOK, "yes", y); counts["po_yes"] += 1
            if n is not None:
                set_playoff(doc, team, BOOK, "no", n); counts["po_no"] += 1
        elif "regular season points" in low and ":" in mk and len(opts) == 2:
            team = mk.split(":")[0]
            line = over = under = None
            for o in opts:
                nm = name_of(o) or ""
                mm = _LINE.search(nm)
                if mm:
                    line = float(mm.group(1).replace(",", "."))
                if nm.lower().startswith("over"):
                    over = o.get("americanOdds")
                elif nm.lower().startswith("under"):
                    under = o.get("americanOdds")
            if line is not None:
                set_team_points(doc, team, BOOK, line, over, under); counts["points"] += 1
            else:
                unmatched.append(f"[pts] {mk}")
        else:
            cat = next((c for k, c in AWARD_KW.items() if k in low), None)
            if cat and ("trophy" in low or "winner" in low):
                for o in opts:
                    od = o.get("americanOdds")
                    if od is not None:
                        set_award(doc, cat, name_of(o), "", BOOK, od); counts[f"award:{cat}"] += 1
            else:
                unmatched.append(f"{m['parent']} | {mk}")


def write_all(payloads):
    doc = load()
    markets = []
    for obj in payloads:
        find_markets(obj, None, markets)
    counts, unmatched, seen = defaultdict(int), [], set()
    route(markets, doc, counts, unmatched, seen)
    print("  wrote BetMGM:", dict(counts))
    if unmatched:
        print("  UNMATCHED (skipped; paste to Claude if any should map):")
        for u in sorted(set(unmatched)):
            print(f"     - {u}")
    if sum(counts.values()):
        save(doc)


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
        for fp in sorted(glob.glob(os.path.join(CACHE_DIR, "betmgm*.har"))):
            payloads += har_payloads(fp)
    else:
        payloads = fetch_direct()  # direct API first
        if payloads:
            print(f"  (direct fetch: {len(payloads)} widget payloads)")
        else:  # fall back to a saved HAR
            print("  direct fetch returned nothing — falling back to saved HAR")
            for fp in sorted(glob.glob(os.path.join(CACHE_DIR, "betmgm*.har"))):
                payloads += har_payloads(fp)

    print(f"widgetdata payloads: {len(payloads)}")
    if not payloads:
        print(f"  No data. Direct fetch failed and no HAR at {CACHE_DIR}\\betmgm.har")
        return
    if args.write:
        write_all(payloads)
    else:
        catalog(payloads)


if __name__ == "__main__":
    main()
