r"""Betano (Ontario) NHL futures scraper (LOCAL, capture-based).

Odds API (via inspect_har): www.betano.ca/api/sport/hockey/north-america/nhl/10118/?bt=<tab>
Each futures TAB is its own request: bt=awards, bt=teams, and (need to capture)
the Cup / Conference / Division tabs (likely bt=outrights / specials / championship).
Prices are DECIMAL (3.5 -> +250, 1.6 -> -167).

Shapes seen:
  - awards: a `tableLayout` {title, rows:[{title: player, groupSelections:[{selections:[{name, price}]}]}]}
  - teams:  blocks {name: "Anaheim Ducks", typeId, selections:[{name:"Yes"/"No", price}]}  (make playoffs)

Capture the futures page as a HAR (F12 -> Network -> click through ALL futures
tabs so each bt= call loads -> Save all as HAR with content -> scrapers/.cache/betano.har):

    python scrapers/betano.py            # catalog: bt tab + markets + selections
    python scrapers/betano.py --file <path>
"""
import argparse
import base64
import glob
import json
import os
import sys
import urllib.parse as up
from collections import defaultdict

import requests
import time

from common import (CACHE_DIR, load, save, set_to_win, set_playoff, set_award,
                    classify_special, set_special)

# Direct-fetch: the three futures tabs the page requests (no auth/cookies). HAR
# is the fallback if Betano ever gates these.
_TABS = ["teams", "awards", "winnerspecials"]
_URL = "https://www.betano.ca/api/sport/hockey/north-america/nhl/10118/?bt={bt}&req=la,s,stnf,c,mb"
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.betano.ca/sport/hockey/north-america/nhl/10118/",
    "X-Requested-With": "XMLHttpRequest",
}


def fetch_direct():
    """GET each futures tab directly (truststore for the corporate MITM).
    Returns [(bt, obj)] like har_payloads; [] on failure so caller falls back."""
    try:
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        pass
    out = []
    for bt in _TABS:
        u = _URL.format(bt=bt) + f"&_={int(time.time() * 1000)}"  # cache-buster
        try:
            r = requests.get(u, headers=_HEADERS, timeout=25)
        except Exception as e:  # noqa: BLE001
            print(f"  {bt}: fetch error {e}")
            continue
        if r.status_code != 200:
            print(f"  {bt}: HTTP {r.status_code}")
            continue
        try:
            obj = r.json()
        except ValueError:
            print(f"  {bt}: non-JSON response")
            continue
        if isinstance(obj, dict) and obj.get("data") is not None:
            out.append((bt, obj))
        else:
            keys = list(obj.keys())[:8] if isinstance(obj, dict) else type(obj).__name__
            print(f"  {bt}: 200 but no 'data'; keys={keys}")
    return out

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

BOOK = "betano"


def har_payloads(fp):
    with open(fp, encoding="utf-8") as f:
        raw = json.load(f)
    entries = (raw.get("log", {}) or {}).get("entries") if isinstance(raw, dict) else None
    if entries is None:
        return [("(file)", raw)]
    out = []
    for e in entries:
        url = e.get("request", {}).get("url", "")
        if "/api/sport/hockey" not in url or "bt=" not in url:
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
        if isinstance(obj, dict) and obj.get("data") is not None:
            bt = up.parse_qs(up.urlparse(url).query).get("bt", ["?"])[0]
            out.append((bt, obj))
    return out


def price_am(p):
    if not isinstance(p, (int, float)) or p <= 1:
        return None
    return round((p - 1) * 100) if p >= 2 else round(-100 / (p - 1))


def sel_entries(container):
    out = []
    for gs in container.get("groupSelections", []) or []:
        for s in gs.get("selections", []) or []:
            out.append((s.get("name"), s.get("price"), s.get("handicap")))
    for s in container.get("selections", []) or []:
        out.append((s.get("name"), s.get("price"), s.get("handicap")))
    return out


def find_markets(node, out):
    if isinstance(node, dict):
        tl = node.get("tableLayout")
        if isinstance(tl, dict) and tl.get("rows") is not None:
            entries = []
            for r in tl.get("rows", []) or []:
                for nm, pr, hc in sel_entries(r):
                    entries.append((r.get("title") or nm, pr, hc))
            out.append(("table", tl.get("title"), entries))
        elif node.get("selections") and isinstance(node.get("name"), str) and node.get("typeId") is not None:
            out.append(("block", node.get("name"), sel_entries(node)))
        for v in node.values():
            find_markets(v, out)
    elif isinstance(node, list):
        for x in node:
            find_markets(x, out)


