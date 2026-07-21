# =============================================================================
# Gas Storage Valuation: a Streamlit tutorial app.
#
# Value a natural gas storage lease two ways:
#
#   1. INTRINSIC: lock in injections/withdrawals against today's forward
#      curve. A linear program: buy summer, sell winter, subject to
#      capacity and rate limits.
#
#   2. ROLLING INTRINSIC: the industry-standard estimate of the lease's full
#      value including optionality. Simulate spot price paths (mean-
#      reverting around the seasonal curve), and on each path re-solve the
#      intrinsic LP at every decision date as prices move, locking in the
#      front period each time. The average across paths exceeds intrinsic;
#      the difference is the EXTRINSIC value of the storage optionality.
#
# Library roadmap:
#   - streamlit : UI framework. Each interaction reruns this script
#                  top-to-bottom; persistent state lives in `st.session_state`.
#   - pyomo     : algebraic modeling for the storage LP. One model with
#                  mutable Params, re-solved thousands of times during the
#                  Monte Carlo via the persistent appsi-HiGHS interface.
#   - HiGHS     : the LP solver, called via Pyomo's appsi_highs interface.
#                  Ships as a pip wheel (`highspy`). Free and fast enough to
#                  re-solve the LP thousands of times per simulation run.
#   - numpy     : vectorized Ornstein-Uhlenbeck path simulation.
#   - altair    : the chart stack (prices, inventory, decisions, P&L).
#
# File roadmap:
#   1. Market + contract: seasonal curve, OU simulation, defaults.
#   2. Solver           : storage LP (Pyomo), persistent re-solve, rolling
#                          intrinsic Monte Carlo.
#   3. State            : session_state init.
#   4. LaTeX            : formulation tab content.
#   5. CSS              : template-family style tweaks.
#   6. Charts           : Altair panels.
#   7. Main             : page config, sidebar, tab assembly.
# =============================================================================

import base64
import math
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import pyomo.environ as pyo
import streamlit as st
from pyomo.common.tee import capture_output

# ---------- Constants ----------

WEEKS = 52                  # decision periods in the contract year
WEEKS_PER_STEP = 4          # weeks locked in per Monte Carlo re-decision

# Wong palette slice, consistent with the rest of the app family.
COLOR_FORWARD = "#0072B2"   # forward curve: blue
COLOR_SPOT = "#999999"      # simulated spot paths: gray
COLOR_ROLLING = "#009E73"  # rolling-intrinsic results: green
COLOR_SELECTED = "#7c3aed"  # highlighted path, all panels: purple


# ---------- 1. Market + contract ----------

def seasonal_curve(base, premium):
    """Seasonal forward curve by week, $/MMBtu. The contract year runs
    April-March, so the winter peak (mid-January) sits at week ~41."""
    peak_week = 41.5
    return base + premium * np.cos(2 * np.pi * (np.arange(WEEKS) - peak_week) / WEEKS)


def simulate_spot(curve, sigma, kappa, n_paths, seed):
    """Exact-discretization Ornstein-Uhlenbeck simulation of log spot around
    the seasonal curve:  x = ln(S/m),  dx = -kappa*x dt + sigma dW.
    Returns an (n_paths, WEEKS) array of spot prices. sigma and kappa are
    annualized; the weekly step uses the exact OU transition so no
    discretization bias enters."""
    dt = 1.0 / WEEKS
    phi = math.exp(-kappa * dt)
    step_std = sigma * math.sqrt((1.0 - phi * phi) / (2.0 * kappa))
    rng = np.random.default_rng(seed)
    x = np.zeros((n_paths, WEEKS))
    for t in range(1, WEEKS):
        x[:, t] = phi * x[:, t - 1] + step_std * rng.standard_normal(n_paths)
    return curve[None, :] * np.exp(x)


def conditional_curve(curve, spot_t, t, kappa, sigma):
    """Forward curve seen at week t given current spot: the conditional
    EXPECTATION of spot under the OU model. The log-deviation's conditional
    mean is x_t * exp(-kappa (d-t)); exponentiating a normal variable picks
    up the Jensen half-variance term, so the curve is
    F_t(d) = m(d) * exp( x_t e^{-kappa tau} + Var[x_d | x_t] / 2 ),
    with Var = sigma^2 (1 - e^{-2 kappa tau}) / (2 kappa)."""
    x_t = math.log(spot_t / curve[t])
    tau = (np.arange(t, WEEKS) - t) / WEEKS
    decay = np.exp(-kappa * tau)
    var = sigma * sigma * (1.0 - np.exp(-2.0 * kappa * tau)) / (2.0 * kappa)
    out = curve.copy()
    out[t:] = curve[t:] * np.exp(x_t * decay + 0.5 * var)
    return out


# ---------- 2. Solver ----------

