"""
Options Second-Order Greeks Analyzer
Schwab API + Black-Scholes | SPY / QQQ / DIA

Layout:
  Left  (40%) : GEX horizontal bar chart
  Right (60%) : Vanna (top) stacked over Charm (bottom)

Controls:
  Symbol dropdown  -> switch SPY / QQQ / DIA
  Vanna toggle     -> Net / Call+Put split
  Charm toggle     -> Net / Call+Put split
  Ctrl+Scroll      -> zoom entire window
  R                -> reset zoom
"""

from dotenv import load_dotenv
load_dotenv()

import os, time, warnings, datetime
import tkinter as tk
from tkinter import ttk

import requests
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import matplotlib.gridspec as gridspec
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from scipy.stats import norm
from scipy.ndimage import gaussian_filter1d
warnings.filterwarnings("ignore")

# ══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════════════════

CLIENT_ID     = os.environ.get("SCHWAB_CLIENT_ID",     "YOUR_CLIENT_ID")
CLIENT_SECRET = os.environ.get("SCHWAB_CLIENT_SECRET", "YOUR_CLIENT_SECRET")
RISK_FREE     = 0.045
SYMBOLS       = ["SPY", "QQQ", "DIA"]
SCHWAB_BASE   = "https://api.schwabapi.com/marketdata/v1"
STRIKE_PCT    = 0.12

C = {
    "bg":         "#0d0d0d", "panel":      "#111111",
    "border":     "#222222", "text":       "#dddddd",
    "subtext":    "#555555", "grid":       "#191919",
    "zero":       "#2a2a2a", "spot":       "#f0c040",
    "put":        "#481F46", "call":       "#FFF669",
    "net_pos":    "#165129", "net_neg":    "#dc2626",
    "vanna_net":  "#481F46", "vanna_call": "#165129",
    "vanna_put":  "#dc2626", "charm_net":  "#481F46",
    "charm_call": "#165129", "charm_put":  "#dc2626",
    "ctrl":       "#0a0a0a", "btn_off":    "#161616",
    "btn_on":     "#2a1f3d", "live":       "#165129",
    "demo":       "#f97316",
}

# ══════════════════════════════════════════════════════════════════════════════
# SCHWAB API
# ══════════════════════════════════════════════════════════════════════════════

def get_options_chain(token, symbol, spot):
    headers   = {"Authorization": f"Bearer {token}"}
    from_date = datetime.date.today().strftime("%Y-%m-%d")
    to_date   = (datetime.date.today() +
                 datetime.timedelta(days=45)).strftime("%Y-%m-%d")
    params = {
        "symbol":           symbol,
        "contractType":     "ALL",
        "includeQuotes":    "TRUE",
        "optionType":       "ALL",
        "range":            "ALL",
        "fromDate":         from_date,
        "toDate":           to_date,
        "strikePriceAbove": round(spot * (1 - STRIKE_PCT), 2),
        "strikePriceBelow": round(spot * (1 + STRIKE_PCT), 2),
    }
    for attempt in range(3):
        try:
            r = requests.get(f"{SCHWAB_BASE}/chains",
                             headers=headers, params=params, timeout=45)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.HTTPError:
            if r.status_code in [502, 503, 504] and attempt < 2:
                w = (attempt + 1) * 5
                print(f"  {r.status_code} - retry in {w}s...")
                time.sleep(w)
                continue
            raise

# ══════════════════════════════════════════════════════════════════════════════
# BLACK-SCHOLES
# ══════════════════════════════════════════════════════════════════════════════

def _d1(S, K, T, r, s):
    return (np.log(S / K) + (r + 0.5 * s**2) * T) / (s * np.sqrt(T))

def _d2(S, K, T, r, s):
    return _d1(S, K, T, r, s) - s * np.sqrt(T)

def calc_gamma(S, K, T, r, s):
    return norm.pdf(_d1(S, K, T, r, s)) / (S * s * np.sqrt(T))

def calc_vanna(S, K, T, r, s):
    return -norm.pdf(_d1(S, K, T, r, s)) * _d2(S, K, T, r, s) / s

