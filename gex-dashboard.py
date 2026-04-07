"""
Options Second-Order Greeks Analyzer
Schwab API + Black-Scholes | SPY / QQQ / DIA

Layout:
  Left  (40%) : GEX horizontal bar chart
  Right (60%) : Vanna (top) stacked over Charm (bottom)

Controls:
  Symbol dropdown  -> switch SPY / QQQ / DIA
  DTE filter       -> 0DTE / 0-7 / 0-21 / 0-45
  Expiry selector  -> isolate a single expiration date
  Strike range     -> ±3% / ±5% / ±8% from spot
  Vanna toggle     -> Net / Call+Put split
  Charm toggle     -> Net / Call+Put split
  Ctrl+Scroll      -> zoom entire window
  R                -> reset zoom

Auto-refresh:
  Data refreshes every 5 minutes automatically in live mode.
  Status indicator (●) in control bar:
    Green  = data is fresh
    Red    = fetching in progress
    Yellow = refresh imminent (<30s)
  Countdown timer shows time until next refresh.
"""

from dotenv import load_dotenv
load_dotenv()

import os, time, warnings, datetime, threading
import tkinter as tk
from tkinter import ttk
from concurrent.futures import ThreadPoolExecutor, as_completed

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
STRIKE_PCT    = 0.08
MAX_DTE       = 45

# Auto-refresh interval in seconds (5 minutes)
REFRESH_INTERVAL = 300

# DTE filter options (label -> max DTE)
DTE_FILTERS   = {"0DTE": 0, "0-7": 7, "0-21": 21, "0-45": 45}

# Strike range options (label -> pct from spot)
STRIKE_RANGES = {"+/-3%": 0.03, "+/-5%": 0.05, "+/-8%": 0.08}

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
    "ind_green":  "#22c55e", "ind_red":    "#dc2626",
    "ind_yellow": "#f59e0b",
}

# ══════════════════════════════════════════════════════════════════════════════
# SCHWAB API
# ══════════════════════════════════════════════════════════════════════════════

def fetch_spot(token, symbol):
    """Fetch current spot price for a single symbol."""
    r = requests.get(
        f"{SCHWAB_BASE}/quotes",
        headers={"Authorization": f"Bearer {token}"},
        params={"symbols": symbol},
        timeout=10,
    )
    r.raise_for_status()
    qd = r.json()
    try:
        inner = qd.get(symbol, list(qd.values())[0] if qd else {})
        spot  = (inner.get("quote", {}).get("lastPrice")
                 or inner.get("lastPrice")
                 or inner.get("mark"))
    except Exception:
        spot = None
    return spot


def get_options_chain(token, symbol, spot):
    headers   = {"Authorization": f"Bearer {token}"}
    from_date = datetime.date.today().strftime("%Y-%m-%d")
    to_date   = (datetime.date.today() +
                 datetime.timedelta(days=MAX_DTE)).strftime("%Y-%m-%d")
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
            if r.status_code in [429, 502, 503, 504] and attempt < 2:
                w = (attempt + 1) * 3
                print(f"  {r.status_code} on {symbol} — retry in {w}s...")
                time.sleep(w)
                continue
            raise


def fetch_symbol_live(token, symbol):
    """
    Fetch spot + chain for one symbol.
    A 1s pause between quote and chain avoids back-to-back hits on the same
    symbol. No sleep between symbols — those run concurrently.
    Returns (symbol, spot, chain) or raises on failure.
    """
    spot = fetch_spot(token, symbol)
    if not spot:
        raise ValueError(f"No spot price for {symbol}")
    time.sleep(1)   # brief gap between quote and chain for same symbol
    chain = get_options_chain(token, symbol, spot)
    return symbol, spot, chain


def fetch_all_symbols(token):
    """Fetch all symbols concurrently. Returns dict {sym: (df, spot)}."""
    results = {}
    with ThreadPoolExecutor(max_workers=len(SYMBOLS)) as executor:
        futures = {
            executor.submit(fetch_symbol_live, token, sym): sym
            for sym in SYMBOLS
        }
        for future in as_completed(futures):
            sym = futures[future]
            try:
                symbol, spot, chain = future.result()
                df = parse_chain(chain)
                if not df.empty:
                    results[symbol] = (df, spot)
                    print(f"  {symbol} ${spot:.2f} — {len(df)} rows")
                else:
                    print(f"  {symbol} — empty chain, skipping")
            except Exception as e:
                print(f"  {sym} failed: {e}")
    return results

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
# ══════════════════════════════════════════════════════════════════════════════