def build_lp(capacity, inj_rate, wd_rate, inj_cost, wd_cost, fuel_pct):
    """Storage LP over the 52 weekly periods, with the forward curve as a
    MUTABLE Param so the rolling-intrinsic Monte Carlo can re-solve the
    same model thousands of times without rebuilding it. Executed history
    is enforced by fixing the flow variables of past weeks.
    """
    m = pyo.ConcreteModel()
    m.T = pyo.RangeSet(0, WEEKS - 1)

    m.F = pyo.Param(m.T, mutable=True, initialize=0.0)
    m.inv_start = pyo.Param(mutable=True, initialize=0.0)

    m.i = pyo.Var(m.T, bounds=(0, inj_rate))
    m.w = pyo.Var(m.T, bounds=(0, wd_rate))
    m.inv = pyo.Var(m.T, bounds=(0, capacity))

    @m.Constraint(m.T)
    def balance(m, t):
        prev = m.inv_start if t == 0 else m.inv[t - 1]
        return m.inv[t] == prev + (1.0 - fuel_pct) * m.i[t] - m.w[t]

    m.end_empty = pyo.Constraint(expr=m.inv[WEEKS - 1] == 0)

    m.obj = pyo.Objective(
        expr=sum(m.F[t] * (m.w[t] - m.i[t]) - inj_cost * m.i[t] - wd_cost * m.w[t]
                 for t in m.T),
        sense=pyo.maximize,
    )
    return m


def _load_curve(m, curve):
    for t in range(WEEKS):
        m.F[t] = float(curve[t])


def solve_intrinsic(m, curve):
    """One-shot intrinsic solve with log capture for the Logs tab."""
    from pyomo.contrib.appsi.solvers import Highs

    _load_curve(m, curve)
    opt = Highs()
    opt.config.stream_solver = True
    with capture_output(capture_fd=True) as buf:
        opt.solve(m)
    value = pyo.value(m.obj)
    inj = np.array([pyo.value(m.i[t]) for t in range(WEEKS)])
    wd = np.array([pyo.value(m.w[t]) for t in range(WEEKS)])
    inv = np.array([pyo.value(m.inv[t]) for t in range(WEEKS)])
    return value, inj, wd, inv, buf.getvalue()


def rolling_intrinsic(m, curve, spot, kappa, sigma, inj_cost, wd_cost, progress=None):
    """Rolling-intrinsic valuation over simulated spot paths.

    Per path: every WEEKS_PER_STEP weeks, rebuild the conditional forward
    curve from the path's current spot, re-solve the LP from the current
    inventory over the remaining horizon, and execute the plan's next
    WEEKS_PER_STEP weeks at those conditional-curve prices. Realized value
    accumulates per path; inventory trajectories are recorded for the fan
    chart. One HiGHS instance carries all re-solves.
    """
    from pyomo.contrib.appsi.solvers import Highs

    opt = Highs()
    n_paths = spot.shape[0]
    pnl = np.zeros(n_paths)
    inv_paths = np.zeros((n_paths, WEEKS))
    decision_weeks = list(range(0, WEEKS, WEEKS_PER_STEP))

    for p in range(n_paths):
        for t0 in decision_weeks:
            cond = conditional_curve(curve, spot[p, t0], t0, kappa, sigma)
            _load_curve(m, cond)
            # Executed history is enforced by the already-fixed flow
            # variables of weeks before t0; the balance equations then
            # reproduce the locked inventory trajectory.
            opt.solve(m)
            for t in range(t0, min(t0 + WEEKS_PER_STEP, WEEKS)):
                i_t = min(max(pyo.value(m.i[t]), 0.0), m.i[t].ub)
                w_t = min(max(pyo.value(m.w[t]), 0.0), m.w[t].ub)
                pnl[p] += cond[t] * (w_t - i_t) - inj_cost * i_t - wd_cost * w_t
                inv_paths[p, t] = pyo.value(m.inv[t])
                # Lock the executed week: freeze its flows for every later
                # re-solve on this path.
                m.i[t].fix(i_t)
                m.w[t].fix(w_t)
        # Unfix everything for the next path.
        for t in range(WEEKS):
            m.i[t].unfix()
            m.w[t].unfix()
        if progress is not None and (p % 5 == 0 or p == n_paths - 1):
            progress.progress((p + 1) / n_paths,
                              text=f"Re-optimizing path {p + 1} of {n_paths}...")
    return pnl, inv_paths


# ---------- 3. State ----------

DEFAULTS = dict(
    capacity=1000.0,     # working gas, thousand MMBtu
    inj_rate=60.0,       # max injection per week (k MMBtu)
    wd_rate=100.0,       # max withdrawal per week (k MMBtu)
    inj_cost=0.02,       # $/MMBtu variable cost
    wd_cost=0.02,
    fuel_pct=0.01,       # fraction of injected gas lost as fuel
    base=3.50,           # $/MMBtu
    premium=1.00,        # winter premium amplitude ($/MMBtu)
    sigma=0.55,          # annualized log-spot volatility
    kappa=6.0,           # mean-reversion speed (per year)
    n_paths=50,
    seed=0,
)


def init_state():
    ss = st.session_state
    ss.setdefault("intrinsic", None)   # (value, inj, wd, inv, log)
    ss.setdefault("mc", None)          # (pnl, inv_paths)


def clear_results():
    st.session_state.intrinsic = None
    st.session_state.mc = None


def clear_mc():
    st.session_state.mc = None


# ---------- 4. LaTeX ----------