def calc_charm(S, K, T, r, s, call):
    d1  = _d1(S, K, T, r, s)
    d2  = _d2(S, K, T, r, s)
    raw = -norm.pdf(d1) * (2 * r * T - d2 * s * np.sqrt(T)) / \
          (2 * T * s * np.sqrt(T))
    return raw / 365 if call else (raw + 2 * r * norm.cdf(-d1)) / 365

# ══════════════════════════════════════════════════════════════════════════════
# PARSE CHAIN
# Sign convention (dealer perspective):
#   GEX   : calls positive, puts negative (* spot for dollar weighting)
#   Vanna : sign * va * mult  (sign=-1 for puts flips negative raw vanna
#           at OTM puts to positive, matching collector/database values)
#   Charm : sign * ch * mult  (same sign convention as vanna)
# ══════════════════════════════════════════════════════════════════════════════

def parse_chain(chain, r=RISK_FREE):
    S    = chain["underlyingPrice"]
    rows = []
    for side, exp_map in [("call", chain.get("callExpDateMap", {})),
                           ("put",  chain.get("putExpDateMap",  {}))]:
        call = (side == "call")
        for exp_key, strikes in exp_map.items():
            try:    dte = float(exp_key.split(":")[1])
            except: continue
            T = dte / 365
            if T <= 0: continue
            for ks, contracts in strikes.items():
                K = float(ks)
                if abs(K - S) / S > STRIKE_PCT: continue
                c     = contracts[0]
                iv    = c.get("volatility", 0)
                if not iv or iv <= 0: continue
                sigma = iv / 100
                oi    = c.get("openInterest", 0) or 0
                if oi < 1: continue
                try:
                    g  = calc_gamma(S, K, T, r, sigma)
                    va = calc_vanna(S, K, T, r, sigma)
                    ch = calc_charm(S, K, T, r, sigma, call)
                except: continue
                mult = oi * 100
                sign = 1 if call else -1
                rows.append({
                    "strike":       K,
                    "type":         side,
                    "dte":          dte,
                    "oi":           oi,
                    # GEX: dollar-weighted, calls pos / puts neg
                    "GEX_call":     g  * mult * S if call     else 0,
                    "GEX_put":     -g  * mult * S if not call else 0,
                    # Vanna: sign * va * mult (no spot multiplier)
                    "VannEX":       sign * va * mult,
                    "VannEX_call":  va * mult      if call     else 0,
                    "VannEX_put":  -va * mult      if not call else 0,
                    # Charm: sign * ch * mult (no spot multiplier)
                    "CharmEX":      sign * ch * mult,
                    "CharmEX_call": ch * mult      if call     else 0,
                    "CharmEX_put": -ch * mult      if not call else 0,
                })
    return pd.DataFrame(rows)

# ══════════════════════════════════════════════════════════════════════════════
# AGGREGATE
# ══════════════════════════════════════════════════════════════════════════════

def aggregate(df):
    cols = ["GEX_call", "GEX_put",
            "VannEX", "VannEX_call", "VannEX_put",
            "CharmEX", "CharmEX_call", "CharmEX_put",
            "oi"]
    a = (df.groupby("strike")[cols]
           .sum()
           .reset_index()
           .sort_values("strike"))
    a["GEX_net"] = a["GEX_call"] + a["GEX_put"]
    return a

# ══════════════════════════════════════════════════════════════════════════════
# CONSOLE SUMMARY
# ══════════════════════════════════════════════════════════════════════════════

def print_summary(symbol, df, spot):
    a  = aggregate(df)
    tg = a["GEX_net"].sum()
    tv = a["VannEX"].sum()
    tc = a["CharmEX"].sum()
    print(f"\n{'='*58}")
    print(f"  {symbol}  |  Spot ${spot:.2f}  |  OI {a['oi'].sum():,.0f}")
    print(f"{'='*58}")
    print(f"  Net GEX     ${tg/1e9:+.3f}B  "
          f"{'POSITIVE' if tg > 0 else 'NEGATIVE'}")
    print(f"  Net VannEX  {tv/1e3:+.0f}K")
    print(f"  Net CharmEX {tc/1e6:+.4f}M")
    print()

