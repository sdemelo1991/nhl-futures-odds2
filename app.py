"""NHL Futures — Pricing Desk (2026-27). Clean light/dark dashboard.

Four sections: To Win, Playoffs, Team Points, Awards. Comparison tables render
as custom cards (theme-aware, brand-color book headers + logos, best cells as
brand chips) with a Sort control and a per-book/per-market OVERROUND (hold %)
row under each book header. Books split SHARP (shaded, first) vs non-sharp;
FanDuel (HOME_BOOK) is outlined and flagged 🚩 on any arb/middle it's a leg of.
"""
import base64
import datetime
import json
import os
import statistics

import streamlit as st

from teams import CONFERENCES, DIVISIONS, TEAMS, teams_in, tricode
from awards import AWARD_CATEGORIES
from player_props import PROP_CATEGORIES
from props_engine import (unify_quotes, line_grid, prop_arbs, prop_arbs_with_book,
                          prop_middles, prop_middles_with_book, primary_line)
from players import player_team, canonical_player
from books import (
    BOOKS, SHARP, HOME_BOOK, book_label, is_sharp, is_home, is_manual, ordered,
    brand_color, text_on,
)
from odds_engine import (
    american_to_decimal, american_to_prob, decimal_to_american, fmt_american,
    best_price, two_way_arb, two_way_arb_with_book, points_same_index_arb,
    points_same_index_arb_with_book, points_middles, points_middles_with_book,
    line_spread,
)

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "odds.json")
HIST_PATH = os.path.join(os.path.dirname(__file__), "data", "price_history.json")
ASSETS = os.path.join(os.path.dirname(__file__), "assets", "logos")
TEAM_ASSETS = os.path.join(os.path.dirname(__file__), "assets", "teams")

st.set_page_config(page_title="NHL Futures · Hub", layout="wide", page_icon="🏒")

SORT_OPTS = ["Best price: fav → long", "Best price: long → fav",
             "Consensus: fav → long", "Consensus: long → fav",
             "Name A → Z", "Name Z → A"]

# --- odds display format (American / Decimal) — global toggle in the header ---
_AM = fmt_american          # keep the original American formatter
ODDS_FMT = "american"       # set from the header toggle each run


def fmt_odds(a):
    """Format an American price per the global display mode. None -> em dash;
    decimal shown to 2 dp. Everything on screen goes through this."""
    if a is None:
        return "—"
    if ODDS_FMT == "decimal":
        d = american_to_decimal(a)
        return f"{d:.2f}" if d is not None else "—"
    return _AM(a)


def _set_odds_fmt(decimal: bool):
    global ODDS_FMT
    ODDS_FMT = "decimal" if decimal else "american"

PALETTES = {
    "light": {
        "bg": "#f3f4f7", "card": "#ffffff", "text": "#191c24", "muted": "#8b90a0",
        "accent": "#6c5ce7", "border": "#ececf1", "hover": "#f7f8fa",
        "pos": "#16a34a", "neg": "#e5484d", "sharp": "#f6f5ff", "cbord": "rgba(0,0,0,.15)",
        "shadow": "0 1px 2px rgba(16,24,40,.06), 0 1px 3px rgba(16,24,40,.05)",
    },
    "dark": {
        "bg": "#20242e", "card": "#2b3039", "text": "#eef1f5", "muted": "#a7adba",
        "accent": "#8b7cf5", "border": "rgba(255,255,255,.12)", "hover": "rgba(255,255,255,.05)",
        "pos": "#3ecf77", "neg": "#f0616d", "sharp": "rgba(139,124,245,.16)", "cbord": "rgba(255,255,255,.35)",
        "shadow": "0 1px 3px rgba(0,0,0,.35)",
    },
}