def parse_chain(chain, r=RISK_FREE):
    S    = chain["underlyingPrice"]
    rows = []
    for side, exp_map in [("call", chain.get("callExpDateMap", {})),
                           ("put",  chain.get("putExpDateMap",  {}))]:
        call = (side == "call")
        for exp_key, strikes in exp_map.items():
            try:
                exp_date = exp_key.split(":")[0]
                dte      = float(exp_key.split(":")[1])
            except: continue
            if dte > MAX_DTE: continue
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
                    "expiry":       exp_date,
                    "oi":           oi,
                    "GEX_call":     g  * mult * S if call     else 0,
                    "GEX_put":     -g  * mult * S if not call else 0,
                    "VannEX":       sign * va * mult,
                    "VannEX_call":  va * mult      if call     else 0,
                    "VannEX_put":  -va * mult      if not call else 0,
                    "CharmEX":      sign * ch * mult,
                    "CharmEX_call": ch * mult      if call     else 0,
                    "CharmEX_put": -ch * mult      if not call else 0,
                })
    return pd.DataFrame(rows)

# ══════════════════════════════════════════════════════════════════════════════
# FILTER
# ══════════════════════════════════════════════════════════════════════════════

def filter_df(df, spot, dte_label="0-45", expiry="ALL", strike_pct=0.05):
    out = df.copy()
    max_dte = DTE_FILTERS.get(dte_label, 45)
    if dte_label == "0DTE":
        out = out[out["dte"] <= 1]
    else:
        out = out[out["dte"] <= max_dte]
    if expiry != "ALL" and "expiry" in out.columns:
        out = out[out["expiry"] == expiry]
    out = out[((out["strike"] - spot).abs() / spot) <= strike_pct]
    return out

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
    plot_agg = (agg.copy()
                .assign(dist=(agg["strike"] - spot).abs())
                .nsmallest(50, "dist")
                .sort_values("strike"))

    strikes = plot_agg["strike"].values
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
# ══════════════════════════════════════════════════════════════════════════════

def draw_vanna(ax, agg, spot, symbol, split):
    _style(ax)
    strikes = agg["strike"].values
    xlo = spot - 50
    xhi = spot + 50

    ax.axhline(0, color=C["zero"], linewidth=0.8, zorder=3)

    if split:
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
        nv    = agg["VannEX"].values / 1e6
        nv_s  = gaussian_filter1d(nv, sigma=0.5)
        all_v = nv
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

    ymx = _clip_ymx(all_v)
    ax.set_ylim(-ymx, ymx)
    ax.set_xlim(xlo, xhi)

    ax.axvline(spot, color=C["spot"], linewidth=1.0,
               linestyle="--", alpha=0.85, zorder=5)
    ax.text(spot, ymx * 0.88, f"${spot:.2f}", color=C["spot"],
            fontsize=8, ha="center", fontweight="bold", zorder=6)

    ax.yaxis.set_major_formatter(mticker.FuncFormatter(
            lambda x, _: f"{x:.0f}M"))
    ax.set_xlabel("Strike",    color=C["subtext"], fontsize=8)
    ax.set_ylabel("Vanna (M)", color=C["subtext"], fontsize=8)
    _title(ax, f"{'Vanna Exposure' if split else 'Net Vanna Exposure'}  -  {symbol}")
    _legend(ax, "upper left")

# ══════════════════════════════════════════════════════════════════════════════
# CHARM CHART
# ══════════════════════════════════════════════════════════════════════════════

def draw_charm(ax, agg, spot, symbol, split):
    _style(ax)
    strikes = agg["strike"].values
    xlo = spot - 50
    xhi = spot + 50

    ax.axhline(0, color=C["zero"], linewidth=0.8, zorder=3)

    if split:
        cc  = gaussian_filter1d(agg["CharmEX_call"].values / 1e6, sigma=0.5)
        pc  = gaussian_filter1d(agg["CharmEX_put"].values  / 1e6, sigma=0.5)
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
        lambda x, _: f"{x*1000:.1f}K" if abs(x) < 1 else f"{x:.1f}M"))
    ax.set_xlabel("Strike",    color=C["subtext"], fontsize=8)
    ax.set_ylabel("Charm (M)", color=C["subtext"], fontsize=8)
    _title(ax, f"{'Charm Exposure' if split else 'Net Charm Exposure'}  -  {symbol}")
    _legend(ax, "upper left")