# ══════════════════════════════════════════════════════════════════════════════
# STYLING HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _style(ax):
    ax.set_facecolor(C["panel"])
    for sp in ax.spines.values(): sp.set_color(C["border"])
    ax.tick_params(colors=C["subtext"], labelsize=8, length=2, width=0.5)
    ax.xaxis.label.set_color(C["subtext"])
    ax.yaxis.label.set_color(C["subtext"])
    ax.grid(color=C["grid"], linewidth=0.4, linestyle="-", zorder=0)
    ax.set_axisbelow(True)

def _title(ax, text):
    ax.set_title(text, color=C["text"], fontsize=10,
                 fontweight="bold", pad=10, loc="left",
                 fontfamily="monospace")

def _legend(ax, loc="upper right"):
    ax.legend(fontsize=8, loc=loc, facecolor=C["panel"],
              edgecolor=C["border"], labelcolor=C["text"], framealpha=0.92)

def _fill_signed(ax, x, y, pos_color, neg_color, alpha=0.15):
    ax.fill_between(x, y, 0, where=(y >= 0), interpolate=True,
                    alpha=alpha, color=pos_color, zorder=2)
    ax.fill_between(x, y, 0, where=(y <= 0), interpolate=True,
                    alpha=alpha, color=neg_color, zorder=2)

def _clip_ymx(vals, pct=95, min_val=0.001):
    """
    Scale Y axis to the Nth percentile of absolute values.
    Prevents a single outlier spike from compressing the rest of the chart.
    """
    nonzero = np.abs(vals[vals != 0])
    if len(nonzero) == 0:
        return min_val
    return max(np.percentile(nonzero, pct) * 2.2, min_val)

def _fmt_vanna(x, _):
    if abs(x) >= 1e6: return f"{x/1e6:.1f}M"
    if abs(x) >= 1e3: return f"{x/1e3:.0f}K"
    return f"{x:.0f}"

def _fmt_charm(x, _):
    if abs(x) >= 1e6: return f"{x/1e6:.2f}M"
    if abs(x) >= 1e3: return f"{x/1e3:.1f}K"
    return f"{x:.4f}"

# ══════════════════════════════════════════════════════════════════════════════
# GEX CHART
# ══════════════════════════════════════════════════════════════════════════════

def draw_gex(ax, agg, spot, symbol):
    _style(ax)

    # 50 strikes nearest to spot
    plot_agg = (agg.copy()
                .assign(dist=(agg["strike"] - spot).abs())
                .nsmallest(50, "dist")
                .sort_values("strike"))

    strikes = plot_agg["strike"].values
    # Scale to K for readable axis labels
    call_v  = plot_agg["GEX_call"].values / 1e3
    put_v   = plot_agg["GEX_put"].values  / 1e3
    net_v   = plot_agg["GEX_net"].values  / 1e3

    n     = len(strikes)
    bar_h = ((strikes.max() - strikes.min()) / n * 0.75) if n > 1 else 0.40

    ax.barh(strikes, put_v,  height=bar_h, color=C["put"],  alpha=0.80,
            label="Put Gamma",  linewidth=0, zorder=2)
    ax.barh(strikes, call_v, height=bar_h, color=C["call"], alpha=0.80,
            label="Call Gamma", linewidth=0, zorder=2)
    net_colors = [C["net_pos"] if v >= 0 else C["net_neg"] for v in net_v]
    ax.barh(strikes, net_v, height=bar_h,
            color=net_colors, alpha=1.0, linewidth=0, zorder=5)
    ax.plot([], [], color=C["net_pos"], linewidth=4, label="Net Gamma +")
    ax.plot([], [], color=C["net_neg"], linewidth=4, label="Net Gamma -")

    ax.axvline(0, color=C["zero"], linewidth=1.0, zorder=3)
    ax.axhline(spot, color=C["spot"], linewidth=1.0,
               linestyle="--", alpha=0.9, zorder=6)

    xmax = max(call_v.max(), abs(put_v.min()), abs(net_v).max()) * 1.18
    if xmax == 0: xmax = 1
    ax.set_xlim(-xmax, xmax)
    ax.set_ylim(strikes.min() - bar_h, strikes.max() + bar_h)
    ax.text(xmax * 0.97, spot, f" ${spot:.2f}", color=C["spot"],
            fontsize=8, va="center", fontweight="bold", ha="right", zorder=7)

    pos = plot_agg[plot_agg["GEX_net"] > 0]["strike"]
    neg = plot_agg[plot_agg["GEX_net"] < 0]["strike"]
    if not pos.empty and not neg.empty:
        flip = (pos.min() + neg.max()) / 2
        ax.axhline(flip, color=C["subtext"], linewidth=0.6,
                   linestyle=":", alpha=0.5, zorder=3)
        ax.text(-xmax * 0.96, flip + bar_h * 0.6,
                f"flip ${flip:.0f}", color=C["subtext"], fontsize=7.5)

    ax.xaxis.set_major_formatter(mticker.FuncFormatter(
        lambda x, _: f"{x/1e3:.0f}M" if abs(x) >= 1e3
                     else f"{x:.0f}K"))
    ax.set_xlabel("Gamma", color=C["subtext"], fontsize=8)
    ax.set_ylabel("Strike", color=C["subtext"], fontsize=8)
    _title(ax, f"Gamma Exposure By Strike  -  {symbol}")
    _legend(ax, "upper right")

