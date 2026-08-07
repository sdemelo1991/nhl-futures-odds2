r"""theScore Bet (Ontario) NHL futures scraper (LOCAL, capture-based).

theScore Bet runs a GraphQL persisted-queries API
(sportsbook.ca-on.thescore.bet/graphql/persisted_queries/<hash>). Odds live in
the response as selection.odds.formattedOdds (American, e.g. "+105" / "-115"),
with selection.name.fullName the team/player/Over-Under label. The persisted
hashes + variables are awkward to replay, so this is HAR-based like DK/BetMGM.

Capture the futures page as a HAR (F12 -> Network -> Preserve log + Disable
cache -> reload + click every futures tab -> Save all as HAR with content ->
scrapers/.cache/thescore.har), then:

    python scrapers/thescore.py            # catalog
    python scrapers/thescore.py --write     # route into odds.json
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

_SKIP_HDRS = {"host", "content-length", "accept-encoding", "connection",
              "cookie", "pragma", "cache-control"}


def _har_requests(fp):
    """(url, headers) for each graphql persisted_query GET in a saved HAR — the
    'recipe' we replay live for fresh odds without re-capturing."""
    raw = json.load(open(fp, encoding="utf-8"))
    out, seen = [], set()
    for e in (raw.get("log", {}) or {}).get("entries", []) or []:
        rq = e.get("request", {}) or {}
        u = rq.get("url", "")
        if "graphql/persisted_queries/" not in u or u in seen:
            continue
        if rq.get("method", "GET").upper() != "GET":
            continue
        seen.add(u)
        hdrs = {h["name"]: h["value"] for h in rq.get("headers", [])
                if not h["name"].startswith(":") and h["name"].lower() not in _SKIP_HDRS}
        out.append((u, hdrs))
    return out


def fetch_direct():
    """Replay the captured persisted-query GETs live (headers carry theScore's
    anonymous-auth token + client IDs). Returns payloads with a 'data' key; []
    on failure so the caller falls back to parsing the saved HAR as-is."""
    hars = sorted(glob.glob(os.path.join(CACHE_DIR, "thescore*.har")))
    if not hars:
        return []
    reqs = _har_requests(hars[-1])
    if not reqs:
        return []
    try:
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        pass
    out = []
    for u, h in reqs:
        try:
            r = requests.get(u, headers=h, timeout=25)
        except Exception as e:  # noqa: BLE001
            print(f"  req error: {e}")
            continue
        if r.status_code != 200:
            print(f"  HTTP {r.status_code} (auth/IDs may have rotated — re-capture HAR)")
            continue
        try:
            obj = r.json()
        except ValueError:
            continue
        if isinstance(obj, dict) and obj.get("data") is not None:
            out.append(obj)
    print(f"  replayed {len(out)}/{len(reqs)} graphql queries live")
    return out

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from teams import TEAMS, normalize_team  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

BOOK = "thescore"
AWARD_KW = {"hart": "hart", "norris": "norris", "vezina": "vezina", "calder": "calder",
            "jack adams": "jack_adams", "art ross": "art_ross",
            "rocket richard": "rocket_richard", "selke": "selke"}
# "winning conference/division/state" are now captured as Cup Specials (below);
# only "winning country/nation" stays skipped (not a tracked market).
SKIP = ("winning country", "winning nation",
        "original six", "moneyline", "game spread", "total goals", " @ ")


def har_payloads(fp):
    raw = json.load(open(fp, encoding="utf-8"))
    out = []
    for e in (raw.get("log", {}) or {}).get("entries", []) or []:
        if "graphql" not in e.get("request", {}).get("url", ""):
            continue
        c = (e.get("response", {}) or {}).get("content", {}) or {}
        b = c.get("text")
        if not b:
            continue
        if c.get("encoding") == "base64":
            try:
                b = base64.b64decode(b).decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                continue
        try:
            obj = json.loads(b)
        except (ValueError, TypeError):
            continue
        if isinstance(obj, dict) and obj.get("data") is not None:
            out.append(obj)
    return out


def sel_name(s):
    n = s.get("name")
    if isinstance(n, dict):
        return n.get("fullName") or n.get("defaultName") or n.get("cleanName")
    return None


def sel_odds(s):
    o = s.get("odds")
    if isinstance(o, dict) and o.get("formattedOdds"):
        raw = (str(o["formattedOdds"]).replace("+", "").replace(",", "")
               .replace("−", "-").strip())
        # theScore prints even money as "Even" (also EV/E/PK/Pick) instead of +100
        if raw.lower() in ("even", "evens", "ev", "e", "pk", "pick", "pick'em", "pickem"):
            return 100
        try:
            return int(raw)
        except ValueError:
            return None
    return None


def find_markets(payloads):
    """Return [(title, [selection dicts])]. A market = a dict with a name/title
    and a list of selection dicts (each has 'odds' + 'name')."""
    out = {}

    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                if isinstance(v, list) and v and isinstance(v[0], dict) \
                        and "odds" in v[0] and "name" in v[0]:
                    title = o.get("name") or o.get("title") or o.get("marketName")
                    if isinstance(title, dict):
                        title = title.get("fullName") or title.get("defaultName")
                    mid = o.get("id") or o.get("rawId") or title
                    if title and mid not in out:
                        out[mid] = (title, [s for s in v if isinstance(s, dict)])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    for p in payloads:
        walk(p)
    return list(out.values())


def ts_team(label):
    """theScore labels teams 'FLA Panthers' / 'UTAH Mammoth' / 'VGK Golden Knights'.
    Normalize via the full label, else match a team ending with the nickname."""
    t = normalize_team(label or "")
    if t in TEAMS:
        return t
    parts = (label or "").split(" ", 1)
    if len(parts) == 2:
        nick = parts[1].strip()
        for team in TEAMS:
            if team.endswith(nick):
                return team
        t2 = normalize_team(nick)
        if t2 in TEAMS:
            return t2
    return t


def _teams(doc, market, sels, counts):
    for s in sels:
        nm, od = ts_team(sel_name(s) or ""), sel_odds(s)
        if nm and od is not None:
            set_to_win(doc, market, nm, BOOK, od); counts[market] += 1


def route(markets, doc, counts, unmatched, seen):
    for title, sels in markets:
        if title in seen:
            continue
        seen.add(title)
        low = (title or "").lower()
        if any(x in low for x in SKIP):
            continue
        sp = classify_special(title)
        if sp:  # Winning Conference / Division / State (champion's attribute)
            for s in sels:
                nm, od = sel_name(s), sel_odds(s)
                if nm and od is not None:
                    set_special(doc, sp, nm, BOOK, od); counts[f"special:{sp}"] += 1
            continue
        if "stanley cup winner" in low:
            _teams(doc, "cup", sels, counts)
        elif "conference winner" in low:
            _teams(doc, "conference", sels, counts)
        elif "division winner" in low:
            _teams(doc, "division", sels, counts)
        elif "presidents" in low and "winner" in low:
            _teams(doc, "presidents", sels, counts)
        elif "to make the playoffs" in low:
            team = title[:low.index(" to make")].strip()
            for s in sels:
                side, od = (sel_name(s) or "").strip().lower(), sel_odds(s)
                if side in ("yes", "no") and od is not None:
                    set_playoff(doc, team, BOOK, side, od); counts["playoffs"] += 1
        elif "regular season total points" in low:
            team = title[:low.index(" regular season")].strip()
            line = over = under = None
            for s in sels:
                nm, od = (sel_name(s) or ""), sel_odds(s)
                m = re.search(r"(\d+(?:\.\d+)?)", nm)
                if m:
                    line = float(m.group(1))
                nl = nm.lower()
                if nl.startswith("over") or nl.startswith("o "):
                    over = od
                elif nl.startswith("under") or nl.startswith("u "):
                    under = od
            if line is not None:
                set_team_points(doc, team, BOOK, line, over, under); counts["points"] += 1
        else:
            cat = next((c for k, c in AWARD_KW.items() if k in low), None)
            if cat and ("trophy" in low or "winner" in low):
                for s in sels:
                    nm, od = sel_name(s), sel_odds(s)
                    if nm and od is not None:
                        set_award(doc, cat, nm, "", BOOK, od); counts[f"award:{cat}"] += 1
            elif sels:
                unmatched.append(title)


def catalog(markets):
    for title, sels in markets:
        print(f"\n• {title!r}  ({len(sels)} sel)")
        for s in sels[:5]:
            print(f"     {sel_name(s)}: {sel_odds(s)}")
    print(f"\n=== {len(markets)} markets ===")


def write_all(payloads):
    doc = load()
    markets = find_markets(payloads)
    counts, unmatched, seen = defaultdict(int), [], set()
    route(markets, doc, counts, unmatched, seen)
    print("  wrote theScore:", dict(counts))
    if unmatched:
        print("  UNMATCHED (skipped):")
        for u in sorted(set(unmatched)):
            print(f"     - {u}")
    if sum(counts.values()):
        save(doc)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=None)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--har", action="store_true", help="parse saved HAR as-is (no live replay)")
    args = ap.parse_args()

    payloads = []
    if args.file:
        payloads = har_payloads(args.file)
    elif args.har:
        for fp in sorted(glob.glob(os.path.join(CACHE_DIR, "thescore*.har"))):
            payloads += har_payloads(fp)
    else:
        payloads = fetch_direct()  # replay the captured queries live
        if not payloads:
            print("  live replay empty — parsing saved HAR as-is (stale)")
            for fp in sorted(glob.glob(os.path.join(CACHE_DIR, "thescore*.har"))):
                payloads += har_payloads(fp)

    print(f"graphql payloads: {len(payloads)}")
    if not payloads:
        print(f"  No data. No live replay and no HAR at {CACHE_DIR}\\thescore.har")
        return
    if args.write:
        write_all(payloads)
    else:
        catalog(find_markets(payloads))


if __name__ == "__main__":
    main()
