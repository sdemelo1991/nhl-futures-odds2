"""Shared helpers for local scrapers: odds.json read/write, team normalization,
and typed setters so each book's scraper writes into the same schema.

Scrapers run LOCALLY (sportsbook sites are blocked in the Claude environment).
Each scraper pulls one book and calls the set_* helpers, then save().
"""
import datetime
import json
import os
import re
import sys

# make teams.py importable when run as `python scrapers/xxx.py`
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from teams import normalize_team  # noqa: E402
from players import canonical_player  # noqa: E402

DATA_PATH = os.path.join(_ROOT, "data", "odds.json")
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")


def load():
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


def save(doc, stamp=True):
    if stamp:
        doc.setdefault("meta", {})["last_updated"] = \
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
    print(f"  saved -> {DATA_PATH}")


def stamp_book(doc, book, when=None):
    """Record when a book's odds were last set (per-book freshness). `when` is a
    date/label string (e.g. from a manual data file); defaults to today."""
    if when is None:
        when = datetime.datetime.now().strftime("%Y-%m-%d")
    doc.setdefault("meta", {}).setdefault("book_updated", {})[book] = when


def dump_raw(name, payload):
    os.makedirs(CACHE_DIR, exist_ok=True)
    p = os.path.join(CACHE_DIR, f"{name}.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"  raw dumped -> {p}")
    return p


# --- typed setters (all team labels normalized on write) --------------------
def set_to_win(doc, market, team, book, odds):
    """market in {cup, conference, division, presidents, worst}. Returns the
    normalized team key so callers can track what they saw this run (for
    prune_stale)."""
    t = normalize_team(team)
    doc.setdefault("to_win", {}).setdefault(market, {}).setdefault(t, {})[book] = int(odds)
    return t


def set_playoff(doc, team, book, side, odds):
    """side in {yes, no}. Returns the normalized team key."""
    t = normalize_team(team)
    doc["playoffs"].setdefault(t, {"yes": {}, "no": {}})
    doc["playoffs"][t].setdefault(side, {})[book] = int(odds)
    return t


def set_team_points(doc, team, book, line, over, under):
    t = normalize_team(team)
    doc["team_points"].setdefault(t, {})[book] = {
        "line": float(line),
        "over": int(over) if over is not None else None,
        "under": int(under) if under is not None else None,
    }
    return t


def _valid_jack_adams_coaches():
    """The 32 current NHL coaches, loaded once. Jack Adams is the one award
    category with a small, closed, authoritative roster, so we can reject
    anything a book briefly exposes (test runners, since-suspended markets)
    that doesn't match a real coach — see e.g. FanDuel's stray 'test' runner
    that leaked a +10000 price into awards.jack_adams."""
    path = os.path.join(_ROOT, "coaches_2026-27.json")
    try:
        with open(path, encoding="utf-8") as f:
            coaches = json.load(f)
        return {c["coach"].strip().lower() for c in coaches}
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return None  # roster unavailable — don't block writes


def set_award(doc, category, player, team, book, odds):
    """Returns the canonical player key on success, None if the roster check
    rejected it (so callers building a prune_stale `seen` set don't add it).
    Canonicalize BEFORE the roster check, not after — a book can suffix a
    disambiguator onto the raw name (e.g. FanDuel's Jack Adams runners went
    from "Peter DeBoer" to "Peter DeBoer (NYI)"), and canonical_player()
    already strips a trailing "(...)" the same way it does for players; check
    the raw string first and every coach fails the roster match."""
    p = canonical_player(player)
    if category == "jack_adams":
        roster = _valid_jack_adams_coaches()
        if roster is not None and p.strip().lower() not in roster:
            print(f"  !! skipped jack_adams runner not on the coach roster: "
                  f"{player!r} ({book}, {odds:+d})")
            return None
    doc["awards"].setdefault(category, {}).setdefault(
        p, {"team": normalize_team(team) if team else "", "prices": {}}
    )["prices"][book] = int(odds)
    return p


def set_player_prop(doc, category, player, team, book,
                    line=None, over=None, under=None, plus=None, yes=None):
    """Write a player-prop quote into player_markets[category][player].
    Two forms (a scraper calls whichever a market is):
      O/U line   -> pass line + over/under
      X+ milestone -> pass plus (the N) + yes (the price)
    Stored so props_engine can normalize N+ to over@(N-0.5)."""
    p = canonical_player(player)
    entry = doc.setdefault("player_markets", {}).setdefault(category, {}).setdefault(
        p, {"team": normalize_team(team) if team else "", "ou": {}, "plus": {}})
    if team and not entry.get("team"):
        entry["team"] = normalize_team(team)
    if line is not None:
        q = entry["ou"].setdefault(book, {})
        q["line"] = float(line)
        if over is not None:
            q["over"] = int(over)
        if under is not None:
            q["under"] = int(under)
    if plus is not None and yes is not None:
        entry["plus"].setdefault(str(int(plus)), {})[book] = int(yes)


# --- "Cup Specials": which conference/division/state the CHAMPION comes from ---
# These are distinct from the team conference/division winner markets. They are
# labelled by an attribute of the champion, not by a team, so outcomes are free
# text ("Eastern Conference", "Atlantic Division", "Florida", ...). Books phrase
# the market title as either "... of Winner" (FanDuel) or "Winning ..." (theScore,
# Betano, etc.); the outcome labels vary, so both title and label are normalized.
_SPECIAL_DIVS = ("Atlantic", "Metropolitan", "Central", "Pacific")


def classify_special(title):
    """Return 'conf' / 'div' / 'state' if `title` is a champion-attribute market,
    else None. Gated on the 'of winner' / 'winning ...' phrasing so it can never
    steal a plain team market ('Conference Winner', 'Atlantic Division - Winner')."""
    t = (title or "").lower()
    if not ("of winner" in t or "winning " in t or t.startswith("winning")):
        return None
    # Reject conference-SCOPED conditional sub-markets (BetMGM: "Eastern Conference:
    # Winning division/state/country") — those are 2-way splits within one conference,
    # not the champion's overall attribute. The real market is "(Stanley Cup) Winning
    # Conference" with East/West outcomes, which never carries an east/west scope.
    if "eastern conference" in t or "western conference" in t:
        return None
    if "country" in t or "nation" in t:  # champion's country — not tracked
        return None
    if "conference" in t:
        return "conf"
    if "division" in t:
        return "div"
    if "state" in t or "province" in t:
        return "state"
    return None


def norm_special(kind, label):
    """Canonicalize an outcome label so the same selection lines up across books."""
    s = (label or "").strip()
    low = s.lower()
    if kind == "conf":
        if "east" in low:
            return "Eastern Conference"
        if "west" in low:
            return "Western Conference"
        return s
    if kind == "div":
        for d in _SPECIAL_DIVS:
            if d.lower() in low:
                return f"{d} Division"
        return s
    # state / province — drop the "(FLA, TBL)" team hint books tack on and any
    # trailing "Team(s)" (DraftKings labels these "Florida Team"); books group
    # states differently, so a bare state/province name is the stable key.
    s = re.sub(r"\s*\([^)]*\)", "", s).strip()
    s = re.sub(r"\s+teams?$", "", s, flags=re.I).strip()
    low = s.lower()
    if "any other" in low or "other state" in low or low in ("other", "field", "the field"):
        return "Any Other State/Province"
    return s


def set_special(doc, kind, label, book, odds):
    """kind in {conf, div, state}. Returns the normalized label."""
    lab = norm_special(kind, label)
    doc.setdefault("cup_specials", {}).setdefault(kind, {}).setdefault(lab, {})[book] = int(odds)
    return lab


def prune_stale(doc, book, seen):
    """Drop `book`'s price from any selection under a covered section/market
    that wasn't seen this run — i.e. the book no longer posts a price there,
    most likely because it got suspended/pulled since the last scrape.

    Only call this for scrapers that pull a COMPLETE live snapshot of a
    market every run (direct APIs / live replays) — never for HAR-replay
    books falling back to a stale capture, since "not seen" there just means
    "not in this old file," not "suspended."

    `seen` covers only the sections/markets this scraper actually touched
    this run; e.g. {"to_win": {"cup": {...}, "conference": {...}},
    "playoffs_yes": {...}, "playoffs_no": {...}, "team_points": {...},
    "awards": {"jack_adams": {...}, "hart": {...}}, "cup_specials": {"conf": {...}}}.
    A market is skipped (left untouched) if its seen set came back empty —
    that almost always means a parsing failure, not a real wipe of the board,
    so we degrade to leaving old data in place rather than risk nuking it.
    """
    removed = 0

    for market, keys in (seen.get("to_win") or {}).items():
        if not keys:
            continue
        for team, prices in doc.get("to_win", {}).get(market, {}).items():
            if team not in keys and book in prices:
                del prices[book]
                removed += 1

    for side_key, side in (("playoffs_yes", "yes"), ("playoffs_no", "no")):
        keys = seen.get(side_key)
        if not keys:
            continue
        for team, sides in doc.get("playoffs", {}).items():
            if team not in keys and book in sides.get(side, {}):
                del sides[side][book]
                removed += 1

    keys = seen.get("team_points")
    if keys:
        for team, prices in doc.get("team_points", {}).items():
            if team not in keys and book in prices:
                del prices[book]
                removed += 1

    for cat, keys in (seen.get("awards") or {}).items():
        if not keys:
            continue
        for player, entry in doc.get("awards", {}).get(cat, {}).items():
            prices = entry.get("prices", {})
            if player not in keys and book in prices:
                del prices[book]
                removed += 1

    for kind, keys in (seen.get("cup_specials") or {}).items():
        if not keys:
            continue
        for label, prices in doc.get("cup_specials", {}).get(kind, {}).items():
            if label not in keys and book in prices:
                del prices[book]
                removed += 1

    if removed:
        print(f"  pruned {removed} stale {book} price(s) (suspended/pulled since last scrape)")
    return removed


def set_liq(doc, section, label, book, dollars, is_player=False):
    """Store per-selection liquidity ($) for a book (e.g. Kalshi order-book depth
    at the quoted price). `section` matches the table it annotates: to-win markets
    use their market name (cup/conference/...), awards use the category (hart/...).
    The label is normalized the same way the price setter normalizes it, so the
    keys line up in the app."""
    key = canonical_player(label) if is_player else normalize_team(label)
    doc.setdefault("liq", {}).setdefault(section, {}).setdefault(key, {})[book] = round(float(dollars))
