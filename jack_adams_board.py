"""Jack Adams Coach-of-the-Year Pricing Engine — Streamlit component."""

import streamlit as st
import base64
import functools
import json
import re
from pathlib import Path

TEAM_ASSETS = Path(__file__).parent / "assets" / "teams"


@functools.lru_cache(maxsize=None)
def team_logo_uri(tri):
    """Base64 data URI for a team's local SVG — same asset source the Comp
    Tool uses, so logos render identically and don't depend on an external
    CDN (assets.nhle.com) that may be slow/blocked in a Databricks sandbox."""
    p = TEAM_ASSETS / f"{tri}.svg"
    if p.exists():
        return "data:image/svg+xml;base64," + base64.b64encode(p.read_bytes()).decode()
    return None


def load_coaches_json():
    """Load coaches data from JSON file."""
    coaches_path = Path("coaches_2026-27.json")
    try:
        with open(coaches_path) as f:
            return json.load(f)
    except FileNotFoundError:
        st.error(f"coaches_2026-27.json not found at {coaches_path}")
        return []


def render_jack_adams_pm(odds_data=None):
    """Render the Jack Adams Pricing Engine board."""
    coaches = load_coaches_json()

    if not coaches:
        st.error("No coach data available. Ensure coaches_2026-27.json is in the project root.")
        return

    # Generate HTML board with inline CSS and JavaScript
    html_content = build_board_html(coaches)

    # Render using Streamlit's HTML component
    st.components.v1.html(html_content, height=2400, scrolling=True)