def theme_css(mode: str) -> str:
    p = PALETTES[mode]
    # In dark mode the light-based native widgets (nav, dropdowns, tabs, expanders)
    # render white — darken them so they don't glare.
    dark_widgets = "" if mode == "light" else """
[data-baseweb="select"] > div { background:#333944 !important; border-color:rgba(255,255,255,.16) !important; }
[data-baseweb="select"] div, [data-baseweb="select"] span, [data-baseweb="select"] input { color:#eef1f5 !important; }
ul[role="listbox"], [data-baseweb="menu"], [data-baseweb="popover"] > div { background:#333944 !important; }
ul[role="listbox"] li, [data-baseweb="menu"] li { color:#eef1f5 !important; }
[data-testid="stTabs"] button[role="tab"] p { color:#c7ccd6 !important; }
[data-testid="stTabs"] button[role="tab"][aria-selected="true"] p { color:#fff !important; }
[data-testid="stExpander"] details { background:#333944 !important; border-color:rgba(255,255,255,.12) !important; }
[data-testid="stExpander"] summary, [data-testid="stExpander"] summary span, [data-testid="stExpander"] p { color:#eef1f5 !important; }
.tlogo { background:#eef1f5 !important; border-radius:5px; padding:1px; }
"""
    return f"""
<style>
:root {{ --text:{p['text']}; --muted:{p['muted']}; --accent:{p['accent']};
  --card:{p['card']}; --border:{p['border']}; --sharp:{p['sharp']}; --hover:{p['hover']};
  --pos:{p['pos']}; --neg:{p['neg']}; --shadow:{p['shadow']}; --cbord:{p['cbord']}; }}
{dark_widgets}
.stApp {{ background:{p['bg']}; color:var(--text); }}
[data-testid="stHeader"] {{ background:transparent; }}
section[data-testid="stSidebar"] > div {{ background:var(--card); border-right:1px solid var(--border); }}
.stApp, .stApp p, .stApp label, .stApp span, .stApp div, .stApp h1,.stApp h2,.stApp h3,.stApp h4 {{ color:var(--text); }}
.stButton>button {{ background:var(--card); color:var(--text); border:1px solid var(--border);
  border-radius:9px; font-weight:600; }}
.stButton>button:hover {{ border-color:var(--accent); color:var(--accent); }}
.app-title {{ font-size:1.7rem; font-weight:800; letter-spacing:-.3px; margin:0; }}
.app-title .accent {{ color:var(--accent); }}
.app-sub {{ color:var(--muted); font-size:.82rem; margin-top:1px; }}
.kpi-row {{ display:flex; gap:14px; flex-wrap:wrap; margin:14px 0 4px 0; }}
.kpi {{ flex:1; min-width:150px; background:var(--card); border:1px solid var(--border);
  border-radius:14px; box-shadow:var(--shadow); padding:14px 16px; }}
.kpi .lab {{ text-transform:uppercase; font-size:.66rem; letter-spacing:.7px; color:var(--muted); font-weight:700; }}
.kpi .val {{ font-size:1.5rem; font-weight:800; margin-top:4px; }}
.kpi .val.pos {{ color:var(--pos); }} .kpi .val.neg {{ color:var(--neg); }}
.kpi .sub {{ color:var(--muted); font-size:.72rem; margin-top:2px; }}
.card {{ background:var(--card); border:1px solid var(--border); border-radius:14px;
  box-shadow:var(--shadow); padding:16px 18px; margin:12px 0; }}
.card h4 {{ margin:0 0 10px 0; font-size:1rem; font-weight:700; }}
.legend {{ color:var(--muted); font-size:.76rem; margin:0 0 8px 2px; }}
.tablewrap {{ overflow:auto; max-height:72vh; }}
table.cmp {{ width:100%; border-collapse:collapse; font-size:.85rem; font-variant-numeric:tabular-nums; }}
.cmp th, .cmp td {{ padding:7px 10px; text-align:right; white-space:nowrap; border:none; }}
.cmp thead tr:only-child th {{ border-bottom:1px solid var(--border); }}
.cmp thead th {{ text-transform:uppercase; font-size:.68rem; letter-spacing:.4px; color:var(--muted); font-weight:700; vertical-align:top; }}
.cmp .upd {{ display:inline-block; margin-top:2px; font-size:.6rem; font-weight:600; color:var(--muted); text-transform:none; letter-spacing:0; }}
.cmp th.name, .cmp td.name {{ text-align:left; }}
.cmp td.name {{ font-weight:600; }}
.cmp th.logocell, .cmp td.logocell {{ text-align:center; }}
.cmp th.sharp {{ background:var(--sharp); }}
.cmp th.home, .cmp td.home {{ box-shadow:inset 0 0 0 1.5px var(--accent); }}
.cmp .dim {{ color:var(--muted); }}
.cmp td .liq {{ font-size:.62rem; font-weight:700; color:var(--muted); margin-top:1px;
  letter-spacing:.2px; }}
.cmp td .pmile {{ font-size:.62rem; color:var(--muted); }}
/* a moved price becomes a click target that opens its history popover */
.pxcell {{ background:none; border:0; padding:0; margin:0; font:inherit; color:inherit; line-height:inherit;
  cursor:pointer; text-decoration:underline dotted rgba(127,127,127,.5); text-underline-offset:3px; }}
.phpop {{ border:1px solid var(--border); border-radius:12px; padding:0; margin:auto; max-height:72vh;
  overflow:auto; background:var(--card); color:var(--text); box-shadow:0 16px 48px rgba(0,0,0,.5); min-width:230px; }}
.phpop::backdrop {{ background:rgba(0,0,0,.45); }}
.phhead {{ font-weight:800; font-size:.9rem; padding:11px 16px 4px; }}
.phsub {{ font-size:.72rem; color:var(--muted); padding:0 16px 8px; }}
.phtab {{ width:100%; border-collapse:collapse; font-size:.82rem; }}
.phtab th {{ text-align:right; color:var(--muted); font-weight:600; padding:6px 16px; position:sticky; top:0;
  background:var(--card); border-bottom:1px solid var(--border); }}
.phtab th:first-child, .phtab td:first-child {{ text-align:left; }}
.phtab td {{ padding:6px 16px; text-align:right; border-top:1px solid rgba(127,127,127,.14); white-space:nowrap; }}
.phtab tr:first-child td {{ font-weight:700; }}  /* most-recent row stands out */
.tlogo {{ height:46px; width:46px; vertical-align:middle; object-fit:contain; }}
.tlogo.sm {{ height:20px; width:20px; }}
.pname {{ display:inline-flex; align-items:center; gap:7px; vertical-align:middle; line-height:1; }}
.pname .tlogo.sm {{ position:relative; top:0; flex:0 0 auto; }}
.cmp tr.hold td, .cmp tr.runners td, .cmp tr.offered td {{ color:var(--muted); font-size:.72rem;
  font-weight:700; padding-top:1px; padding-bottom:1px; }}
.cmp tr.hold td {{ padding-top:5px; }}
.cmp tr.lastsub td {{ border-bottom:1px solid var(--border); padding-bottom:5px; }}
.cmp tr.hold td.name, .cmp tr.runners td.name, .cmp tr.offered td.name {{ text-transform:uppercase; letter-spacing:.5px; }}
/* FREEZE PANES: header row + Hold + #-of-runners stay put; body scrolls under.
   Sticky cells need opaque backgrounds; sharp columns use a translucent tint, so
   layer that tint over a solid card fill (gradient trick) to stop bleed-through. */
.cmp thead th, .cmp thead td {{ position:sticky; z-index:2; background:var(--card); }}
.cmp thead th.sharp, .cmp thead td.sharp {{ background:linear-gradient(var(--sharp), var(--sharp)), var(--card); }}
.cmp thead tr:first-child th {{ top:0; height:48px; z-index:3; }}
.cmp thead tr.hold td {{ top:48px; height:24px; }}
.cmp thead tr.runners td {{ top:72px; height:24px; }}
.cmp thead tr.offered td {{ top:96px; height:24px; }}
.cmp thead tr.lastsub td, .cmp thead tr:only-child th {{ box-shadow:inset 0 -1px 0 var(--border); }}
.dot {{ display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:5px; vertical-align:middle; }}
.chip {{ display:inline-flex; align-items:center; gap:4px; padding:2px 8px; border-radius:7px;
  font-weight:800; font-size:.82rem; border:1px solid var(--cbord); }}
.chip img, .lg {{ height:14px; vertical-align:middle; }}
.deskcard {{ border-left:4px solid var(--muted); position:relative; }}
.deskcard.fd {{ border-left:4px solid var(--accent); }}
.deskcard .row {{ margin-top:5px; font-size:.9rem; }}
.deskcard .meta {{ color:var(--muted); font-size:.8rem; margin-top:3px; }}
.flag {{ position:absolute; left:30%; top:50%; transform:translateY(-50%); background:#1493FF;
  color:#fff; padding:2px 11px; border-radius:6px; font-weight:800; font-size:1.25rem; line-height:1.1; }}
.free {{ background:var(--pos); color:#fff; padding:0 6px; border-radius:5px; font-weight:700; font-size:.7rem; }}
.deskcard.compact {{ padding:6px 12px; margin:5px 0; border-radius:10px; }}
.deskcard.compact .row {{ font-size:.82rem; margin-top:2px; }}
.deskcard.compact .meta {{ font-size:.72rem; margin-top:1px; }}
.deskcard.compact .flag {{ font-size:1.05rem; padding:2px 8px; }}
/* FanDuel Desk KPI tile — clickable, calm (uses card bg so dark mode isn't glaring),
   FD-blue left accent + FanDuel logo as a left icon (URL injected in main).
   Targeted via the button's own key wrapper (attribute-contains = build-robust). */
.st-key-kpirow {{ margin:14px 0 4px 0; }}
[class*="st-key-fdkpi_btn"], [class*="st-key-fdkpi_btn"] .stButton {{ height:100%; }}
[class*="st-key-fdkpi_btn"] button {{ width:100%; height:100%; min-height:88px;
  background-color:var(--card) !important; color:var(--text) !important;
  border:1px solid var(--border) !important; border-left:4px solid #1493FF !important;
  border-radius:14px !important; box-shadow:var(--shadow) !important;
  padding:12px 16px 12px 62px !important;
  display:flex !important; flex-direction:column; align-items:flex-start; justify-content:center;
  gap:2px; line-height:1.25; text-align:left !important; font-weight:600 !important;
  background-repeat:no-repeat; background-position:14px center; background-size:38px auto; }}
[class*="st-key-fdkpi_btn"] button p {{ margin:0 !important; color:var(--text) !important; }}
[class*="st-key-fdkpi_btn"] button:hover {{ background-color:var(--hover) !important;
  color:var(--text) !important; border-color:var(--border) !important;
  border-left-color:#1493FF !important; }}
/* bigger header toggles — use `zoom` (reserves real layout space, unlike
   transform:scale) so the enlarged toggle never spills over the search box. */
[class*="st-key-thememode"], [class*="st-key-oddsfmt"] {{ zoom:1.5; }}
/* big section nav — custom button bar (proven .stButton selector) */
.st-key-secnav {{ margin:8px 0 6px 0; }}
.st-key-secnav .stButton>button {{ font-size:2.0rem !important; font-weight:800 !important;
  padding:20px 10px !important; height:auto !important; border-radius:13px !important;
  letter-spacing:-.3px; white-space:nowrap; }}
.st-key-secnav .stButton>button[kind="primary"] {{ background:var(--accent) !important;
  color:#fff !important; border-color:var(--accent) !important; }}
.st-key-secnav .stButton>button[kind="secondary"] {{ background:var(--card) !important;
  color:var(--text) !important; border:1px solid var(--border) !important; }}
.st-key-secnav .stButton>button[kind="secondary"]:hover {{ border-color:var(--accent) !important;
  color:var(--accent) !important; }}
[class*="st-key-search_sel"] {{ margin-top:2px; }}
/* bigger sub-tabs */
[data-testid="stTabs"] button[role="tab"] {{ padding:8px 16px !important; height:auto !important; }}
[data-testid="stTabs"] button[role="tab"] p {{ font-size:1.25rem !important; font-weight:600; }}
</style>"""


# --------------------------------------------------------------------------- data
@st.cache_data(show_spinner=False)
def load_data(mtime: float):
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


def get_data():
    mtime = os.path.getmtime(DATA_PATH) if os.path.exists(DATA_PATH) else 0.0
    return load_data(mtime)


@st.cache_data(show_spinner=False)
def load_history(mtime: float):
    if not os.path.exists(HIST_PATH):
        return {}
    with open(HIST_PATH, encoding="utf-8") as f:
        return json.load(f)


def get_history():
    mtime = os.path.getmtime(HIST_PATH) if os.path.exists(HIST_PATH) else 0.0
    return load_history(mtime)


_LOGO_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
              ".webp": "image/webp", ".svg": "image/svg+xml"}


@st.cache_data(show_spinner=False)
def logo_uri(book: str):
    for ext, mime in _LOGO_MIME.items():
        p = os.path.join(ASSETS, f"{book}{ext}")
        if os.path.exists(p):
            return f"data:{mime};base64," + base64.b64encode(open(p, "rb").read()).decode()
    return None


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def logo_img(book):
    uri = logo_uri(book)
    return f"<img class='lg' src='{uri}'/>" if uri else ""


@st.cache_data(show_spinner=False)
def team_logo_uri(tri):
    p = os.path.join(TEAM_ASSETS, f"{tri}.svg")
    if os.path.exists(p):
        return "data:image/svg+xml;base64," + base64.b64encode(open(p, "rb").read()).decode()
    return None


def team_logo(team, cls="tlogo"):
    tri = tricode(team)
    uri = team_logo_uri(tri) if tri else None
    return f"<img class='{cls}' src='{uri}' title='{esc(team)}'/>" if uri else esc(team)


SHADE_MIN, SHADE_MAX = 0.07, 0.46  # brand-color cell tint (between subtle & bold)


def _hexrgb(h):
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def shade(book, prob, lo, hi):
    """Inline style tinting a price cell in the book's brand color, intensity
    scaled by implied probability within that book's column."""
    if prob is None:
        return ""
    frac = 0.5 if hi == lo else (prob - lo) / (hi - lo)
    a = SHADE_MIN + frac * (SHADE_MAX - SHADE_MIN)
    r, g, b = _hexrgb(brand_color(book))
    return f"background:rgba({r},{g},{b},{a:.2f})"


def chip(book, text):
    c = brand_color(book)
    return f"<span class='chip' style='background:{c};color:{text_on(c)}'>{logo_img(book)}{esc(text)}</span>"


def leg_badge(book, odds):
    return chip(book, f"{fmt_odds(odds)} · {book_label(book)}")


def best_of(prices, subset=None):
    if subset is not None:
        prices = {b: o for b, o in prices.items() if b in subset}
    return best_price(prices)


def best_chip(prices, subset=None):
    bk, od = best_of(prices, subset)
    return chip(bk, f"{fmt_odds(od)} {book_label(bk)}") if bk else "<span class='dim'>—</span>"


def overround(rows, book):
    """Sum of implied probabilities for a book's prices across a market's field."""
    ps = [american_to_prob(rows[l].get(book)) for l in rows]
    ps = [p for p in ps if p is not None]
    return sum(ps) if ps else None


def runners_to_100(rows, book):
    """How many selections (biggest favorite downward) it takes for this book's
    cumulative implied probability to reach 100%, linearly interpolated to one
    decimal. Lower = book juices the chalk / less depth; higher = more depth.
    None if the book's field never sums to 100% (overround < 1)."""
    probs = sorted((p for p in (american_to_prob(rows[l].get(book)) for l in rows)
                    if p is not None), reverse=True)
    cum = 0.0
    for i, p in enumerate(probs):
        if cum + p >= 1.0 and p > 0:
            return round(i + (1.0 - cum) / p, 1)
        cum += p
    return None


