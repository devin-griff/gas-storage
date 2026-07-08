# Setup — bootstrapping a new app from this template

This is the one-time setup you do after using the template to create a new
repo. After this is done, every `git push origin main` auto-deploys to Fly.

## Prerequisites

- `gh` CLI installed and authenticated: `gh auth status`
- `flyctl` installed and authenticated: `~/.fly/bin/flyctl auth whoami`
- Cloudflare account with `griffith-pse.com` DNS zone

## 1. Create the repo from this template

Either use the GitHub UI's "Use this template" button on this repo's page,
or via CLI:

```bash
APP_SLUG=pinch-analysis           # short, lowercase, hyphenated
APP_TITLE="Pinch Analysis"        # human-readable display name
APP_TAGLINE="Heat-integration via the pinch design method"

gh repo create devin-griff/$APP_SLUG \
    --template devin-griff/griffith-pse-app-template \
    --private \
    --clone

cd $APP_SLUG
```

## 2. Substitute placeholders

Replace `<APP_SLUG>`, `<APP_TITLE>`, `<APP_NAME>`, and `<APP_TAGLINE>` in
every text file (including the Dockerfile and fly.toml):

```bash
find . -type f \( -name '*.py' -o -name '*.md' -o -name '*.toml' -o -name 'Dockerfile' \) \
    -exec sed -i \
    "s|<APP_SLUG>|$APP_SLUG|g; \
     s|<APP_TITLE>|$APP_TITLE|g; \
     s|<APP_NAME>|griffith-pse-$APP_SLUG|g; \
     s|<APP_TAGLINE>|$APP_TAGLINE|g" {} +
```

Sanity check — no placeholders left:
```bash
grep -rn '<APP_' . --include='*.py' --include='*.md' --include='*.toml' --include='Dockerfile' || echo "all substituted"
```

## 3. Add Python dependencies

Edit `requirements.txt`. Pure-pip libraries — `pyomo`, `pyomo-ripopt`,
`scikit-learn`, `scipy`, `plotly`, `altair`, `networkx`, `cvxpy`, `openai`,
`anthropic`, etc. — just go on a line each.

If you need a system library (GLPK solver binary, GraphViz, FFmpeg, etc.),
uncomment the matching block in the `Dockerfile`.

### Document the system deps in the README

No current app needs a system-binary solver — every one uses a
pip-installable solver (or none at all), so the boilerplate
`pip install -r requirements.txt && streamlit run app.py` is all the
README's "Run locally" section needs. For reference:

- **HiGHS via `highspy`** (Knapsack, Diet) — LP/MIP solver, plain pip wheel.
- **rIPOPT via `pyomo-ripopt`** (Quad-tank) — NLP solver; the wheel bundles
  the solver binary, so no separate install either.

If your new app *does* need a genuine system-binary dependency: uncomment the
GLPK (or GraphViz, FFmpeg) block in the `Dockerfile`, and add a matching note
to the README's "Run locally" section so anyone running it outside Docker can
install it — for GLPK, a short block listing `apt-get install glpk-utils` and
`brew install glpk`.

### Sidebar vs. no sidebar

`app.py` ships with the home-link logo wired up via `st.markdown` (the
sidebarless pattern used by Knapsack and Diet). If your app uses a sidebar
for set-then-solve workflows (the quad-tank pattern), swap the call for
`st.sidebar.markdown` — see the comment block above the call.

The sidebarless variant pins the logo to the viewport's top-left corner via
`position: fixed`. The sidebar variant (commented out in the CSS block)
drops the logo into the sidebar's flow via `display: block` so it sits at
the top of the sidebar and scrolls with the rest of the controls. Pick the
variant that matches your `markdown` call.

> **Tip — you can push to GitHub before the deploy is set up.** The
> deploy workflow checks for `FLY_API_TOKEN` and exits cleanly when the
> secret is missing, so iterating on `app.py` and committing while you
> figure out the deploy story produces clean no-op runs (no email noise).
> Steps 4–7 below are still required before the first real deploy.

## 4. Create the Fly app

```bash
~/.fly/bin/flyctl apps create griffith-pse-$APP_SLUG
```

## 5. Issue a deploy token + add as GitHub secret (one pipe)

The token must NEVER pass through chat or shell history. Use this pipe so
it goes straight from `flyctl` stdout into `gh` stdin:

```bash
~/.fly/bin/flyctl tokens create deploy -a griffith-pse-$APP_SLUG --name github-actions \
    | gh secret set FLY_API_TOKEN --repo devin-griff/$APP_SLUG
```

Verify the secret was set:
```bash
gh secret list --repo devin-griff/$APP_SLUG
```

## 6. Add Cloudflare DNS records for the subdomain

In the Cloudflare dashboard for `griffith-pse.com`:

