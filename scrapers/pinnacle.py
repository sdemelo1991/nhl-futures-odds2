"""Pinnacle NHL futures scraper (LOCAL) — via the public Arcadia guest API.

Two phases:
  1. Discovery (default):   python scrapers/pinnacle.py
       Fetches NHL special/futures matchups + prices, dumps raw JSON to
       scrapers/.cache/, and prints a CATALOG of every futures market Pinnacle
       is posting (description + participant count + sample prices). Paste that
       catalog back to Claude to build the exact section mapping.
  2. Write (once mapping is confirmed): python scrapers/pinnacle.py --write
       Best-effort maps outright "winner" markets (Cup / Conference / Division)
       into data/odds.json under book "pinnacle".

If the request is blocked (403 / Cloudflare), tell Claude — we'll pivot to a
Playwright-based capture. Prices from Arcadia are American odds (ints).
"""
import argparse
import sys

import requests

from common import load, save, dump_raw, set_to_win, classify_special, set_special

_VERIFY = True  # set False by --insecure


def configure_tls(insecure: bool):
    """Corporate networks (FanDuel) MITM TLS with a private root CA that Python's
    bundled certs don't trust. Prefer the OS trust store via `truststore`; fall
    back to disabling verification only when explicitly asked."""
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
        print("  (truststore not installed — if this SSL-fails, run: pip install truststore)")

ARCADIA = "https://guest.api.arcadia.pinnacle.com/0.1"
NHL_LEAGUE = 1456
# Public guest API key embedded in Pinnacle's own web client.
API_KEY = "CmX2KcMrXuFmNg6YFbmTxE0y9CIrOi0R"
HEADERS = {
    "X-API-Key": API_KEY,
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Referer": "https://www.pinnacle.ca/",
    "Accept": "application/json",
}
BOOK = "pinnacle"


def get(path):
    url = f"{ARCADIA}{path}"
    r = requests.get(url, headers=HEADERS, timeout=20, verify=_VERIFY)
    if r.status_code != 200:
        print(f"  !! {url} -> HTTP {r.status_code}\n{r.text[:300]}")
        r.raise_for_status()
    return r.json()


def fetch():
    print("Fetching Pinnacle NHL matchups + markets ...")
    matchups = get(f"/leagues/{NHL_LEAGUE}/matchups")
    markets = get(f"/leagues/{NHL_LEAGUE}/markets/straight")
    dump_raw("pinnacle_matchups", matchups)
    dump_raw("pinnacle_markets", markets)
    return matchups, markets


def index_specials(matchups):
    """Return {matchupId: {"desc":.., "participants": {pid: name}}} for the
    special/futures matchups only."""
    out = {}
    for m in matchups:
        if m.get("type") != "special" and not m.get("special"):
            continue
        sp = m.get("special") or {}
        desc = sp.get("description") or m.get("league", {}).get("name") or str(m.get("id"))
        parts = {p.get("id"): p.get("name") for p in (m.get("participants") or [])}
        out[m.get("id")] = {"desc": desc, "participants": parts}
    return out


def prices_by_matchup(markets):
    """Return {matchupId: [(participantId, price), ...]} for outright markets."""
    out = {}
    for mk in markets:
        mid = mk.get("matchupId")
        for pr in mk.get("prices", []):
            pid = pr.get("participantId")
            price = pr.get("price")
            if pid is None or price is None:
                continue
            out.setdefault(mid, []).append((pid, price))
    return out


def catalog(specials, priced):
    print("\n================= PINNACLE NHL FUTURES CATALOG =================")
    if not specials:
        print("(no special/futures matchups found — paste the raw cache files)")
    for mid, info in specials.items():
        plist = priced.get(mid, [])
        print(f"\n• [{mid}] {info['desc']}  ({len(info['participants'])} participants)")
        for pid, price in plist[:6]:
            print(f"     {info['participants'].get(pid, pid)}: {price:+d}")
        if len(plist) > 6:
            print(f"     ... +{len(plist)-6} more")
    print("\n===============================================================")
    print("Paste the above (and/or the two files in scrapers/.cache/) back to Claude.")


def route_market(desc):
    """Heuristic: map a market description to a to_win market key, or None."""
    d = desc.lower()
    if "stanley cup" in d or ("cup" in d and "winner" in d):
        return "cup"
    if "conference" in d:
        return "conference"
    if any(div in d for div in ("atlantic", "metropolitan", "central", "pacific")):
        return "division"
    return None


def write(doc, specials, priced):
    n = 0
    for mid, info in specials.items():
        sp = classify_special(info["desc"])
        if sp:  # champion's conference/division/state — outcomes are not teams
            for pid, price in priced.get(mid, []):
                label = info["participants"].get(pid)
                if label:
                    set_special(doc, sp, label, BOOK, price); n += 1
            continue
        market = route_market(info["desc"])
        if not market:
            continue
        for pid, price in priced.get(mid, []):
            team = info["participants"].get(pid)
            if not team:
                continue
            set_to_win(doc, market, team, BOOK, price)
            n += 1
    print(f"  wrote {n} Pinnacle prices into to_win + cup_specials")
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true",
                    help="best-effort write outright winner markets into odds.json")
    ap.add_argument("--insecure", action="store_true",
                    help="disable TLS verification (last resort behind MITM proxy)")
    args = ap.parse_args()
    configure_tls(args.insecure)

    try:
        matchups, markets = fetch()
    except Exception as e:  # noqa: BLE001
        print(f"\nFETCH FAILED: {e}\nLikely blocked (Cloudflare/geo) or endpoint "
              f"changed. Tell Claude — we'll switch to a Playwright capture.")
        sys.exit(1)

    specials = index_specials(matchups)
    priced = prices_by_matchup(markets)
    catalog(specials, priced)

    if args.write:
        doc = load()
        if write(doc, specials, priced):
            save(doc)


if __name__ == "__main__":
    main()