def consensus_dec(prices, books, stat):
    """Mean or median of the books' decimal prices for a selection."""
    ds = [american_to_decimal(prices.get(b)) for b in books]
    ds = [d for d in ds if d]
    if not ds:
        return None
    return statistics.mean(ds) if stat == "Average" else statistics.median(ds)


def consensus_american(prices, books, stat):
    d = consensus_dec(prices, books, stat)
    return decimal_to_american(d) if d else None


def sort_labels(rows, opt, all_books=(), stat="Average"):
    def bdec(l):
        d = american_to_decimal(best_of(rows[l])[1])
        return d if d else float("inf")

    def cdec(l):
        d = consensus_dec(rows[l], all_books, stat)
        return d if d else float("inf")

    def tier(l):
        """Ranking tier for price/consensus sorts: FanDuel-listed runners first
        (our home book only lists real contenders), then non-FD names with 2+
        books, then 'rogue' singles (one non-FD book) last — so a lone Kambi
        +3000 longshot, or a Kambi-floor pile, can't outrank FD-listed players."""
        p = rows[l]
        if p.get(HOME_BOOK) is not None:
            return 0
        return 1 if sum(1 for v in p.values() if v is not None) >= 2 else 2

    def desc_key(fn):
        return lambda l: (fn(l) == float("inf"), -(fn(l) if fn(l) != float("inf") else 0))

    labels = list(rows)
    if opt == "Best price: fav → long":
        labels.sort(key=lambda l: (tier(l), bdec(l)))
    elif opt == "Best price: long → fav":
        labels.sort(key=lambda l: (tier(l),) + desc_key(bdec)(l))
    elif opt == "Consensus: fav → long":
        labels.sort(key=lambda l: (tier(l), cdec(l)))
    elif opt == "Consensus: long → fav":
        labels.sort(key=lambda l: (tier(l),) + desc_key(cdec)(l))
    elif opt == "Name Z → A":
        labels.sort(key=lambda l: l.lower(), reverse=True)
    else:
        labels.sort(key=lambda l: l.lower())
    return labels


# --------------------------------------------------------------------------- comparison table
BOOK_UPDATED = {}  # book -> last-updated label, filled from odds.json meta
BOOK_MARKET_UPDATED = {}  # book -> {market_key -> date}; per-market freshness override
PRICE_HISTORY = {}  # market_key -> {selection -> {book -> [[date, value], ...]}}
CONSENSUS = "Average"  # "Average" | "Median", set per section from the UI control


def fmt_updated(s):
    try:
        d = datetime.datetime.strptime(str(s)[:10], "%Y-%m-%d")
        return f"{d.strftime('%b')} {d.day}"
    except (ValueError, TypeError):
        return str(s)


_POP_ID = [0]


def _pid():
    _POP_ID[0] += 1
    return f"ph{_POP_ID[0]}"


def merge_sides(a, b):
    """Combine two 1-way trails ([[date, val], ...]) into [(date, aval, bval)] at
    every change point of either side (forward-filling the other), newest-first.
    Used for 2-way markets (Yes/No, Over/Under) so both sit on one row per date."""
    a, b = a or [], b or []
    def asof(trail, date):
        val = None
        for d, v in trail:
            if d <= date:
                val = v
            else:
                break
        return val
    out = []
    for d in sorted({d for d, _ in a} | {d for d, _ in b}):
        row = (d, asof(a, d), asof(b, d))
        if not out or (out[-1][1], out[-1][2]) != (row[1], row[2]):
            out.append(row)
    return list(reversed(out))


def popover(trigger, book, subtitle, header_cols, rows):
    """Wrap `trigger` (the visible price) in a click-to-open history popover.
    header_cols = column labels; rows = list of pre-formatted string lists,
    newest-first. Returns the full cell HTML (trigger button + hidden popover)."""
    if not rows:
        return trigger
    pid = _pid()
    thead = "".join(f"<th>{esc(c)}</th>" for c in header_cols)
    trs = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    sub = f"<div class='phsub'>{esc(subtitle)}</div>" if subtitle else ""
    return (f"<button type='button' class='pxcell' popovertarget='{pid}'>{trigger}</button>"
            f"<div id='{pid}' popover class='phpop'>"
            f"<div class='phhead'>{esc(book_label(book))}</div>{sub}"
            f"<table class='phtab'><thead><tr>{thead}</tr></thead><tbody>{trs}</tbody></table></div>")


def one_way_cell(cell, book, label, trail):
    """cell HTML for a 1-way price; adds a Date/Price history popover if it moved."""
    if not trail or len(trail) < 2:
        return cell
    rows = [[fmt_updated(d), fmt_odds(v)] for d, v in reversed(trail)]
    return popover(cell, book, label, ["Date", "Price"], rows)


def ou_cell(cell, book, label, trail):
    """cell HTML for an O/U price; popover columns Date | Line | Over | Under."""
    if not trail or len(trail) < 2:
        return cell
    rows = [[fmt_updated(d),
             f"{q['line']:g}" if isinstance(q.get("line"), (int, float)) else str(q.get("line")),
             fmt_odds(q.get("over")), fmt_odds(q.get("under"))]
            for d, q in reversed(trail) if isinstance(q, dict)]
    return popover(cell, book, label, ["Date", "Line", "Over", "Under"], rows)


def book_th(b, cls, market=None):
    """Header cell for a book column; manual books get an 'updated <date>' line.
    A per-market date (BOOK_MARKET_UPDATED[b][market]) overrides the book-level one,
    so a market vetted today reads fresh even if the rest of the book wasn't touched."""
    upd = ""
    if b == "kalshi":
        upd = "<br><span class='upd'>liq @ best · $300 min</span>"
    elif is_manual(b):
        when = BOOK_MARKET_UPDATED.get(b, {}).get(market) or BOOK_UPDATED.get(b)
        if when:
            upd = f"<br><span class='upd'>updated {esc(fmt_updated(when))}</span>"
    return (f"<th class='{cls}'><span class='dot' style='background:{brand_color(b)}'></span>"
            f"{esc(book_label(b))}{upd}</th>")


def comparison_html(rows, sharp_cols, nonsharp_cols, sort_opt, kind="team", team_map=None,
                    consensus=None, count_row=False, liq=None, name_hdr=None, market=None,
                    hist=None):
    if not rows:
        return "<div class='legend'>No prices yet.</div>"
    stat = consensus or CONSENSUS
    all_books = sharp_cols + nonsharp_cols
    home = HOME_BOOK if HOME_BOOK in all_books else None
    blanks = "<td></td><td></td><td></td>"  # consensus + Best(Sharp) + Best(All)

    def bkcls(b):
        return (("sharp " if is_sharp(b) else "") + ("home" if b == home else "")).strip()

    # per-book implied lo/hi for brand-color shading
    lohi = {}
    for b in all_books:
        ps = [p for p in (american_to_prob(rows[l].get(b)) for l in rows) if p is not None]
        lohi[b] = (min(ps), max(ps)) if ps else (0.0, 0.0)

    # header row 1: names
    cons_hdr = "Median" if stat == "Median" else "Avg"
    namecls = "name logocell" if kind == "team" else "name"
    hdr_lbl = name_hdr or ("Team" if kind == "team" else "Player")
    hdr_style = " style='text-align:center'" if name_hdr else ""
    th = [f"<th class='{namecls}'{hdr_style}>{hdr_lbl}</th>"]
    for b in all_books:
        th.append(book_th(b, bkcls(b), market))
    th.append(f"<th>{cons_hdr}</th><th>Best (Sharp)</th><th>Best (All)</th>")

    # sub-header row: overround / hold
    hold = ["<td class='name' style='text-align:center'>Hold</td>"]
    for b in all_books:
        ov = overround(rows, b)
        hold.append(f"<td class='{bkcls(b)}'>{ov*100:.1f}%</td>" if ov else f"<td class='{bkcls(b)}'>—</td>")
    hold.append(blanks)

    # sub-header row: runners to reach 100%
    r100 = ["<td class='name' style='text-align:center'># of runners @ 100%</td>"]
    for b in all_books:
        v = runners_to_100(rows, b)
        r100.append(f"<td class='{bkcls(b)}'>{v:.1f}</td>" if v is not None else f"<td class='{bkcls(b)}'>—</td>")
    r100.append(blanks)

    # optional sub-header row (awards): total selections offered per book
    offered = None
    if count_row:
        offered = ["<td class='name' style='text-align:center'># of runners</td>"]
        for b in all_books:
            c = sum(1 for l in rows if rows[l].get(b) is not None)
            offered.append(f"<td class='{bkcls(b)}'>{c or '—'}</td>")
        offered.append(blanks)

    body = []
    for label in sort_labels(rows, sort_opt, all_books, stat):
        prices = rows[label]
        if kind == "team":
            ident = team_logo(label)
        else:
            tm = (team_map or {}).get(label, "")
            lg = team_logo(tm, "tlogo sm") if tm else ""
            ident = f"<span class='pname'>{esc(label)}{lg}</span>"
        tds = [f"<td class='{namecls}'>{ident}</td>"]
        for b in all_books:
            v = prices.get(b)
            if v is not None:
                lo, hi = lohi[b]
                cell = fmt_odds(v)
                if b == "kalshi" and liq and liq.get(label):
                    cell += f"<div class='liq'>${liq[label]:,.0f}</div>"
                trail = (hist or {}).get(label, {}).get(b)
                tds.append(f"<td class='{bkcls(b)}' style='{shade(b, american_to_prob(v), lo, hi)}'>"
                           f"{one_way_cell(cell, b, label, trail)}</td>")
            else:
                tds.append(f"<td class='{bkcls(b)}'><span class='dim'>—</span></td>")
        tds.append(f"<td>{fmt_odds(consensus_american(prices, all_books, stat))}</td>")
        tds.append(f"<td>{best_chip(prices, subset=SHARP)}</td><td>{best_chip(prices)}</td>")
        body.append("<tr>" + "".join(tds) + "</tr>")

    subrows = [f"<tr class='hold'>{''.join(hold)}</tr>",
               f"<tr class='runners'>{''.join(r100)}</tr>"]
    if offered:
        subrows.append(f"<tr class='offered'>{''.join(offered)}</tr>")
    subrows[-1] = subrows[-1].replace("<tr class='", "<tr class='lastsub ", 1)  # divider on last

    return (f"<div class='tablewrap'><table class='cmp'><thead>"
            f"<tr>{''.join(th)}</tr>{''.join(subrows)}</thead>"
            f"<tbody>{''.join(body)}</tbody></table></div>")


