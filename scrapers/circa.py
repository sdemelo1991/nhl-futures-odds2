r"""Circa NHL Futures (LOCAL, semi-automated).

Circa posts a manually-updated Dropbox folder of PDF odds sheets. The NHL sheet
("NHL Futures 2026-27.pdf") is an IMAGE (no text layer) with Cup + Conference
winner prices for all 32 teams — so it can't be parsed as text, and OCR on
prices is risky. Instead:

  * DETECTION is automated: --check downloads the folder, hashes the NHL PDF,
    and reports whether it changed vs the hash we last transcribed. It also
    renders the current page to scrapers/.cache/circa_nhl.png for eyeballing.
  * APPLICATION is automated from scrapers/circa_data.json (Claude transcribes
    that file from the PDF when --check flags a change — rare, Circa updates
    infrequently). --write merges it into odds.json.

    python scrapers/circa.py            # check for updates (schedulable)
    python scrapers/circa.py --write     # apply circa_data.json to odds.json

Schedule --check (Task Scheduler) to get alerted when Circa updates; then ping
Claude to refresh circa_data.json, and run --write.
"""
import argparse
import hashlib
import io
import json
import os
import sys
import zipfile

import requests

from common import CACHE_DIR, load, save, set_to_win, stamp_book

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

BOOK = "circa"
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "circa_data.json")
FOLDER_URL = ("https://www.dropbox.com/scl/fo/9clr2jrvjbdfmn6pe7wzg/"
              "AIko5lXuRnsrAP8e7W4i8HE?rlkey=oq3gvnmsmcinl1ixioffnvjcb&dl=1")
PDF_NAME = "NHL Futures 2026-27.pdf"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def _tls():
    try:
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        pass


def fetch_pdf():
    """Download the Dropbox folder zip and return the NHL futures PDF bytes."""
    r = requests.get(FOLDER_URL, headers=HEADERS, timeout=90)
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = [n for n in z.namelist() if n == PDF_NAME] or \
            [n for n in z.namelist() if n.endswith(PDF_NAME) and "Circa Sports sheets" not in n]
    if not names:
        raise FileNotFoundError(f"{PDF_NAME} not found in folder. Names: {z.namelist()[:20]}")
    info = z.getinfo(names[0])
    return z.read(names[0]), info.date_time


def render_png(pdf_bytes):
    try:
        import fitz
        d = fitz.open(stream=pdf_bytes, filetype="pdf")
        pix = d[0].get_pixmap(matrix=fitz.Matrix(2, 2))
        os.makedirs(CACHE_DIR, exist_ok=True)
        out = os.path.join(CACHE_DIR, "circa_nhl.png")
        pix.save(out)
        return out
    except ImportError:
        return None


def check():
    _tls()
    with open(DATA_FILE, encoding="utf-8") as f:
        known = json.load(f)
    pdf, mtime = fetch_pdf()
    live = hashlib.sha256(pdf).hexdigest()
    changed = live != known.get("source_sha256")
    png = render_png(pdf)
    stamp = "-".join(f"{p:02d}" for p in mtime[:3]) + f" {mtime[3]:02d}:{mtime[4]:02d}"
    print(f"Circa NHL PDF   file-modified: {stamp}")
    print(f"  live sha:  {live}")
    print(f"  known sha: {known.get('source_sha256')}")
    if changed:
        print("  *** CHANGED — circa_data.json is STALE. Send the rendered PNG "
              "to Claude to refresh it, then run --write. ***")
        if png:
            print(f"  rendered current sheet -> {png}")
    else:
        print("  no change — circa_data.json is current.")
    return changed


def write():
    with open(DATA_FILE, encoding="utf-8") as f:
        data = json.load(f)
    doc = load()
    n = 0
    for market in ("cup", "conference"):
        for team, odds in data.get(market, {}).items():
            set_to_win(doc, market, team, BOOK, odds)
            n += 1
    stamp_book(doc, BOOK, data.get("updated"))
    print(f"  wrote {n} Circa prices (cup + conference) from circa_data.json "
          f"[transcribed {data.get('updated')}]")
    if n:
        save(doc)
    flag = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "CIRCA_UPDATED.flag")
    if os.path.exists(flag):
        os.remove(flag)
        print("  cleared CIRCA_UPDATED.flag")
    print("  (run `python scrapers\\circa.py` to poll Dropbox for a newer sheet)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="apply circa_data.json to odds.json")
    args = ap.parse_args()
    if args.write:
        write()
    else:
        # exit 2 signals "Circa updated" so the scheduled task can flag it
        sys.exit(2 if check() else 0)


if __name__ == "__main__":
    main()