- Type **A**, name `<APP_SLUG>`, value `66.241.124.X` (Fly's edge — get the
  exact IP from `flyctl certs add` below; often the same IP used by other
  apps in your org)
- Type **AAAA**, name `<APP_SLUG>`, value `2a09:8280:1::112:XXXX:0`
- **Both records must be DNS-only (gray cloud)**, not Proxied. Streamlit's
  WebSocket connections won't survive Cloudflare's proxy on Fly origins.

## 7. Issue the SSL cert via Fly

```bash
~/.fly/bin/flyctl certs add $APP_SLUG.griffith-pse.com -a griffith-pse-$APP_SLUG
```

Fly responds with the recommended A/AAAA values — paste those into Cloudflare
if you didn't already in step 6. Cert validation takes 30–60 s once DNS resolves.

## 8. First deploy + commit the substituted template

SETUP.md has done its job — untrack it so it can't ship as a stale doc in the
app repo. It's already in `.gitignore`, so `git rm --cached` is a one-time
removal (the file stays on disk for reference):

```bash
git rm --cached SETUP.md
git add -A
git commit -m "Bootstrap from template"
git push origin main
```

This triggers GitHub Actions which runs `flyctl deploy --remote-only`. About
2–3 minutes from push to live at `https://$APP_SLUG.griffith-pse.com`.

## 9. (Optional) Add a card to the Quarto site

On the `griffith-pse-site` repo's `main` branch, add a new entry to
`index.qmd` under "Featured demos". The card is a clickable screenshot
that launches the app — matches the existing card pattern on the home page:

```markdown
::: {.g-col-12 .g-col-md-4}
[![](images/<APP_SLUG>.png){.app-screenshot fig-alt="<APP_TITLE> — click to launch"}](https://<APP_SLUG>.griffith-pse.com){.app-card-link target="_blank"}

### <APP_TITLE>

<short description of what the app does>
:::
```

You'll need to drop a screenshot of the app at `griffith-pse-site/images/<APP_SLUG>.png`
(21:10 aspect ratio crops cleanly into the card grid). Push the site repo
→ Cloudflare Pages rebuilds in ~30 s.

---

## UI patterns used across the apps

These aren't required for a new app to build/deploy — pick them up if your
app has a comparable shape (a "You vs. solver" view, or a heavily-edited
data table).

### Color palette

Default to **Wong (2011)** — the color-blind-safe pair from the Nature
Methods paper *Points of View: Color blindness*. It's designed-together,
holds up under deuteranopia / protanopia / tritanopia, and is what knapsack,
diet, and the chart layers in both apps now use.

| Role | Hex | Where |
| --- | --- | --- |
| User / "Your" side | `#0072B2` (blue) | User-side slider thumbs, selectable item cards, "You" bar in comparison charts |
| Solver / "Optimal" side | `#E69F00` (amber) | Optimal-side slider thumbs, highlighted solver-picked cards, "Optimal" bar |
| Alert (constraint marker, violation glyph) | `#dc2626` (red) | Dotted limit / minimum lines on charts, ⚠ violation glyph above a bar that breaks a constraint, "Your value/cost" indicator when it falls on the wrong side of the optimum |
| Pre-solve inert | `#cbd5e1` (light gray) | Optimal-side sliders before Run-Optimizer is clicked — read-only, awaiting a solve |
| Cost-match success (when user matches/beats the optimum) | `#16a34a` (green) | Used by the colored-metric helper. Independent of the violation alert. |

Conventions to follow if you want to fit the family:

- **The user vs. solver story is told by blue vs. amber.** Don't use red
  for "selected" or "active" state — red is reserved for constraint /
  alert signaling so the violation glyph remains unambiguous.
- **Match indicator** in the comparison metric:
  - Maximization problem (knapsack): `your_value >= opt_value` → green.
  - Minimization problem (diet): `your_cost <= opt_cost` → green.
  - Otherwise red. The math-side correctness of "meet or beat" is only
    achievable while feasible, but the chart's ⚠ glyph flags
    infeasibility independently — keep the two signals orthogonal.
- **Streamlit's `type="primary"` button** is red by default (the
  `--primary-color` variable). When you need a primary-styled button to
  match the user-side blue (e.g., the "Your knapsack" toggle buttons),
  override scoped to a marker element rather than globally rewriting
  `--primary-color`:

  ```python
  # Inside the user-side column:
  st.markdown('<div class="user-bank" style="display:none"></div>',
              unsafe_allow_html=True)
  # In the CSS:
  [data-testid="stColumn"]:has(.user-bank) button[kind="primary"] {
      background-color: #0072B2 !important;
      border-color: #0072B2 !important;
  }
  ```

  The hidden marker scopes the override; Run-Optimizer and other primary
  buttons outside that column keep Streamlit's default styling.

### Heavily-edited data tables (the "Apply changes" pattern)