def render_formulation():
    st.markdown("### The product")
    st.markdown(
        "A storage lease grants the right to inject, hold, and withdraw gas "
        "over a contract year (April–March), subject to a working-gas "
        "capacity, weekly injection and withdrawal rate limits, variable "
        "costs, and a fuel loss on injection. The facility starts and ends "
        "empty. Its value has two parts: the **intrinsic** value locked in "
        "against today's forward curve, and the **extrinsic** value of "
        "re-optimizing as prices move."
    )

    st.markdown("### Intrinsic value: a linear program")
    st.latex(r"""
        \begin{aligned}
        \max_{i, w, v} \quad & \sum_{t=1}^{52} F_t (w_t - i_t) - c_i\, i_t - c_w\, w_t \\
        \text{s.t.} \quad & v_t = v_{t-1} + (1-\phi)\, i_t - w_t, \qquad v_0 = 0,\; v_{52} = 0 \\
        & 0 \le v_t \le V^{\max}, \quad 0 \le i_t \le I^{\max}, \quad 0 \le w_t \le W^{\max}
        \end{aligned}
    """)
    st.markdown(
        "**Decision variables**: $i_t$ = gas injected during week $t$ "
        "(k MMBtu), $w_t$ = gas withdrawn during week $t$ (k MMBtu), "
        "$v_t$ = inventory at the end of week $t$ (k MMBtu).\n\n"
        "**Data**: $F_t$ = forward price for delivery in week $t$ "
        "(\\$/MMBtu), $c_i$ and $c_w$ = variable injection and withdrawal "
        "costs (\\$/MMBtu), $\\phi$ = fuel-loss fraction on injection, "
        "$V^{\\max}$ = working-gas capacity, $I^{\\max}$ and $W^{\\max}$ = "
        "weekly injection and withdrawal rate limits.\n\n"
        "The optimal plan buys the cheap season and sells the expensive "
        "one as hard as the rate limits allow: the classic seasonal "
        "storage trade."
    )

    st.markdown("### Spot price process")
    st.markdown(
        "Log spot mean-reverts around the seasonal curve: a one-factor "
        "Schwartz model, in which the log deviation follows an "
        "Ornstein-Uhlenbeck (OU) process. Here $S_t$ = the spot price in "
        "week $t$, $m(t)$ = the seasonal forward curve, and "
        "$x_t = \\ln(S_t/m(t))$ = the log-deviation of spot from the "
        "curve. $\\kappa$ = the mean-reversion speed (per year), "
        "$\\sigma$ = the annualized log-spot volatility, and $B_t$ = a "
        "standard Brownian motion:"
    )
    st.latex(r"dx_t = -\kappa\, x_t\, dt + \sigma\, dB_t")
    st.markdown(
        "Simulation uses the exact OU transition over each weekly step "
        "$\\Delta t = 1/52$ years, with $\\varepsilon$ a standard normal "
        "draw, so no discretization bias enters:"
    )
    st.latex(r"""
        x_{t+\Delta t} = e^{-\kappa \Delta t}\, x_t + \sigma
        \sqrt{\tfrac{1 - e^{-2\kappa \Delta t}}{2\kappa}}\; \varepsilon,
        \qquad \varepsilon \sim \mathcal{N}(0, 1)
    """)
    st.markdown(
        "The forward curve seen from week $t$, written $F_t(d)$ for the "
        "price of delivery in a later week $d$, is the conditional "
        "expectation of spot under this process: today's shock decays "
        "toward the seasonal curve at rate $\\kappa$:"
    )
    st.latex(r"""F_t(d) = m(d)\, \exp\!\Big( x_t\, e^{-\kappa (d - t)}
        + \tfrac{1}{2}\,\mathrm{Var}[x_d \mid x_t] \Big), \qquad
        \mathrm{Var}[x_d \mid x_t] = \tfrac{\sigma^2}{2\kappa}
        \big(1 - e^{-2\kappa (d - t)}\big)""")
    st.markdown(
        "The half-variance term is the Jensen correction: the expectation "
        "of a lognormal variable exceeds the exponential of its log-mean, "
        "so without it the curve would be the conditional *median* of "
        "spot rather than its mean."
    )

    st.markdown("### Rolling intrinsic")
    st.markdown(
        "The industry-standard lower-bound estimate of full storage value:\n\n"
        "1. Simulate a spot path.\n"
        "2. At each decision date (every 4 weeks), rebuild the conditional "
        "forward curve from the path's current spot.\n"
        "3. Re-solve the intrinsic LP over the remaining horizon, with the "
        "already-executed weeks locked at their committed flows.\n"
        "4. Execute the plan's next 4 weeks at those prices; accumulate "
        "the realized value.\n"
        "5. Average across paths.\n\n"
        "Individual paths can realize less than the intrinsic value: this "
        "implementation locks only the front weeks and leaves the rest of "
        "the plan exposed to price moves, so a path where prices collapse "
        "before the stored gas is sold ends below the locked-in number "
        "(visible in the left tail of the value distribution). On "
        "*average*, though, re-optimizing beats locking, because each "
        "re-solve only deviates from the standing plan when the new prices "
        "make deviating better. The average uplift over intrinsic is (a "
        "lower bound on) the extrinsic value, and it grows with volatility "
        "and with re-decision frequency. A fully hedged variant that "
        "re-trades the entire forward strip at each decision would lock "
        "value as it goes and beat intrinsic on every path, not just on "
        "average. Exact valuation requires stochastic dynamic programming "
        "on the inventory state (e.g. Longstaff–Schwartz regression, "
        "Boogert & de Jong [1]); rolling intrinsic typically captures most "
        "of the optionality at a fraction of the complexity, which is why "
        "storage traders quote it in practice.\n\n"
        "In control-theory terms: intrinsic is the optimal open-loop plan, "
        "and rolling intrinsic is certainty-equivalent (nominal) model "
        "predictive control, re-planning with feedback against the "
        "expected future."
    )

    st.markdown("### References")
    st.markdown(
        "[1] A. Boogert and C. de Jong, \"Gas Storage Valuation Using a "
        "Monte Carlo Method,\" *The Journal of Derivatives*, vol. 15, "
        "no. 3, pp. 81–98, 2008. "
        "[PM Research](https://www.pm-research.com/content/iijderiv/15/3/81)\n\n"
        "[2] N. Secomandi, \"Optimal Commodity Trading with a Capacitated "
        "Storage Asset,\" *Management Science*, vol. 56, no. 3, "
        "pp. 449–467, 2010. "
        "[INFORMS](https://pubsonline.informs.org/doi/10.1287/mnsc.1090.1049)\n\n"
        "[3] A. Eydeland and K. Wolyniec, *Energy and Power Risk "
        "Management: New Developments in Modeling, Pricing, and Hedging*. "
        "Hoboken: Wiley, 2003.\n\n"
        "[4] M. L. Bynum, G. A. Hackebeil, W. E. Hart, C. D. Laird, "
        "B. L. Nicholson, J. D. Siirola, J.-P. Watson, and D. L. Woodruff, "
        "*Pyomo: Optimization Modeling in Python*, 3rd ed. Cham: "
        "Springer, 2021. "
        "[Springer](https://link.springer.com/book/10.1007/978-3-030-68928-5)"
    )


