"""Player-name normalization so the same player from different books merges.

Two problems this solves:
  1. Accent differences (Ārturs Šilovs vs Arturs Silovs, Merzļikins vs
     Merzlikins) — handled by stripping diacritics.
  2. Genuine spelling drift between books (Hellebuck vs Hellebuyck, Phillipp
     vs Philipp, Luukonen vs Luukkonen) — handled by the ALIASES map below.

`canonical_player()` returns a single display name for a given input, so all
variants collapse to one row. Add new corrections to ALIASES as you spot them
(key = lowercased, accent-stripped variant; value = correct display name).
"""
import re
import unicodedata

# characters unicodedata's NFKD doesn't decompose
_SPECIAL = str.maketrans({
    "ø": "o", "Ø": "O", "ł": "l", "Ł": "L", "đ": "d", "Đ": "D",
    "ß": "ss", "æ": "ae", "Æ": "Ae", "œ": "oe", "Œ": "Oe", "’": "'",
})

# key: lowercased + accent-stripped variant  ->  correct display name
# (also merges pure casing diffs, e.g. "Gavin Mckenna" vs "Gavin McKenna")
ALIASES = {
    "connor hellebuck": "Connor Hellebuyck",
    "phillipp grubauer": "Philipp Grubauer",
    "ukko-pekka luukonen": "Ukko-Pekka Luukkonen",
    "matt boldy": "Matthew Boldy",
    "mitch marner": "Mitchell Marner",
    "gavin mckenna": "Gavin McKenna",
    "caleb desnoyer": "Caleb Desnoyers",
    "jackson lacomb": "Jackson LaCombe",
    "sebastian aho (car)": "Sebastian Aho",
    "will nylander": "William Nylander",
    "alex debrincat": "Alex DeBrincat",
    "j.t. miller": "JT Miller",
    "jt miller": "JT Miller",
    "tj hughes": "T.J. Hughes",
    "t.j. hughes": "T.J. Hughes",
    "j.t. hughes": "T.J. Hughes",
    "daniel vladar": "Dan Vladar",
    # collapse every Elias Pettersson spelling (forward, "(1998)", plain) to one row
    "elias pettersson": "Elias Pettersson (f)",
    "joshua morrissey": "Josh Morrissey",
    "mackenzie blackwood": "Mackenzie Blackwood",  # normalize "MacKenzie" casing
    # Calder prospects spelled differently across books
    "albert smits": "Alberts Šmits",
    "alberts smits": "Alberts Šmits",
    "bradley nadeau": "Bradly Nadeau",
    "c. desnoyers": "Caleb Desnoyers",
    "oskar fisker molgaard": "Oscar Fisker Mølgaard",
    "oscar fisker molgaard": "Oscar Fisker Mølgaard",
    "oscar molgaard": "Oscar Fisker Mølgaard",
    "sebastian antero aho": "Sebastian Aho",
    "alexander ovechkin": "Alex Ovechkin",
    "matthew barzal": "Mathew Barzal",
    "trey-jonathan hughes": "T.J. Hughes",
    "oscar fisker moelgaard": "Oscar Fisker Mølgaard",
    "joshua samanski": "Josh Samanski",
    "will horcoff": "William Horcoff",
}


def strip_accents(s: str) -> str:
    s = s.translate(_SPECIAL)
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def canonical_player(name: str) -> str:
    """Merge-safe display name: accent-stripped, whitespace-collapsed, and
    corrected via ALIASES. Same output for every spelling of a player."""
    if not name:
        return name
    base = strip_accents(name)
    # Drop a trailing disambiguator in parens, e.g. "Elias Pettersson (1998)",
    # "Sebastian Aho (CAR)", "... (#12)" — so year/team/number suffixes merge.
    # (checked against ALIASES first so an explicit alias can still win.)
    stripped = re.sub(r"\s*\([^)]*\)\s*$", "", base)
    base = " ".join(base.split())
    stripped = " ".join(stripped.split())
    return ALIASES.get(base.lower(), ALIASES.get(stripped.lower(), stripped))