def card(inner, title=None):
    head = f"<h4>{esc(title)}</h4>" if title else ""
    st.markdown(f"<div class='card'>{head}{inner}</div>", unsafe_allow_html=True)


LEGEND = ("<div class='legend'>Shaded = sharp book · FanDuel outlined = home book · "
          "Hold = market overround (Σ implied prob) · best cells in brand color</div>")


def show_cards(cards, top=3, more_label="more"):
    """Render the first `top` arb/middle cards; tuck the rest behind an expander
    so these sections stay compact and don't bury the tables below."""
    if not cards:
        return
    st.markdown("".join(cards[:top]), unsafe_allow_html=True)
    if len(cards) > top:
        with st.expander(f"Show {len(cards) - top} {more_label}"):
            st.markdown("".join(cards[top:]), unsafe_allow_html=True)


# --------------------------------------------------------------------------- KPIs
def compute_kpis(data):
    books, priced = set(), 0
    for m in ("cup", "conference", "division"):
        for _, p in data["to_win"][m].items():
            if p:
                priced += 1
                books |= set(p)
    for _, s in data["playoffs"].items():
        for side in ("yes", "no"):
            if s.get(side):
                books |= set(s[side])
        if s.get("yes") or s.get("no"):
            priced += 1
    for _, l in data["team_points"].items():
        if l:
            priced += 1
            books |= set(l)
    for _, players in data["awards"].items():
        for _, v in players.items():
            if v.get("prices"):
                priced += 1
                books |= set(v["prices"])

    arbs, edges, mids = 0, [], 0
    for _, s in data["playoffs"].items():
        a = two_way_arb(s.get("yes", {}), s.get("no", {}))
        if a:
            arbs += 1
            edges.append(a["margin"])
    for _, l in data["team_points"].items():
        for a in points_same_index_arb(l):
            arbs += 1
            edges.append(a["margin"])
        mids += len(points_middles(l, min_gap=1.0))
    return {"priced": priced, "books": len(books), "arbs": arbs, "middles": mids,
            "edge": max(edges) if edges else None}


def fd_signals(data, max_gap=3.0):
    """Every arb & middle where FanDuel (HOME_BOOK) is a leg, across Playoffs +
    Team Points + Player Props. Returns (arbs, mids); each item is a dict with a
    pre-rendered 'card' and a sort key ('margin' for arbs, 'gap' for middles).
    This is the data behind both the FD KPI tile and the FD Desk page."""
    arbs, mids = [], []

    def arb_card(kind, headline, a_leg, b_leg):
        stake = (f" · stake {a_leg['stake_a_pct']*100:.0f}% / {a_leg['stake_b_pct']*100:.0f}%"
                 if "stake_a_pct" in a_leg else "")
        return (f"<div class='card deskcard compact fd'>"
                f"<span class='pmile'>{kind}</span> <b>{headline}</b>"
                f"<div class='row'>{a_leg['legs']}</div>"
                f"<div class='meta'>Profit <b>{a_leg['margin']*100:.2f}%</b>{stake}</div></div>")

    def mid_item(kind, headline, m):
        free = " <span class='free'>FREE MIDDLE</span>" if m.get("is_free_middle") else ""
        legs = (f"Over {m['over_line']:g} {leg_badge(m['over_book'], m['over_odds'])} &nbsp;vs&nbsp; "
                f"Under {m['under_line']:g} {leg_badge(m['under_book'], m['under_odds'])}")
        card = (f"<div class='card deskcard compact fd'>"
                f"<span class='pmile'>{kind}</span> <b>{headline}</b> · gap <b>{m['gap']}</b>{free}"
                f"<div class='row'>{legs}</div>"
                f"<div class='meta'>Middle band <b>{m['over_line']:g} – {m['under_line']:g}</b> · "
                f"combined implied {m['combined_implied']*100:.1f}%</div></div>")
        return {"gap": m["gap"], "card": card}

    # --- Playoffs (Yes/No arb; no middle concept) ---
    # Force FanDuel onto a leg: a market can have a bigger arb via two other books
    # while FD still forms a real arb of its own — the Desk must show FD's.
    for team in TEAMS:
        s = data["playoffs"].get(team, {})
        a = two_way_arb_with_book(s.get("yes", {}), s.get("no", {}), HOME_BOOK)
        if a:
            a["legs"] = (f"Yes {leg_badge(a['a_book'], a['a_odds'])} &nbsp;vs&nbsp; "
                         f"No {leg_badge(a['b_book'], a['b_odds'])}")
            arbs.append({"margin": a["margin"], "card": arb_card("Playoffs", esc(team), a, None)})

    # --- Team Points (same-line arb + cross-index middles) ---
    for team in TEAMS:
        l = data["team_points"].get(team)
        if not l:
            continue
        for a in points_same_index_arb_with_book(l, HOME_BOOK):
            a["legs"] = (f"Over {leg_badge(a['a_book'], a['a_odds'])} &nbsp;vs&nbsp; "
                         f"Under {leg_badge(a['b_book'], a['b_odds'])}")
            arbs.append({"margin": a["margin"],
                         "card": arb_card("Team Points", f"{esc(team)} · line {a['line']:g}", a, None)})
        for m in points_middles_with_book(l, HOME_BOOK, min_gap=0.5):
            mids.append(mid_item("Team Points", esc(team), m))

    # --- Player Props (unified O/U + X+; arbs + cross-form middles) ---
    for cat, players in (data.get("player_markets", {}) or {}).items():
        clabel = PROP_CATEGORIES.get(cat, cat)
        for name, entry in players.items():
            q = unify_quotes(entry)
            logo = team_logo(player_team(name) or entry.get("team", ""), "tlogo sm")
            head = f"{esc(name)} {logo}"
            for a in prop_arbs_with_book(q, HOME_BOOK):
                a["legs"] = (f"Over {leg_badge(a['a_book'], a['a_odds'])} &nbsp;vs&nbsp; "
                             f"Under {leg_badge(a['b_book'], a['b_odds'])}")
                arbs.append({"margin": a["margin"],
                             "card": arb_card(f"Props · {clabel}", f"{head} · o{a['line']:g}", a, None)})
            for m in prop_middles_with_book(q, HOME_BOOK, min_gap=1.0, max_gap=max_gap):
                mids.append(mid_item(f"Props · {clabel}", head, m))

    return arbs, mids


def kpi_row(k, fd_arb_n=0, fd_mid_n=0):
    def cell(lab, val, sub, tone=""):
        return (f"<div class='kpi'><div class='lab'>{lab}</div>"
                f"<div class='val {tone}'>{val}</div><div class='sub'>{sub}</div></div>")
    edge = f"{k['edge']*100:.2f}%" if k["edge"] is not None else "—"
    tiles = [
        cell("Priced Selections", f"{k['priced']}", "teams / players with a price"),
        cell("Books Live", f"{k['books']}", f"of {len(BOOKS)} tracked"),
        cell("Open Arbs", f"{k['arbs']}", "playoffs + team points", "pos" if k["arbs"] else ""),
        cell("Open Middles", f"{k['middles']}", "≥ 1 index apart", "pos" if k["middles"] else ""),
        cell("Top Edge", edge, "best guaranteed margin", "pos" if k["edge"] else ""),
    ]
    box = st.container(key="kpirow")
    with box:
        cols = st.columns([1, 1, 1, 1, 1, 1.25], gap="small")
        for col, h in zip(cols[:5], tiles):
            col.markdown(h, unsafe_allow_html=True)
        with cols[5]:
            clicked = st.button(
                f"FanDuel Desk  \n{fd_arb_n} arbs · {fd_mid_n} middles",
                key="fdkpi_btn", use_container_width=True,
                help="Every arb & middle FanDuel is a leg of — Playoffs, Team Points "
                     "& Player Props. The book we manage; monitor it closest.")
    if clicked:
        st.session_state["nav_section"] = "FD Desk"
        st.session_state["_clear_search"] = True  # FD Desk overrides any active search
        st.rerun()


# --------------------------------------------------------------------------- sections
def kalshi_liq(data):
    """Return liq_of(section) -> {label: dollars}, Kalshi's stored order-book
    liquidity at the quoted price, keyed the same way the price rows are."""
    liq = data.get("liq", {}) or {}

    def liq_of(section):
        sect = liq.get(section) or {}
        return {lab: v.get("kalshi") for lab, v in sect.items() if v.get("kalshi")}
    return liq_of