# ---------- 5. CSS ----------

CSS = """
<style>
/* Top padding shared across the template family: clears the sticky
   header without clipping the title. See griffith-pse-app-template. */
.block-container,
[data-testid="stMainBlockContainer"] {
    padding-top: 2.5rem !important;
}
/* Home-link logo at the very top of the sidebar, in normal document flow
   so it scrolls with the sidebar content (not pinned to the viewport). */
.home-logo-corner {
    display: inline-block;   /* shrink to the icon so only the G is clickable */
    margin: 0 0 0.75rem;
}
.home-logo-corner img {
    width: 32px; height: 32px; border-radius: 4px; display: block;
}
/* Hide Streamlit's sticky sidebar header (which hosts the «« collapse
   arrow) so the home-logo sits at the very top of the sidebar with no
   chrome above it. Trade-off: the user can no longer collapse the sidebar
   via the button. The sidebar is the app's control panel and is meant
   to stay visible, so this is fine for this app. */
[data-testid="stSidebarHeader"] {
    display: none !important;
}
[data-testid="stSidebarUserContent"] {
    padding-top: 0.5rem !important;
    padding-bottom: 0.5rem !important;
}
/* Monte Carlo progress bar: a floating overlay centered on the chart area,
   out of the page flow so nothing shifts while it runs. */
[class*="st-key-mc_overlay"] {
    position: fixed;
    top: calc(50% + 130px);
    left: calc(50% - 50px);   /* centered on the chart grid, which hugs the
                                 left of the main area beside the sidebar */
    transform: translate(-50%, -50%);
    width: 480px;
    z-index: 9999;
    background: rgba(255, 255, 255, 0.97);
    border: 1px solid #d3d7db;
    border-radius: 10px;
    padding: 1.1rem 1.4rem;
    box-shadow: 0 8px 30px rgba(0, 0, 0, 0.15);
}
/* Compact sidebar: tighten the vertical rhythm so Contract, Market, and
   Simulation all fit a typical viewport without scrolling. */
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
    gap: 0.55rem !important;
}
section[data-testid="stSidebar"] h2 {
    padding: 0.25rem 0 0.3rem 0 !important;
    font-size: 1.05rem !important;
}
section[data-testid="stSidebar"] [data-testid="stSlider"] {
    margin-bottom: -0.35rem !important;
}
</style>
"""


# ---------- 6. Charts ----------

_AXIS_X = alt.X("week:Q", title="week of contract year (Apr–Mar)",
                scale=alt.Scale(domain=[0, WEEKS]))


def _boundary(series):
    """Inventory is an end-of-week (boundary) quantity: prepend the empty
    starting state so node t+1 carries the level after week t's flow."""
    return np.concatenate([[0.0], series])