def build_board_html(coaches):
    """Build the complete HTML board with inline CSS and JavaScript."""
    rows_html = ""
    paste_lines = []

    for idx, coach in enumerate(coaches, 1):
        # Format values
        fair_us = coach.get("fair_us", 0)
        fair_dec = float(coach.get("fair_dec", 0))
        model_pct = float(coach.get("model_pct", 0))  # Already in percentage form (7.1 = 7.1%)
        proj_pts = int(coach.get("proj_pts", 0))
        ly_pts = int(coach.get("ly_pts", 0))
        delta_pts = proj_pts - ly_pts
        playoff_pct = int(float(coach.get("make_playoffs", 0)) * 100)
        best_avail = coach.get("best_avail", 0)
        best_avail_book = coach.get("best_avail_book", "")
        edge = float(coach.get("edge", 0))
        team = coach.get("team", "")
        tri = coach.get("tri", "")
        coach_name = coach.get("coach", "")

        # Build drivers
        drivers_html = ""
        driver_codes = coach.get("drivers", [])
        for driver_code in driver_codes:
            driver_label = map_driver_label(driver_code, coach)
            driver_color = get_driver_color(driver_code)
            driver_text_color = get_driver_text_color(driver_code)
            has_dash = driver_code == "lean"
            border_style = "border: 1px dashed #e0a460;" if has_dash else ""
            drivers_html += f'<span class="pill" style="background:{driver_color};color:{driver_text_color};{border_style}">{driver_label}</span>'

        # Parse lean note: extract date FIRST to preserve it, then get adjustment value
        lean_note_raw = coach.get("lean_note", "")
        lean_note_display = ""
        if lean_note_raw:
            # Convert to ASCII only - removes corrupted Unicode characters
            clean_note = ''.join(c if ord(c) < 128 else '' for c in lean_note_raw)
            # Extract date FIRST: find (YYYY-MM-DD) and convert to (MM-DD)
            date_match = re.search(r'\((\d{4})-(\d{2})-(\d{2})\)', clean_note)
            if date_match:
                clean_note = clean_note.replace(date_match.group(0), f"({date_match.group(2)}-{date_match.group(3)})")
            # NOW extract adjustment value (only look for ± followed by 1-2 digits at start)
            value_match = re.search(r'([-+]\d{1,2})(?=\s)', clean_note)
            if value_match:
                value = value_match.group(1)
                rest = re.sub(r'([-+]\d{1,2})\s+', '', clean_note, count=1).strip()
            else:
                value = None
                rest = clean_note
            # Build the final display
            if value:
                lean_note_display = f'<b style="font-size: 13px;">[{value}]</b> {rest}'
            else:
                lean_note_display = rest

        # Edge color
        edge_sign = "+" if edge >= 0 else ""

        logo_uri = team_logo_uri(tri)
        logo_html = (f'<img class="logo" src="{logo_uri}" alt="" loading="lazy">'
                     if logo_uri else "")

        rows_html += f"""
        <tr>
            <td class="rk" data-v="{idx}">{idx}</td>
            <td class="coach" data-v="{coach_name.lower()}">
                <span class="cwrap">
                    {logo_html}
                    <span class="cn">{coach_name}<span class="tm">{team}</span></span>
                </span>
            </td>
            <td class="fair" data-v="{fair_us / 10000}">+{fair_us}</td>
            <td class="dec" data-v="{fair_dec}">{fair_dec:.2f}</td>
            <td class="pct" data-v="{model_pct / 100}">{model_pct:.1f}%</td>
            <td class="num" data-v="{proj_pts}">{proj_pts}</td>
            <td class="num" data-v="{ly_pts}">{ly_pts}</td>
            <td class="num {'pos' if delta_pts >= 0 else 'neg'}" data-v="{delta_pts}">{delta_pts:+d}</td>
            <td class="num" data-v="{playoff_pct / 100}">{playoff_pct}%</td>
            <td class="badges">{drivers_html}</td>
            <td class="lnote">{lean_note_display}</td>
            <td class="book mkt" data-v="{1 / (best_avail / 10000) if best_avail > 0 else 0}">+{best_avail}<span class="bk">{best_avail_book}</span></td>
            <td class="edge mkt" data-v="{edge / 100}"><span class="{'pos' if edge >= 0 else 'neg'}">{edge_sign}{edge:.1f}%</span></td>
        </tr>
        """

        # Build paste format: Name (TRI)\tFair_Dec\t0\tteam_slug
        team_slug = coach.get("team_slug", "")
        paste_lines.append(f"{coach_name} ({tri})\t{fair_dec:.3f}\t0\t{team_slug}")

    paste_text = "\n".join(paste_lines)

    html = f"""
    <!doctype html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <title>Jack Adams 2026-27 — Model Board</title>
        <style>
        :root{{
            --bg:#f4f5f8;
            --card:#fff;
            --text:#1a1d24;
            --muted:#7a8694;
            --faint:#aab2bd;
            --line:#f1f2f6;
            --thead:#fafbfc;
            --accent:#1877D8;
            --hover:#fafbff;
            --mkt:#f6f8fb;
            --mkthead:#eef1f6;
            --mktbord:#ccd3de;
            --shadow:rgba(0,0,0,.08);
            --pos:#0a9d5a;
            --neg:#d5433f;
            --ctrl:#fff;
            --ctrlbord:#dfe3ea
        }}
        body.dark{{
            --bg:#0d1117;
            --card:#161b22;
            --text:#e6edf3;
            --muted:#8b98a6;
            --faint:#5b6673;
            --line:#222b36;
            --thead:#1b222c;
            --accent:#4a9eff;
            --hover:#1b222c;
            --mkt:#11151b;
            --mkthead:#1b222c;
            --mktbord:#2a333f;
            --shadow:rgba(0,0,0,.45);
            --pos:#3fb950;
            --neg:#f85149;
            --ctrl:#1b222c;
            --ctrlbord:#2a333f
        }}
        body{{
            margin:0;
            background:var(--bg);
            color:var(--text);
            font:14px/1.45 -apple-system,Segoe UI,Roboto,sans-serif;
            transition:background .2s,color .2s
        }}
        .wrap{{max-width:1600px;margin:0 auto;padding:26px 20px 60px}}
        .top{{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap;margin-bottom:4px}}
        h1{{font-size:22px;margin:0}}
        .sub{{color:var(--muted);font-size:12.5px;margin:2px 0 14px}}
        .ctrls{{display:flex;gap:8px;align-items:center}}
        .themebtn{{font-size:12px;font-weight:600;padding:7px 13px;border-radius:9px;border:1px solid var(--ctrlbord);background:var(--ctrl);color:var(--text);text-decoration:none;cursor:pointer;white-space:nowrap}}
        .themebtn:hover{{border-color:var(--accent);color:var(--accent)}}
        .hint{{color:var(--faint);font-size:11px;margin:0 0 8px}}
        table{{width:100%;table-layout:fixed;border-collapse:collapse;background:var(--card);border-radius:12px;box-shadow:0 1px 3px var(--shadow)}}
        th{{position:sticky;top:0;z-index:5;font-size:10.5px;letter-spacing:.04em;text-transform:uppercase;color:var(--muted);text-align:right;padding:11px 10px;border-bottom:2px solid var(--line);background:var(--thead);cursor:pointer;user-select:none;white-space:nowrap}}
        th:hover{{color:var(--accent)}}
        th.l{{text-align:left}}
        th.static{{cursor:default}}
        th.static:hover{{color:var(--muted)}}
        td{{padding:8px 10px;text-align:right;border-bottom:1px solid var(--line);font-variant-numeric:tabular-nums;vertical-align:middle}}
        td.coach{{text-align:left}}
        .cwrap{{display:flex;align-items:center;gap:9px}}
        .logo{{width:24px;height:24px;flex:0 0 24px;object-fit:contain;background:#eef1f5;border-radius:5px;padding:1px}}
        tr:hover td{{background:var(--hover)}}
        .rk{{color:var(--faint);width:26px}}
        .cn{{font-weight:600;line-height:1.2}}
        .tm{{display:block;font-weight:400;color:var(--muted);font-size:11.5px}}
        .fair{{font-weight:700;color:var(--accent)}}
        .dec{{color:var(--accent)}}
        .pct{{color:var(--text)}}
        .book{{color:var(--muted)}}
        .bk{{display:block;font-size:10px;color:var(--faint);text-transform:capitalize}}
        .num{{color:var(--text)}}
        .pos{{color:var(--pos);font-weight:600}}
        .neg{{color:var(--neg);font-weight:600}}
        .badges{{text-align:left;white-space:nowrap}}
        .pill{{display:inline-block;font-size:10px;font-weight:600;padding:2px 7px;border-radius:10px;margin:1px 2px}}
        .first{{background:#e5efff;color:#1568d6}}
        .due{{background:#fff2d9;color:#a9761a}}
        .rep{{background:#fde5e4;color:#c0322e}}
        .recent{{background:#efe7fb;color:#7a45c9}}
        .build{{background:#e3f2fb;color:#1877D8}}
        .pres{{background:#e3f7ec;color:#0a8a50}}
        .prestige{{background:#f0ecfa;color:#6b46c1}}
        .lean{{background:#fde9d0;color:#b25309;border:1px dashed #e0a460}}
        td.lnote{{text-align:left;max-width:230px;white-space:normal;font-size:11px;line-height:1.35;border-left:1px dashed var(--mktbord)}}
        .ntag{{display:inline-block;background:#fde9d0;color:#b25309;font-weight:700;font-size:10px;padding:1px 5px;border-radius:8px;margin-right:4px}}
        .ntxt{{color:var(--muted)}}
        .ndate{{display:block;color:var(--faint);font-size:9.5px;margin-top:1px}}
        td.mkt{{background:var(--mkt);color:var(--muted)}}
        th.mkt{{background:var(--mkthead)}}
        td.book.mkt, th.mktstart{{border-left:2px solid var(--mktbord)}}
        .method{{background:var(--card);border-radius:12px;padding:18px 22px;margin-top:16px;box-shadow:0 1px 3px var(--shadow)}}
        .method h2{{font-size:12px;margin:0 0 10px;letter-spacing:.05em;text-transform:uppercase;color:var(--muted)}}
        .method ol{{margin:0;padding-left:20px}}
        .method li{{margin:7px 0;color:var(--text);font-size:12.5px;line-height:1.55}}
        .method b{{color:var(--accent)}}
        .method .lg{{margin-top:12px;color:var(--muted);font-size:11.5px;line-height:1.7}}
        </style>
    </head>
    <body>
    <div class="wrap">
    <div class="top">
        <div><h1>Jack Adams 2026-27 — Model Board</h1></div>
        <div class="ctrls">
            <button class="themebtn" onclick="toggleTheme()">🌙 Dark</button>
        </div>
    </div>
    <div class="sub">Fair value for every coach in the Coach-of-the-Year market · expectation anchored to FanDuel lines ·
        50,000 Monte Carlo seasons · τ=0.045 · σ=9.4 · process-noise 20%</div>
    <div class="hint">↕ click any column header to sort</div>
    <div style="max-height:700px;overflow-y:auto;overflow-x:hidden;border-radius:12px;box-shadow:0 1px 3px var(--shadow)">
    <table style="width:100%;min-width:1550px">
    <colgroup>
    <col style="width:2.5%"><col style="width:17%"><col style="width:6.5%"><col style="width:6.5%">
    <col style="width:5.5%"><col style="width:4.5%"><col style="width:4.5%"><col style="width:4.5%">
    <col style="width:5.5%"><col style="width:12%"><col style="width:17%"><col style="width:8.5%"><col style="width:5.5%">
    </colgroup>
    <thead><tr>
    <th class="l static">#</th>
    <th class="l" onclick="st(1)">Coach / Team</th>
    <th onclick="st(2)">Fair (US)</th>
    <th onclick="st(3)">Fair (Dec)</th>
    <th onclick="st(4)">Model %</th>
    <th onclick="st(5)">Proj</th>
    <th onclick="st(6)">'25-26</th>
    <th onclick="st(7)">Δpts</th>
    <th onclick="st(8)">Playoff %</th>
    <th class="l static">Drivers</th>
    <th class="l static">Lean Note</th>
    <th class="mkt mktstart" onclick="st(11)">Best Avail</th>
    <th class="mkt" onclick="st(12)">Edge</th>
    </tr></thead><tbody>
    {rows_html}
    </tbody></table>
    </div>

    <div class="method" style="margin-bottom: 16px;">
    <h2>Copy / Paste for FD's MPM</h2>
    <p style="font-size: 12px; color: var(--muted); margin-bottom: 10px;">Select all text below and paste into FD's MPM. Updates automatically with fair-value changes.</p>
    <pre style="background: var(--card); border: 1px solid var(--line); padding: 12px; border-radius: 8px; overflow-x: auto; font-size: 11px; line-height: 1.6; user-select: all; cursor: text;">{paste_text}</pre>
    </div>

    <div class="method">
    <h2>How this works</h2>
    <ol>
    <li><b>The bar</b> — each team's projected points and playoff likelihood come from <b>FanDuel's own lines</b> (points O/U + To-Make-Playoffs, de-vigged). That's the expectation every coach is measured against.</li>
    <li><b>What wins the award</b> — overperformance vs that bar: mostly <b>surprise</b> (finishing above the line) and <b>improvement</b> off the team's established level, plus a multi-year <b>build</b> term — all <b>gated by playoff odds</b> (miss the playoffs → essentially no votes).</li>
    <li><b>Narrative factors</b> — first-year coach, "due," prestige/blackball, recent-winner and recent-Cup penalties, and a Presidents-<b>dominance</b> ceiling for elite teams (win it big, not merely be good). A broadcaster-voted, highly subjective award.</li>
    <li><b>Scores → prices</b> — a Monte Carlo runs 50,000 simulated seasons (finishes drawn around each line, with a rating-error cushion), scores the field each season, and a softmax converts to win probabilities summing to a true 100% (no vig) → the <b>Fair</b> price. A 20% <b>process-noise</b> floor reflects the award's real volatility (last year 1/3-1/2 of voters didn't submit ballots).</li>
    <li><b>Edge</b> = Model % − Best-Available implied %. Positive = the model rates the coach likelier than the market price.</li>
    <li><b>In-season</b> — same engine, projections update nightly from live standings/pace; "surprise" becomes real, and a narrative/momentum layer (historic runs, man-games-lost) kicks in.</li>
    </ol>
    <div class="lg"><b>Model columns (left):</b> Proj = FanDuel points line (84-game) · Δpts = projection vs 2025-26 actual · Playoff % = de-vigged FanDuel make-playoffs · Drivers = narrative factors · Lean Note = manual trader adjustments (− shorten / + lengthen) with context + date.
    &nbsp; <b>Market columns (far right, shaded):</b> Best Avail = longest posted price across all books (FanDuel, Caesars, bet365) · Edge = Model % − Best-Available implied %.</div>
    </div>
    </div>
    <script>
    // Fix dates on page load
    (function(){{
        document.querySelectorAll('.lnote').forEach(function(cell){{
            var text = cell.innerHTML;
            text = text.replace('(2026-', '(').replace('(2027-', '(');
            cell.innerHTML = text;
        }});
    }})();
    // Sticky header uses native CSS position:sticky on th (see table{{}}/th{{}}
    // rules above) — it's the same table, so header/body columns can never
    // drift out of alignment the way a JS-cloned header could.
    function st(i){{
        var tb=document.querySelector('tbody');
        var rs=Array.prototype.slice.call(tb.querySelectorAll('tr'));
        var th=document.querySelectorAll('th')[i];
        var asc=th.getAttribute('data-asc')!=='1';
        th.setAttribute('data-asc',asc?'1':'0');
        rs.sort(function(a,b){{
            var x=a.children[i].getAttribute('data-v'), y=b.children[i].getAttribute('data-v');
            var nx=parseFloat(x), ny=parseFloat(y), n=!isNaN(nx)&&!isNaN(ny);
            var c=n?nx-ny:(x<y?-1:x>y?1:0);
            // Tiebreaker: sort by Fair Dec (column 3) descending when primary column is tied
            if(c===0 && i!==3){{
                var fx=parseFloat(a.children[3].getAttribute('data-v'));
                var fy=parseFloat(b.children[3].getAttribute('data-v'));
                c=fy-fx;
            }}
            return asc?c:-c;
        }});
        rs.forEach(function(r){{tb.appendChild(r);}});
    }}
    function toggleTheme(){{
        var d=document.body.classList.toggle('dark');
        try{{localStorage.setItem('ja_theme',d?'dark':'light');}}catch(e){{}}
        document.querySelector('.themebtn').textContent=d?'☀ Light':'🌙 Dark';
    }}
    (function(){{
        try{{
            if(localStorage.getItem('ja_theme')==='dark'){{
                document.body.classList.add('dark');
                document.querySelector('.themebtn').textContent='☀ Light';
            }}
        }}catch(e){{}}
    }})();
    </script>
    </body>
    </html>
    """

    return html