# ══════════════════════════════════════════════════════════════════════════════
# VANNA CHART
# Raw values stored in VannEX column are: sign * vanna * OI * 100
# These are in raw greek units (not dollar-weighted).
# At $630 strike with heavy put OI this produces large positive values ~30M.
# We display in K units on the Y axis.
# ══════════════════════════════════════════════════════════════════════════════

def draw_vanna(ax, agg, spot, symbol, split):
    _style(ax)
    strikes = agg["strike"].values

    # Narrow x-axis to spot +/- 50 for readability
    xlo = spot - 50
    xhi = spot + 50

    ax.axhline(0, color=C["zero"], linewidth=0.8, zorder=3)

    if split:
        # Display in M units
        cv = gaussian_filter1d(agg["VannEX_call"].values / 1e6, sigma=0.5)
        pv = gaussian_filter1d(agg["VannEX_put"].values  / 1e6, sigma=0.5)
        ax.plot(strikes, cv, color=C["vanna_call"], linewidth=2.0,
                label="Call Vanna", zorder=4)
        ax.plot(strikes, pv, color=C["vanna_put"],  linewidth=2.0,
                label="Put Vanna",  zorder=4)
        ax.fill_between(strikes, cv, 0, alpha=0.12,
                        color=C["vanna_call"], zorder=2)
        ax.fill_between(strikes, pv, 0, alpha=0.12,
                        color=C["vanna_put"],  zorder=2)
        all_v = np.concatenate([cv, pv])
        for vals, col in [(cv, C["vanna_call"]), (pv, C["vanna_put"])]:
            if len(vals):
                idx = int(np.argmax(np.abs(vals)))
                ax.annotate(f"${strikes[idx]:.0f}",
                            xy=(strikes[idx], vals[idx]), color=col,
                            fontsize=7.5, fontweight="bold",
                            xytext=(0, 7), textcoords="offset points",
                            ha="center", zorder=6)
    else:
        # Display in M units
        nv     = agg["VannEX"].values / 1e6
        nv_s   = gaussian_filter1d(nv, sigma=0.5)
        all_v  = nv
        ax.plot(strikes, nv_s, color=C["vanna_net"], linewidth=2.2,
                label="Vanna", zorder=4)
        _fill_signed(ax, strikes, nv_s, C["net_pos"], C["net_neg"])
        if len(nv):
            idx = int(np.argmax(np.abs(nv)))
            ax.annotate(f"${strikes[idx]:.0f}",
                        xy=(strikes[idx], nv[idx]),
                        color=C["vanna_net"], fontsize=7.5, fontweight="bold",
                        xytext=(0, 7), textcoords="offset points",
                        ha="center", zorder=6)

    # Clip Y axis to 95th percentile so outlier spikes don't compress the chart
    ymx = _clip_ymx(all_v)
    ax.set_ylim(-ymx, ymx)
    ax.set_xlim(xlo, xhi)

    ax.axvline(spot, color=C["spot"], linewidth=1.0,
               linestyle="--", alpha=0.85, zorder=5)
    ax.text(spot, ymx * 0.88, f"${spot:.2f}", color=C["spot"],
            fontsize=8, ha="center", fontweight="bold", zorder=6)

    ax.yaxis.set_major_formatter(mticker.FuncFormatter(
            lambda x, _: f"{x:.0f}M"
        ))
    ax.set_xlabel("Strike",  color=C["subtext"], fontsize=8)
    ax.set_ylabel("Vanna (M)", color=C["subtext"], fontsize=8)
    _title(ax, f"{'Vanna Exposure' if split else 'Net Vanna Exposure'}  -  {symbol}")
    _legend(ax, "upper left")