def catalog(payloads):
    for bt, obj in payloads:
        markets = []
        find_markets(obj.get("data"), markets)
        print(f"\n================= bt={bt}  ({len(markets)} markets) =================")
        seen = set()
        for kind, title, entries in markets:
            sig = (title, tuple(e[0] for e in entries))
            if sig in seen:
                continue
            seen.add(sig)
            print(f"\n• [{kind}] {title!r}  ({len(entries)} selections)")
            for nm, pr, hc in entries[:8]:
                hc_s = f"  hcap={hc}" if hc else ""
                print(f"     {nm!r}: {pr} ({price_am(pr):+d})" if price_am(pr) is not None
                      else f"     {nm!r}: {pr}{hc_s}")
            if len(entries) > 8:
                print(f"     ... +{len(entries)-8} more")
    print("\nPaste this catalog back to Claude to build the Betano routing.")


_AWARD = {"hart": "hart", "vezina": "vezina", "calder": "calder", "norris": "norris",
          "jack adams": "jack_adams", "art ross": "art_ross",
          "rocket richard": "rocket_richard", "selke": "selke"}


def winner_market(title):
    low = (title or "").lower()
    if any(x in low for x in ("nation of", "winning conference", "winning division")):
        return None
    if "regular season winner" in low:
        return "presidents"
    if "stanley cup winner" in low:
        return "cup"
    if "conference" in low and "winner" in low:
        return "conference"
    if "division" in low and "winner" in low:
        return "division"
    return None


def write_all(payloads):
    doc = load()
    counts, unmatched = defaultdict(int), []
    for bt, obj in payloads:
        markets = []
        find_markets(obj.get("data"), markets)
        for kind, title, entries in markets:
            if bt == "teams" and kind == "block":  # per-team make playoffs
                y = next((price_am(pr) for nm, pr, _ in entries if nm == "Yes"), None)
                n = next((price_am(pr) for nm, pr, _ in entries if nm == "No"), None)
                if y is not None:
                    set_playoff(doc, title, BOOK, "yes", y); counts["po_yes"] += 1
                if n is not None:
                    set_playoff(doc, title, BOOK, "no", n); counts["po_no"] += 1
            elif bt == "awards" and kind == "table":
                cat = next((c for k, c in _AWARD.items() if k in (title or "").lower()), None)
                if cat:
                    for nm, pr, _ in entries:
                        am = price_am(pr)
                        if nm and am is not None:
                            set_award(doc, cat, nm, "", BOOK, am); counts[f"award:{cat}"] += 1
                else:
                    unmatched.append(f"[awards] {title}")
            elif bt == "winnerspecials" and kind == "block":
                sp = classify_special(title)
                if sp:  # Winning Conference / Division / State (champion's attribute)
                    for nm, pr, _ in entries:
                        am = price_am(pr)
                        if nm and am is not None:
                            set_special(doc, sp, nm, BOOK, am); counts[f"special:{sp}"] += 1
                    continue
                market = winner_market(title)
                if market:
                    for nm, pr, _ in entries:
                        am = price_am(pr)
                        if nm and am is not None:
                            set_to_win(doc, market, nm, BOOK, am); counts[market] += 1
                # else: exotic (nation) — skip silently
    print("  wrote Betano:", dict(counts))
    if unmatched:
        print("  UNMATCHED:", sorted(set(unmatched)))
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
        for fp in sorted(glob.glob(os.path.join(CACHE_DIR, "betano*.har"))):
            payloads += har_payloads(fp)
    else:
        payloads = fetch_direct()  # direct API first
        if payloads:
            print(f"  (direct fetch: {len(payloads)} tab payloads)")
        else:
            print("  direct fetch returned nothing — falling back to saved HAR")
            for fp in sorted(glob.glob(os.path.join(CACHE_DIR, "betano*.har"))):
                payloads += har_payloads(fp)

    print(f"bt= payloads: {len(payloads)}")
    if not payloads:
        print(f"  No data. Direct fetch failed and no HAR at {CACHE_DIR}\\betano.har")
        return
    if args.write:
        write_all(payloads)
    else:
        catalog(payloads)


if __name__ == "__main__":
    main()