# Player -> current NHL team, for the team logo shown beside award/prop names.
# Award feeds don't include the player's team, so we map it here. Grouped by
# team (inverted below). Add players as they appear; unmapped = no logo (fine
# for draft prospects without an NHL club yet).
_ROSTER = {
    "Edmonton Oilers": ["Connor McDavid", "Leon Draisaitl", "Evan Bouchard", "Stuart Skinner", "Zach Hyman"],
    "Colorado Avalanche": ["Nathan MacKinnon", "Cale Makar", "Martin Necas", "Mackenzie Blackwood",
                           "Devon Toews", "Scott Wedgewood", "Brock Nelson"],
    "San Jose Sharks": ["Macklin Celebrini", "Yaroslav Askarov", "William Eklund", "Tyler Toffoli"],
    "Tampa Bay Lightning": ["Nikita Kucherov", "Andrei Vasilevskiy", "Victor Hedman", "Brayden Point",
                            "Jake Guentzel", "Darren Raddysh"],
    "Minnesota Wild": ["Kirill Kaprizov", "Matthew Boldy", "Jesper Wallstedt", "Filip Gustavsson",
                       "Brock Faber", "Zeev Buium", "Marco Rossi"],
    "Boston Bruins": ["David Pastrnak", "Jeremy Swayman", "Charlie McAvoy", "James Hagens", "Fabian Lysell"],
    "Toronto Maple Leafs": ["Auston Matthews", "William Nylander", "Anthony Stolarz", "Morgan Rielly",
                            "Matthew Knies", "Ben Danford"],
    "New Jersey Devils": ["Jack Hughes", "Jacob Markstrom", "Luke Hughes", "Nico Hischier",
                          "Dougie Hamilton", "Jesper Bratt"],
    "Vancouver Canucks": ["Quinn Hughes", "Thatcher Demko", "Kevin Lankinen", "Elias Pettersson"],
    "Vegas Golden Knights": ["Jack Eichel", "Mitchell Marner", "Adin Hill", "Shea Theodore", "Mark Stone"],
    "Dallas Stars": ["Mikko Rantanen", "Jason Robertson", "Jake Oettinger", "Miro Heiskanen",
                     "Wyatt Johnston", "Roope Hintz"],
    "Montreal Canadiens": ["Nick Suzuki", "Cole Caufield", "Lane Hutson", "Noah Dobson", "Juraj Slafkovsky",
                           "Jakub Dobes", "Jacob Fowler", "David Reinbacher", "Ivan Demidov"],
    "Chicago Blackhawks": ["Connor Bedard", "Spencer Knight", "Anton Frondell", "Artyom Levshunov"],
    "Winnipeg Jets": ["Connor Hellebuyck", "Kyle Connor", "Mark Scheifele", "Josh Morrissey", "Gabriel Vilardi"],
    "New York Rangers": ["Igor Shesterkin", "Adam Fox", "Artemi Panarin", "Mika Zibanejad",
                         "J.T. Miller", "Vincent Trocheck"],
    "Carolina Hurricanes": ["Sebastian Aho", "Frederik Andersen", "Seth Jarvis", "Andrei Svechnikov",
                            "Nikolaj Ehlers", "K'Andre Miller", "Jaccob Slavin", "Logan Stankoven",
                            "Bradly Nadeau", "Shayne Gostisbehere"],
    "Buffalo Sabres": ["Tage Thompson", "Rasmus Dahlin", "Ukko-Pekka Luukkonen", "Alex Tuch",
                       "Owen Power", "Konsta Helenius", "Alex Lyon"],
    "Florida Panthers": ["Matthew Tkachuk", "Aleksander Barkov", "Sam Reinhart", "Sergei Bobrovsky",
                         "Sam Bennett", "Brad Marchand", "Carter Verhaeghe"],
    "Columbus Blue Jackets": ["Zach Werenski", "Kirill Marchenko", "Jet Greaves", "Adam Fantilli"],
    "Detroit Red Wings": ["Alex DeBrincat", "Dylan Larkin", "Moritz Seider", "Lucas Raymond",
                          "Patrick Kane", "John Gibson"],
    "St. Louis Blues": ["Jordan Kyrou", "Robert Thomas", "Jordan Binnington", "Cam Fowler",
                        "Dylan Holloway", "Theo Lindstein", "Jimmy Snuggerud", "Pavel Buchnevich"],
    "Los Angeles Kings": ["Adrian Kempe", "Darcy Kuemper", "Anze Kopitar", "Quinton Byfield",
                          "Brandt Clarke", "Kevin Fiala"],
    "Ottawa Senators": ["Brady Tkachuk", "Tim Stutzle", "Jake Sanderson", "Linus Ullmark",
                        "Drake Batherson", "Dylan Cozens"],
    "Pittsburgh Penguins": ["Sidney Crosby", "Erik Karlsson", "Tristan Jarry", "Evgeni Malkin",
                            "Rickard Rakell", "Harrison Brunicke"],
    "Washington Capitals": ["Alex Ovechkin", "Logan Thompson", "Jakob Chychrun", "John Carlson",
                            "Dylan Strome", "Cole Hutson", "Ilya Protas"],
    "Nashville Predators": ["Roman Josi", "Juuse Saros", "Filip Forsberg", "Steven Stamkos", "Ryan O'Reilly"],
    "Utah Mammoth": ["Clayton Keller", "Mikhail Sergachev", "Karel Vejmelka", "Logan Cooley",
                     "Dylan Guenther", "Tij Iginla", "Keaton Verhoeff", "Nick Schmaltz"],
    "Anaheim Ducks": ["Leo Carlsson", "Cutter Gauthier", "Lukas Dostal", "Jackson LaCombe",
                      "Mason McTavish", "Troy Terry", "Chris Kreider"],
    "Seattle Kraken": ["Joey Daccord", "Matty Beniers", "Jared McCann", "Braeden Cootes", "Chandler Stephenson"],
    "Calgary Flames": ["Dustin Wolf", "Rasmus Andersson", "Nazem Kadri", "Carter Yakemchuk"],
    "New York Islanders": ["Ilya Sorokin", "Bo Horvat", "Mathew Barzal", "Matthew Schaefer", "Anders Lee"],
    "Philadelphia Flyers": ["Trevor Zegras", "Travis Konecny", "Dan Vladar", "Porter Martone",
                            "Matvei Michkov", "Oliver Bonk", "Owen Tippett"],
}
PLAYER_TEAM = {canonical_player(p): team for team, ps in _ROSTER.items() for p in ps}