def render_to_win(data, sharp_cols, nonsharp_cols):
    global CONSENSUS
    st.markdown(LEGEND, unsafe_allow_html=True)
    cc = st.columns([2, 1])
    sort_opt = cc[0].selectbox("Sort", SORT_OPTS, key="sort_towin")
    CONSENSUS = cc[1].selectbox("Consensus (Avg / Median)", ["Average", "Median"], key="cons_towin")
    liq_of = kalshi_liq(data)
    t_cup, t_conf, t_div, t_pres, t_worst, t_spec = st.tabs(
        ["🏆 Stanley Cup", "Conference", "Division", "Most Points", "Least Points",
         "Cup Specials"])
    with t_cup:
        rows = {t: p for t, p in data["to_win"]["cup"].items() if p}
        card(comparison_html(rows, sharp_cols, nonsharp_cols, sort_opt, liq=liq_of("cup"),
                             hist=PRICE_HISTORY.get("cup")),
             "Stanley Cup — To Win")
    with t_conf:
        for conf in CONFERENCES:
            rows = {t: data["to_win"]["conference"].get(t, {}) for t in teams_in(conference=conf)
                    if data["to_win"]["conference"].get(t)}
            card(comparison_html(rows, sharp_cols, nonsharp_cols, sort_opt, liq=liq_of("conference"),
                                 hist=PRICE_HISTORY.get("conference")),
                 f"{conf}ern Conference")
    with t_div:
        for div in DIVISIONS:
            rows = {t: data["to_win"]["division"].get(t, {}) for t in teams_in(division=div)
                    if data["to_win"]["division"].get(t)}
            card(comparison_html(rows, sharp_cols, nonsharp_cols, sort_opt,
                                 hist=PRICE_HISTORY.get("division")), f"{div} Division")
    with t_pres:
        pres = data["to_win"].get("presidents", {})
        rows = {t: pres.get(t, {}) for t in TEAMS if pres.get(t)}
        card(comparison_html(rows, sharp_cols, nonsharp_cols, sort_opt,
                             hist=PRICE_HISTORY.get("presidents")),
             "Most Points (Presidents' Trophy)")
    with t_worst:
        worst = data["to_win"].get("worst", {})
        rows = {t: worst.get(t, {}) for t in TEAMS if worst.get(t)}
        card(comparison_html(rows, sharp_cols, nonsharp_cols, sort_opt,
                             hist=PRICE_HISTORY.get("worst")),
             "Least Points (Worst Record)")
    with t_spec:
        sp = data.get("cup_specials", {}) or {}
        st.caption("Which conference / division / state-province the Stanley Cup "
                   "champion comes from — a lower-priority board, so it lives here.")
        any_sp = False
        for kind, title in (("conf", "Champion's Conference"),
                            ("div", "Champion's Division"),
                            ("state", "Champion's State / Province")):
            rows = {lab: pr for lab, pr in (sp.get(kind) or {}).items() if pr}
            if rows:
                any_sp = True
                card(comparison_html(rows, sharp_cols, nonsharp_cols, sort_opt,
                                     kind="player", name_hdr="Outcome"), title)
        if not any_sp:
            st.info("No Cup Specials prices yet — they populate the next time a book "
                    "that lists them is refreshed (FanDuel, theScore, DAZN, Betano, etc.).")


def render_playoffs(data, sharp_cols, nonsharp_cols):
    all_books = sharp_cols + nonsharp_cols
    arbs = []
    for team in TEAMS:
        sides = data["playoffs"].get(team, {})
        arb = two_way_arb(sides.get("yes", {}), sides.get("no", {}))
        if arb:
            fd = is_home(arb["a_book"]) or is_home(arb["b_book"])
            arbs.append((team, arb, fd))
    arbs.sort(key=lambda x: (not x[2], -x[1]["margin"]))

    st.markdown("#### ⚡ Arbitrage")
    if arbs:
        html = []
        for team, a, fd in arbs:
            flag = "<span class='flag'>🚩 FD</span>" if fd else ""
            html.append(
                f"<div class='card deskcard compact {'fd' if fd else ''}'><b>{esc(team)}</b> — Make Playoffs{flag}"
                f"<div class='row'>Yes {leg_badge(a['a_book'], a['a_odds'])} &nbsp;vs&nbsp; "
                f"No {leg_badge(a['b_book'], a['b_odds'])}</div>"
                f"<div class='meta'>Profit <b>{a['margin']*100:.2f}%</b> · "
                f"stake {a['stake_a_pct']*100:.0f}% / {a['stake_b_pct']*100:.0f}%</div></div>")
        show_cards(html, top=3, more_label="more arbs")
    else:
        st.caption("No Yes/No arbitrage right now.")

    st.markdown("#### Odds — each book shows Yes / No (Hold = Yes+No implied)")
    sort_opt = st.selectbox("Sort", SORT_OPTS, key="sort_po")
    rows = {t: data["playoffs"][t].get("yes", {}) for t in TEAMS
            if data["playoffs"].get(t, {}).get("yes") or data["playoffs"].get(t, {}).get("no")}
    if not rows:
        st.caption("No playoff prices yet.")
        return
    home = HOME_BOOK if HOME_BOOK in all_books else None

    def bkcls(b):
        return (("sharp " if is_sharp(b) else "") + ("home" if b == home else "")).strip()

    # per-book implied lo/hi (of the Yes side) for shading
    lohi = {}
    for b in all_books:
        ps = [p for p in (american_to_prob(data["playoffs"][t].get("yes", {}).get(b))
                          for t in rows) if p is not None]
        lohi[b] = (min(ps), max(ps)) if ps else (0.0, 0.0)

    th = ["<th class='name logocell'>Team</th>"]
    for b in all_books:
        th.append(book_th(b, bkcls(b)))
    th.append("<th>Best Yes</th><th>Best No</th>")
    body = []
    for team in sort_labels(rows, sort_opt):
        yes = data["playoffs"][team].get("yes", {})
        no = data["playoffs"][team].get("no", {})
        tds = [f"<td class='name logocell'>{team_logo(team)}</td>"]
        for b in all_books:
            y, n = yes.get(b), no.get(b)
            if y or n:
                py, pn = american_to_prob(y), american_to_prob(n)
                hold = f"<br><span class='dim' style='font-size:.72rem'>{(py+pn)*100:.1f}%</span>" \
                    if (py is not None and pn is not None) else ""
                lo, hi = lohi[b]
                sty = shade(b, py, lo, hi) if py is not None else ""
                base = f"{fmt_odds(y)} / {fmt_odds(n)}"
                merged = merge_sides(PRICE_HISTORY.get("playoffs:yes", {}).get(team, {}).get(b),
                                     PRICE_HISTORY.get("playoffs:no", {}).get(team, {}).get(b))
                if len(merged) > 1:
                    prows = [[fmt_updated(d), fmt_odds(yv), fmt_odds(nv)] for d, yv, nv in merged]
                    base = popover(base, b, f"{team} — Make Playoffs", ["Date", "Yes", "No"], prows)
                tds.append(f"<td class='{bkcls(b)}' style='{sty}'>{base}{hold}</td>")
            else:
                tds.append(f"<td class='{bkcls(b)}'><span class='dim'>—</span></td>")
        tds.append(f"<td>{best_chip(yes)}</td><td>{best_chip(no)}</td>")
        body.append("<tr>" + "".join(tds) + "</tr>")
    card(f"<div class='tablewrap'><table class='cmp'><thead><tr>{''.join(th)}</tr></thead>"
         f"<tbody>{''.join(body)}</tbody></table></div>")


def fd_middle_band(book_lines):
    """Largest middle FanDuel is a leg of: FD's line vs the book whose line is
    farthest from it (>= 1 apart). Returns (low_line, high_line, gap) or None."""
    fd = book_lines.get(HOME_BOOK)
    if not fd or fd.get("line") is None:
        return None
    f = fd["line"]
    best = None
    for b, q in book_lines.items():
        if b == HOME_BOOK or not q or q.get("line") is None:
            continue
        gap = abs(q["line"] - f)
        if gap >= 1 and (best is None or gap > best[2]):
            best = (min(f, q["line"]), max(f, q["line"]), gap)
    return best


