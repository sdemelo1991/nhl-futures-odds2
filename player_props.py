"""Player-prop stat categories tracked in the Player Props section.

key -> display label. Same pattern as awards.py: add/remove categories here and
they flow through the schema and UI. Launching with Goals + Points; assists,
shots, etc. can be added later just by extending this map.
"""

PROP_CATEGORIES = {
    "goals": "Goals",
    "points": "Points",
}