# Corrections / additions applied on top of _ROSTER (latest first). Overrides win,
# so a player listed both here and in _ROSTER lands on the team below.
_OVERRIDES = {
    "Jordan Kyrou": "Washington Capitals",
    "Quinn Hughes": "Minnesota Wild",
    "Thomas Harley": "Dallas Stars",
    "Darren Raddysh": "Toronto Maple Leafs",
    "Rasmus Andersson": "Vegas Golden Knights",
    "Sergei Bobrovsky": "Toronto Maple Leafs",
    "Stuart Skinner": "Washington Capitals",
    "Arturs Silovs": "Pittsburgh Penguins",
    "Gavin McKenna": "Toronto Maple Leafs",
    "Brandon Hagel": "Tampa Bay Lightning",
    "Elias Pettersson": "Vancouver Canucks",
    "Brady Tkachuk": "Florida Panthers",
    "Matt Duchene": "Dallas Stars",
    "Bowen Byram": "Chicago Blackhawks",
    "Dmitry Orlov": "San Jose Sharks",
    "Filip Hronek": "Vancouver Canucks",
    "Philip Broberg": "St. Louis Blues",
    "John Carlson": "San Jose Sharks",
    "Carter Yakemchuk": "Ottawa Senators",
    "Gustav Forsling": "Florida Panthers",
    "Vince Dunn": "Seattle Kraken",
    "Zayne Parekh": "Calgary Flames",
    "Sam Dickinson": "San Jose Sharks",
    "Travis Sanheim": "Philadelphia Flyers",
    "Zeev Buium": "Vancouver Canucks",
    "Dan Vladar": "Philadelphia Flyers",
    "Brandon Bussi": "Carolina Hurricanes",
    "Jake Allen": "New Jersey Devils",
    "Mackenzie Blackwood": "Colorado Avalanche",
    "Carter Hart": "Vegas Golden Knights",
    "Joel Hofer": "St. Louis Blues",
    "Philipp Grubauer": "Seattle Kraken",
    "Elvis Merzlikins": "Columbus Blue Jackets",
    "Frederik Andersen": "Edmonton Oilers",
    "Tristan Jarry": "Edmonton Oilers",
    "Devon Levi": "Edmonton Oilers",
    "Ryan Shea": "Edmonton Oilers",  # defenceman (Ingram left out — pending FA)
    "Darnell Nurse": "San Jose Sharks",
    # --- Calder prospects ---
    "Adam Novotny": "Vancouver Canucks",
    "Adam Sykora": "New York Rangers",
    "Alberts Šmits": "New York Rangers",
    "Alex Bump": "Philadelphia Flyers",
    "Artur Akhtyamov": "Toronto Maple Leafs",
    "Bradly Nadeau": "Carolina Hurricanes",
    "Brady Martin": "Nashville Predators",
    "Brodie Ziemer": "Winnipeg Jets",
    "Caleb Desnoyers": "Utah Mammoth",
    "Caleb Malhotra": "Vancouver Canucks",
    "Carson Carels": "Calgary Flames",
    "Chase Reid": "Seattle Kraken",
    "Cole Beaudoin": "New York Rangers",
    "Cole Eiserman": "New York Islanders",
    "Daxon Rudolph": "Buffalo Sabres",
    "Eduard Sale": "Seattle Kraken",
    "Ethan Belchetz": "Utah Mammoth",
    "Felix Unger Sorum": "Carolina Hurricanes",
    "Ivar Stenberg": "San Jose Sharks",
    "Jackson Smith": "Columbus Blue Jackets",
    "Jake O'Brien": "Seattle Kraken",
    "Jett Luchanko": "Philadelphia Flyers",
    "Joakim Kemell": "Nashville Predators",
    "Josh Samanski": "Edmonton Oilers",
    "Kashawn Aitcheson": "New York Islanders",
    "Keaton Verhoeff": "San Jose Sharks",
    "Liam Greentree": "Vegas Golden Knights",
    "Michael Brandsegg-Nygard": "Detroit Red Wings",
    "Nikita Chibrikov": "Winnipeg Jets",
    "Nikita Klepov": "Anaheim Ducks",
    "Oscar Fisker Mølgaard": "Seattle Kraken",
    "Radim Mrtka": "Buffalo Sabres",
    "Roger McQueen": "Anaheim Ducks",
    "Roman Kantserov": "Chicago Blackhawks",
    "Ryan Ufko": "Nashville Predators",
    "Ryker Lee": "Nashville Predators",
    "Sacha Boisvert": "Chicago Blackhawks",
    "Sam O'Reilly": "Tampa Bay Lightning",
    "Samuel Honzek": "Calgary Flames",
    "Sebastian Cossa": "Utah Mammoth",
    "Sergei Murashov": "Pittsburgh Penguins",
    "T.J. Hughes": "Colorado Avalanche",
    "Trevor Connelly": "Vegas Golden Knights",
    "Victor Eklund": "New York Islanders",
    "Viggo Bjorck": "Winnipeg Jets",
    "Will Zellers": "Colorado Avalanche",
    "William Horcoff": "Pittsburgh Penguins",
}
PLAYER_TEAM.update({canonical_player(p): t for p, t in _OVERRIDES.items()})


def player_team(name: str) -> str:
    """Current NHL team for a player (for the logo beside their name), or ''."""
    return PLAYER_TEAM.get(canonical_player(name), "")