def render_team_points(data, sharp_cols, nonsharp_cols):
    teams_with = [t for t in TEAMS if data["team_points"].get(t)]
    if not teams_with:
        st.caption("No team-points prices yet.")
        return
    arb_cards, mid_cards = [], []
    for team in teams_with:
        for a in points_same_index_arb(data["team_points"][team]):
            fd = is_home(a["a_book"]) or is_home(a["b_book"])
            arb_cards.append((team, a, fd))
        for m in points_middles(data["team_points"][team], min_gap=0.5):
            fd = is_home(m["over_book"]) or is_home(m["under_book"])
            mid_cards.append((team, m, fd))
    arb_cards.sort(key=lambda x: (not x[2], -x[1]["margin"]))
    mid_cards.sort(key=lambda x: (not x[2], -x[1]["gap"]))

    st.markdown("#### ⚡ Arbitrage — same line, Over/Under")
    if arb_cards:
        html = []
        for team, a, fd in arb_cards:
            flag = "<span class='flag'>🚩 FD</span>" if fd else ""
            html.append(
                f"<div class='card deskcard compact {'fd' if fd else ''}'><b>{esc(team)}</b> · line {a['line']}{flag}"
                f"<div class='row'>Over {leg_badge(a['a_book'], a['a_odds'])} &nbsp;vs&nbsp; "
                f"Under {leg_badge(a['b_book'], a['b_odds'])}</div>"
                f"<div class='meta'>Profit <b>{a['margin']*100:.2f}%</b> · "
                f"stake {a['stake_a_pct']*100:.0f}% / {a['stake_b_pct']*100:.0f}%</div></div>")
        show_cards(html, top=3, more_label="more arbs")
    else:
        st.caption("No same-line arbitrage right now.")

    st.markdown("#### 🎯 Middles — books off by ≥ 1 index (ranked by gap)")
    min_gap = st.slider("Minimum line gap (index)", 0.5, 5.0, 1.0, 0.5)
    shown = [(t, m, fd) for (t, m, fd) in mid_cards if m["gap"] >= min_gap]
    if shown:
        html = []
        for team, m, fd in shown:
            flag = "<span class='flag'>🚩 FD</span>" if fd else ""
            free = "<span class='free'>FREE MIDDLE</span>" if m["is_free_middle"] else ""
            html.append(
                f"<div class='card deskcard compact {'fd' if fd else ''}'><b>{esc(team)}</b> "
                f"· gap <b>{m['gap']}</b> {free}{flag}"
                f"<div class='row'>Over {m['over_line']} {leg_badge(m['over_book'], m['over_odds'])} "
                f"&nbsp;vs&nbsp; Under {m['under_line']} {leg_badge(m['under_book'], m['under_odds'])}</div>"
                f"<div class='meta'>Middle band <b>{m['over_line']} – {m['under_line']}</b> · "
                f"combined implied {m['combined_implied']*100:.1f}%</div></div>")
        show_cards(html, top=4, more_label="more middles")
    else:
        st.caption(f"No books ≥ {min_gap} index apart right now.")

    # teams ordered by division -> alphabetical (shared by Team View + grid)
    ordered = []
    for div in DIVISIONS:
        ordered += sorted(t for t in teams_with if TEAMS[t][1] == div)
    all_books = sharp_cols + nonsharp_cols
    home = HOME_BOOK if HOME_BOOK in all_books else None

    def bkcls(b):
        return (("sharp " if is_sharp(b) else "") + ("home" if b == home else "")).strip()

    # ---- Team View (drill-down) ----
    st.divider()
    st.markdown("#### Team View")

    # dropdown with non-selectable division header rows; teams indented beneath
    dd_options, headers, first_team = [], set(), 1
    for div in DIVISIONS:
        divteams = sorted(t for t in teams_with if TEAMS[t][1] == div)
        if not divteams:
            continue
        hdr = f"—————  {div} Division  —————"
        headers.add(hdr)
        if not dd_options:
            first_team = 1  # first real team sits right after the first header
        dd_options.append(hdr)
        dd_options.extend(divteams)

    def tv_label(o):
        if o in headers:
            return o
        band = fd_middle_band(data["team_points"][o])
        if band:
            lo, hi, _ = band
            return f"    {o}   (lines {lo:g}–{hi:g})  *FD middle*"
        return f"    {o}"

    sel = st.selectbox("Team", dd_options, index=first_team, format_func=tv_label, key="tp_team")
    if sel in headers:
        st.caption("Pick a team under a division.")
    else:
        rowsh = []
        for b in all_books:
            q = data["team_points"][sel].get(b)
            if not q:
                continue
            o, u = q.get("over"), q.get("under")
            po, pu = american_to_prob(o), american_to_prob(u)
            hold = f"{(po+pu)*100:.1f}%" if (po is not None and pu is not None) else "—"
            cls = "sharp" if is_sharp(b) else ""
            rowsh.append(f"<tr><td class='name {cls}'><span class='dot' style='background:{brand_color(b)}'></span>"
                         f"{logo_img(b)}{esc(book_label(b))}</td>"
                         f"<td>{q.get('line')}</td><td>{fmt_odds(o)}</td><td>{fmt_odds(u)}</td>"
                         f"<td class='dim'>{hold}</td></tr>")
        s = line_spread(data["team_points"][sel])
        card(f"<div class='tablewrap'><table class='cmp'><thead><tr>"
             f"<th class='name'>Book</th><th>Line</th><th>Over</th><th>Under</th><th>Hold</th>"
             f"</tr></thead><tbody>{''.join(rowsh)}</tbody></table></div>"
             f"<div class='legend'>Line spread {s['spread']} pts across {s['n_books']} books "
             f"({s['distinct_lines']} distinct lines).</div>", title=sel)

    # ---- All-teams grid (third component) ----
    st.divider()
    st.markdown("#### All Teams — Points O/U by Book")
    gth = [f"<th class='name logocell'>Team</th>"] + [book_th(b, bkcls(b)) for b in all_books]
    gbody = []
    for team in sorted(teams_with):
        tds = [f"<td class='name logocell'>{team_logo(team)}</td>"]
        for b in all_books:
            q = data["team_points"][team].get(b)
            if q and q.get("line") is not None:
                cell = (f"o{q['line']:g} {fmt_odds(q.get('over'))} / "
                        f"u {fmt_odds(q.get('under'))}")
                trail = PRICE_HISTORY.get("team_points", {}).get(team, {}).get(b)
                tds.append(f"<td class='{bkcls(b)}'>{ou_cell(cell, b, team, trail)}</td>")
            else:
                tds.append(f"<td class='{bkcls(b)}'><span class='dim'>—</span></td>")
        gbody.append("<tr>" + "".join(tds) + "</tr>")
    card(f"<div class='tablewrap'><table class='cmp'><thead><tr>{''.join(gth)}</tr></thead>"
         f"<tbody>{''.join(gbody)}</tbody></table></div>"
         f"<div class='legend'>Each cell = that book's line + Over / Under price. "
         f"Different lines across books are the index gaps the middle finder ranks.</div>")


def _line_range(data, team):
    s = line_spread(data["team_points"][team])
    if s["min_line"] is None:
        return "—"
    return f"{s['min_line']}" if s["min_line"] == s["max_line"] else f"{s['min_line']}–{s['max_line']}"


def render_awards(data, sharp_cols, nonsharp_cols):
    global CONSENSUS
    st.markdown(LEGEND, unsafe_allow_html=True)
    cc = st.columns([2, 1])
    sort_opt = cc[0].selectbox("Sort", SORT_OPTS, key="sort_awards")
    CONSENSUS = cc[1].selectbox("Consensus (Avg / Median)", ["Average", "Median"], key="cons_awards")
    cats = list(AWARD_CATEGORIES.keys())
    tabs = st.tabs([AWARD_CATEGORIES[c] for c in cats])
    for cat, tab in zip(cats, tabs):
        with tab:
            players = data["awards"].get(cat, {})
            # Merge name variants at display time (e.g. "Elias Pettersson (1998)",
            # "Elias Pettersson", "Elias Pettersson (f)") so books that spell a
            # player differently collapse to one row regardless of odds.json state.
            merged, feed_team = {}, {}
            for p, v in players.items():
                if not v.get("prices"):
                    continue
                cname = canonical_player(p)
                dst = merged.setdefault(cname, {})
                for bk, price in v["prices"].items():
                    if price not in (None, "") and dst.get(bk) in (None, ""):
                        dst[bk] = price
                if v.get("team") and not feed_team.get(cname):
                    feed_team[cname] = v["team"]
            rows = {p: pr for p, pr in merged.items() if pr}
            team_map = {p: (player_team(p) or feed_team.get(p, "")) for p in rows}
            card(comparison_html(rows, sharp_cols, nonsharp_cols, sort_opt,
                                 kind="player", team_map=team_map, count_row=True,
                                 liq=kalshi_liq(data)(cat), market=f"award:{cat}",
                                 hist=PRICE_HISTORY.get(f"award:{cat}")),
                 AWARD_CATEGORIES[cat])


PROP_LEGEND = ("<div class='legend'>Player totals unified across forms: each "
               "<b>N+</b> milestone is treated as <b>Over (N−0.5)</b>, so O/U lines and "
               "X+ milestones share one line axis — best price, arbs, and cross-form "
               "middles all come from the same math.</div>")


def _prop_pchip(book, odds):
    return f"{fmt_odds(odds)} <span class='dim'>{esc(book_label(book))}</span>" if odds is not None else "—"


def prop_middle_card(name, entry, m):
    fd = HOME_BOOK in (m["over_book"], m["under_book"])
    flag = "<span class='flag'>FD</span>" if fd else ""
    free = " <span class='free'>FREE MIDDLE</span>" if m["is_free_middle"] else ""
    logo = team_logo(player_team(name) or entry.get("team", ""), "tlogo sm")
    return (f"<div class='deskcard compact{' fd' if fd else ''}'>{flag}"
            f"<div class='row'><b>{esc(name)}</b> {logo} &nbsp;·&nbsp; gap {m['gap']}{free}</div>"
            f"<div class='meta'>Over o{m['over_line']:g} {fmt_odds(m['over_odds'])} "
            f"({esc(book_label(m['over_book']))}) &nbsp;·&nbsp; "
            f"Under u{m['under_line']:g} {fmt_odds(m['under_odds'])} "
            f"({esc(book_label(m['under_book']))})</div></div>")


def prop_arb_card(name, entry, a):
    fd = HOME_BOOK in (a["a_book"], a["b_book"])
    flag = "<span class='flag'>FD</span>" if fd else ""
    logo = team_logo(player_team(name) or entry.get("team", ""), "tlogo sm")
    return (f"<div class='deskcard compact{' fd' if fd else ''}'>{flag}"
            f"<div class='row'><b>{esc(name)}</b> {logo} &nbsp;·&nbsp; o/u {a['line']:g} "
            f"&nbsp;·&nbsp; {a['margin']*100:.1f}% edge</div>"
            f"<div class='meta'>Over {fmt_odds(a['a_odds'])} ({esc(book_label(a['a_book']))}) "
            f"&nbsp;·&nbsp; Under {fmt_odds(a['b_odds'])} ({esc(book_label(a['b_book']))})</div></div>")