# ══════════════════════════════════════════════════════════════════════════════
# CHARM CHART
# Raw values stored in CharmEX column are: sign * charm * OI * 100
# Displayed in M units on Y axis.
# ══════════════════════════════════════════════════════════════════════════════

def draw_charm(ax, agg, spot, symbol, split):
    _style(ax)
    strikes = agg["strike"].values

    xlo = spot - 50
    xhi = spot + 50

    ax.axhline(0, color=C["zero"], linewidth=0.8, zorder=3)

    if split:
        cc    = gaussian_filter1d(agg["CharmEX_call"].values / 1e6, sigma=0.5)
        pc    = gaussian_filter1d(agg["CharmEX_put"].values  / 1e6, sigma=0.5)
        ax.plot(strikes, cc, color=C["charm_call"], linewidth=2.0,
                label="Call Charm", zorder=4)
        ax.plot(strikes, pc, color=C["charm_put"],  linewidth=2.0,
                label="Put Charm",  zorder=4)
        ax.fill_between(strikes, cc, 0, alpha=0.12,
                        color=C["charm_call"], zorder=2)
        ax.fill_between(strikes, pc, 0, alpha=0.12,
                        color=C["charm_put"],  zorder=2)
        all_v = np.concatenate([cc, pc])
        for vals, col in [(cc, C["charm_call"]), (pc, C["charm_put"])]:
            if len(vals):
                idx = int(np.argmax(np.abs(vals)))
                ax.annotate(f"${strikes[idx]:.0f}",
                            xy=(strikes[idx], vals[idx]), color=col,
                            fontsize=7.5, fontweight="bold",
                            xytext=(0, 7), textcoords="offset points",
                            ha="center", zorder=6)
    else:
        nc    = agg["CharmEX"].values / 1e6
        nc_s  = gaussian_filter1d(nc, sigma=0.5)
        all_v = nc
        ax.plot(strikes, nc_s, color=C["charm_net"], linewidth=2.2,
                label="Charm", zorder=4)
        _fill_signed(ax, strikes, nc_s, C["net_pos"], C["net_neg"])
        if len(nc):
            idx = int(np.argmax(np.abs(nc)))
            ax.annotate(f"${strikes[idx]:.0f}",
                        xy=(strikes[idx], nc[idx]),
                        color=C["charm_net"], fontsize=7.5, fontweight="bold",
                        xytext=(0, 7), textcoords="offset points",
                        ha="center", zorder=6)

    ymx = _clip_ymx(all_v)
    ax.set_ylim(-ymx, ymx)
    ax.set_xlim(xlo, xhi)

    ax.axvline(spot, color=C["spot"], linewidth=1.0,
               linestyle="--", alpha=0.85, zorder=5)
    ax.text(spot, ymx * 0.88, f"${spot:.2f}", color=C["spot"],
            fontsize=8, ha="center", fontweight="bold", zorder=6)

    ax.yaxis.set_major_formatter(mticker.FuncFormatter(
        lambda x, _: f"{x*1000:.1f}K" if abs(x) < 1 else f"{x:.1f}M"
    ))
    ax.set_xlabel("Strike",  color=C["subtext"], fontsize=8)
    ax.set_ylabel("Charm (M)", color=C["subtext"], fontsize=8)
    _title(ax, f"{'Charm Exposure' if split else 'Net Charm Exposure'}  -  {symbol}")
    _legend(ax, "upper left")