# ══════════════════════════════════════════════════════════════════════════════
# TKINTER DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

def launch_dashboard(all_data, demo=False):
    """
    all_data : dict {symbol: (df, spot)}
    demo     : True if running without live credentials
    """
    root = tk.Tk()
    root.title("Options Greeks Analyzer")
    root.configure(bg=C["bg"])
    root.state("zoomed")

    sw  = root.winfo_screenwidth()
    sh  = root.winfo_screenheight()
    dpi = 96

    # Shared mutable data store — updated by background refresh thread
    _data_lock = threading.Lock()
    _live_data = {"data": dict(all_data)}   # {sym: (df, spot)}

    sym_var     = tk.StringVar(value=list(all_data.keys())[0])
    vanna_split = tk.BooleanVar(value=False)
    charm_split = tk.BooleanVar(value=False)
    dte_var     = tk.StringVar(value="0-45")
    expiry_var  = tk.StringVar(value="ALL")
    strike_var  = tk.StringVar(value="+/-5%")

    # ── Control bar ────────────────────────────────────────────────────────────
    ctrl = tk.Frame(root, bg=C["ctrl"], pady=7, padx=14)
    ctrl.pack(side="top", fill="x")

    tk.Label(ctrl, text="OPTIONS  GREEKS  ANALYZER",
             fg=C["text"], bg=C["ctrl"],
             font=("Courier New", 11, "bold")).pack(side="left", padx=(0, 20))

    def div():
        tk.Frame(ctrl, bg=C["border"], width=1).pack(
            side="left", fill="y", padx=10, pady=4)

    sty = ttk.Style()
    sty.theme_use("clam")
    sty.configure("D.TCombobox",
        fieldbackground=C["btn_off"], background=C["btn_off"],
        foreground=C["text"], selectbackground=C["btn_on"],
        selectforeground=C["text"], bordercolor=C["border"],
        arrowcolor=C["subtext"])

    # Symbol
    tk.Label(ctrl, text="SYMBOL", fg=C["subtext"], bg=C["ctrl"],
             font=("Courier New", 7)).pack(side="left", padx=(0, 4))
    sym_cb = ttk.Combobox(ctrl, textvariable=sym_var,
                          values=list(all_data.keys()),
                          state="readonly", width=5,
                          style="D.TCombobox",
                          font=("Courier New", 10))
    sym_cb.pack(side="left", padx=(0, 6))
    div()

    # DTE filter
    tk.Label(ctrl, text="DTE", fg=C["subtext"], bg=C["ctrl"],
             font=("Courier New", 7)).pack(side="left", padx=(0, 4))
    dte_cb = ttk.Combobox(ctrl, textvariable=dte_var,
                          values=list(DTE_FILTERS.keys()),
                          state="readonly", width=6,
                          style="D.TCombobox",
                          font=("Courier New", 10))
    dte_cb.pack(side="left", padx=(0, 6))
    div()

    # Expiry selector
    tk.Label(ctrl, text="EXPIRY", fg=C["subtext"], bg=C["ctrl"],
             font=("Courier New", 7)).pack(side="left", padx=(0, 4))
    expiry_cb = ttk.Combobox(ctrl, textvariable=expiry_var,
                             values=["ALL"],
                             state="readonly", width=11,
                             style="D.TCombobox",
                             font=("Courier New", 10))
    expiry_cb.pack(side="left", padx=(0, 6))
    div()

    # Strike range
    tk.Label(ctrl, text="RANGE", fg=C["subtext"], bg=C["ctrl"],
             font=("Courier New", 7)).pack(side="left", padx=(0, 4))
    range_cb = ttk.Combobox(ctrl, textvariable=strike_var,
                            values=list(STRIKE_RANGES.keys()),
                            state="readonly", width=6,
                            style="D.TCombobox",
                            font=("Courier New", 10))
    range_cb.pack(side="left", padx=(0, 6))
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

    # ── Right side of control bar: status indicator + countdown ───────────────
    # Live/Demo badge
    tk.Label(ctrl,
             text="LIVE" if not demo else "DEMO",
             fg=C["live"] if not demo else C["demo"], bg=C["ctrl"],
             font=("Courier New", 9, "bold")).pack(side="right", padx=(10, 4))

    tk.Label(ctrl, text="Ctrl+Scroll: Zoom  |  R: Reset",
             fg=C["subtext"], bg=C["ctrl"],
             font=("Courier New", 7)).pack(side="right", padx=10)

    # Only show refresh indicator in live mode
    if not demo:
        div_r = tk.Frame(ctrl, bg=C["border"], width=1)
        div_r.pack(side="right", fill="y", padx=10, pady=4)

        # Countdown label  e.g. "next 4:52"
        countdown_var = tk.StringVar(value="")
        tk.Label(ctrl, textvariable=countdown_var,
                 fg=C["subtext"], bg=C["ctrl"],
                 font=("Courier New", 8)).pack(side="right", padx=(0, 6))

        # Status dot  ●
        ind_color = tk.StringVar(value=C["ind_green"])
        ind_label = tk.Label(ctrl, text="●",
                             fg=C["ind_green"], bg=C["ctrl"],
                             font=("Courier New", 14))
        ind_label.pack(side="right", padx=(0, 2))

        def _set_indicator(state: str):
            """state: 'green' | 'red' | 'yellow'"""
            color = {"green": C["ind_green"],
                     "red":   C["ind_red"],
                     "yellow": C["ind_yellow"]}[state]
            ind_label.config(fg=color)

    tk.Frame(root, bg=C["border"], height=1).pack(fill="x")

    # ── Figure layout ──────────────────────────────────────────────────────────
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

    # Hover tooltip
    tooltip = tk.Label(root, text="", bg="#1a1a2e", fg=C["text"],
                       font=("Courier New", 8), relief="flat",
                       borderwidth=1, padx=8, pady=5, justify="left")

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

    # ── Render ──────────────────────────────────────────────────────────────────

    def _update_expiry_list(*_):
        sym      = sym_var.get()
        with _data_lock:
            df, spot = _live_data["data"][sym]
        dte_lbl  = dte_var.get()
        filtered = filter_df(df, spot, dte_label=dte_lbl,
                             expiry="ALL",
                             strike_pct=STRIKE_RANGES.get(strike_var.get(), 0.05))
        if "expiry" in filtered.columns:
            expiries = sorted(filtered["expiry"].unique().tolist())
        else:
            expiries = []
        expiry_cb["values"] = ["ALL"] + expiries
        if expiry_var.get() not in ["ALL"] + expiries:
            expiry_var.set("ALL")

    def render(*_):
        sym = sym_var.get()
        with _data_lock:
            df, spot = _live_data["data"][sym]

        dte_lbl    = dte_var.get()
        expiry_sel = expiry_var.get()
        spct       = STRIKE_RANGES.get(strike_var.get(), 0.05)

        fdf = filter_df(df, spot,
                        dte_label=dte_lbl,
                        expiry=expiry_sel,
                        strike_pct=spct)

        if fdf.empty:
            for ax in [ax_gex, ax_vanna, ax_charm]:
                ax.clear()
                ax.set_facecolor(C["panel"])
                ax.text(0.5, 0.5, "No data for selected filters",
                        transform=ax.transAxes, ha="center", va="center",
                        color=C["subtext"], fontsize=11)
            canvas.draw()
            return

        agg = aggregate(fdf)

        expiry_lbl = f"  |  {expiry_sel}" if expiry_sel != "ALL" else ""
        filter_lbl = f"DTE: {dte_lbl}  Range: {strike_var.get()}{expiry_lbl}"

        for ax in [ax_gex, ax_vanna, ax_charm]:
            ax.clear()

        draw_gex(ax_gex, agg, spot, sym)

        nv = agg["VannEX"].values  / 1e6
        nc = agg["CharmEX"].values / 1e6
        _store_line(ax_vanna, agg["strike"].values, nv)
        _store_line(ax_charm, agg["strike"].values, nc)

        draw_vanna(ax_vanna, agg, spot, sym, vanna_split.get())
        draw_charm(ax_charm, agg, spot, sym, charm_split.get())

        ts = datetime.datetime.now().strftime("%H:%M:%S")
        fig.suptitle(f"{sym}   Spot ${spot:.2f}   {ts}   |   {filter_lbl}",
                     color=C["subtext"], fontsize=8.5,
                     x=0.5, y=0.975, fontfamily="monospace")
        canvas.draw()
        fig.savefig("dashboard.png", dpi=dpi,
                    bbox_inches="tight", facecolor=C["bg"])

    sym_cb.bind("<<ComboboxSelected>>", lambda e: [_update_expiry_list(), render()])
    dte_cb.bind("<<ComboboxSelected>>", lambda e: [_update_expiry_list(), render()])
    expiry_cb.bind("<<ComboboxSelected>>", render)
    range_cb.bind("<<ComboboxSelected>>", render)

    _update_expiry_list()

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

    # ── Auto-refresh (live mode only) ──────────────────────────────────────────

    if not demo:
        _refresh_state = {
            "last_refresh": time.time(),   # timestamp of last successful fetch
            "fetching":     False,
        }

        def _do_refresh():
            """Background thread: fetch all symbols, update shared data, re-render."""
            _refresh_state["fetching"] = True
            root.after(0, lambda: _set_indicator("red"))

            try:
                from auth import get_valid_access_token
                token    = get_valid_access_token(silent=True)
                new_data = fetch_all_symbols(token)

                if new_data:
                    with _data_lock:
                        _live_data["data"].update(new_data)
                    _refresh_state["last_refresh"] = time.time()
                    # Re-render on the main thread
                    root.after(0, _update_expiry_list)
                    root.after(0, render)
                    root.after(0, lambda: _set_indicator("green"))
                else:
                    # Fetch returned nothing — stay red briefly then go green
                    root.after(0, lambda: _set_indicator("green"))

            except Exception as e:
                print(f"  Auto-refresh failed: {e}")
                root.after(0, lambda: _set_indicator("green"))
            finally:
                _refresh_state["fetching"] = False

        def _tick():
            """
            Called every second by root.after.
            Manages the countdown display and triggers refresh when due.
            """
            if not _refresh_state["fetching"]:
                elapsed   = time.time() - _refresh_state["last_refresh"]
                remaining = max(0, REFRESH_INTERVAL - elapsed)
                m  = int(remaining) // 60
                s  = int(remaining) % 60
                countdown_var.set(f"next {m}:{s:02d}")

                # Warn when <30s until refresh
                if remaining <= 30:
                    _set_indicator("yellow")

                # Trigger refresh
                if remaining <= 0:
                    t = threading.Thread(target=_do_refresh, daemon=True)
                    t.start()
            else:
                countdown_var.set("fetching...")

            root.after(1000, _tick)

        _tick()

    render()
    root.mainloop()