def price_chart(curve, spot, sel_path):
    """Forward curve + simulated spot fan (10-90% band + sample paths)."""
    df_fwd = pd.DataFrame({"week": np.arange(WEEKS), "price": curve})
    _domain = ["forward"] + (["spot paths"] if spot is not None else []) + (
        ["highlighted path"] if sel_path is not None else [])
    _range = [COLOR_FORWARD] + ([COLOR_SPOT] if spot is not None else []) + (
        [COLOR_SELECTED] if sel_path is not None else [])
    _color = alt.Color(
        "series:N",
        scale=alt.Scale(domain=_domain, range=_range),
        legend=alt.Legend(title=None, orient="top", direction="horizontal", symbolOpacity=1, symbolStrokeWidth=3, labelFontSize=13,
                          labelFontWeight="bold"),
    )
    layers = []
    if spot is not None:
        lo = np.percentile(spot, 10, axis=0)
        hi = np.percentile(spot, 90, axis=0)
        band = pd.DataFrame({"week": np.arange(WEEKS), "lo": lo, "hi": hi})
        layers.append(
            alt.Chart(band).mark_area(color=COLOR_SPOT, opacity=0.25)
            .encode(x=_AXIS_X, y=alt.Y("lo:Q", title="$/MMBtu"), y2="hi:Q")
        )
        sample = spot[: min(30, spot.shape[0])]
        df_paths = pd.DataFrame({
            "week": np.tile(np.arange(WEEKS), sample.shape[0]),
            "price": sample.ravel(),
            "path": np.repeat(np.arange(sample.shape[0]), WEEKS),
        })
        layers.append(
            alt.Chart(df_paths).transform_calculate(series='"spot paths"')
            .mark_line(opacity=0.3, strokeWidth=0.7)
            .encode(x=_AXIS_X, y="price:Q", detail="path:N", color=_color)
        )
        if sel_path is not None:
            df_sel = pd.DataFrame({"week": np.arange(WEEKS),
                                   "price": spot[sel_path]})
            layers.append(
                alt.Chart(df_sel)
                .transform_calculate(series='"highlighted path"')
                .mark_line(strokeWidth=2)
                .encode(x=_AXIS_X, y="price:Q", color=_color,
                        tooltip=[alt.Tooltip("week:Q"),
                                 alt.Tooltip("price:Q", format=".2f")])
            )
    layers.append(
        alt.Chart(df_fwd).transform_calculate(series='"forward"')
        .mark_line(strokeWidth=2.5)
        .encode(x=_AXIS_X, y=alt.Y("price:Q", title="$/MMBtu"),
                color=_color,
                tooltip=[alt.Tooltip("week:Q"),
                         alt.Tooltip("price:Q", format=".2f",
                                     title="forward")])
    )
    return alt.layer(*layers).properties(width=560, height=285).configure_axis(labelFontSize=13, titleFontSize=14)


def inventory_chart(inv_intrinsic, inv_paths, sel_path):
    """Intrinsic inventory schedule (area) + rolling-intrinsic fan.
    Plotted on week BOUNDARIES (0..52): the value at x = t+1 is the level
    after week t's flow, so the panel lines up with the flow bars below."""
    df_int = pd.DataFrame({"week": np.arange(WEEKS + 1),
                           "inv": _boundary(inv_intrinsic)})
    _domain = ["intrinsic plan"] + (
        ["re-optimized paths"] if inv_paths is not None else []) + (
        ["highlighted path"] if sel_path is not None else [])
    _range = [COLOR_FORWARD] + (
        [COLOR_SPOT] if inv_paths is not None else []) + (
        [COLOR_SELECTED] if sel_path is not None else [])
    _color = alt.Color(
        "series:N",
        scale=alt.Scale(domain=_domain, range=_range),
        legend=alt.Legend(title=None, orient="top", direction="horizontal", symbolOpacity=1, symbolStrokeWidth=3, labelFontSize=13,
                          labelFontWeight="bold"),
    )
    layers = [
        alt.Chart(df_int).transform_calculate(series='"intrinsic plan"')
        .mark_line(strokeWidth=2.5)
        .encode(x=_AXIS_X,
                y=alt.Y("inv:Q", title="inventory (k MMBtu)"),
                color=_color,
                tooltip=[alt.Tooltip("week:Q"),
                         alt.Tooltip("inv:Q", format=".0f",
                                     title="inventory at start of week")])
    ]
    if inv_paths is not None:
        sample = inv_paths[: min(30, inv_paths.shape[0])]
        sample = np.hstack([np.zeros((sample.shape[0], 1)), sample])
        df_paths = pd.DataFrame({
            "week": np.tile(np.arange(WEEKS + 1), sample.shape[0]),
            "inv": sample.ravel(),
            "path": np.repeat(np.arange(sample.shape[0]), WEEKS + 1),
        })
        layers.append(
            alt.Chart(df_paths)
            .transform_calculate(series='"re-optimized paths"')
            .mark_line(opacity=0.3, strokeWidth=0.7)
            .encode(x=_AXIS_X, y="inv:Q", detail="path:N", color=_color)
        )
        if sel_path is not None:
            df_sel = pd.DataFrame({"week": np.arange(WEEKS + 1),
                                   "inv": _boundary(inv_paths[sel_path])})
            layers.append(
                alt.Chart(df_sel)
                .transform_calculate(series='"highlighted path"')
                .mark_line(strokeWidth=2)
                .encode(x=_AXIS_X, y="inv:Q", color=_color,
                        tooltip=[alt.Tooltip("week:Q"),
                                 alt.Tooltip("inv:Q", format=".0f")])
            )
    return alt.layer(*layers).properties(width=560, height=285).configure_axis(labelFontSize=13, titleFontSize=14)


