"""Futures Comparison Tool, exposed as a single callable for a hub app.

    from futures_comp import render_comp_tool
    render_comp_tool(odds_dict)                     # history read from disk
    render_comp_tool(odds_dict, history_dict)       # or pass both explicitly

This is a thin wrapper over app.py so there is ONE source of truth: every
render_* function (to_win, playoffs, team_points, awards, props, fd_desk,
team_view, player_view), the shared comparison-table renderer, and the
price-history popovers all live in app.py and are driven by render_comp_tool().

Integration notes (hub / Databricks):
  * The CALLER owns st.set_page_config(...); render_comp_tool never calls it.
  * `data` is the full odds.json (dict). `history` is the optional
    price_history.json (dict) — pass it when the files live on a Databricks
    Volume rather than on local disk next to app.py.
  * render_comp_tool draws the whole comp-tool page (sidebar book filters, theme
    toggles, KPI row, section nav, and the active section). A hub can gate it
    behind its own top-level nav (e.g. "Comparison Tool" vs "Jack Adams Board").
"""

from app import render_comp_tool  # noqa: F401  (re-export the single entry point)

__all__ = ["render_comp_tool"]
