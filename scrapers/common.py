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
    """market in {cup, conference, division, presidents, worst}."""
    t = normalize_team(team)
    doc.setdefault("to_win", {}).setdefault(market, {}).setdefault(t, {})[book] = int(odds)


def set_playoff(doc, team, book, side, odds):
    """side in {yes, no}."""
    t = normalize_team(team)
    doc["playoffs"].setdefault(t, {"yes": {}, "no": {}})
    doc["playoffs"][t].setdefault(side, {})[book] = int(odds)


def set_team_points(doc, team, book, line, over, under):
    t = normalize_team(team)
    doc["team_points"].setdefault(t, {})[book] = {
        "line": float(line),
        "over": int(over) if over is not None else None,
        "under": int(under) if under is not None else None,
    }


def set_award(doc, category, player, team, book, odds):
    p = canonical_player(player)
    doc["awards"].setdefault(category, {}).setdefault(
        p, {"team": normalize_team(team) if team else "", "prices": {}}
    )["prices"][book] = int(odds)


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
    """kind in {conf, div, state}."""
    lab = norm_special(kind, label)
    doc.setdefault("cup_specials", {}).setdefault(kind, {}).setdefault(lab, {})[book] = int(odds)


def set_liq(doc, section, label, book, dollars, is_player=False):
    """Store per-selection liquidity ($) for a book (e.g. Kalshi order-book depth
    at the quoted price). `section` matches the table it annotates: to-win markets
    use their market name (cup/conference/...), awards use the category (hart/...).
    The label is normalized the same way the price setter normalizes it, so the
    keys line up in the app."""
    key = canonical_player(label) if is_player else normalize_team(label)
    doc.setdefault("liq", {}).setdefault(section, {}).setdefault(key, {})[book] = round(float(dollars))