def decision_chart(inj, wd, path_flows=None):
    """Intrinsic plan's weekly net flow: injections up, withdrawals down.
    When a Monte Carlo path is highlighted, its realized net weekly flows
    overlay the plan as a purple step line."""
    df = pd.DataFrame({
        "week": np.arange(WEEKS),
        "flow": inj - wd,
    })
    y_axis = alt.Y("flow:Q", title="flow (k MMBtu/wk)",
                   axis=alt.Axis(values=[-100, -50, 0, 50, 100]),
                   scale=alt.Scale(domain=[float(-wd.max() - 10),
                                           float(inj.max() + 10)]))
    # Colors ride a shared field-based scale so the chart carries a legend;
    # the highlighted-path entry only exists when a path is shown.
    _domain = ["intrinsic net flow"] + (
        ["highlighted path"] if path_flows is not None else [])
    _range = [COLOR_FORWARD] + (
        [COLOR_SELECTED] if path_flows is not None else [])
    _color = alt.Color(
        "series:N",
        scale=alt.Scale(domain=_domain, range=_range),
        legend=alt.Legend(title=None, orient="top", direction="horizontal", symbolOpacity=1, symbolStrokeWidth=3, labelFontSize=13,
                          labelFontWeight="bold"),
    )
    flow_bars = (
        alt.Chart(df).transform_calculate(series='"intrinsic net flow"')
        .mark_bar()
        .encode(x=_AXIS_X, y=y_axis, color=_color,
                tooltip=[alt.Tooltip("week:Q"),
                         alt.Tooltip("flow:Q", format=".1f")])
    )
    zero = (
        alt.Chart(pd.DataFrame({"y": [0.0]}))
        .mark_rule(color="#4b5563", strokeWidth=1.2)
        .encode(y="y:Q")
    )
    layers = [flow_bars, zero]
    if path_flows is not None:
        df_sel = pd.DataFrame({"week": np.arange(WEEKS), "flow": path_flows})
        layers.append(
            alt.Chart(df_sel)
            .transform_calculate(series='"highlighted path"')
            .mark_line(strokeWidth=2.5, interpolate="step-after")
            .encode(x=_AXIS_X, y=alt.Y("flow:Q", title=""), color=_color,
                    tooltip=[alt.Tooltip("week:Q"),
                             alt.Tooltip("flow:Q", format=".1f",
                                         title="path net flow")])
        )
    return alt.layer(*layers).properties(width=560, height=285).configure_axis(labelFontSize=13, titleFontSize=14)


def pnl_chart(pnl, intrinsic_value, sel_value=None):
    """Distribution of realized value across paths, with the intrinsic
    value, the rolling-intrinsic mean, and (when a path is highlighted)
    that path's realized value marked."""
    df = pd.DataFrame({"pnl": pnl})
    hist = (
        alt.Chart(df).mark_bar(color=COLOR_SPOT, opacity=0.75)
        .encode(
            x=alt.X("pnl:Q", bin=alt.Bin(maxbins=40),
                    title="realized value per path (k$)"),
            y=alt.Y("count()", title="paths"),
        )
    )
    rules = pd.DataFrame({
        "x": [intrinsic_value, float(np.mean(pnl))]
             + ([sel_value] if sel_value is not None else []),
        "label": ["intrinsic", "avg rolling intrinsic"]
                 + (["highlighted path"] if sel_value is not None else []),
        "color": [COLOR_FORWARD, COLOR_ROLLING]
                 + ([COLOR_SELECTED] if sel_value is not None else []),
    })
    rule = (
        alt.Chart(rules).mark_rule(strokeWidth=2.5)
        .encode(x="x:Q",
                color=alt.Color(
                    "label:N",
                    scale=alt.Scale(domain=list(rules["label"]),
                                    range=list(rules["color"])),
                    legend=alt.Legend(title=None, orient="top",
                                      direction="horizontal",
                                      labelFontSize=13,
                                      labelFontWeight="bold")),
                tooltip=[alt.Tooltip("label:N"),
                         alt.Tooltip("x:Q", format=".1f")])
    )
    return (
        alt.layer(hist, rule)
        .properties(width=560, height=285)
        .configure_axis(labelFontSize=13, titleFontSize=14)
    )


# ---------- 7. Main ----------

