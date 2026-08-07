"""NHL team reference data for the 2026-27 season.

Single source of truth for team names, division/conference alignment, and
name-normalization aliases. Scrapers and paste-in parsing should route every
book's team label through `normalize_team()` so prices from different books
line up on the same canonical team key.
"""
import unicodedata


def _deaccent(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


# Canonical team -> (conference, division)
TEAMS = {
    # Eastern - Atlantic
    "Boston Bruins": ("East", "Atlantic"),
    "Buffalo Sabres": ("East", "Atlantic"),
    "Detroit Red Wings": ("East", "Atlantic"),
    "Florida Panthers": ("East", "Atlantic"),
    "Montreal Canadiens": ("East", "Atlantic"),
    "Ottawa Senators": ("East", "Atlantic"),
    "Tampa Bay Lightning": ("East", "Atlantic"),
    "Toronto Maple Leafs": ("East", "Atlantic"),
    # Eastern - Metropolitan
    "Carolina Hurricanes": ("East", "Metropolitan"),
    "Columbus Blue Jackets": ("East", "Metropolitan"),
    "New Jersey Devils": ("East", "Metropolitan"),
    "New York Islanders": ("East", "Metropolitan"),
    "New York Rangers": ("East", "Metropolitan"),
    "Philadelphia Flyers": ("East", "Metropolitan"),
    "Pittsburgh Penguins": ("East", "Metropolitan"),
    "Washington Capitals": ("East", "Metropolitan"),
    # Western - Central
    "Chicago Blackhawks": ("West", "Central"),
    "Colorado Avalanche": ("West", "Central"),
    "Dallas Stars": ("West", "Central"),
    "Minnesota Wild": ("West", "Central"),
    "Nashville Predators": ("West", "Central"),
    "St. Louis Blues": ("West", "Central"),
    "Utah Mammoth": ("West", "Central"),
    "Winnipeg Jets": ("West", "Central"),
    # Western - Pacific
    "Anaheim Ducks": ("West", "Pacific"),
    "Calgary Flames": ("West", "Pacific"),
    "Edmonton Oilers": ("West", "Pacific"),
    "Los Angeles Kings": ("West", "Pacific"),
    "San Jose Sharks": ("West", "Pacific"),
    "Seattle Kraken": ("West", "Pacific"),
    "Vancouver Canucks": ("West", "Pacific"),
    "Vegas Golden Knights": ("West", "Pacific"),
}

CONFERENCES = ["East", "West"]
DIVISIONS = ["Atlantic", "Metropolitan", "Central", "Pacific"]

# Canonical team -> NHL tricode (for official logo assets on assets.nhle.com).
TRICODE = {
    "Boston Bruins": "BOS", "Buffalo Sabres": "BUF", "Detroit Red Wings": "DET",
    "Florida Panthers": "FLA", "Montreal Canadiens": "MTL", "Ottawa Senators": "OTT",
    "Tampa Bay Lightning": "TBL", "Toronto Maple Leafs": "TOR",
    "Carolina Hurricanes": "CAR", "Columbus Blue Jackets": "CBJ", "New Jersey Devils": "NJD",
    "New York Islanders": "NYI", "New York Rangers": "NYR", "Philadelphia Flyers": "PHI",
    "Pittsburgh Penguins": "PIT", "Washington Capitals": "WSH", "Chicago Blackhawks": "CHI",
    "Colorado Avalanche": "COL", "Dallas Stars": "DAL", "Minnesota Wild": "MIN",
    "Nashville Predators": "NSH", "St. Louis Blues": "STL", "Utah Mammoth": "UTA",
    "Winnipeg Jets": "WPG", "Anaheim Ducks": "ANA", "Calgary Flames": "CGY",
    "Edmonton Oilers": "EDM", "Los Angeles Kings": "LAK", "San Jose Sharks": "SJS",
    "Seattle Kraken": "SEA", "Vancouver Canucks": "VAN", "Vegas Golden Knights": "VGK",
}


def tricode(team):
    return TRICODE.get(team)

# Alias -> canonical. Lowercased on lookup. Add entries here whenever a book
# labels a team differently (nicknames, city-only, abbreviations).
_ALIASES = {
    "boston": "Boston Bruins", "bruins": "Boston Bruins", "bos": "Boston Bruins",
    "buffalo": "Buffalo Sabres", "sabres": "Buffalo Sabres", "buf": "Buffalo Sabres",
    "detroit": "Detroit Red Wings", "red wings": "Detroit Red Wings", "det": "Detroit Red Wings",
    "florida": "Florida Panthers", "panthers": "Florida Panthers", "fla": "Florida Panthers",
    "montreal": "Montreal Canadiens", "canadiens": "Montreal Canadiens", "habs": "Montreal Canadiens", "mtl": "Montreal Canadiens",
    "ottawa": "Ottawa Senators", "senators": "Ottawa Senators", "ott": "Ottawa Senators",
    "tampa bay": "Tampa Bay Lightning", "tampa": "Tampa Bay Lightning", "lightning": "Tampa Bay Lightning", "tbl": "Tampa Bay Lightning",
    "toronto": "Toronto Maple Leafs", "maple leafs": "Toronto Maple Leafs", "leafs": "Toronto Maple Leafs", "tor": "Toronto Maple Leafs",
    "carolina": "Carolina Hurricanes", "hurricanes": "Carolina Hurricanes", "canes": "Carolina Hurricanes", "car": "Carolina Hurricanes",
    "columbus": "Columbus Blue Jackets", "blue jackets": "Columbus Blue Jackets", "cbj": "Columbus Blue Jackets",
    "new jersey": "New Jersey Devils", "devils": "New Jersey Devils", "njd": "New Jersey Devils", "nj": "New Jersey Devils",
    "islanders": "New York Islanders", "ny islanders": "New York Islanders", "nyi": "New York Islanders",
    "rangers": "New York Rangers", "ny rangers": "New York Rangers", "nyr": "New York Rangers",
    "philadelphia": "Philadelphia Flyers", "flyers": "Philadelphia Flyers", "phi": "Philadelphia Flyers",
    "pittsburgh": "Pittsburgh Penguins", "penguins": "Pittsburgh Penguins", "pens": "Pittsburgh Penguins", "pit": "Pittsburgh Penguins",
    "washington": "Washington Capitals", "capitals": "Washington Capitals", "caps": "Washington Capitals", "wsh": "Washington Capitals",
    "chicago": "Chicago Blackhawks", "blackhawks": "Chicago Blackhawks", "chi": "Chicago Blackhawks",
    "colorado": "Colorado Avalanche", "avalanche": "Colorado Avalanche", "avs": "Colorado Avalanche", "col": "Colorado Avalanche",
    "dallas": "Dallas Stars", "stars": "Dallas Stars", "dal": "Dallas Stars",
    "minnesota": "Minnesota Wild", "wild": "Minnesota Wild", "min": "Minnesota Wild",
    "nashville": "Nashville Predators", "predators": "Nashville Predators", "preds": "Nashville Predators", "nsh": "Nashville Predators",
    "st. louis": "St. Louis Blues", "st louis": "St. Louis Blues", "blues": "St. Louis Blues", "stl": "St. Louis Blues",
    "st louis blues": "St. Louis Blues", "st. louis blues": "St. Louis Blues",
    "saint louis": "St. Louis Blues", "saint louis blues": "St. Louis Blues",
    "utah": "Utah Mammoth", "mammoth": "Utah Mammoth", "utah mammoth": "Utah Mammoth", "uta": "Utah Mammoth",
    "utah hockey club": "Utah Mammoth",
    "winnipeg": "Winnipeg Jets", "jets": "Winnipeg Jets", "wpg": "Winnipeg Jets",
    "anaheim": "Anaheim Ducks", "ducks": "Anaheim Ducks", "ana": "Anaheim Ducks",
    "calgary": "Calgary Flames", "flames": "Calgary Flames", "cgy": "Calgary Flames",
    "edmonton": "Edmonton Oilers", "oilers": "Edmonton Oilers", "edm": "Edmonton Oilers",
    "los angeles": "Los Angeles Kings", "la kings": "Los Angeles Kings", "kings": "Los Angeles Kings", "lak": "Los Angeles Kings",
    "san jose": "San Jose Sharks", "sharks": "San Jose Sharks", "sjs": "San Jose Sharks",
    "seattle": "Seattle Kraken", "kraken": "Seattle Kraken", "sea": "Seattle Kraken",
    "vancouver": "Vancouver Canucks", "canucks": "Vancouver Canucks", "van": "Vancouver Canucks",
    "vegas": "Vegas Golden Knights", "golden knights": "Vegas Golden Knights", "vgk": "Vegas Golden Knights", "las vegas": "Vegas Golden Knights",
}


def normalize_team(raw: str) -> str:
    """Map a book's team label to a canonical team name. Returns the input
    unchanged (stripped) if no alias matches, so unknown labels surface instead
    of silently dropping."""
    if not raw:
        return raw
    # try raw and an accent-stripped variant (e.g. "Montréal" -> "Montreal")
    for key in (raw.strip(), _deaccent(raw.strip())):
        if key in TEAMS:
            return key
        if key.lower() in _ALIASES:
            return _ALIASES[key.lower()]
    return raw.strip()


def teams_in(conference: str = None, division: str = None):
    out = []
    for team, (conf, div) in TEAMS.items():
        if conference and conf != conference:
            continue
        if division and div != division:
            continue
        out.append(team)
    return out
