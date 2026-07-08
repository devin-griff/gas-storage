"""
<APP_TITLE>
<APP_TAGLINE>
"""
import base64
from pathlib import Path

import streamlit as st

# `set_page_config` must be the first Streamlit call in the script.
st.set_page_config(
    page_title="<APP_TITLE>",
    page_icon="favicon.png",
    layout="wide",
)

# ── Home-link logo ────────────────────────────────────────────────────────────
# A 32x32 Griffith PSE blackletter G that links back to https://griffith-pse.com
# (same tab — the user is leaving the demo). Image is embedded from the local
# favicon.png as a base64 data URL — no network call when the app loads, so
# cloners running locally don't ping griffith-pse.com on every render.
#
# Two layout patterns — pick one and uncomment the matching CSS + markdown
# call below. The sidebarless variant is the default; the sidebar variant
# requires extra CSS to hide Streamlit's sticky header chrome (which
# otherwise pushes the logo 2-3rem below the top of the sidebar).
st.markdown("""
<style>
/* === Main block top padding ============================================= */
/* Streamlit's default `block-container` padding-top is 6rem, which pushes
   the title well below the page fold on a 13" laptop. 2.5rem clears the
   sticky header (the «« sidebar toggle and the running-script spinner sit
   in the top-right corner) without hiding the title underneath it. Same
   value used by every app in this template family (quad-tank, knapsack,
   diet, ...). Going below 2rem starts clipping the title. */
.block-container,
[data-testid="stMainBlockContainer"] {
    padding-top: 2.5rem !important;
}

/* === Sidebarless apps (default — Knapsack, Diet pattern) ================ */
.home-logo-corner {
    position: fixed;
    top: 0.5rem;
    left: 0.75rem;
    z-index: 999999;
}
.home-logo-corner img {
    width: 32px;
    height: 32px;
    border-radius: 4px;
    display: block;
}

/* === Sidebar apps (quad-tank pattern) =================================== */
/* If you're using `st.sidebar.markdown(_HOME_LOGO_HTML, ...)` below
   instead of the main-page variant, comment out the `.home-logo-corner`
   block above and uncomment everything below. The in-flow positioning
   makes the logo sit naturally at the top of the sidebar; hiding
   `stSidebarHeader` removes Streamlit's sticky chrome (the «« collapse
   button) so nothing pushes the logo down. Trade-off: users can't
   collapse the sidebar via «« — fine if the sidebar IS the control panel. */
/*
.home-logo-corner {
    display: block;
    margin: 0 0 0.75rem;
}
.home-logo-corner img {
    width: 32px;
    height: 32px;
    border-radius: 4px;
    display: block;
}
[data-testid="stSidebarHeader"] {
    display: none !important;
}
[data-testid="stSidebarUserContent"] {
    padding-top: 0.5rem !important;
}
*/
</style>
""", unsafe_allow_html=True)

_FAVICON_DATA_URL = "data:image/png;base64," + base64.b64encode(
    (Path(__file__).parent / "favicon.png").read_bytes()
).decode()

_HOME_LOGO_HTML = (
    '<a class="home-logo-corner" href="https://griffith-pse.com" target="_self">'
    f'<img src="{_FAVICON_DATA_URL}" '
        'alt="Griffith PSE — home" />'
    '</a>'
)

# Sidebarless apps (default — Knapsack, Diet pattern):
st.markdown(_HOME_LOGO_HTML, unsafe_allow_html=True)

# Sidebar apps (quad-tank pattern) — comment out the line above, uncomment
# the line below, and swap the CSS blocks above accordingly:
# st.sidebar.markdown(_HOME_LOGO_HTML, unsafe_allow_html=True)

# ── Title block ───────────────────────────────────────────────────────────────
st.title("<APP_TITLE>")
st.caption("<APP_TAGLINE>")
# Alternative title style used by the apps that wrap a Pyomo model around a
# solver — the title carries a GitHub source link (a title-colored octicon
# between the title and the tagline) and a "powered by Pyomo + <solver>"
# line in a muted gray. Drop this in place of the st.title + st.caption
# above when you adopt that pattern; substitute the app title, repo URL,
# solver name, and solver URL:
#
# st.markdown(
#     "<h2 style='margin: 0 0 0.25rem 0; padding: 0; font-size: 1.5rem; "
#     "font-weight: 700;'>"
#     "<APP_TITLE> "
#     "<a href='<REPO_URL>' target='_blank' "
#     "title='View source on GitHub' "
#     "style='display: inline-block; vertical-align: 0.02em; "
#     "margin: 0 0.35rem 0 0.1rem; color: inherit;'>"
#     "<svg viewBox='0 0 16 16' width='20' height='20' fill='currentColor' "
#     "aria-label='GitHub'>"
#     "<path d='M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17."
#     "55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-"
#     ".82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 "
#     "2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59."
#     "82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27"
#     ".68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51"
#     ".56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1."
#     "07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-"
#     "8-8-8z'/></svg></a>"
#     "<span style='font-size: 1.15rem; font-weight: 400; color: #6b7280;'>"
#     "powered by "
#     "<a href='https://github.com/Pyomo/pyomo' target='_blank' "
#     "style='color: #6b7280; text-decoration: underline;'>Pyomo</a>"
#     " + "
#     "<a href='<SOLVER_URL>' target='_blank' "
#     "style='color: #6b7280; text-decoration: underline;'><SOLVER_NAME></a>"
#     "</span>"
#     "</h2>",
#     unsafe_allow_html=True,
# )
# st.caption("<APP_TAGLINE>")
#
# Solver references currently in use across the family:
#   HiGHS:  https://github.com/ERGO-Code/HiGHS   (LP / MILP)
#   rIPOPT: https://github.com/jkitchin/ripopt   (NLP via IPOPT in Rust)
# "Pyomo" is the official mixed-case capitalization; "HiGHS" capitalizes
# the H, G, and final S; "rIPOPT" starts lowercase.

# ── Sidebar inputs ────────────────────────────────────────────────────────────
# Sliders, file uploaders, model parameters, dropdowns, etc. Use a sidebar
# when the workflow is set-then-solve (configure inputs, hit a button, view
# results). Skip the sidebar when interaction is continuous and inputs are
# few — put controls inline in the main area instead.
#
# Example:
#   st.sidebar.header("Inputs")
#   x = st.sidebar.slider("x", 0.0, 10.0, 5.0)

# ── Main computation ──────────────────────────────────────────────────────────
# Build your model, call your library, run the analysis.
# Cache expensive work with @st.cache_data (for serializable returns) or
# @st.cache_resource (for solver objects, ML models, etc.).
#
# Example:
#   @st.cache_data
#   def fit_model(data):
#       return some_model(data).fit()

# ── Display ───────────────────────────────────────────────────────────────────
# Plotly / Altair charts, data tables, text output, math via st.latex, etc.

st.write("Hello, world. Replace this with your app.")