# ══════════════════════════════════════════════════════════════════════════════
# TKINTER DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

def launch_dashboard(all_data):
    root = tk.Tk()
    root.title("Options Greeks Analyzer")
    root.configure(bg=C["bg"])
    root.state("zoomed")

    sw  = root.winfo_screenwidth()
    sh  = root.winfo_screenheight()
    dpi = 96

    sym_var     = tk.StringVar(value=list(all_data.keys())[0])
    vanna_split = tk.BooleanVar(value=False)
    charm_split = tk.BooleanVar(value=False)

    # Control bar
    ctrl = tk.Frame(root, bg=C["ctrl"], pady=7, padx=14)
    ctrl.pack(side="top", fill="x")

    tk.Label(ctrl, text="OPTIONS  GREEKS  ANALYZER",
             fg=C["text"], bg=C["ctrl"],
             font=("Courier New", 11, "bold")).pack(side="left", padx=(0, 20))

    def div():
        tk.Frame(ctrl, bg=C["border"], width=1).pack(
            side="left", fill="y", padx=10, pady=4)

    tk.Label(ctrl, text="SYMBOL", fg=C["subtext"], bg=C["ctrl"],
             font=("Courier New", 7)).pack(side="left", padx=(0, 4))

    sty = ttk.Style()
    sty.theme_use("clam")
    sty.configure("D.TCombobox",
        fieldbackground=C["btn_off"], background=C["btn_off"],
        foreground=C["text"], selectbackground=C["btn_on"],
        selectforeground=C["text"], bordercolor=C["border"],
        arrowcolor=C["subtext"])
    sym_cb = ttk.Combobox(ctrl, textvariable=sym_var,
                          values=list(all_data.keys()),
                          state="readonly", width=5,
                          style="D.TCombobox",
                          font=("Courier New", 10))
    sym_cb.pack(side="left", padx=(0, 6))
    div()

    def make_toggle(label, var):
        tk.Label(ctrl, text=label, fg=C["subtext"], bg=C["ctrl"],
                 font=("Courier New", 7)).pack(side="left", padx=(0, 4))
        dv  = tk.StringVar(value="NET")
        btn = tk.Button(ctrl, textvariable=dv,
                        bg=C["btn_off"], fg=C["text"],
                        activebackground=C["btn_on"],
                        activeforeground=C["text"],
                        relief="flat",
                        highlightbackground=C["border"],
                        highlightthickness=1,
                        font=("Courier New", 9, "bold"),
                        cursor="hand2", padx=14, pady=3)
        btn.pack(side="left", padx=(0, 4))
        def toggle():
            var.set(not var.get())
            dv.set("SPLIT" if var.get() else "NET")
            btn.config(bg=C["btn_on"] if var.get() else C["btn_off"])
            render()
        btn.config(command=toggle)

    make_toggle("VANNA", vanna_split)
    div()
    make_toggle("CHARM", charm_split)
    div()

    live = CLIENT_ID != "YOUR_CLIENT_ID"
    tk.Label(ctrl,
             text="LIVE" if live else "DEMO",
             fg=C["live"] if live else C["demo"], bg=C["ctrl"],
             font=("Courier New", 9, "bold")).pack(side="right", padx=10)
    tk.Label(ctrl, text="Ctrl+Scroll: Zoom  |  R: Reset",
             fg=C["subtext"], bg=C["ctrl"],
             font=("Courier New", 7)).pack(side="right", padx=10)

    tk.Frame(root, bg=C["border"], height=1).pack(fill="x")

    # Figure layout: GEX left 40%, Vanna+Charm stacked right 60%
    fig_w = sw / dpi
    fig_h = (sh - 52) / dpi
    fig   = plt.Figure(figsize=(fig_w, fig_h), facecolor=C["bg"], dpi=dpi)

    outer = gridspec.GridSpec(1, 2, figure=fig,
                              left=0.05, right=0.975,
                              top=0.93,  bottom=0.07,
                              wspace=0.28,
                              width_ratios=[1, 1.5])
    ax_gex   = fig.add_subplot(outer[0, 0])
    right    = outer[0, 1].subgridspec(2, 1, hspace=0.42)
    ax_vanna = fig.add_subplot(right[0, 0])
    ax_charm = fig.add_subplot(right[1, 0])

    canvas = FigureCanvasTkAgg(fig, master=root)
    cw     = canvas.get_tk_widget()
    cw.pack(fill="both", expand=True)

    # Hover tooltip — shows nearest datapoint Strike/Value and cursor position
    tooltip = tk.Label(root, text="", bg="#1a1a2e", fg=C["text"],
                       font=("Courier New", 8), relief="flat",
                       borderwidth=1, padx=8, pady=5, justify="left")

    # Store line data per axis for nearest-point lookup
    _line_data = {}

    def _store_line(ax, x_vals, y_vals):
        _line_data[id(ax)] = {
            "x": np.array(x_vals),
            "y": np.array(y_vals),
        }

    def _fmt_tip(v):
        if abs(v) >= 1e6:  return f"{v/1e6:+.3f}M"
        if abs(v) >= 1e3:  return f"{v/1e3:+.1f}K"
        return f"{v:+.4f}"

    def on_hover(event):
        if event.inaxes is None:
            tooltip.place_forget()
            return
        ax = event.inaxes
        x  = event.xdata
        y  = event.ydata
        if x is None or y is None:
            tooltip.place_forget()
            return

        dat = _line_data.get(id(ax))
        if dat is not None and len(dat["x"]) > 0:
            idx  = int(np.argmin(np.abs(dat["x"] - x)))
            nx   = dat["x"][idx]
            ny   = dat["y"][idx]
            text = (f"Strike : ${nx:.0f}\n"
                    f"Value  : {_fmt_tip(ny)}\n"
                    f"Cursor : {_fmt_tip(y)}")
        else:
                    tooltip.place_forget()
                    return
        tooltip.config(text=text)

        ptr_x = root.winfo_pointerx() - root.winfo_rootx()
        ptr_y = root.winfo_pointery() - root.winfo_rooty()
        wx = min(max(ptr_x + 15, 5), root.winfo_width()  - 160)
        wy = min(max(ptr_y - 65,  5), root.winfo_height() - 80)
        tooltip.place(x=wx, y=wy)
        tooltip.lift()

    fig.canvas.mpl_connect("motion_notify_event", on_hover)

    def render(*_):
        sym      = sym_var.get()
        df, spot = all_data[sym]
        agg      = aggregate(df)

        for ax in [ax_gex, ax_vanna, ax_charm]:
            ax.clear()

        draw_gex(ax_gex, agg, spot, sym)

        # Store line data for hover (in same units as draw functions use)
        nv = agg["VannEX"].values  / 1e6   # M units, matches draw_vanna
        nc = agg["CharmEX"].values / 1e6   # M units, matches draw_charm
        _store_line(ax_vanna, agg["strike"].values, nv)
        _store_line(ax_charm, agg["strike"].values, nc)

        draw_vanna(ax_vanna, agg, spot, sym, vanna_split.get())
        draw_charm(ax_charm, agg, spot, sym, charm_split.get())

        ts = datetime.datetime.now().strftime("%H:%M:%S")
        fig.suptitle(f"{sym}   Spot ${spot:.2f}   {ts}",
                     color=C["subtext"], fontsize=8.5,
                     x=0.5, y=0.975, fontfamily="monospace")
        canvas.draw()
        fig.savefig("dashboard.png", dpi=dpi,
                    bbox_inches="tight", facecolor=C["bg"])

    sym_cb.bind("<<ComboboxSelected>>", render)

    zoom = [1.0]; base_w = [sw]; base_h = [sh - 52]

    def on_scroll(event):
        if not (event.state & 0x4): return
        zoom[0] = max(0.4, min(3.5,
                               zoom[0] * (0.88 if event.delta > 0 else 1.12)))
        nw = int(base_w[0] * zoom[0])
        nh = int(base_h[0] * zoom[0])
        fig.set_size_inches(nw / dpi, nh / dpi)
        cw.config(width=nw, height=nh)
        canvas.draw()

    def on_key(event):
        if event.keysym.lower() == "r":
            zoom[0] = 1.0
            fig.set_size_inches(base_w[0] / dpi, base_h[0] / dpi)
            cw.config(width=base_w[0], height=base_h[0])
            render()

    root.bind("<MouseWheel>", on_scroll)
    root.bind("<Key>", on_key)
    render()
    root.mainloop()

