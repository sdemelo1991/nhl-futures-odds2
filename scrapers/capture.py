r"""Local browser-driven capture for the HAR-only books — no manual clicking.

Some books can't be fetched server-side (DraftKings = Akamai, theScore = GraphQL,
BetMGM/BetOnline/Betano = bot-gated), but a REAL browser loads them fine. This
drives a local (headless) Chromium via Playwright, opens a book's futures page,
records the JSON API responses the page makes, and writes them to
scrapers/.cache/<book>.har in standard HAR shape — so the existing per-book
parser (`<book>.py --write`) reads it unchanged. Runs on YOUR machine (same as
the other scrapers); can be driven unattended by a scheduled task.

Setup (one time):
    pip install playwright
    playwright install chromium

Use:
    python scrapers/capture.py betmgm                 # headless -> .cache/betmgm.har
    python scrapers/capture.py betmgm --headed        # watch it (first run / debugging)
    python scrapers/capture.py betmgm --url "<page>"  # override the futures-page URL
then parse as usual:
    python scrapers/betmgm.py --write
"""
import argparse
import json
import os
import time

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")

# Per-book capture config. `match` = URL substrings; a response whose URL
# contains any is saved. `url` = the human futures page (override with --url
# until confirmed). `settle` = extra seconds after network idle for late XHRs.
BOOKS = {
    "betmgm": {
        "url": "https://sports.on.betmgm.ca/en/sports/hockey-12/nhl-34",
        "match": ["widgetdata"],
        "settle": 6.0,
    },
    # placeholders — url/match get confirmed as we pilot each book:
    "thescore":   {"url": "", "match": ["graphql"], "settle": 6.0},
    "draftkings": {"url": "", "match": ["sportscontent"], "settle": 6.0},
    "betonline":  {"url": "", "match": ["get-contests"], "settle": 6.0},
    "betano":     {"url": "", "match": ["/api/sport/"], "settle": 6.0},
}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def capture(book, url, headed):
    from playwright.sync_api import sync_playwright

    cfg = BOOKS[book]
    match = cfg["match"]
    entries, seen = [], set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        ctx = browser.new_context(user_agent=UA, locale="en-CA",
                                  viewport={"width": 1440, "height": 900})
        page = ctx.new_page()

        def on_response(resp):
            u = resp.url
            if u in seen or not any(m in u for m in match):
                return
            try:
                body = resp.text()
            except Exception:  # noqa: BLE001
                return
            if not body:
                return
            seen.add(u)
            entries.append({
                "request": {"url": u},
                "response": {"status": resp.status,
                             "content": {"mimeType": "application/json", "text": body}},
            })
            print(f"    + {len(body):>8,}B  {u[:90]}")

        page.on("response", on_response)
        print(f"  navigating: {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=45000)
        except Exception:  # noqa: BLE001
            pass
        for _ in range(4):  # nudge lazy-loaded futures sections into view
            page.mouse.wheel(0, 4000)
            time.sleep(1.0)
        time.sleep(cfg.get("settle", 5.0))
        browser.close()

    return entries


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("book", choices=list(BOOKS))
    ap.add_argument("--url", default=None, help="futures-page URL (overrides the config)")
    ap.add_argument("--headed", action="store_true", help="show the browser (first run/debug)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    url = args.url or BOOKS[args.book]["url"]
    if not url:
        print(f"No page URL configured for {args.book}. Pass --url \"<the futures page you open>\".")
        return

    try:
        entries = capture(args.book, url, args.headed)
    except ImportError:
        print("Playwright not installed. Run:\n"
              "  pip install playwright\n  playwright install chromium")
        return

    os.makedirs(CACHE, exist_ok=True)
    out = args.out or os.path.join(CACHE, f"{args.book}.har")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"log": {"version": "1.2", "entries": entries}}, f, ensure_ascii=False)
    print(f"  captured {len(entries)} matching response(s) -> {out}")
    if not entries:
        print("  (0 captured — run with --headed to watch; the page URL or the "
              "'match' filter may need adjusting.)")
    else:
        print(f"  next: python scrapers\\{args.book}.py --write")


if __name__ == "__main__":
    main()
