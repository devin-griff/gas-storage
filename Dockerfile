# Streamlit app on Python 3.12 slim, deployed to Fly.io.
# This Dockerfile is the template default. Pure-pip apps (scikit-learn,
# scipy, plotly, pyomo, pyomo-ripopt, etc.) need NO changes here — pip
# installs everything from requirements.txt.
#
# If your app needs a system-level library (a solver binary, GraphViz,
# FFmpeg, etc.) uncomment the matching block below.
FROM python:3.12-slim

# ── Optional system dependencies ─────────────────────────────────────────────
# Uncomment whichever your app needs. Default is nothing — most apps don't
# need any system packages.
#
# # GLPK (LP/MIP solver via Pyomo: SolverFactory('glpk'))
# RUN apt-get update \
#     && apt-get install -y --no-install-recommends glpk-utils \
#     && rm -rf /var/lib/apt/lists/*
#
# # GraphViz (for network/graph diagrams)
# RUN apt-get update \
#     && apt-get install -y --no-install-recommends graphviz \
#     && rm -rf /var/lib/apt/lists/*
#
# # FFmpeg (video / audio processing)
# RUN apt-get update \
#     && apt-get install -y --no-install-recommends ffmpeg \
#     && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python dependencies first (better Docker layer caching).
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# App source + favicon (referenced by st.set_page_config(page_icon=...)).
COPY app.py favicon.png ./

# Overwrite Streamlit's default static index.html: title, favicon, and
# inject Open Graph + Twitter Card meta tags so links to *.griffith-pse.com
# unfurl as a rich card on LinkedIn / Slack / iMessage. Without this,
# Streamlit's default index.html has no OG tags and link previews fall back
# to a bare title.
RUN STATIC=$(python -c "import streamlit, os; print(os.path.join(os.path.dirname(streamlit.__file__), 'static'))") \
    && sed -i 's|<title>Streamlit</title>|<title><APP_TITLE></title>|' "$STATIC/index.html" \
    && sed -i 's|</head>|<link rel="icon" type="image/png" href="./favicon.png"/><meta property="og:type" content="website"/><meta property="og:title" content="<APP_TITLE>"/><meta property="og:description" content="<APP_TAGLINE>"/><meta property="og:image" content="https://griffith-pse.com/images/<APP_SLUG>.png"/><meta property="og:site_name" content="Griffith PSE"/><meta name="twitter:card" content="summary_large_image"/><meta name="twitter:title" content="<APP_TITLE>"/><meta name="twitter:description" content="<APP_TAGLINE>"/><meta name="twitter:image" content="https://griffith-pse.com/images/<APP_SLUG>.png"/></head>|' "$STATIC/index.html" \
    && cp /app/favicon.png "$STATIC/favicon.png" && cp /app/favicon.png "$STATIC/favicon.ico"

# Run as a non-root user. If a future Streamlit (or transitive dep) RCE
# lands in the container, the attacker doesn't get root. Defense in depth.
RUN useradd -m -u 1000 streamlit && chown -R streamlit:streamlit /app
USER streamlit

EXPOSE 8080
CMD ["streamlit", "run", "app.py", \
     "--server.port=8080", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