def map_driver_label(code, coach):
    """Map driver code to display label."""
    mapping = {
        "first": "1st yr",
        "due": "due",
        "prestige": "respected",
        "pres": "contender",
        "rep": "blackball",
        "lean": "▼ lean",
        "build": "building",
    }

    if code == "recent":
        # Map years_since_win to year
        years_since = coach.get("years_since_win", 999)
        if years_since == 0:
            return "won 2026"
        elif years_since == 1:
            return "won 2025"
        elif years_since == 2:
            return "won 2024"
        elif years_since == 3:
            return "won 2023"
        else:
            return "won"

    return mapping.get(code, code)


def get_driver_color(code):
    """Get background color for driver badge."""
    colors = {
        "first": "#e5efff",
        "due": "#fff2d9",
        "rep": "#fde5e4",
        "recent": "#efe7fb",
        "build": "#e3f2fb",
        "pres": "#e3f7ec",
        "prestige": "#f0ecfa",
        "lean": "#fde9d0",
    }
    return colors.get(code, "#f0f0f0")


def get_driver_text_color(code):
    """Get text color for driver badge."""
    colors = {
        "first": "#1568d6",
        "due": "#a9761a",
        "rep": "#c0322e",
        "recent": "#7a45c9",
        "build": "#1877D8",
        "pres": "#0a8a50",
        "prestige": "#6b46c1",
        "lean": "#b25309",
    }
    return colors.get(code, "#333")