`st.data_editor` auto-commits every cell change, triggering a script
rerun. If your app does anything expensive on a data change — re-solve
an LP, rebuild a chart, remount widgets that re-read bounds from the
data — every keystroke fires that work and the UI flashes.

The fix is to **buffer edits** and gate the heavy work behind an explicit
**Apply changes** button. The diet app's `render_data_tab` is the
reference implementation.

Sketch:

```python
def render_data_tab():
    # Reserve top spot for Apply / Reset action row + pending banner.
    # The action-row state depends on whether widget values diverge
    # from st.session_state.data, which we only know after rendering
    # the inputs below. st.container() lets us fill the slot later.
    top_slot = st.container()

    # ── Inputs ──
    # Render your number_inputs, st.data_editor, etc. Widget keys keep
    # values across reruns (Streamlit's normal session_state behavior).
    new_needs = {...}
    edited = st.data_editor(df, key="data_editor", num_rows="dynamic", ...)
    new_data = df_to_data(edited, new_needs)
    has_pending = new_data != st.session_state.data

    # Fill the top slot now that has_pending is known.
    with top_slot:
        c1, c2, _ = st.columns([1, 1, 4])
        with c1:
            apply_clicked = st.button(
                "Apply changes",
                type="primary" if has_pending else "secondary",
                width="stretch",
                disabled=not has_pending,
            )
        with c2:
            reset_clicked = st.button("Reset to defaults", width="stretch")
        if has_pending:
            st.info("Edits pending. Click **Apply changes** to update.")

    if apply_clicked:
        st.session_state.data = new_data
        # ... do the expensive work: re-solve, snap slider state, rerun
        st.rerun()
    if reset_clicked:
        st.session_state["_pending_reset"] = True
        st.rerun()
```

Key bits:

- **Top action row via `st.container()` placeholder.** Streamlit executes
  top-to-bottom; the buttons need to render at top but their
  `disabled` / `type` props depend on `has_pending`, which requires
  rendering inputs first. The container reserves the slot; we fill it
  after computing `has_pending`. (Streamlit's `st.button` still returns
  True/False correctly when rendered inside a `with container:` block
  that's filled later in script flow.)
- **`disabled=not has_pending`** keeps the button inert when there's
  nothing to commit, and primary-styled when there is — gives the user
  a clear "click me" cue.
- **Banner** under the buttons reinforces the "nothing has happened yet"
  state for users who don't notice the button style change.
- **Reset uses the deferred-flag pattern** (`_pending_reset` consumed in
  `init_state`) because widget-backed session_state keys can't be set
  directly after the widget has rendered.

When you adopt this pattern, also make sure any *implicit* commits in
the old code (e.g., the `if new_data != session_state.data: st.rerun()`
auto-commit pattern that's intuitive but causes the same flash) are
replaced with the `apply_clicked` branch.

---

## Future-app extension hints

### AI / LLM apps (OpenAI, Anthropic, etc.)

Set the API key as a Fly secret — it's mounted as an env var at runtime,
never committed to the repo:

```bash
~/.fly/bin/flyctl secrets set OPENAI_API_KEY=sk-... -a griffith-pse-$APP_SLUG
```

Read in the app via `os.environ["OPENAI_API_KEY"]` (or `st.secrets` if you
prefer Streamlit's wrapper). For local development, use a `.env` file (and
add `.env` to `.gitignore`).

### Heavier compute

Bump the machine size in `fly.toml` `[[vm]]` block. See the comments there
for options. Cost scales linearly with size; auto-stop still keeps idle
cost at $0.

**When you change the machine size, also update the README's `## Deployment`
section** — both the **Machine** bullet (size + RAM) and the **Cost ceiling**
number. The default block in this template assumes `shared-cpu-1x` / 1 GB →
~$3.89/mo ceiling. If you bump to `shared-cpu-2x` / 2 GB, the ceiling is
~$7.78/mo; for `performance-1x` / 4 GB, ~$23/mo. Look up the current rate
at https://fly.io/docs/about/pricing/ and refresh the footnote date.

### GPU workloads

Fly supports GPU machines (`a10`, `a100`). They require a CUDA-enabled base
image and a different Dockerfile entirely. This template targets CPU; you'd
fork it for GPU work.

### Persistent state (DB, file uploads, user history)

Add a `[mounts]` block to `fly.toml` and create a Fly volume:
```bash
flyctl volumes create data --size 1 -a griffith-pse-$APP_SLUG
```
Then in `fly.toml`:
```toml
[[mounts]]
  source = "data"
  destination = "/data"
```
SQLite at `/data/app.db` is the simplest pattern. For Postgres, use a
separate Fly Postgres app + connection string.

### Commercial solvers (Gurobi, CPLEX)

License files mount via `fly secrets`. Dockerfile fetches at startup. Out
of scope for this template, but the pattern is documented in Fly's docs.