# ══════════════════════════════════════════════════════════════════════════════
# DEMO DATA
# ══════════════════════════════════════════════════════════════════════════════

def generate_demo_chain(spot, symbol):
    np.random.seed({"SPY": 42, "QQQ": 7, "DIA": 13}.get(symbol, 0))
    rows = []
    r    = RISK_FREE
    for dte in [3, 7, 14, 21, 28, 45]:
        T  = dte / 365
        lo = round(spot * (1 - STRIKE_PCT))
        hi = round(spot * (1 + STRIKE_PCT))
        for K in np.arange(lo, hi + 1, 1.0):
            for side, call in [("call", True), ("put", False)]:
                mn    = np.log(K / spot)
                sigma = max(0.10, 0.28 + abs(mn)*0.4 + (-0.3*mn)
                            + np.random.normal(0, 0.01))
                atm_w = np.exp(-((K-spot)**2) / (2*(spot*0.03)**2))
                oi    = int(np.random.poisson(
                    8000 * atm_w * (1.4 if not call else 1.0)))
                if oi < 10: continue
                try:
                    g  = calc_gamma(spot, K, T, r, sigma)
                    va = calc_vanna(spot, K, T, r, sigma)
                    ch = calc_charm(spot, K, T, r, sigma, call)
                except: continue
                mult = oi * 100
                sign = 1 if call else -1
                rows.append({
                    "strike":       round(K, 2),
                    "type":         side,
                    "dte":          dte,
                    "oi":           oi,
                    "GEX_call":     g  * mult * spot if call     else 0,
                    "GEX_put":     -g  * mult * spot if not call else 0,
                    "VannEX":       sign * va * mult,
                    "VannEX_call":  va * mult         if call     else 0,
                    "VannEX_put":  -va * mult         if not call else 0,
                    "CharmEX":      sign * ch * mult,
                    "CharmEX_call": ch * mult         if call     else 0,
                    "CharmEX_put": -ch * mult         if not call else 0,
                })
    return pd.DataFrame(rows)

# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

DEMO_SPOTS = {"SPY": 650.35, "QQQ": 560.80, "DIA": 463.19}

def main():
    demo = (CLIENT_ID == "YOUR_CLIENT_ID")

    if demo:
        print("DEMO mode - add credentials to .env for live data\n")
        all_data = {}
        for sym in SYMBOLS:
            spot          = DEMO_SPOTS[sym]
            df            = generate_demo_chain(spot, sym)
            all_data[sym] = (df, spot)
            print_summary(sym, df, spot)
    else:
        from auth import get_valid_access_token
        token    = get_valid_access_token()
        all_data = {}

        for sym in SYMBOLS:
            print(f"  Fetching {sym}...")
            time.sleep(5)
            try:
                qr = requests.get(
                    f"{SCHWAB_BASE}/quotes",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"symbols": sym},
                    timeout=10,
                )
                qd = qr.json()
                try:
                    inner = qd.get(sym, list(qd.values())[0] if qd else {})
                    spot  = (inner.get("quote", {}).get("lastPrice")
                             or inner.get("lastPrice")
                             or inner.get("mark"))
                except Exception:
                    spot = None
                if not spot:
                    print(f"  No spot price for {sym}: {qd}")
                    continue
                print(f"  {sym} ${spot:.2f}")
                chain = get_options_chain(token, sym, spot)
                df    = parse_chain(chain)
                if df.empty:
                    print(f"  Empty chain for {sym}")
                    continue
                all_data[sym] = (df, spot)
                print_summary(sym, df, spot)
            except Exception as e:
                print(f"  Failed {sym}: {e}")
                continue

    if not all_data:
        print("No data loaded.")
        return

    print("Launching dashboard...")
    launch_dashboard(all_data)


if __name__ == "__main__":
    main()
