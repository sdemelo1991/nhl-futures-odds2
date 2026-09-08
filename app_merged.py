"""
NHL Futures Comp Tool + Jack Adams PM — unified Streamlit app.
Hub landing page routes to two tools via query_params state.

Run: streamlit run app.py
    → Landing page with two tabs (Futures Comp / Jack Adams PM)
    → Click either tab to navigate
    → From within each tool, top-right link jumps to the other
"""

import streamlit as st
import json
from pathlib import Path

# Set page config early (must be first Streamlit call)
st.set_page_config(
    page_title="FanDuel Odds — Comp & Coach Pricing",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Initialize session state for navigation
if "page" not in st.session_state:
    st.session_state.page = st.query_params.get("page", "hub")
if "nav_radio" not in st.session_state:
    st.session_state.nav_radio = st.session_state.page

def go_to(page):
    """Navigate by setting durable session state.

    Note: we deliberately do NOT write st.query_params here. On Databricks Apps,
    mutating the URL resets the WebSocket connection and wipes st.session_state,
    which silently breaks button-based navigation (buttons only report a click
    for a single run). Driving nav purely through session_state avoids that.
    """
    st.session_state.page = page
    st.session_state.nav_radio = page

def get_data():
    """Load odds.json once, cached by mtime. On Databricks, point to Volume path."""
    # Local: C:\Users\StevenDeMelo\Downloads\nhl-futures-odds\data\odds.json
    # Databricks: /Volumes/<catalog>/<schema>/<volume>/odds.json
    odds_path = Path("data/odds.json")
    try:
        with open(odds_path) as f:
            return json.load(f)
    except FileNotFoundError:
        st.error(f"odds.json not found at {odds_path}")
        return {}

@st.cache_data
def load_odds_cached():
    """Cached odds load with mtime tracking."""
    return get_data()

def render_hub():
    """Landing page: two big squared tabs to choose from."""
    st.markdown("""
    <style>
    .hub-title { font-size: 84px; font-weight: bold; margin-bottom: 80px; color: #1a1d24; text-align: center; }
    .stButton button {
        width: 100% !important;
        height: 550px !important;
        font-size: 82px !important;
        font-weight: 900 !important;
        border-radius: 20px !important;
        border: 4px solid #ddd !important;
        padding: 40px !important;
    }
    .stButton button * {
        font-size: 82px !important;
    }
    .stButton button p, .stButton button div, .stButton button span {
        font-size: 82px !important;
        line-height: 1 !important;
    }
    .stButton > button:hover {
        transform: scale(1.03);
        box-shadow: 0 8px 24px rgba(0,0,0,0.1);
    }
    </style>
    <div style="text-align: center;">
        <div class="hub-title">FanDuel NHL Futures Hub</div>
    </div>
    """, unsafe_allow_html=True)

    col1, col2 = st.columns(2, gap="large")

    with col1:
        st.button("🏒\n\nFutures Comp Tool", key="btn_comp", use_container_width=True,
                  on_click=go_to, args=("comp",))

    with col2:
        st.button("🏆\n\nJack Adams PM", key="btn_jack", use_container_width=True,
                  on_click=go_to, args=("jack",))

def render_nav_top_right(current_page):
    """Top-right bidirectional nav link."""
    col1, col2, col3 = st.columns([1, 10, 1])
    with col3:
        target_page = "comp" if current_page == "jack" else "jack"
        target_label = "← Comp Tool" if current_page == "jack" else "Jack Adams →"
        st.button(target_label, key="nav_link", help=f"Jump to {target_page}",
                  on_click=go_to, args=(target_page,))

def main():
    """Main router."""
    try:
        # Hub navigation radio in sidebar (always visible above tool-specific sidebar)
        with st.sidebar:
            st.radio(
                "Navigate",
                options=["hub", "comp", "jack"],
                format_func=lambda x: {"hub": "🏠 Hub", "comp": "🏒 Futures Comp", "jack": "🏆 Jack Adams PM"}[x],
                key="nav_radio",
                on_change=lambda: go_to(st.session_state.nav_radio),
            )
            st.divider()

        # Page-specific content
        if st.session_state.page == "hub":
            render_hub()
        elif st.session_state.page == "comp":
            render_nav_top_right("comp")
            st.markdown("---")
            # Import and run the existing futures comp tool
            # (renders its own sidebar content below the hub nav radio)
            try:
                from futures_comp import render_comp_tool
                render_comp_tool(load_odds_cached())
            except ImportError:
                st.info("Futures Comp Tool not yet integrated. Ensure app.py is in the same directory.")
        elif st.session_state.page == "jack":
            render_nav_top_right("jack")
            st.markdown("---")
            # Import and run the Jack Adams PM tool
            try:
                from jack_adams_board import render_jack_adams_pm
                render_jack_adams_pm(load_odds_cached())
            except ImportError as e:
                st.error(f"Failed to load Jack Adams PM: {e}")
        else:
            st.error(f"Unknown page: {st.session_state.page}")
    except Exception as e:
        st.error(f"**App Error:** {type(e).__name__}: {str(e)}")
        st.write("**Stack trace:**")
        import traceback
        st.code(traceback.format_exc())

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        st.error(f"**Fatal Error:** {type(e).__name__}: {str(e)}")
        import traceback
        st.code(traceback.format_exc())
