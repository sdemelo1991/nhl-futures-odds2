"""Sportsbook registry: canonical order, sharp classification, display labels.

Single source of truth so app.py and build_seed.py never drift on the book list.
Sharp = the books whose prices anchor the market (first 5 + Caesars). Non-sharp
= the rest, shown for line-shopping but weighted lower for pricing decisions.
"""

BOOKS = [
    "pinnacle", "circa", "fanduel", "kalshi", "bookmaker", "betonline", "caesars",  # sharp
    "draftkings", "betmgm", "hardrock", "bet365", "thescore", "kambi", "betano", "dazn",  # non-sharp
]
# Dropped: bet99, betvictor — both blocked by FanDuel corporate network (sites
# won't load on the work laptop, so neither scrapeable nor readable-to-paste).
# LABELS/BRAND entries kept below so they're a one-line re-add from a home machine.

SHARP = {"pinnacle", "circa", "fanduel", "kalshi", "bookmaker", "betonline", "caesars"}

# Books entered by paste (no scraper) — mobile-only / no usable API / blocked
# on the work network (bet365), or stream odds over an uncapturable WebSocket
# (hardrock — HAR only yields the static price ladder, not the board). See memory.
MANUAL = {"circa", "bookmaker", "caesars", "bet365", "hardrock"}

# The book we manage / want to be alerted about when it's on an arb or middle.
HOME_BOOK = "fanduel"

LABELS = {
    "pinnacle": "Pinnacle", "circa": "Circa", "fanduel": "FanDuel", "kalshi": "Kalshi",
    "bookmaker": "Bookmaker", "betonline": "BetOnline", "caesars": "Caesars",
    "draftkings": "DraftKings", "betmgm": "BetMGM", "kambi": "Kambi",
    "bet99": "Bet99", "betano": "Betano", "hardrock": "Hard Rock", "dazn": "DAZN",
    "betvictor": "BetVictor", "bet365": "bet365", "thescore": "theScore",
}


# Approximate brand colors (hex). Used for badges and best-book/price highlights.
BRAND = {
    "pinnacle": "#4A4F57", "circa": "#1D2C8F", "fanduel": "#1493FF", "kalshi": "#00B84A",
    "bookmaker": "#202124", "betonline": "#D0021B", "caesars": "#B8892B",
    "draftkings": "#61C250", "betmgm": "#A67C2E", "kambi": "#00B5A5",
    "bet99": "#ED1B34", "betano": "#FF6A00", "hardrock": "#7B2D8B",
    "dazn": "#C4B200", "betvictor": "#0A8A43", "bet365": "#027B5B", "thescore": "#12306E",
}


def book_label(b):
    return LABELS.get(b, (b or "").capitalize())


def is_manual(b):
    return b in MANUAL


def brand_color(b):
    return BRAND.get(b, "#7A8AA0")


def text_on(hexcolor):
    """Pick black/white text for contrast against a brand background."""
    h = hexcolor.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return "#0b1622" if lum > 0.6 else "#ffffff"


def is_sharp(b):
    return b in SHARP


def is_home(b):
    return b == HOME_BOOK


def ordered(active):
    """Return active books sharp-first, preserving BOOKS order within each group."""
    active = set(active)
    sharp = [b for b in BOOKS if b in active and is_sharp(b)]
    nonsharp = [b for b in BOOKS if b in active and not is_sharp(b)]
    return sharp, nonsharp