st.set_page_config(
    page_title="Gas Storage",
    page_icon="favicon.png",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(CSS, unsafe_allow_html=True)

# Home-link logo (sidebar variant): clicking the Griffith PSE blackletter G
# returns to the portfolio site. Image embedded as a base64 data URL so
# loading the page makes no third-party network call.
_FAVICON_DATA_URL = "data:image/png;base64," + base64.b64encode(
    (Path(__file__).parent / "favicon.png").read_bytes()
).decode()
st.sidebar.markdown(
    f'<a class="home-logo-corner" href="https://griffith-pse.com" target="_self">'
    f'<img src="{_FAVICON_DATA_URL}" alt="Griffith PSE: home" width="32" height="32" style="width:32px;height:32px;border-radius:4px;display:block" />'
    f'</a>',
    unsafe_allow_html=True,
)

init_state()

# ---- Sidebar ----

st.sidebar.header("Contract")
capacity = st.sidebar.slider("Working gas capacity (k MMBtu)", 200.0, 2000.0,
                             DEFAULTS["capacity"], step=100.0, format="%.0f",
                             key="capacity", on_change=clear_results)
inj_rate = st.sidebar.slider("Max injection (k MMBtu/wk)", 20.0, 200.0,
                             DEFAULTS["inj_rate"], step=10.0, format="%.0f",
                             key="inj_rate", on_change=clear_results)
wd_rate = st.sidebar.slider("Max withdrawal (k MMBtu/wk)", 20.0, 200.0,
                            DEFAULTS["wd_rate"], step=10.0, format="%.0f",
                            key="wd_rate", on_change=clear_results)

st.sidebar.header("Market")
base = st.sidebar.slider("Base price ($/MMBtu)", 2.0, 6.0, DEFAULTS["base"],
                         step=0.25, format="%.2f", key="base",
                         on_change=clear_results)
premium = st.sidebar.slider("Winter premium ($/MMBtu)", 0.0, 3.0,
                            DEFAULTS["premium"], step=0.25, format="%.2f",
                            key="premium", on_change=clear_results)
sigma = st.sidebar.slider("Spot volatility σ (annualized)", 0.1, 1.5,
                          DEFAULTS["sigma"], step=0.05, format="%.2f",
                          key="sigma", on_change=clear_mc)
kappa = st.sidebar.slider("Mean reversion κ (per year)", 1.0, 20.0,
                          DEFAULTS["kappa"], step=1.0, format="%.0f",
                          key="kappa", on_change=clear_mc)

st.sidebar.header("Simulation")
n_paths = st.sidebar.slider("Monte Carlo paths", 50, 500,
                            DEFAULTS["n_paths"], step=50, key="n_paths",
                            on_change=clear_mc)
seed = st.sidebar.number_input("Random seed", 0, 9999, DEFAULTS["seed"],
                               step=1, key="seed", on_change=clear_mc)

mc_btn = st.sidebar.button("Run Monte Carlo", type="primary",
                           use_container_width=True)

# ---- Title ----

st.markdown(
    "<h2 style='margin: 0 0 0.25rem 0; padding: 0; font-size: 1.5rem; font-weight: 700;'>"
    "Gas Storage Valuation "
    "<a href='https://github.com/devin-griff/gas-storage' target='_blank' "
    "title='View source on GitHub' "
    "style='display: inline-block; vertical-align: 0.02em; margin: 0 0.35rem 0 0.1rem; "
    "color: inherit;'>"
    "<svg viewBox='0 0 16 16' width='20' height='20' fill='currentColor' "
    "aria-label='GitHub'>"
    "<path d='M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17."
    "55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-"
    ".82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 "
    "2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59."
    "82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27"
    ".68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51"
    ".56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1."
    "07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-"
    "8-8-8z'/></svg></a>"
    "<span style='font-size: 1.15rem; font-weight: 400; color: #6b7280;'>"
    "powered by "
    "<a href='https://github.com/Pyomo/pyomo' target='_blank' "
    "style='color: #6b7280; text-decoration: underline;'>Pyomo</a>"
    " + "
    "<a href='https://github.com/ERGO-Code/HiGHS' target='_blank' "
    "style='color: #6b7280; text-decoration: underline;'>HiGHS</a>"
    "</span>"
    "</h2>",
    unsafe_allow_html=True,
)
_caption_col, _ = st.columns([6, 3])
with _caption_col:
    st.markdown(
        "Value a natural gas storage lease. The **intrinsic** value locks "
        "a plan against today's forward curve with a linear program: buy "
        "summer, sell winter: and updates live as you move the contract "
        "and price sliders. **Run Monte Carlo** simulates mean-reverting "
        "spot paths and re-optimizes the plan as prices move (rolling "
        "intrinsic). The extra value over the static plan is optionality the "
        "strategy captures, a lower bound on the storage's **extrinsic** "
        "value: watch it grow with volatility."
    )

tab_val, tab_form, tab_logs = st.tabs(
    ["▶ Valuation", "📐 Formulation", "📋 Logs"]
)

# ---- Solve handlers ----

curve = seasonal_curve(base, premium)
_fuel = DEFAULTS["fuel_pct"]
_ci, _cw = DEFAULTS["inj_cost"], DEFAULTS["wd_cost"]

if st.session_state.intrinsic is None:
    lp = build_lp(capacity, inj_rate, wd_rate, _ci, _cw, _fuel)
    st.session_state.intrinsic = solve_intrinsic(lp, curve)

spot = simulate_spot(curve, sigma, kappa, int(n_paths), int(seed))

if mc_btn:
    lp = build_lp(capacity, inj_rate, wd_rate, _ci, _cw, _fuel)
    # The keyed container is styled position:fixed (see CSS), so the bar
    # floats over the charts instead of occupying space in the page flow.
    # An outer st.empty() slot removes the whole styled card afterward,
    # not just the progress element inside it.
    _overlay = st.empty()
    bar = _overlay.container(key="mc_overlay").progress(
        0.0, text="Rolling-intrinsic re-optimization...")
    pnl, inv_paths = rolling_intrinsic(lp, curve, spot, kappa, sigma, _ci,
                                       _cw, progress=bar)
    _overlay.empty()
    st.session_state.mc = (pnl, inv_paths)
    # Fresh results open on the best path; runs before the selector widget
    # is instantiated this rerun, so the state write is allowed.
    st.session_state.path_sel = "best"

intrinsic = st.session_state.intrinsic
mc = st.session_state.mc

# ---- Valuation tab ----

with tab_val:
    m1, m2, m3, sel_col = st.columns([0.8, 1.0, 1.0, 3.2],
                                     vertical_alignment="top")

    def _metric(col, label, value, color="inherit"):
        col.markdown(
            f"<div style='font-size: 0.85rem; color: #6b7280;'>{label}</div>"
            f"<div style='font-size: 1.9rem; font-weight: 600; "
            f"color: {color}; line-height: 1.2;'>{value}</div>",
            unsafe_allow_html=True,
        )

    iv = intrinsic[0] if intrinsic else None
    _metric(m1, "Intrinsic (k$)", f"{iv:,.0f}" if iv is not None else "-",
            COLOR_FORWARD if iv is not None else "inherit")
    if mc and iv is not None:
        rv = float(np.mean(mc[0]))
        _metric(m2, "Avg rolling intrinsic (k$)", f"{rv:,.0f}", COLOR_ROLLING)
        _metric(m3, "Extrinsic uplift (k$)", f"+{rv - iv:,.0f}")
    else:
        _metric(m2, "Avg rolling intrinsic (k$)", "-")
        _metric(m3, "Extrinsic uplift (k$)", "-")

    sel_path = None
    picks = {}
    if mc:
        # Named picks: the extremes and the median tell the story; two fixed
        # array positions stand in as ordinary draws.
        order = np.argsort(mc[0])
        picks = {
            "worst": int(order[0]),
            "median": int(order[len(order) // 2]),
            "best": int(order[-1]),
        }
        # Samples are the first array positions not already taken by the
        # named picks, so no two buttons ever alias the same path.
        _free = (k for k in range(len(mc[0])) if k not in picks.values())
        picks["sample A"] = next(_free)
        picks["sample B"] = next(_free)
    with sel_col:
        # Rendered before any Monte Carlo run too (single disabled "None"
        # entry) so the header band keeps its shape.
        # The label row is a placeholder filled after the control below
        # reports its choice, so the realized-value note can sit on the
        # label line. Plain HTML also keeps the $ signs out of Streamlit's
        # LaTeX detection.
        label_slot = st.empty()
        choice = st.segmented_control(
            "Highlight path",
            options=["None"] + list(picks),
            key="path_sel",
            disabled=not mc,
            label_visibility="collapsed",
        )
        note = ""
        if mc and choice is not None and choice != "None":
            sel_path = picks[choice]
            note = (f"The <b>{choice}</b> path realized "
                    f"<b>{mc[0][sel_path]:,.0f} k$</b>.")
        label_slot.markdown(
            "<div style='font-size: 0.85rem; margin-bottom: 0.25rem;'>"
            "<span style='color: #6b7280;'>Highlight path</span>"
            f"<span style='margin-left: 1.25rem;'>{note}</span></div>",
            unsafe_allow_html=True,
        )

    # 2x2 grid: prices | inventory, flows | value distribution. The grid
    # lives in a sub-column sized to the charts, so the two columns hug the
    # panels instead of splitting the full page width and leaving a dead
    # strip between them.
    grid, _ = st.columns([12, 1])
    row1_l, row1_r = grid.columns(2, gap="medium")
    with row1_l:
        st.markdown("**Prices**: forward curve and simulated spot "
                    "(price for that week)")
        st.altair_chart(price_chart(curve, spot, sel_path),
                        use_container_width=False)
    with row1_r:
        st.markdown("**Inventory**: intrinsic schedule and re-optimized "
                    "paths (level at start of week)")
        st.altair_chart(
            inventory_chart(intrinsic[3], mc[1] if mc else None, sel_path),
            use_container_width=False,
        )
    row2_l, row2_r = grid.columns(2, gap="medium")
    with row2_l:
        st.markdown("**Intrinsic plan**: flow during each week "
                    "(injections up, withdrawals down)")
        path_flows = None
        if mc and sel_path is not None:
            path_flows = np.diff(np.concatenate([[0.0], mc[1][sel_path]]))
        st.altair_chart(
            decision_chart(intrinsic[1], intrinsic[2], path_flows),
            use_container_width=False,
        )
    with row2_r:
        st.markdown("**Value distribution**: realized P&L across paths")
        if mc:
            st.altair_chart(
                pnl_chart(mc[0], intrinsic[0],
                          float(mc[0][sel_path]) if sel_path is not None
                          else None),
                use_container_width=False,
            )
        else:
            st.caption("Run the Monte Carlo to populate the distribution.")

with tab_form:
    render_formulation()

with tab_logs:
    if intrinsic and intrinsic[4].strip():
        st.caption(
            "Intrinsic LP solve. The Monte Carlo's re-solves (13 per path) "
            "run with logging off for speed."
        )
        st.code(intrinsic[4], language=None)
    else:
        st.info("Run a valuation to see HiGHS output for the intrinsic LP.")