# ══════════════════════════════════════════════════════════════════════════════
# DEMO DATA
# ══════════════════════════════════════════════════════════════════════════════

def generate_demo_chain(spot, symbol):
    np.random.seed({"SPY": 42, "QQQ": 7, "DIA": 13}.get(symbol, 0))
    rows = []
    r    = RISK_FREE
    today = datetime.date.today()
    for dte in [0, 3, 7, 14, 21, 28, 45]:
        if dte > MAX_DTE: continue
        T        = max(dte, 0.5) / 365
        exp_date = (today + datetime.timedelta(days=dte)).strftime("%Y-%m-%d")
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
                    "expiry":       exp_date,
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
        print("DEMO mode — add credentials to .env for live data\n")
        all_data = {}
        for sym in SYMBOLS:
            spot          = DEMO_SPOTS[sym]
            df            = generate_demo_chain(spot, sym)
            all_data[sym] = (df, spot)
            print_summary(sym, df, spot)
    else:
        from auth import get_valid_access_token
        token    = get_valid_access_token()
        print("Fetching all symbols concurrently...")
        all_data = fetch_all_symbols(token)
        for sym, (df, spot) in all_data.items():
            print_summary(sym, df, spot)

    if not all_data:
        print("No data loaded.")
        return

    print("Launching dashboard...")
    launch_dashboard(all_data, demo=demo)


if __name__ == "__main__":
    main()