def props_table_html(players, sharp_cols, nonsharp_cols, hist=None):
    """One row per player, one column per book — each cell shows that book's O/U
    (line + over/under) and/or its X+ milestone ladder. Low/High = the span of
    posted lines/indexes across the market. For milestone-only books, the
    threshold nearest the market's average line is bolded; the rest follow in
    brackets."""
    all_books = list(sharp_cols) + list(nonsharp_cols)
    present = set()
    for e in players.values():
        present |= set(e.get("ou", {}))
        for bk in (e.get("plus", {}) or {}).values():
            present |= set(bk)
    cols = [b for b in all_books if b in present]
    if not cols:
        return "<div class='legend'>No prices yet.</div>"

    def bkcls(b):
        return (("sharp " if is_sharp(b) else "") + ("home" if b == HOME_BOOK else "")).strip()

    th = ["<th class='name'>Player</th>", "<th>Best Over</th>", "<th>Best Under</th>"]
    for b in cols:
        th.append(book_th(b, bkcls(b)))

    def best_ou(quotes, extreme, tag):
        """Best available side (O/U only): the over at the lowest posted line, the
        under at the highest — best price at that line — named book + o/u + price."""
        if not quotes:
            return "<span class='dim'>—</span>"
        ln = extreme(q[0] for q in quotes)
        bb, bo = best_price({bk: od for l2, bk, od in quotes if l2 == ln})
        return chip(bb, f"{tag}{ln:g} {fmt_odds(bo)}")

    body = []
    for name, entry in sorted(players.items(),
                              key=lambda kv: (-(primary_line(kv[1]) or -1), kv[0])):
        ou, plus = entry.get("ou", {}), (entry.get("plus", {}) or {})
        ou_lines = [q["line"] for q in ou.values() if q.get("line") is not None]
        avg_line = sum(ou_lines) / len(ou_lines) if ou_lines else None
        overs = [(q["line"], bk, q["over"]) for bk, q in ou.items()
                 if q.get("line") is not None and q.get("over") is not None]
        unders = [(q["line"], bk, q["under"]) for bk, q in ou.items()
                  if q.get("line") is not None and q.get("under") is not None]
        logo = team_logo(player_team(name) or entry.get("team", ""), "tlogo sm")
        ident = f"<span class='pname'>{esc(name)}{logo}</span>"
        tds = [f"<td class='name'>{ident}</td>",
               f"<td>{best_ou(overs, min, 'o')}</td>",
               f"<td>{best_ou(unders, max, 'u')}</td>"]
        for b in cols:
            parts = []
            q = ou.get(b)
            if q and q.get("line") is not None:
                parts.append(f"o{q['line']:g} {fmt_odds(q.get('over'))} / "
                             f"u {fmt_odds(q.get('under'))}")
            ms = sorted((int(t), plus[t][b]) for t in plus if b in plus[t])
            if ms:
                ref = avg_line if avg_line is not None else [t for t, _ in ms][len(ms) // 2]
                closest = min(ms, key=lambda x: abs(x[0] - ref))[0]
                main = next(f"<b>{t}+ {fmt_odds(o)}</b>" for t, o in ms if t == closest)
                others = [f"{t}+ {fmt_odds(o)}" for t, o in ms if t != closest]
                parts.append(main + (f"<br><span class='pmile'>({' · '.join(others)})</span>"
                                     if others else ""))
            cell = "<br>".join(parts) if parts else "<span class='dim'>—</span>"
            trail = (hist or {}).get(name, {}).get(b)
            if q and q.get("line") is not None:  # O/U history popover (milestone-only cells stay plain)
                cell = ou_cell(cell, b, name, trail)
            tds.append(f"<td class='{bkcls(b)}'>{cell}</td>")
        body.append("<tr>" + "".join(tds) + "</tr>")
    return (f"<div class='tablewrap'><table class='cmp'><thead><tr>{''.join(th)}</tr></thead>"
            f"<tbody>{''.join(body)}</tbody></table></div>")


def render_props(data, sharp_cols, nonsharp_cols):
    st.markdown(PROP_LEGEND, unsafe_allow_html=True)
    max_gap = st.slider("Max middle gap (indexes apart)", 1.0, 6.0, 2.0, 0.5, key="gap_props",
                        help="Caps how far the two legs can sit apart — keeps middles "
                             "to comparable, interpretable index ranges.")
    pm = data.get("player_markets", {})
    cats = list(PROP_CATEGORIES.keys())
    tabs = st.tabs([PROP_CATEGORIES[c] for c in cats])
    for cat, tab in zip(cats, tabs):
        with tab:
            players = pm.get(cat, {})
            if not players:
                st.markdown("<div class='legend'>No player-prop data yet — populates "
                            "once a book's prop scraper runs.</div>", unsafe_allow_html=True)
                continue
            mids, arbs = [], []
            for name, entry in players.items():
                q = unify_quotes(entry)
                for a in prop_arbs(q):
                    arbs.append((name, entry, a))
                for m in prop_middles(q, min_gap=1.0, max_gap=max_gap):
                    mids.append((name, entry, m))
            if arbs:
                st.markdown("###### Arbitrage")
                show_cards([prop_arb_card(n, e, a) for n, e, a in arbs], top=3, more_label="more arbs")
            if mids:
                mids.sort(key=lambda x: (x[2]["combined_implied"], x[2]["gap"]))
                st.markdown("###### Middles")
                show_cards([prop_middle_card(n, e, m) for n, e, m in mids], top=3, more_label="more middles")
            card(props_table_html(players, sharp_cols, nonsharp_cols,
                                  hist=PRICE_HISTORY.get(f"prop:{cat}")), PROP_CATEGORIES[cat])


def render_fd_desk(data, sharp_cols, nonsharp_cols):
    uri = logo_uri(HOME_BOOK)
    logo = f"<img src='{uri}' style='height:40px;border-radius:8px;'/>" if uri else ""
    st.markdown(
        f"<div style='display:flex;align-items:center;gap:12px;margin:2px 0 6px 0;'>{logo}"
        f"<span style='font-size:1.5rem;font-weight:800;letter-spacing:-.3px;'>FanDuel Desk</span></div>",
        unsafe_allow_html=True)
    st.markdown(
        "<div class='legend'>Every arbitrage & middle where <b>FanDuel</b> is a leg — "
        "<b>Playoffs</b>, <b>Team Points</b> and <b>Player Props</b> in one place. This is the "
        "book we manage, so it's watched closer than the general comparison pages.</div>",
        unsafe_allow_html=True)
    arbs, mids = fd_signals(data, max_gap=3.0)

    st.markdown(f"#### ⚡ FD Arbitrage — {len(arbs)}")
    if arbs:
        arbs.sort(key=lambda s: -s["margin"])
        show_cards([s["card"] for s in arbs], top=6, more_label="more FD arbs")
    else:
        st.caption("No arbs with a FanDuel leg right now.")

    st.markdown("#### 🎯 FD Middles")
    min_gap = st.slider("Minimum middle gap (index)", 0.5, 5.0, 1.0, 0.5, key="fd_gap")
    shown = [s for s in mids if s["gap"] >= min_gap]
    shown.sort(key=lambda s: -s["gap"])
    if shown:
        st.markdown(f"<div class='legend'>{len(shown)} middle(s) with a FanDuel leg, "
                    f"≥ {min_gap:g} index apart.</div>", unsafe_allow_html=True)
        show_cards([s["card"] for s in shown], top=8, more_label="more FD middles")
    else:
        st.caption(f"No FanDuel middles ≥ {min_gap:g} index apart right now.")


def _mini_table(headers, rows):
    """Small standardized comparison table (reuses .cmp styling)."""
    th = "".join(f"<th class='{'name' if i == 0 else ''}'>{h}</th>" for i, h in enumerate(headers))
    body = "".join("<tr>" + "".join(
        f"<td class='{'name' if i == 0 else ''}'>{c}</td>" for i, c in enumerate(r)) + "</tr>"
        for r in rows)
    return (f"<div class='tablewrap'><table class='cmp'><thead><tr>{th}</tr></thead>"
            f"<tbody>{body}</tbody></table></div>")


def _team_has_any(data, t):
    if any(data["to_win"].get(m, {}).get(t) for m in ("cup", "conference", "division", "presidents", "worst")):
        return True
    return bool(data["playoffs"].get(t) or data["team_points"].get(t))


def _all_players(data):
    s = set()
    for players in data.get("awards", {}).values():
        s |= set(players)
    for players in data.get("player_markets", {}).values():
        s |= set(players)
    return s


def render_team_view(data, team, sharp_cols, nonsharp_cols):
    all_books = sharp_cols + nonsharp_cols
    conf, div = TEAMS.get(team, ("", ""))
    conf_lbl = "Eastern" if conf == "East" else "Western" if conf == "West" else conf
    st.markdown(
        f"<div style='display:flex;align-items:center;gap:14px;margin:4px 0 10px;'>{team_logo(team)}"
        f"<div><div style='font-size:1.6rem;font-weight:800;letter-spacing:-.3px;'>{esc(team)}</div>"
        f"<div class='legend' style='margin:0;'>{esc(div)} Division · {conf_lbl} Conference</div></div></div>",
        unsafe_allow_html=True)

    # --- outright markets (one row each): consensus + best chips ---
    rows = []
    for key, label in (("cup", "Stanley Cup"), ("conference", "Conference"), ("division", "Division"),
                       ("presidents", "Most Points"), ("worst", "Least Points")):
        prices = data["to_win"].get(key, {}).get(team)
        if not prices:
            continue
        rows.append([label, fmt_odds(consensus_american(prices, all_books, "Average")),
                     best_chip(prices, subset=SHARP), best_chip(prices)])
    if rows:
        card(_mini_table(["Market", "Average", "Best (Sharp)", "Best (All)"], rows),
             "Outright markets")

    # --- two-way & totals: playoffs (Yes/No + arb) and points (line range + middle) ---
    tw = []
    sides = data["playoffs"].get(team, {})
    yes, no = sides.get("yes", {}), sides.get("no", {})
    if yes or no:
        arb = two_way_arb(yes, no)
        sig = (f"⚡ {arb['margin']*100:.2f}% ({esc(book_label(arb['a_book']))}/{esc(book_label(arb['b_book']))})"
               if arb else "—")
        tw.append(["Make Playoffs", best_chip(yes), best_chip(no), sig])
    lines = data["team_points"].get(team, {})
    priced = [(b, q.get("line")) for b, q in lines.items() if q and q.get("line") is not None]
    if priced:
        hi = max(priced, key=lambda x: x[1])
        lo = min(priced, key=lambda x: x[1])
        parts = []
        if points_same_index_arb(lines):
            parts.append(f"⚡ {max(a['margin'] for a in points_same_index_arb(lines))*100:.2f}%")
        mids = points_middles(lines, min_gap=0.5)
        if mids:
            parts.append(f"🎯 gap {max(m['gap'] for m in mids):g}")
        tw.append(["Reg. Season Points", chip(hi[0], f"{hi[1]:g} · {book_label(hi[0])}"),
                   chip(lo[0], f"{lo[1]:g} · {book_label(lo[0])}"), " · ".join(parts) or "—"])
    if tw:
        card(_mini_table(["Market", "Best (Yes / Highest)", "Best (No / Lowest)", "Arb / Middle"], tw),
             "Yes/No & totals")
    if not rows and not tw:
        st.info(f"No markets found for {team} yet.")


def render_player_view(data, player, sharp_cols, nonsharp_cols):
    all_books = sharp_cols + nonsharp_cols
    tm = player_team(player)
    logo = team_logo(tm) if tm else ""
    st.markdown(
        f"<div style='display:flex;align-items:center;gap:14px;margin:4px 0 10px;'>{logo}"
        f"<div style='font-size:1.6rem;font-weight:800;letter-spacing:-.3px;'>{esc(player)}</div></div>",
        unsafe_allow_html=True)

    # --- awards (one row each): consensus + best chips ---
    rows = []
    for cat, label in AWARD_CATEGORIES.items():
        entry = data.get("awards", {}).get(cat, {}).get(player)
        if not entry or not entry.get("prices"):
            continue
        prices = entry["prices"]
        rows.append([label, fmt_odds(consensus_american(prices, all_books, "Average")),
                     best_chip(prices, subset=SHARP), best_chip(prices)])
    if rows:
        card(_mini_table(["Award", "Average", "Best (Sharp)", "Best (All)"], rows), "Award markets")

    # --- player props: Best Over / Best Under (O/U lines only, same logic as the
    # Player Props tab — milestones stay out of the line "range" so it isn't
    # misleading) + arb/middle signal (which does span cross-form middles). ---
    def _best_ou(ou, extreme, side):
        """Over at the lowest posted line / Under at the highest (best price at
        that line) — O/U only, matching the Player Props tab. side in {over,under}."""
        pts = [(q["line"], bk, q[side]) for bk, q in ou.items()
               if q.get("line") is not None and q.get(side) is not None]
        if not pts:
            return "<span class='dim'>—</span>"
        ln = extreme(p[0] for p in pts)
        bb, bo = best_price({bk: od for l2, bk, od in pts if l2 == ln})
        return chip(bb, f"{'o' if side == 'over' else 'u'}{ln:g} {fmt_odds(bo)}")

    prows = []
    for cat, label in PROP_CATEGORIES.items():
        entry = data.get("player_markets", {}).get(cat, {}).get(player)
        if not entry:
            continue
        q = unify_quotes(entry)
        if not q:
            continue
        ou = entry.get("ou", {}) or {}
        parts = []
        if prop_arbs(q):
            parts.append(f"⚡ {max(a['margin'] for a in prop_arbs(q))*100:.2f}%")
        mids = prop_middles(q, min_gap=1.0, max_gap=3.0)
        if mids:
            parts.append(f"🎯 gap {max(m['gap'] for m in mids):g}")
        prows.append([label, _best_ou(ou, min, "over"), _best_ou(ou, max, "under"),
                      " · ".join(parts) or "—"])
    if prows:
        card(_mini_table(["Prop", "Best Over", "Best Under", "Arb / Middle"], prows), "Player props")
    if not rows and not prows:
        st.info(f"No markets found for {player} yet.")


# --------------------------------------------------------------------------- main
def main():
    # A nav-tab / FD-tile click asks to leave search; clear the selectbox here,
    # BEFORE it's instantiated (can't modify a widget's state after it renders).
    if st.session_state.pop("_clear_search", False):
        st.session_state.pop("search_sel", None)
    with st.sidebar:
        st.header("Books")
        st.caption("SHARP")
        sharp_active = [b for b in BOOKS if is_sharp(b)
                        and st.checkbox(book_label(b), value=True, key=f"bk_{b}")]
        st.caption("NON-SHARP")
        nonsharp_active = [b for b in BOOKS if not is_sharp(b)
                           and st.checkbox(book_label(b), value=True, key=f"bk_{b}")]
        st.divider()
        if st.button("↻ Reload data", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    hc = st.columns([2.4, 2.4, 2.2], gap="large")
    with hc[2]:
        # Per-user, survives reload on the shared link: theme lives in each
        # browser's own URL (?theme=). session_state wins once toggled in-session.
        saved_theme = st.query_params.get("theme", "light")
        dark = st.toggle("🌙 Dark mode", value=(saved_theme == "dark"), key="thememode")
        saved_odds = st.query_params.get("odds", "american")
        dec = st.toggle("Decimal odds", value=(saved_odds == "decimal"), key="oddsfmt")
    mode = "dark" if dark else "light"
    if st.query_params.get("theme") != mode:
        st.query_params["theme"] = mode  # remember this user's choice across reloads
    _set_odds_fmt(dec)
    if st.query_params.get("odds") != ("decimal" if dec else "american"):
        st.query_params["odds"] = "decimal" if dec else "american"
    st.markdown(theme_css(mode), unsafe_allow_html=True)
    _fd_logo = logo_uri(HOME_BOOK)
    if _fd_logo:  # paint the FanDuel logo onto the clickable FD Desk KPI tile
        st.markdown(f"<style>[class*='st-key-fdkpi_btn'] button{{background-image:url('{_fd_logo}');}}</style>",
                    unsafe_allow_html=True)

    if not os.path.exists(DATA_PATH):
        st.error("data/odds.json not found. Run `python build_seed.py` first.")
        return
    data = get_data()
    meta = data.get("meta", {})
    BOOK_UPDATED.clear()
    BOOK_UPDATED.update(meta.get("book_updated") or {})
    BOOK_MARKET_UPDATED.clear()
    BOOK_MARKET_UPDATED.update(meta.get("book_market_updated") or {})
    PRICE_HISTORY.clear()
    PRICE_HISTORY.update(get_history())

    with hc[0]:
        st.markdown(
            f"<div class='app-title'>NHL Futures <span class='accent'>Hub</span></div>"
            f"<div class='app-sub'>Cup · Conference · Division · Playoffs · Team Points · Awards "
            f"— {esc(meta.get('season','?'))} &nbsp;·&nbsp; updated {esc(meta.get('last_updated') or '—')}</div>",
            unsafe_allow_html=True)
    with hc[1]:  # persistent search — always in view, filters live as you type
        idx = {t: ("team", t) for t in sorted(TEAMS) if _team_has_any(data, t)}
        for p in sorted(_all_players(data)):
            idx.setdefault(p, ("player", p))
        sel = st.selectbox("Search", sorted(idx), index=None, key="search_sel",
                           placeholder="🔎  Search a team or player…",
                           label_visibility="collapsed")
    if meta.get("notes"):
        st.info(meta["notes"], icon="ℹ️")

    fd_arbs, fd_mids = fd_signals(data)
    kpi_row(compute_kpis(data), len(fd_arbs), len(fd_mids))

    sharp_cols, nonsharp_cols = ordered(sharp_active + nonsharp_active)

    # Custom button bar for the section nav — reliable sizing + dark-mode contrast.
    SECTIONS = ["To Win", "Playoffs", "Team Points", "Awards", "Player Props"]
    # FD Desk is reachable only via the top-right KPI tile, not the nav bar.
    if st.session_state.get("nav_section") not in SECTIONS + ["FD Desk"]:
        st.session_state["nav_section"] = "To Win"
    nav = st.container(key="secnav")
    with nav:
        for col, name in zip(st.columns(len(SECTIONS)), SECTIONS):
            with col:
                active = st.session_state["nav_section"] == name and not sel
                if st.button(name, key=f"nav_{name}", use_container_width=True,
                             type="primary" if active else "secondary"):
                    st.session_state["nav_section"] = name
                    st.session_state["_clear_search"] = True  # leave search for the tab
                    st.rerun()
    section = st.session_state["nav_section"]
    st.divider()

    if sel:  # isolated team/player snapshot (search selection)
        kind, name = idx[sel]
        (render_team_view if kind == "team" else render_player_view)(
            data, name, sharp_cols, nonsharp_cols)
    elif section == "FD Desk":
        render_fd_desk(data, sharp_cols, nonsharp_cols)
    elif section == "Playoffs":
        render_playoffs(data, sharp_cols, nonsharp_cols)
    elif section == "Team Points":
        render_team_points(data, sharp_cols, nonsharp_cols)
    elif section == "Awards":
        render_awards(data, sharp_cols, nonsharp_cols)
    elif section == "Player Props":
        render_props(data, sharp_cols, nonsharp_cols)
    else:
        render_to_win(data, sharp_cols, nonsharp_cols)


if __name__ == "__main__":
    main()
