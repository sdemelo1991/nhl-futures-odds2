r"""One-off maintenance: collapse duplicate player keys in odds.json.

Scrapers key awards/props by canonical_player() on write, but ALIASES added
*after* a book was last written leave stale variant keys behind (set_* only
writes, never deletes). This re-applies canonical_player() to every existing
player key in awards + player_markets and merges any that now collide, so the
search list and award/prop tables show one row per player.

    python scrapers/dedupe_players.py            # dry run (report only)
    python scrapers/dedupe_players.py --write     # apply + save
"""
import argparse
import sys

from common import load, save

sys.path.insert(0, __import__("os").path.dirname(
    __import__("os").path.dirname(__import__("os").path.abspath(__file__))))
from players import canonical_player  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def _merge_award(dst, src):
    if not dst.get("team") and src.get("team"):
        dst["team"] = src["team"]
    dst.setdefault("prices", {}).update(src.get("prices", {}))
    return dst


def _merge_prop(dst, src):
    if not dst.get("team") and src.get("team"):
        dst["team"] = src["team"]
    dst.setdefault("ou", {}).update(src.get("ou", {}))
    for thr, bookmap in (src.get("plus", {}) or {}).items():
        dst.setdefault("plus", {}).setdefault(thr, {}).update(bookmap)
    return dst


def dedupe(doc, section, merge):
    changes = []
    for cat, players in (doc.get(section, {}) or {}).items():
        merged = {}
        for name, entry in players.items():
            ck = canonical_player(name)
            if ck in merged and ck != name:
                changes.append(f"{section}:{cat}: {name!r} -> {ck!r}")
            elif ck != name:
                changes.append(f"{section}:{cat}: {name!r} -> {ck!r}")
            if ck in merged:
                merge(merged[ck], entry)
            else:
                merged[ck] = entry
        doc[section][cat] = merged
    return changes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    doc = load()
    changes = dedupe(doc, "awards", _merge_award) + dedupe(doc, "player_markets", _merge_prop)
    if not changes:
        print("No duplicate player keys found.")
        return
    print(f"{len(changes)} key(s) re-canonicalized / merged:")
    for c in sorted(set(changes)):
        print("  ", c)
    if args.write:
        save(doc)
    else:
        print("\n(dry run — re-run with --write to apply)")


if __name__ == "__main__":
    main()
