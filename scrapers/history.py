r"""Per-selection price history for the dashboard hover tooltips.

Builds/updates data/price_history.json:

    { market_key: { selection: { book: [[date, value], ...] } } }

where value is an int (odds markets) or {line,over,under} (O/U markets), and a
new [date, value] pair is appended ONLY when the price actually changed. That
keeps it compact and gives each cell a "was X on <date>" trail.

    python scrapers/history.py --backfill   # mine git history of data/odds.json (one-time)
    python scrapers/history.py               # append today's changes from current odds.json

The forward-append is also called after every manual apply / auto-refresh so the
trail stays current for both manual and automated books.
"""
import json
import os
import subprocess
import sys
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ODDS = os.path.join(ROOT, "data", "odds.json")
HIST = os.path.join(ROOT, "data", "price_history.json")


def extract(doc):
    """Flat {(market_key, selection, book): value} for every priced cell."""
    out = {}
    for mkt, teams in (doc.get("to_win") or {}).items():
        for team, books in teams.items():
            for bk, od in books.items():
                if od is not None:
                    out[(mkt, team, bk)] = od
    for team, sides in (doc.get("playoffs") or {}).items():
        for side in ("yes", "no"):
            for bk, od in (sides.get(side) or {}).items():
                if od is not None:
                    out[(f"playoffs:{side}", team, bk)] = od
    for team, books in (doc.get("team_points") or {}).items():
        for bk, q in books.items():
            if isinstance(q, dict):
                out[("team_points", team, bk)] = q
    for cat, players in (doc.get("awards") or {}).items():
        for pl, entry in players.items():
            for bk, od in ((entry or {}).get("prices") or {}).items():
                if od is not None:
                    out[(f"award:{cat}", pl, bk)] = od
    for cat, players in (doc.get("player_markets") or {}).items():
        for pl, entry in players.items():
            for bk, q in ((entry or {}).get("ou") or {}).items():
                if isinstance(q, dict):
                    out[(f"prop:{cat}", pl, bk)] = q
    return out


def _last(hist, mk, sel, bk):
    try:
        return hist[mk][sel][bk][-1][1]
    except (KeyError, IndexError):
        return None


def apply_snapshot(hist, doc, date):
    """Append (date, value) for every cell whose value changed vs the last record."""
    changed = 0
    for (mk, sel, bk), val in extract(doc).items():
        if _last(hist, mk, sel, bk) != val:
            hist.setdefault(mk, {}).setdefault(sel, {}).setdefault(bk, []).append([date, val])
            changed += 1
    return changed


def load_hist():
    if os.path.exists(HIST):
        with open(HIST, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_hist(hist):
    with open(HIST, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, separators=(",", ":"))
    n = sum(len(bl) for m in hist.values() for s in m.values() for bl in s.values())
    print(f"  wrote {HIST}  ({n} price points, {os.path.getsize(HIST)//1024} KB)")


def backfill():
    """Replay every committed version of data/odds.json (oldest->newest).

    Streams all blobs through one `git cat-file --batch` process (one subprocess
    instead of 715) so the whole week replays in seconds."""
    out = subprocess.run(["git", "log", "--reverse", "--format=%H %cs", "--", "data/odds.json"],
                         cwd=ROOT, capture_output=True, text=True, check=True)
    commits = [ln.split(" ", 1) for ln in out.stdout.splitlines() if ln.strip()]
    print(f"  replaying {len(commits)} odds.json commits ...")
    spec = "".join(f"{sha}:data/odds.json\n" for sha, _ in commits).encode()
    proc = subprocess.run(["git", "cat-file", "--batch"], cwd=ROOT, input=spec,
                          stdout=subprocess.PIPE)
    buf, pos, hist = proc.stdout, 0, {}
    for i, (sha, date) in enumerate(commits):
        nl = buf.index(b"\n", pos)
        header = buf[pos:nl].split()
        pos = nl + 1
        if len(header) < 3:           # "<oid> missing"
            continue
        size = int(header[2])
        blob, pos = buf[pos:pos + size], pos + size + 1  # +1 skips trailing \n
        try:
            apply_snapshot(hist, json.loads(blob), date)
        except json.JSONDecodeError:
            pass
        if (i + 1) % 200 == 0:
            print(f"    {i + 1}/{len(commits)}")
    save_hist(hist)


def update():
    """Append changes from the current on-disk odds.json (used after each write)."""
    with open(ODDS, encoding="utf-8") as f:
        doc = json.load(f)
    hist = load_hist()
    date = datetime.datetime.now().strftime("%Y-%m-%d")
    n = apply_snapshot(hist, doc, date)
    save_hist(hist)
    print(f"  logged {n} price changes [{date}]")


if __name__ == "__main__":
    backfill() if "--backfill" in sys.argv else update()
