"""NHL award categories tracked in the Awards section.

key -> display label. Players are stored per category in the odds file; add or
remove categories here and they flow through the schema and UI automatically.
"""

AWARD_CATEGORIES = {
    "hart": "Hart (MVP)",
    "norris": "Norris (Best Defenseman)",
    "vezina": "Vezina (Best Goalie)",
    "calder": "Calder (Rookie)",
    "jack_adams": "Jack Adams (Coach)",
    "art_ross": "Art Ross (Most Points)",
    "rocket_richard": "Rocket Richard (Most Goals)",
    "selke": "Selke (Best Defensive Forward)",
}
