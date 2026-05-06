"""
Options Second-Order Greeks Analyzer
Schwab API + Black-Scholes | SPY

Tabs:
  CHARTS  : GEX (left) | Vanna + Charm (right)
  MACRO   : Regime badge (top) | Yield curve + data table (middle)
            | Vol Smile (bottom)
  BACKTEST: Historical GEX surface (left) | SPY price chart (right)

Changes from v1:
  - SPY only — symbol dropdown removed, static label
  - MACRO tab replaces VOL SMILE tab
  - Yield curve panel added (Treasury.gov data via db.py)
  - Macro regime badge with plain English signal
  - Backtest flip level bug fixed — uses draw_gex() return value
  - Backtest max pain bug fixed — recomputed from surface data
  - Vol Smile moved inside MACRO tab (bottom panel)
  - Auto-refresh unchanged (5 min)
"""

from dotenv import load_dotenv
load_dotenv()

import os, time, warnings, datetime, threading, json
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
import matplotlib.dates as mdates
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from scipy.stats import norm
from scipy.ndimage import gaussian_filter1d
from tkcalendar import DateEntry
warnings.filterwarnings("ignore")

# ══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════════════════

CLIENT_ID     = os.environ.get("SCHWAB_CLIENT_ID",     "YOUR_CLIENT_ID")
CLIENT_SECRET = os.environ.get("SCHWAB_CLIENT_SECRET", "YOUR_CLIENT_SECRET")
RISK_FREE     = 0.045
SYMBOL        = "SPY"
SCHWAB_BASE   = "https://api.schwabapi.com/marketdata/v1"
STRIKE_PCT    = 0.08
MAX_DTE       = 45
REFRESH_INTERVAL = 300

DTE_FILTERS   = {"0DTE": 0, "0-7": 7, "0-21": 21, "0-45": 45}
STRIKE_RANGES = {"+/-3%": 0.03, "+/-5%": 0.05, "+/-8%": 0.08}

# Yield curve maturity labels and db column names
MATURITIES = [
    ("3M",  "m3"),
    ("6M",  "m6"),
    ("1Y",  "y1"),
    ("2Y",  "y2"),
    ("5Y",  "y5"),
    ("7Y",  "y7"),
    ("10Y", "y10"),
    ("20Y", "y20"),
    ("30Y", "y30"),
]

C = {
    "bg":         "#0d0d0d", "panel":      "#111111",
    "border":     "#222222", "text":       "#dddddd",
    "subtext":    "#555555", "grid":       "#191919",
    "zero":       "#2a2a2a", "spot":       "#17A2B8",
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
    "smile_call": "#FFF669", "smile_put":  "#9B59B6",
    "smile_fill": "#2a1f3d",
    "candle_up":  "#22c55e", "candle_down":"#dc2626",
    # Macro regime colors
    "regime_green":  "#22c55e",
    "regime_yellow": "#f59e0b",
    "regime_orange": "#f97316",
    "regime_red":    "#dc2626",
    # Yield curve
    "curve_today":     "#17A2B8",
    "curve_yesterday": "#333355",
    "curve_danger":    "#dc2626",
    "curve_inversion": "#3a1a1a",
}

CONFIG_FILE = "dashboard_config.json"

def _load_config() -> dict:
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def _save_config(data: dict):
    try:
        existing = _load_config()
        existing.update(data)
        with open(CONFIG_FILE, "w") as f:
            json.dump(existing, f, indent=2)
    except Exception:
        pass

# ══════════════════════════════════════════════════════════════════════════════
# SCHWAB API
# ══════════════════════════════════════════════════════════════════════════════

def fetch_spot(token):
    r = requests.get(
        f"{SCHWAB_BASE}/quotes",
        headers={"Authorization": f"Bearer {token}"},
        params={"symbols": SYMBOL},
        timeout=10,
    )
    r.raise_for_status()
    qd    = r.json()
    inner = qd.get(SYMBOL, list(qd.values())[0] if qd else {})
    return (inner.get("quote", {}).get("lastPrice")
            or inner.get("lastPrice")
            or inner.get("mark"))


def get_options_chain(token, spot):
    headers   = {"Authorization": f"Bearer {token}"}
    from_date = datetime.date.today().strftime("%Y-%m-%d")
    to_date   = (datetime.date.today() +
                 datetime.timedelta(days=MAX_DTE)).strftime("%Y-%m-%d")
    params = {
        "symbol":           SYMBOL,
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
                time.sleep((attempt + 1) * 3)
                continue
            raise


def fetch_vix(token) -> dict | None:
    try:
        r = requests.get(
            f"{SCHWAB_BASE}/quotes",
            headers={"Authorization": f"Bearer {token}"},
            params={"symbols": "$VIX"},
            timeout=10,
        )
        r.raise_for_status()
        qd    = r.json()
        inner = qd.get("$VIX", {})
        quote = inner.get("quote", inner)
        last  = quote.get("lastPrice") or quote.get("mark") or quote.get("closePrice")
        prev  = quote.get("closePrice") or last
        if not last:
            return None
        change     = last - (prev or last)
        change_pct = (change / prev * 100) if prev else 0
        return {"last": last, "prev_close": prev,
                "change": change, "change_pct": change_pct}
    except Exception as e:
        print(f"  VIX fetch failed: {e}")
        return None


def fetch_live_data(token):
    """Fetch SPY chain + VIX concurrently. Returns (df, spot), vix_data."""
    import threading
    results  = [None]
    vix_data = [None]

    def _fetch_spy():
        try:
            spot  = fetch_spot(token)
            if not spot:
                return
            time.sleep(1)
            chain = get_options_chain(token, spot)
            df    = parse_chain(chain)
            if not df.empty:
                results[0] = (df, spot)
                print(f"  {SYMBOL} ${spot:.2f} — {len(df)} rows")
        except Exception as e:
            print(f"  {SYMBOL} failed: {e}")

    def _fetch_vix():
        vix_data[0] = fetch_vix(token)

    t1 = threading.Thread(target=_fetch_spy,  daemon=True)
    t2 = threading.Thread(target=_fetch_vix,  daemon=True)
    t1.start(); t2.start()
    t1.join();  t2.join()

    return results[0], vix_data[0]

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
            except:
                continue
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
                except:
                    continue
                mult = oi * 100
                sign = 1 if call else -1
                rows.append({
                    "strike":       K,
                    "type":         side,
                    "dte":          dte,
                    "expiry":       exp_date,
                    "oi":           oi,
                    "iv_raw":       sigma,
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
# FILTER / AGGREGATE
# ══════════════════════════════════════════════════════════════════════════════

def filter_df(df, spot, dte_label="0-45", expiry="ALL", strike_pct=0.05):
    out     = df.copy()
    max_dte = DTE_FILTERS.get(dte_label, 45)
    if dte_label == "0DTE":
        out = out[out["dte"] <= 1]
    else:
        out = out[out["dte"] <= max_dte]
    if expiry != "ALL" and "expiry" in out.columns:
        out = out[out["expiry"] == expiry]
    out = out[((out["strike"] - spot).abs() / spot) <= strike_pct]
    return out


def aggregate(df):
    cols = ["GEX_call", "GEX_put",
            "VannEX", "VannEX_call", "VannEX_put",
            "CharmEX", "CharmEX_call", "CharmEX_put", "oi"]
    a = (df.groupby("strike")[cols]
           .sum()
           .reset_index()
           .sort_values("strike"))
    a["GEX_net"] = a["GEX_call"] + a["GEX_put"]
    return a


def build_smile_df(df, spot, expiry):
    out = df.copy()
    if expiry != "ALL":
        out = out[out["expiry"] == expiry]
    if out.empty:
        return pd.DataFrame()
    unique_strikes = out["strike"].unique()
    dists          = np.abs(unique_strikes - spot)
    sorted_strikes = unique_strikes[np.argsort(dists)][:40]
    out            = out[out["strike"].isin(sorted_strikes)]
    pivot = (out.pivot_table(
                    index="strike",
                    columns="type",
                    values="iv_raw",
                    aggfunc="mean")
               .reset_index()
               .rename(columns={"call": "call_iv", "put": "put_iv"})
               .sort_values("strike"))
    return pivot.dropna(subset=["call_iv", "put_iv"])


def _calc_max_pain(df: pd.DataFrame) -> float | None:
    if df.empty or "strike" not in df.columns:
        return None
    strikes = df["strike"].unique()
    if len(strikes) == 0:
        return None
    pain  = {}
    calls = df[df["type"] == "call"]
    puts  = df[df["type"] == "put"]
    for s in strikes:
        call_pain = ((s - calls["strike"]).clip(lower=0) * calls["oi"]).sum()
        put_pain  = ((puts["strike"] - s).clip(lower=0)  * puts["oi"]).sum()
        pain[s]   = call_pain + put_pain
    return float(min(pain, key=pain.get))

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

# ══════════════════════════════════════════════════════════════════════════════
# GEX CHART
# ══════════════════════════════════════════════════════════════════════════════

def draw_gex(ax, agg, spot, symbol, max_pain=None):
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
    ax.axhline(spot, color=C["spot"], linewidth=1.2,
               linestyle="--", alpha=0.9, zorder=6)

    xmax = max(call_v.max(), abs(put_v.min()), abs(net_v).max()) * 1.18
    if xmax == 0: xmax = 1
    ax.set_xlim(-xmax, xmax)
    ax.set_ylim(strikes.min() - bar_h, strikes.max() + bar_h)
    ax.text(xmax * 0.97, spot, f" ${spot:.2f}", color=C["spot"],
            fontsize=8, va="center", fontweight="bold", ha="right", zorder=7)

    # Gamma flip — computed from filtered data (source of truth)
    pos = plot_agg[plot_agg["GEX_net"] > 0]["strike"]
    neg = plot_agg[plot_agg["GEX_net"] < 0]["strike"]
    computed_flip = None
    if not pos.empty and not neg.empty:
        computed_flip = (pos.min() + neg.max()) / 2
        ax.axhline(computed_flip, color=C["subtext"], linewidth=0.6,
                   linestyle=":", alpha=0.5, zorder=3)
        ax.text(-xmax * 0.96, computed_flip + bar_h * 0.6,
                f"flip ${computed_flip:.0f}", color=C["subtext"], fontsize=7.5)

    if max_pain is not None:
        y_lo = strikes.min() - bar_h
        y_hi = strikes.max() + bar_h
        if y_lo <= max_pain <= y_hi:
            ax.axhline(max_pain, color=C["net_neg"], linewidth=0.9,
                       linestyle="--", alpha=0.75, zorder=4)
            ax.text(xmax * 0.97, max_pain + bar_h * 0.6,
                    f"max pain ${max_pain:.0f}",
                    color=C["net_neg"], fontsize=7.5, ha="right", zorder=5)

    ax.xaxis.set_major_formatter(mticker.FuncFormatter(
        lambda x, _: f"{x/1e3:.0f}M" if abs(x) >= 1e3 else f"{x:.0f}K"))
    ax.set_xlabel("Gamma", color=C["subtext"], fontsize=8)
    ax.set_ylabel("Strike", color=C["subtext"], fontsize=8)
    _title(ax, f"Gamma Exposure By Strike  -  {symbol}")
    _legend(ax, "upper right")
    return computed_flip   # always return for price chart to consume

# ══════════════════════════════════════════════════════════════════════════════
# VANNA CHART
# ══════════════════════════════════════════════════════════════════════════════

def draw_vanna(ax, agg, spot, symbol, split):
    _style(ax)
    strikes = agg["strike"].values
    xlo = spot - 50; xhi = spot + 50
    ax.axhline(0, color=C["zero"], linewidth=0.8, zorder=3)

    if split:
        cv = gaussian_filter1d(agg["VannEX_call"].values / 1e6, sigma=0.5)
        pv = gaussian_filter1d(agg["VannEX_put"].values  / 1e6, sigma=0.5)
        ax.plot(strikes, cv, color=C["vanna_call"], linewidth=2.0,
                label="Call Vanna", zorder=4)
        ax.plot(strikes, pv, color=C["vanna_put"],  linewidth=2.0,
                label="Put Vanna",  zorder=4)
        ax.fill_between(strikes, cv, 0, alpha=0.12, color=C["vanna_call"], zorder=2)
        ax.fill_between(strikes, pv, 0, alpha=0.12, color=C["vanna_put"],  zorder=2)
        all_v = np.concatenate([cv, pv])
    else:
        nv   = agg["VannEX"].values / 1e6
        nv_s = gaussian_filter1d(nv, sigma=0.5)
        all_v = nv
        ax.plot(strikes, nv_s, color=C["vanna_net"], linewidth=2.2,
                label="Vanna", zorder=4)
        _fill_signed(ax, strikes, nv_s, C["net_pos"], C["net_neg"])

    ymx = _clip_ymx(all_v)
    ax.set_ylim(-ymx, ymx)
    ax.set_xlim(xlo, xhi)
    ax.axvline(spot, color=C["spot"], linewidth=1.2,
               linestyle="--", alpha=0.85, zorder=5)
    ax.text(spot, ymx * 0.88, f"${spot:.2f}", color=C["spot"],
            fontsize=8, ha="center", fontweight="bold", zorder=6)
    ax.yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda x, _: f"{x:.0f}M"))
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
    xlo = spot - 50; xhi = spot + 50
    ax.axhline(0, color=C["zero"], linewidth=0.8, zorder=3)

    if split:
        cc = gaussian_filter1d(agg["CharmEX_call"].values / 1e6, sigma=0.5)
        pc = gaussian_filter1d(agg["CharmEX_put"].values  / 1e6, sigma=0.5)
        ax.plot(strikes, cc, color=C["charm_call"], linewidth=2.0,
                label="Call Charm", zorder=4)
        ax.plot(strikes, pc, color=C["charm_put"],  linewidth=2.0,
                label="Put Charm",  zorder=4)
        ax.fill_between(strikes, cc, 0, alpha=0.12, color=C["charm_call"], zorder=2)
        ax.fill_between(strikes, pc, 0, alpha=0.12, color=C["charm_put"],  zorder=2)
        all_v = np.concatenate([cc, pc])
    else:
        nc   = agg["CharmEX"].values / 1e6
        nc_s = gaussian_filter1d(nc, sigma=0.5)
        all_v = nc
        ax.plot(strikes, nc_s, color=C["charm_net"], linewidth=2.2,
                label="Charm", zorder=4)
        _fill_signed(ax, strikes, nc_s, C["net_pos"], C["net_neg"])

    ymx = _clip_ymx(all_v)
    ax.set_ylim(-ymx, ymx)
    ax.set_xlim(xlo, xhi)
    ax.axvline(spot, color=C["spot"], linewidth=1.2,
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
# VOL SMILE CHART
# ══════════════════════════════════════════════════════════════════════════════

def draw_vol_smile(ax, smile_df, spot, symbol, expiry):
    _style(ax)
    if smile_df.empty:
        ax.text(0.5, 0.5, "No data for selected expiry",
                transform=ax.transAxes, ha="center", va="center",
                color=C["subtext"], fontsize=11)
        return None, None, None

    strikes  = smile_df["strike"].values
    call_iv  = smile_df["call_iv"].values * 100
    put_iv   = smile_df["put_iv"].values  * 100
    call_iv_s = gaussian_filter1d(call_iv, sigma=0.8)
    put_iv_s  = gaussian_filter1d(put_iv,  sigma=0.8)

    ax.fill_between(strikes, call_iv_s, put_iv_s,
                    alpha=0.18, color=C["smile_fill"], zorder=2)
    ax.plot(strikes, call_iv_s, color=C["smile_call"], linewidth=2.2,
            label="Call IV", zorder=4)
    ax.plot(strikes, put_iv_s,  color=C["smile_put"],  linewidth=2.2,
            label="Put IV",  zorder=4)
    ax.axvline(spot, color=C["spot"], linewidth=1.4,
               linestyle="-", alpha=0.9, zorder=5)

    ymax = max(call_iv_s.max(), put_iv_s.max())
    ymin = min(call_iv_s.min(), put_iv_s.min())
    ypad = (ymax - ymin) * 0.12
    ax.set_ylim(max(0, ymin - ypad), ymax + ypad * 2)
    ax.set_xlim(strikes.min(), strikes.max())

    ax.text(spot, ax.get_ylim()[1] * 0.97, f"  ${spot:.2f}",
            color=C["spot"], fontsize=8.5, ha="left",
            fontweight="bold", zorder=6, va="top")

    atm_idx  = int(np.argmin(np.abs(strikes - spot)))
    atm_call = call_iv_s[atm_idx]
    atm_put  = put_iv_s[atm_idx]
    ax.annotate(f"ATM Call {atm_call:.1f}%",
                xy=(strikes[atm_idx], atm_call),
                color=C["smile_call"], fontsize=7.5, fontweight="bold",
                xytext=(6, 6), textcoords="offset points", zorder=7)
    ax.annotate(f"ATM Put {atm_put:.1f}%",
                xy=(strikes[atm_idx], atm_put),
                color=C["smile_put"], fontsize=7.5, fontweight="bold",
                xytext=(6, -14), textcoords="offset points", zorder=7)

    ax.yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda x, _: f"{x:.1f}%"))
    ax.set_xlabel("Strike",             color=C["subtext"], fontsize=9)
    ax.set_ylabel("Implied Volatility", color=C["subtext"], fontsize=9)
    expiry_lbl = expiry if expiry != "ALL" else "All Expiries"
    _title(ax, f"Implied Volatility Smile  -  {symbol}  |  {expiry_lbl}")
    _legend(ax, "upper right")
    return strikes, call_iv_s, put_iv_s

# ══════════════════════════════════════════════════════════════════════════════
# YIELD CURVE CHART
# ══════════════════════════════════════════════════════════════════════════════

def draw_yield_curve(ax, today_curve: dict | None,
                     yesterday_curve: dict | None):
    """
    Plot the Treasury yield curve for today (solid) and yesterday (ghost).
    Annotates the 5% danger zone threshold as a red dashed horizontal.
    Shades any inversion zones (where shorter yield > longer yield).
    """
    _style(ax)

    if today_curve is None:
        ax.text(0.5, 0.5,
                "No yield curve data available.\nRun collector.py to fetch.",
                transform=ax.transAxes, ha="center", va="center",
                color=C["subtext"], fontsize=11)
        _title(ax, "U.S. Treasury Yield Curve")
        return

    # Build x positions and labels
    x_pos    = list(range(len(MATURITIES)))
    x_labels = [m[0] for m in MATURITIES]
    db_keys  = [m[1] for m in MATURITIES]

    today_yields = [today_curve.get(k) for k in db_keys]

    # Filter out None values for plotting
    valid_today = [(x, y) for x, y in zip(x_pos, today_yields) if y is not None]
    if not valid_today:
        ax.text(0.5, 0.5, "Yield curve data incomplete.",
                transform=ax.transAxes, ha="center", va="center",
                color=C["subtext"], fontsize=11)
        return

    vx, vy = zip(*valid_today)

    # Yesterday ghost line
    if yesterday_curve:
        yest_yields = [yesterday_curve.get(k) for k in db_keys]
        valid_yest  = [(x, y) for x, y in zip(x_pos, yest_yields) if y is not None]
        if valid_yest:
            yx, yy = zip(*valid_yest)
            ax.plot(yx, yy, color=C["curve_yesterday"], linewidth=1.5,
                    linestyle="--", alpha=0.6, label="Yesterday", zorder=2)
            ax.fill_between(yx, yy, 0, alpha=0.04,
                            color=C["curve_yesterday"], zorder=1)

    # Today's curve — solid
    ax.plot(vx, vy, color=C["curve_today"], linewidth=2.5,
            label=f"Today ({today_curve.get('date', '')})", zorder=4)
    ax.fill_between(vx, vy, 0, alpha=0.08, color=C["curve_today"], zorder=2)

    # Dot markers at each maturity
    ax.scatter(vx, vy, color=C["curve_today"], s=40, zorder=5)

    # Annotate each point with its yield value
    for x, y in zip(vx, vy):
        ax.annotate(f"{y:.2f}%",
                    xy=(x, y), xytext=(0, 8),
                    textcoords="offset points",
                    color=C["text"], fontsize=7,
                    ha="center", zorder=6)

    # 5% danger zone threshold
    y_vals_all = list(vy)
    y_max      = max(y_vals_all) * 1.15
    y_min      = min(y_vals_all) * 0.85
    y_min      = min(y_min, 0)

    ax.axhline(5.0, color=C["curve_danger"], linewidth=1.0,
               linestyle="--", alpha=0.7, zorder=3)
    ax.text(len(MATURITIES) - 0.5, 5.0,
            " 5% danger zone",
            color=C["curve_danger"], fontsize=7.5,
            va="bottom", ha="right", zorder=6)

    # Shade inversion zones (where yield[i] > yield[i+1])
    for i in range(len(vx) - 1):
        if vy[i] > vy[i + 1]:
            ax.axvspan(vx[i] - 0.4, vx[i + 1] + 0.4,
                       alpha=0.12, color=C["curve_danger"], zorder=1)

    ax.set_xlim(-0.5, len(MATURITIES) - 0.5)
    ax.set_ylim(y_min, max(y_max, 5.2))
    ax.set_xticks(x_pos)
    ax.set_xticklabels(x_labels, fontsize=8)
    ax.yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda x, _: f"{x:.2f}%"))
    ax.set_xlabel("Maturity",       color=C["subtext"], fontsize=8)
    ax.set_ylabel("Yield (%)",      color=C["subtext"], fontsize=8)
    _title(ax, "U.S. Treasury Yield Curve")
    _legend(ax, "upper left")


def draw_yield_data_table(ax, today_curve: dict | None,
                          yesterday_curve: dict | None,
                          macro: dict | None):
    """
    Draw the data table below the yield curve showing:
    - Per-maturity yield + Δ vs yesterday
    - Key spreads
    - TLT, Oil (USO), TNX, TYX live values
    """
    ax.set_facecolor(C["panel"])
    ax.axis("off")

    if today_curve is None and macro is None:
        ax.text(0.5, 0.5, "No data available",
                transform=ax.transAxes, ha="center", va="center",
                color=C["subtext"], fontsize=10)
        return

    # Build rows: maturity | yield | Δ
    col_labels = []
    col_yields = []
    col_deltas = []

    for label, key in MATURITIES:
        today_y = today_curve.get(key) if today_curve else None
        yest_y  = yesterday_curve.get(key) if yesterday_curve else None
        if today_y is None:
            continue
        delta = round(today_y - yest_y, 3) if yest_y else None
        col_labels.append(label)
        col_yields.append(f"{today_y:.2f}%")
        col_deltas.append(
            (f"{delta:+.3f}%" if delta is not None else "—",
             C["ind_red"] if (delta and delta > 0) else
             C["ind_green"] if (delta and delta < 0) else C["subtext"])
        )

    # Render as text columns across the axes
    n    = len(col_labels)
    if n == 0:
        return

    x_step = 1.0 / (n + 1)
    y_mat  = 0.82
    y_yld  = 0.52
    y_dlt  = 0.22

    # Headers
    ax.text(0.0, 0.97, "Maturity:", color=C["subtext"],
            fontsize=7.5, transform=ax.transAxes,
            fontfamily="monospace", fontweight="bold")
    ax.text(0.0, 0.67, "Yield:",    color=C["subtext"],
            fontsize=7.5, transform=ax.transAxes,
            fontfamily="monospace", fontweight="bold")
    ax.text(0.0, 0.37, "Δ vs yest:", color=C["subtext"],
            fontsize=7.5, transform=ax.transAxes,
            fontfamily="monospace", fontweight="bold")

    for i, (lbl, yld, (dlt, dlt_c)) in enumerate(
            zip(col_labels, col_yields, col_deltas)):
        x = 0.12 + i * x_step
        ax.text(x, y_mat, lbl, color=C["text"],   fontsize=7.5,
                transform=ax.transAxes, ha="center",
                fontfamily="monospace")
        ax.text(x, y_yld, yld, color=C["text"],   fontsize=7.5,
                transform=ax.transAxes, ha="center",
                fontfamily="monospace")
        ax.text(x, y_dlt, dlt, color=dlt_c,       fontsize=7.5,
                transform=ax.transAxes, ha="center",
                fontfamily="monospace")

    # Separator line
    ax.axhline(0.05, color=C["border"], linewidth=0.5,
               transform=ax.transAxes)

    # Bottom row: spreads + live macro values
    spread_10_2  = today_curve.get("spread_10_2")  if today_curve else None
    spread_10_3m = today_curve.get("spread_10_3m") if today_curve else None

    bottom_items = []
    if spread_10_2 is not None:
        inv = spread_10_2 < 0
        bottom_items.append((
            f"10Y-2Y: {spread_10_2:+.2f}%"
            + (" ⚠ INVERTED" if inv else ""),
            C["ind_red"] if inv else C["subtext"]
        ))
    if spread_10_3m is not None:
        inv = spread_10_3m < 0
        bottom_items.append((
            f"10Y-3M: {spread_10_3m:+.2f}%"
            + (" ⚠ INVERTED" if inv else ""),
            C["ind_red"] if inv else C["subtext"]
        ))
    if macro:
        tlt = macro.get("tlt_price")
        tlt_pct = macro.get("tlt_chg_pct")
        uso = macro.get("uso_price")
        uso_pct = macro.get("uso_chg_pct")
        tnx = macro.get("tnx_yield")
        tyx = macro.get("tyx_yield")
        if tlt:
            arrow = "▲" if (tlt_pct or 0) >= 0 else "▼"
            bottom_items.append((
                f"TLT ${tlt:.2f} {arrow}{abs(tlt_pct or 0):.1f}%",
                C["ind_green"] if (tlt_pct or 0) >= 0 else C["ind_red"]
            ))
        if uso:
            arrow = "▲" if (uso_pct or 0) >= 0 else "▼"
            bottom_items.append((
                f"USO ${uso:.2f} {arrow}{abs(uso_pct or 0):.1f}%",
                C["ind_red"] if (uso_pct or 0) >= 0 else C["ind_green"]
            ))
        if tnx:
            bottom_items.append((f"TNX {tnx:.2f}%", C["subtext"]))
        if tyx:
            color = C["ind_red"] if tyx >= 5.0 else \
                    C["ind_yellow"] if tyx >= 4.75 else C["subtext"]
            bottom_items.append((f"TYX {tyx:.2f}%", color))

    x_step_b = 1.0 / max(len(bottom_items), 1)
    for i, (text, color) in enumerate(bottom_items):
        ax.text(0.01 + i * x_step_b, 0.0, text,
                color=color, fontsize=7.5,
                transform=ax.transAxes,
                fontfamily="monospace")
        
# ══════════════════════════════════════════════════════════════════════════════
# BACKTEST PRICE CHART RENDERER
# ══════════════════════════════════════════════════════════════════════════════

def _draw_price_chart(ax, bars, selected_date, gamma_flip,
                      max_pain, symbol, frequency):
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")

    ax.set_facecolor(C["panel"])
    for sp in ax.spines.values(): sp.set_color(C["border"])
    ax.tick_params(colors=C["subtext"], labelsize=7.5, length=2, width=0.5)
    ax.grid(color=C["grid"], linewidth=0.3, linestyle="-", zorder=0)
    ax.set_axisbelow(True)

    if bars.empty:
        ax.text(0.5, 0.5, "No price data available\nfor selected date",
                transform=ax.transAxes, ha="center", va="center",
                color=C["subtext"], fontsize=11)
        _title(ax, f"{symbol} Price  |  {selected_date}  |  {frequency}")
        return

    bars_et = bars.copy()
    bars_et.index = bars_et.index.tz_convert(ET)
    bars_et = bars_et[bars_et.index.date == selected_date]

    if bars_et.empty:
        ax.text(0.5, 0.5, f"No bars for {selected_date}",
                transform=ax.transAxes, ha="center", va="center",
                color=C["subtext"], fontsize=11)
        _title(ax, f"{symbol} Price  |  {selected_date}  |  {frequency}")
        return

    width_map = {"1min": 0.65, "5min": 3.5, "10min": 7.0,
                 "15min": 10.5, "30min": 21.0}
    candle_w = pd.Timedelta(minutes=width_map.get(frequency, 3.5))

    for idx, row in bars_et.iterrows():
        o, h, l, c = row["Open"], row["High"], row["Low"], row["Close"]
        color = C["candle_up"] if c >= o else C["candle_down"]
        ax.plot([idx, idx], [l, h], color=color, linewidth=0.8, zorder=2)
        body_h = max(abs(c - o), 0.005)
        body_y = min(o, c)
        ax.bar(idx, body_h, bottom=body_y, width=candle_w,
               color=color, linewidth=0, zorder=3)

    day_high = bars_et["High"].max()
    day_low  = bars_et["Low"].min()
    buf = max((day_high - day_low) * 0.08, day_high * 0.005)
    y_lo = day_low  - buf
    y_hi = day_high + buf
    ax.set_ylim(y_lo, y_hi)
    ax.set_xlim(bars_et.index[0]  - candle_w,
                bars_et.index[-1] + candle_w)

    # Gamma flip — use computed_flip from draw_gex() (source of truth)
    if gamma_flip and y_lo <= gamma_flip <= y_hi:
        ax.axhline(gamma_flip, color=C["spot"], linewidth=1.1,
                   linestyle="--", alpha=0.9, zorder=5)
        ax.text(bars_et.index[-1] + candle_w * 0.3, gamma_flip,
                f" flip ${gamma_flip:.0f}",
                color=C["spot"], fontsize=7.5,
                va="center", fontweight="bold", zorder=6, clip_on=False)

    # Max pain — recomputed from surface (fix applied in render_backtest)
    if max_pain and y_lo <= max_pain <= y_hi:
        ax.axhline(max_pain, color=C["net_neg"], linewidth=0.9,
                   linestyle="--", alpha=0.8, zorder=5)
        ax.text(bars_et.index[0] - candle_w * 0.3, max_pain,
                f"max pain ${max_pain:.0f} ",
                color=C["net_neg"], fontsize=7.5,
                va="center", ha="right", zorder=6, clip_on=False)

    ax.xaxis.set_major_locator(mdates.HourLocator(interval=1, tz=ET))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=ET))
    plt.setp(ax.xaxis.get_majorticklabels(), visible=False)
    ax.tick_params(axis="x", which="both", length=0)
    ax.spines["bottom"].set_visible(False)
    ax.set_ylabel("Price", color=C["subtext"], fontsize=8)
    ax.yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda x, _: f"${x:.2f}"))
    _title(ax, f"{symbol} Price  |  {selected_date}  |  {frequency}")


def _draw_volume_panel(ax, bars, selected_date, vol_90th, vol_avg, frequency="5min"):
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")

    ax.set_facecolor(C["panel"])
    for sp in ax.spines.values(): sp.set_color(C["border"])
    ax.tick_params(colors=C["subtext"], labelsize=6.5, length=2, width=0.5)
    ax.grid(color=C["grid"], linewidth=0.3, linestyle="-", zorder=0, axis="y")
    ax.set_axisbelow(True)

    if bars.empty:
        return

    bars_et = bars.copy()
    bars_et.index = bars_et.index.tz_convert(ET)
    bars_et = bars_et[bars_et.index.date == selected_date]
    if bars_et.empty:
        return

    width_map = {"1min": 0.65, "5min": 3.5, "10min": 7.0,
                 "15min": 10.5, "30min": 21.0}
    candle_w = pd.Timedelta(minutes=width_map.get(frequency, 3.5))

    for idx, row in bars_et.iterrows():
        ax.bar(idx, row["Volume"], width=candle_w,
               color=C["call"], alpha=0.75, linewidth=0, zorder=2)

    day_total = bars_et["Volume"].sum()
    n_bars    = len(bars_et)
    y_max     = vol_90th if vol_90th else bars_et["Volume"].max() * 1.3
    ax.set_ylim(0, y_max * 1.05)

    if vol_avg and n_bars > 0:
        avg_per_bar = vol_avg / n_bars
        ax.axhline(avg_per_bar, color=C["subtext"], linewidth=0.7,
                   linestyle="--", alpha=0.6, zorder=3)

    if vol_avg and vol_avg > 0:
        pct_diff = (day_total - vol_avg) / vol_avg * 100
        arrow    = "▲" if day_total >= vol_avg else "▼"
        color    = C["ind_green"] if day_total >= vol_avg else C["net_neg"]
        label    = f"{day_total/1e6:.1f}M  {arrow} {abs(pct_diff):.0f}% vs avg"
    else:
        color = C["subtext"]
        label = f"{day_total/1e6:.1f}M"

    ax.text(0.99, 0.92, label, transform=ax.transAxes,
            color=color, fontsize=7.5, fontweight="bold",
            ha="right", va="top", fontfamily="monospace", zorder=5)

    ax.yaxis.set_major_formatter(mticker.FuncFormatter(
        lambda x, _: f"{x/1e6:.0f}M" if x >= 1e6 else f"{x/1e3:.0f}K"))
    ax.set_ylabel("Vol", color=C["subtext"], fontsize=7)
    ax.spines["top"].set_visible(False)

    ax.xaxis.set_major_locator(mdates.HourLocator(interval=1, tz=ET))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=ET))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=0,
             ha="center", fontsize=7.5, visible=True)
    ax.set_xlabel("Time (ET)", color=C["subtext"], fontsize=7.5)

# ══════════════════════════════════════════════════════════════════════════════
# TKINTER DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

def launch_dashboard(initial_data, demo=False, vix_data=None):
    root = tk.Tk()
    root.title("Options Greeks Analyzer")
    root.configure(bg=C["bg"])
    root.state("zoomed")

    sw  = root.winfo_screenwidth()
    sh  = root.winfo_screenheight()
    dpi = 96

    _data_lock = threading.Lock()
    _live_data = {"df": initial_data[0], "spot": initial_data[1]}
    _vix_state = {"data": vix_data}
    _macro_state = {"data": None}   # updated each refresh from db

    vanna_split = tk.BooleanVar(value=False)
    charm_split = tk.BooleanVar(value=False)
    dte_var     = tk.StringVar(value="0-45")
    expiry_var  = tk.StringVar(value="ALL")
    strike_var  = tk.StringVar(value="+/-5%")
    active_tab  = tk.StringVar(value="CHARTS")

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

    # Tab buttons
    def make_tab_btn(label):
        btn = tk.Button(ctrl, text=label,
                        bg=C["btn_on"] if label == "CHARTS" else C["btn_off"],
                        fg=C["text"],
                        activebackground=C["btn_on"],
                        activeforeground=C["text"],
                        relief="flat",
                        highlightbackground=C["border"],
                        highlightthickness=1,
                        font=("Courier New", 9, "bold"),
                        cursor="hand2", padx=14, pady=3)
        btn.pack(side="left", padx=(0, 4))
        return btn

    charts_btn   = make_tab_btn("CHARTS")
    macro_btn    = make_tab_btn("MACRO")
    backtest_btn = make_tab_btn("BACKTEST")
    div()

    # Static SPY label (replaces dropdown)
    tk.Label(ctrl, text="SYMBOL", fg=C["subtext"], bg=C["ctrl"],
             font=("Courier New", 7)).pack(side="left", padx=(0, 4))
    tk.Label(ctrl, text="SPY", fg=C["text"], bg=C["ctrl"],
             font=("Courier New", 10, "bold")).pack(side="left", padx=(0, 6))
    div()

    # CHARTS-only controls
    charts_ctrl_widgets = []

    def _lbl(text):
        w = tk.Label(ctrl, text=text, fg=C["subtext"], bg=C["ctrl"],
                     font=("Courier New", 7))
        w.pack(side="left", padx=(0, 4))
        charts_ctrl_widgets.append(w)
        return w

    def _div_c():
        w = tk.Frame(ctrl, bg=C["border"], width=1)
        w.pack(side="left", fill="y", padx=10, pady=4)
        charts_ctrl_widgets.append(w)
        return w

    _lbl("DTE")
    dte_cb = ttk.Combobox(ctrl, textvariable=dte_var,
                          values=list(DTE_FILTERS.keys()),
                          state="readonly", width=6,
                          style="D.TCombobox",
                          font=("Courier New", 10))
    dte_cb.pack(side="left", padx=(0, 6))
    charts_ctrl_widgets.append(dte_cb)
    _div_c()

    _lbl("EXPIRY")
    expiry_cb = ttk.Combobox(ctrl, textvariable=expiry_var,
                             values=["ALL"],
                             state="readonly", width=11,
                             style="D.TCombobox",
                             font=("Courier New", 10))
    expiry_cb.pack(side="left", padx=(0, 6))
    charts_ctrl_widgets.append(expiry_cb)
    _div_c()

    _lbl("RANGE")
    range_cb = ttk.Combobox(ctrl, textvariable=strike_var,
                            values=list(STRIKE_RANGES.keys()),
                            state="readonly", width=6,
                            style="D.TCombobox",
                            font=("Courier New", 10))
    range_cb.pack(side="left", padx=(0, 6))
    charts_ctrl_widgets.append(range_cb)
    _div_c()

    def make_toggle(label, var):
        lbl = tk.Label(ctrl, text=label, fg=C["subtext"], bg=C["ctrl"],
                       font=("Courier New", 7))
        lbl.pack(side="left", padx=(0, 4))
        charts_ctrl_widgets.append(lbl)
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
        charts_ctrl_widgets.append(btn)
        def toggle():
            var.set(not var.get())
            dv.set("SPLIT" if var.get() else "NET")
            btn.config(bg=C["btn_on"] if var.get() else C["btn_off"])
            render_charts()
        btn.config(command=toggle)

    make_toggle("VANNA", vanna_split)
    _div_c()
    make_toggle("CHARM", charm_split)
    _div_c()

    # Right side badges
    tk.Label(ctrl,
             text="LIVE" if not demo else "DEMO",
             fg=C["live"] if not demo else C["demo"], bg=C["ctrl"],
             font=("Courier New", 9, "bold")).pack(side="right", padx=(10, 4))

    tk.Label(ctrl, text="Ctrl+Scroll: Zoom  |  R: Reset",
             fg=C["subtext"], bg=C["ctrl"],
             font=("Courier New", 7)).pack(side="right", padx=10)

    _vix_str = {"text": ""}

    def _build_vix_str(vd):
        if vd is None:
            _vix_str["text"] = "VIX --.-"
            return
        arrow = "▲" if vd["change"] >= 0 else "▼"
        _vix_str["text"] = (
            f"VIX {vd['last']:.2f}  "
            f"{arrow} {abs(vd['change']):.2f} ({abs(vd['change_pct']):.1f}%)"
        )

    _build_vix_str(vix_data)

    if not demo:
        tk.Frame(ctrl, bg=C["border"], width=1).pack(
            side="right", fill="y", padx=10, pady=4)
        countdown_var = tk.StringVar(value="")
        tk.Label(ctrl, textvariable=countdown_var,
                 fg=C["subtext"], bg=C["ctrl"],
                 font=("Courier New", 8)).pack(side="right", padx=(0, 6))
        ind_label = tk.Label(ctrl, text="●",
                             fg=C["ind_green"], bg=C["ctrl"],
                             font=("Courier New", 14))
        ind_label.pack(side="right", padx=(0, 2))

        def _set_indicator(state):
            color = {"green": C["ind_green"],
                     "red":   C["ind_red"],
                     "yellow": C["ind_yellow"]}[state]
            ind_label.config(fg=color)

    tk.Frame(root, bg=C["border"], height=1).pack(fill="x")

    # ── Content area ───────────────────────────────────────────────────────────
    content = tk.Frame(root, bg=C["bg"])
    content.pack(fill="both", expand=True)

    # ══════════════════════════════════════════════════════════════════════════
    # CHARTS TAB
    # ══════════════════════════════════════════════════════════════════════════

    charts_frame = tk.Frame(content, bg=C["bg"])
    charts_frame.place(relx=0, rely=0, relwidth=1, relheight=1)

    fig_w = sw / dpi
    fig_h = (sh - 52) / dpi
    fig   = plt.Figure(figsize=(fig_w, fig_h), facecolor=C["bg"], dpi=dpi)

    outer    = gridspec.GridSpec(1, 2, figure=fig,
                                 left=0.05, right=0.975,
                                 top=0.93, bottom=0.07,
                                 wspace=0.28, width_ratios=[1, 1.5])
    ax_gex   = fig.add_subplot(outer[0, 0])
    right    = outer[0, 1].subgridspec(2, 1, hspace=0.42)
    ax_vanna = fig.add_subplot(right[0, 0])
    ax_charm = fig.add_subplot(right[1, 0])

    charts_canvas = FigureCanvasTkAgg(fig, master=charts_frame)
    charts_canvas.get_tk_widget().pack(fill="both", expand=True)

    # ══════════════════════════════════════════════════════════════════════════
    # MACRO TAB
    # ══════════════════════════════════════════════════════════════════════════

    macro_frame = tk.Frame(content, bg=C["bg"])

    # Regime badge strip at top
    badge_frame = tk.Frame(macro_frame, bg=C["ctrl"], pady=8, padx=14)
    badge_frame.pack(side="top", fill="x")

    regime_label = tk.Label(badge_frame, text="██ MACRO REGIME: —",
                            fg=C["subtext"], bg=C["ctrl"],
                            font=("Courier New", 13, "bold"))
    regime_label.pack(side="left", padx=(0, 20))

    reason_label = tk.Label(badge_frame, text="",
                            fg=C["subtext"], bg=C["ctrl"],
                            font=("Courier New", 9))
    reason_label.pack(side="left", padx=(0, 20))

    signal_label = tk.Label(badge_frame, text="",
                            fg=C["subtext"], bg=C["ctrl"],
                            font=("Courier New", 10, "bold"))
    signal_label.pack(side="right", padx=(20, 0))

    gex_regime_label = tk.Label(badge_frame, text="",
                                fg=C["subtext"], bg=C["ctrl"],
                                font=("Courier New", 9))
    gex_regime_label.pack(side="right", padx=(0, 10))

    tk.Frame(macro_frame, bg=C["border"], height=1).pack(fill="x")

    # Macro matplotlib figure — yield curve + data table + vol smile
    macro_fig_w = sw / dpi
    macro_fig_h = (sh - 100) / dpi
    macro_fig   = plt.Figure(figsize=(macro_fig_w, macro_fig_h),
                             facecolor=C["bg"], dpi=dpi)

    # Vertical layout: yield curve (45%), data table (15%), vol smile (40%)
    macro_gs = gridspec.GridSpec(
        3, 1, figure=macro_fig,
        left=0.07, right=0.97,
        top=0.96, bottom=0.06,
        hspace=0.35,
        height_ratios=[45, 15, 40],
    )
    ax_curve  = macro_fig.add_subplot(macro_gs[0, 0])
    ax_table  = macro_fig.add_subplot(macro_gs[1, 0])
    ax_smile  = macro_fig.add_subplot(macro_gs[2, 0])

    macro_canvas = FigureCanvasTkAgg(macro_fig, master=macro_frame)
    macro_canvas.get_tk_widget().pack(fill="both", expand=True)

    # Expiry var for smile inside macro tab
    macro_expiry_var = tk.StringVar(value="ALL")

    # ══════════════════════════════════════════════════════════════════════════
    # BACKTEST TAB
    # ══════════════════════════════════════════════════════════════════════════

    backtest_frame = tk.Frame(content, bg=C["bg"])

    _cfg            = _load_config()
    _saved_date_str = _cfg.get("backtest_date", "")
    try:
        _init_date = datetime.date.fromisoformat(_saved_date_str)
    except (ValueError, TypeError):
        if not demo:
            import schwab_price
            _init_date = schwab_price.prev_trading_day(datetime.date.today())
        else:
            _init_date = datetime.date.today() - datetime.timedelta(days=1)

    bt_ctrl = tk.Frame(backtest_frame, bg=C["ctrl"], pady=6, padx=14)
    bt_ctrl.pack(side="top", fill="x")

    tk.Label(bt_ctrl, text="DATE", fg=C["subtext"], bg=C["ctrl"],
             font=("Courier New", 7)).pack(side="left", padx=(0, 4))

    bt_date_entry = DateEntry(
        bt_ctrl,
        date_pattern="mm/dd/yy",
        background=C["btn_off"], foreground=C["text"],
        bordercolor=C["border"],
        headersbackground=C["ctrl"], headersforeground=C["text"],
        selectbackground=C["btn_on"], selectforeground=C["text"],
        normalbackground=C["panel"], normalforeground=C["text"],
        weekendbackground=C["panel"], weekendforeground=C["subtext"],
        othermonthbackground=C["bg"], othermonthforeground=C["border"],
        font=("Courier New", 10), width=10, state="readonly",
    )
    bt_date_entry.set_date(_init_date)
    bt_date_entry.pack(side="left", padx=(0, 6))

    tk.Frame(bt_ctrl, bg=C["border"], width=1).pack(
        side="left", fill="y", padx=10, pady=4)

    tk.Label(bt_ctrl, text="GEX", fg=C["subtext"], bg=C["ctrl"],
             font=("Courier New", 7)).pack(side="left", padx=(0, 4))
    bt_dte_var = tk.StringVar(value="0-45")
    for lbl in ["0DTE", "0-45"]:
        tk.Radiobutton(
            bt_ctrl, text=lbl, variable=bt_dte_var, value=lbl,
            bg=C["ctrl"], fg=C["text"], selectcolor=C["btn_on"],
            activebackground=C["ctrl"], activeforeground=C["text"],
            font=("Courier New", 9), cursor="hand2",
            command=lambda: render_backtest(),
        ).pack(side="left", padx=(0, 2))

    tk.Frame(bt_ctrl, bg=C["border"], width=1).pack(
        side="left", fill="y", padx=10, pady=4)

    tk.Label(bt_ctrl, text="TIMEFRAME", fg=C["subtext"], bg=C["ctrl"],
             font=("Courier New", 7)).pack(side="left", padx=(0, 4))
    bt_tf_var  = tk.StringVar(value="5min")
    bt_tf_btns = {}
    for tf in ["1min", "5min", "10min", "15min", "30min"]:
        btn = tk.Button(
            bt_ctrl, text=tf,
            bg=C["btn_on"] if tf == "5min" else C["btn_off"],
            fg=C["text"],
            activebackground=C["btn_on"], activeforeground=C["text"],
            relief="flat", highlightbackground=C["border"],
            highlightthickness=1,
            font=("Courier New", 9, "bold"),
            cursor="hand2", padx=10, pady=3,
        )
        btn.pack(side="left", padx=(0, 2))
        bt_tf_btns[tf] = btn

    def _set_tf(tf):
        bt_tf_var.set(tf)
        for t, b in bt_tf_btns.items():
            b.config(bg=C["btn_on"] if t == tf else C["btn_off"])
        render_backtest()

    for tf, btn in bt_tf_btns.items():
        btn.config(command=lambda t=tf: _set_tf(t))

    tk.Frame(bt_ctrl, bg=C["border"], width=1).pack(
        side="left", fill="y", padx=10, pady=4)

    bt_status_var = tk.StringVar(value="")
    tk.Label(bt_ctrl, textvariable=bt_status_var,
             fg=C["subtext"], bg=C["ctrl"],
             font=("Courier New", 8)).pack(side="left", padx=(0, 6))

    bt_fig_w = sw / dpi
    bt_fig_h = (sh - 90) / dpi
    bt_fig   = plt.Figure(figsize=(bt_fig_w, bt_fig_h),
                          facecolor=C["bg"], dpi=dpi)

    bt_outer  = gridspec.GridSpec(1, 2, figure=bt_fig,
                                  left=0.05, right=0.975,
                                  top=0.93, bottom=0.07,
                                  wspace=0.28, width_ratios=[1, 1.5])
    ax_bt_gex = bt_fig.add_subplot(bt_outer[0, 0])
    right_gs  = bt_outer[0, 1].subgridspec(2, 1, hspace=0.0,
                                            height_ratios=[4, 1])
    ax_bt_price  = bt_fig.add_subplot(right_gs[0, 0])
    ax_bt_volume = bt_fig.add_subplot(right_gs[1, 0], sharex=ax_bt_price)

    bt_canvas = FigureCanvasTkAgg(bt_fig, master=backtest_frame)
    bt_canvas.get_tk_widget().pack(fill="both", expand=True)

    # ── Tooltip ────────────────────────────────────────────────────────────────
    tooltip = tk.Label(root, text="", bg="#1a1a2e", fg=C["text"],
                       font=("Courier New", 8), relief="flat",
                       borderwidth=1, padx=8, pady=5, justify="left")

    _line_data  = {}
    _smile_data = {}

    def _store_line(ax, x_vals, y_vals):
        _line_data[id(ax)] = {"x": np.array(x_vals), "y": np.array(y_vals)}

    def _store_smile(ax, strikes, call_iv, put_iv):
        _smile_data[id(ax)] = {
            "x": np.array(strikes),
            "call_iv": np.array(call_iv),
            "put_iv":  np.array(put_iv),
        }

    def _fmt_tip(v):
        if abs(v) >= 1e6: return f"{v/1e6:+.3f}M"
        if abs(v) >= 1e3: return f"{v/1e3:+.1f}K"
        return f"{v:+.4f}"

    def on_hover_charts(event):
        if event.inaxes is None:
            tooltip.place_forget(); return
        dat = _line_data.get(id(event.inaxes))
        x   = event.xdata
        if x is None or dat is None or not len(dat["x"]):
            tooltip.place_forget(); return
        idx  = int(np.argmin(np.abs(dat["x"] - x)))
        text = (f"Strike : ${dat['x'][idx]:.0f}\n"
                f"Value  : {_fmt_tip(dat['y'][idx])}\n"
                f"Cursor : {_fmt_tip(event.ydata)}")
        tooltip.config(text=text)
        px = root.winfo_pointerx() - root.winfo_rootx()
        py = root.winfo_pointery() - root.winfo_rooty()
        tooltip.place(x=min(max(px+15, 5), root.winfo_width()-160),
                      y=min(max(py-65,  5), root.winfo_height()-80))
        tooltip.lift()

    def on_hover_smile(event):
        if event.inaxes is None:
            tooltip.place_forget(); return
        dat = _smile_data.get(id(event.inaxes))
        x   = event.xdata
        if x is None or dat is None or not len(dat["x"]):
            tooltip.place_forget(); return
        idx  = int(np.argmin(np.abs(dat["x"] - x)))
        text = (f"Strike  : ${dat['x'][idx]:.0f}\n"
                f"Call IV : {dat['call_iv'][idx]:.2f}%\n"
                f"Put IV  : {dat['put_iv'][idx]:.2f}%")
        tooltip.config(text=text)
        px = root.winfo_pointerx() - root.winfo_rootx()
        py = root.winfo_pointery() - root.winfo_rooty()
        tooltip.place(x=min(max(px+15, 5), root.winfo_width()-160),
                      y=min(max(py-65,  5), root.winfo_height()-80))
        tooltip.lift()

    fig.canvas.mpl_connect("motion_notify_event", on_hover_charts)
    macro_fig.canvas.mpl_connect("motion_notify_event", on_hover_smile)

    # ── Expiry list ────────────────────────────────────────────────────────────

    def _update_expiry_list(*_):
        with _data_lock:
            df   = _live_data["df"]
            spot = _live_data["spot"]
        filtered = filter_df(df, spot, dte_label=dte_var.get(),
                             expiry="ALL",
                             strike_pct=STRIKE_RANGES.get(strike_var.get(), 0.05))
        expiries = sorted(filtered["expiry"].unique().tolist()) \
                   if "expiry" in filtered.columns else []
        expiry_cb["values"] = ["ALL"] + expiries
        if expiry_var.get() not in ["ALL"] + expiries:
            expiry_var.set("ALL")
        # Also update macro tab smile expiry options
        macro_expiry_var.set("ALL")

    # ══════════════════════════════════════════════════════════════════════════
    # RENDER: CHARTS TAB
    # ══════════════════════════════════════════════════════════════════════════

    def render_charts(*_):
        with _data_lock:
            df   = _live_data["df"]
            spot = _live_data["spot"]

        fdf = filter_df(df, spot,
                        dte_label=dte_var.get(),
                        expiry=expiry_var.get(),
                        strike_pct=STRIKE_RANGES.get(strike_var.get(), 0.05))

        for ax in [ax_gex, ax_vanna, ax_charm]:
            ax.clear()

        if fdf.empty:
            for ax in [ax_gex, ax_vanna, ax_charm]:
                ax.set_facecolor(C["panel"])
                ax.text(0.5, 0.5, "No data for selected filters",
                        transform=ax.transAxes, ha="center", va="center",
                        color=C["subtext"], fontsize=11)
            charts_canvas.draw()
            return

        agg      = aggregate(fdf)
        max_pain = _calc_max_pain(fdf)

        draw_gex(ax_gex, agg, spot, SYMBOL, max_pain=max_pain)

        nv = agg["VannEX"].values  / 1e6
        nc = agg["CharmEX"].values / 1e6
        _store_line(ax_vanna, agg["strike"].values, nv)
        _store_line(ax_charm, agg["strike"].values, nc)

        draw_vanna(ax_vanna, agg, spot, SYMBOL, vanna_split.get())
        draw_charm(ax_charm, agg, spot, SYMBOL, charm_split.get())

        expiry_lbl = f"  |  {expiry_var.get()}" if expiry_var.get() != "ALL" else ""
        filter_lbl = f"DTE: {dte_var.get()}  Range: {strike_var.get()}{expiry_lbl}"
        ts         = datetime.datetime.now().strftime("%H:%M:%S")

        fig.suptitle(
            f"SPY   Spot ${spot:.2f}      {_vix_str['text']}   "
            f"|   {ts}   |   {filter_lbl}",
            color=C["subtext"], fontsize=8.5,
            x=0.5, y=0.975, fontfamily="monospace"
        )
        charts_canvas.draw()
        fig.savefig("dashboard.png", dpi=dpi,
                    bbox_inches="tight", facecolor=C["bg"])

    # ══════════════════════════════════════════════════════════════════════════
    # RENDER: MACRO TAB
    # ══════════════════════════════════════════════════════════════════════════

    def _update_regime_badge(signal_data: dict | None):
        """Update the regime badge labels from combined signal dict."""
        if signal_data is None:
            regime_label.config(text="██ MACRO REGIME: —",
                                fg=C["subtext"])
            reason_label.config(text="No macro data — run collector.py")
            signal_label.config(text="")
            gex_regime_label.config(text="")
            return

        macro_regime = signal_data.get("macro_regime", "—")
        gex_regime   = signal_data.get("gex_regime",   "—")
        signal       = signal_data.get("signal",        "—")
        reason       = signal_data.get("reason",         "")

        regime_color = {
            "GREEN":  C["regime_green"],
            "YELLOW": C["regime_yellow"],
            "ORANGE": C["regime_orange"],
            "RED":    C["regime_red"],
        }.get(macro_regime, C["subtext"])

        regime_label.config(
            text=f"██ MACRO REGIME: {macro_regime}",
            fg=regime_color
        )
        reason_label.config(text=reason, fg=C["subtext"])
        gex_regime_label.config(
            text=f"GEX: {gex_regime}", fg=C["subtext"]
        )

        signal_color = (C["regime_red"]    if "SHORT" in signal or "CAUTION" in signal
                   else C["regime_green"]  if "LONG"  in signal
                   else C["regime_yellow"] if "NEUTRAL" in signal
                   else C["subtext"])
        signal_label.config(text=f"→ {signal}", fg=signal_color)

    def render_macro(*_):
        """
        Render the MACRO tab:
        - Update regime badge from db.get_combined_signal()
        - Draw yield curve (today + yesterday) from db
        - Draw data table below curve
        - Draw vol smile at bottom
        """
        # Load macro data from db
        try:
            import db
            signal_data  = db.get_combined_signal()
            today_curve, yesterday_curve = db.get_yield_curve_two_days()
            macro_data   = db.get_latest_macro()
        except Exception as e:
            print(f"  db load failed in render_macro: {e}")
            signal_data  = None
            today_curve  = None
            yesterday_curve = None
            macro_data   = None

        # Update regime badge
        _update_regime_badge(signal_data)

        # Clear and redraw matplotlib panels
        for ax in [ax_curve, ax_table, ax_smile]:
            ax.clear()

        draw_yield_curve(ax_curve, today_curve, yesterday_curve)
        draw_yield_data_table(ax_table, today_curve, yesterday_curve, macro_data)

        # Vol smile — use current live data
        with _data_lock:
            df   = _live_data["df"]
            spot = _live_data["spot"]

        smile_df = build_smile_df(df, spot, macro_expiry_var.get())
        result   = draw_vol_smile(ax_smile, smile_df, spot,
                                  SYMBOL, macro_expiry_var.get())
        if result[0] is not None:
            _store_smile(ax_smile, result[0], result[1], result[2])

        ts = datetime.datetime.now().strftime("%H:%M:%S")
        macro_fig.suptitle(
            f"SPY   Spot ${spot:.2f}      {_vix_str['text']}   |   {ts}",
            color=C["subtext"], fontsize=8.5,
            x=0.5, y=0.99, fontfamily="monospace"
        )
        macro_canvas.draw()

    # ══════════════════════════════════════════════════════════════════════════
    # RENDER: BACKTEST TAB
    # ══════════════════════════════════════════════════════════════════════════

    _bt_fetch_lock = threading.Lock()

    def render_backtest(*_):
        if demo:
            for ax in [ax_bt_gex, ax_bt_price, ax_bt_volume]:
                ax.clear()
                ax.set_facecolor(C["panel"])
            ax_bt_gex.text(
                0.5, 0.5,
                "Backtest tab requires live mode.\n"
                "Add Schwab API credentials to .env to enable.",
                transform=ax_bt_gex.transAxes, ha="center", va="center",
                color=C["subtext"], fontsize=11)
            bt_canvas.draw()
            return

        if not _bt_fetch_lock.acquire(blocking=False):
            return

        selected_date     = bt_date_entry.get_date()
        selected_date_str = selected_date.strftime("%Y-%m-%d")
        dte_lbl           = bt_dte_var.get()
        frequency         = bt_tf_var.get()

        _save_config({"backtest_date": selected_date_str})
        bt_status_var.set("Fetching...")
        root.update_idletasks()

        def _fetch_and_render():
            try:
                import db
                import schwab_price

                # ── Left: GEX surface ─────────────────────────────────────────
                has_gex       = False
                snap_spot     = 0
                agg_df        = None
                computed_flip = None   # from draw_gex() — source of truth
                surface_max_pain = None  # recomputed from surface

                snapshot = db.get_opening_snapshot(SYMBOL, selected_date)
                is_today = (selected_date == datetime.date.today())

                # For today, use latest summary for key levels
                if is_today:
                    latest = db.get_latest_summary(SYMBOL)
                    if latest:
                        snap_spot = latest.get("spot", 0)
                else:
                    if snapshot:
                        snap_spot = snapshot.get("spot", 0)

                snap_regime = ""
                if snapshot:
                    snap_regime = snapshot.get("regime", "")
                    ts          = snapshot.get("timestamp", "")
                    surface     = db.get_gex_surface(SYMBOL, ts)

                    if surface is not None and not surface.empty:
                        if dte_lbl == "0DTE":
                            sf = surface[surface["dte"] <= 1]
                        else:
                            sf = surface[surface["dte"] <= 45]

                        if not sf.empty:
                            cols = ["GEX_call", "GEX_put", "GEX_net",
                                    "VannEX_call", "VannEX_put", "VannEX_net",
                                    "CharmEX_call", "CharmEX_put", "CharmEX_net",
                                    "total_oi"]
                            rename_map = {
                                "VannEX_net":  "VannEX",
                                "CharmEX_net": "CharmEX",
                                "total_oi":    "oi",
                            }
                            agg_cols = [c for c in cols if c in sf.columns]
                            agg_df   = (sf.groupby("strike")[agg_cols]
                                          .sum()
                                          .reset_index()
                                          .rename(columns=rename_map)
                                          .sort_values("strike"))
                            if "GEX_net" not in agg_df.columns:
                                agg_df["GEX_net"] = (
                                    agg_df.get("GEX_call", 0) +
                                    agg_df.get("GEX_put",  0)
                                )
                            has_gex = True

                            # Recompute max pain from filtered surface
                            # Build a minimal df compatible with _calc_max_pain
                            if "type" in sf.columns:
                                surface_max_pain = _calc_max_pain(sf)

                # ── Right: price bars ─────────────────────────────────────────
                from auth import get_valid_access_token
                token = get_valid_access_token(silent=True)
                bars  = schwab_price.get_single_day_bars(
                    token, SYMBOL, selected_date, frequency=frequency)

                hist_vol = schwab_price.get_historical_volume(token, SYMBOL)
                vol_90th = None
                vol_avg  = None
                if not hist_vol.empty and "Volume" in hist_vol.columns:
                    daily_vols = hist_vol["Volume"]
                    vol_90th   = float(np.percentile(daily_vols, 90))
                    vol_avg    = float(daily_vols.mean())
                    n_bars_est = {"1min": 390, "5min": 78, "10min": 39,
                                  "15min": 26, "30min": 13}.get(frequency, 78)
                    vol_90th   = vol_90th / n_bars_est

                def _draw():
                    ax_bt_gex.clear()
                    ax_bt_price.clear()
                    ax_bt_volume.clear()

                    nonlocal computed_flip

                    if has_gex:
                        # draw_gex returns computed_flip — use this for
                        # price chart overlay (bug fix: was using snap_flip)
                        computed_flip = draw_gex(
                            ax_bt_gex, agg_df, snap_spot, SYMBOL,
                            max_pain=surface_max_pain
                        )
                        _title(ax_bt_gex,
                               f"GEX at Open  -  {SYMBOL}  |  "
                               f"{selected_date_str}  [{dte_lbl}]")
                        ax_bt_gex.text(
                            0.01, 0.01, f"Regime: {snap_regime}",
                            transform=ax_bt_gex.transAxes,
                            color=C["subtext"], fontsize=7.5,
                            fontfamily="monospace", va="bottom",
                        )
                    else:
                        _style(ax_bt_gex)
                        ax_bt_gex.text(
                            0.5, 0.5,
                            f"No Greeks data\nfor {selected_date_str}",
                            transform=ax_bt_gex.transAxes,
                            ha="center", va="center",
                            color=C["subtext"], fontsize=11,
                        )
                        _title(ax_bt_gex,
                               f"GEX at Open  -  {SYMBOL}  |  "
                               f"{selected_date_str}")

                    # Price chart receives computed_flip from draw_gex()
                    # and surface_max_pain recomputed from filtered data
                    _draw_price_chart(
                        ax_bt_price, bars, selected_date,
                        computed_flip,    # source of truth for flip
                        surface_max_pain, # recomputed, not from summary
                        SYMBOL, frequency
                    )
                    _draw_volume_panel(
                        ax_bt_volume, bars, selected_date,
                        vol_90th, vol_avg, frequency
                    )

                    bt_fig.suptitle(
                        f"SPY   {selected_date_str}   |   "
                        f"{frequency}   |   {dte_lbl} GEX",
                        color=C["subtext"], fontsize=8.5,
                        x=0.5, y=0.975, fontfamily="monospace",
                    )
                    bt_canvas.draw()
                    bt_status_var.set(
                        f"Updated {datetime.datetime.now().strftime('%H:%M:%S')}"
                    )

                root.after(0, _draw)

            except Exception as e:
                print(f"  Backtest render failed: {e}")
                root.after(0, lambda: bt_status_var.set(f"Error: {e}"))
            finally:
                _bt_fetch_lock.release()

        threading.Thread(target=_fetch_and_render, daemon=True).start()

    bt_date_entry.bind("<<DateEntrySelected>>", lambda e: render_backtest())

    # ── Tab switching ──────────────────────────────────────────────────────────

    def switch_to_charts():
        active_tab.set("CHARTS")
        charts_btn.config(bg=C["btn_on"])
        macro_btn.config(bg=C["btn_off"])
        backtest_btn.config(bg=C["btn_off"])
        macro_frame.place_forget()
        backtest_frame.place_forget()
        charts_frame.place(relx=0, rely=0, relwidth=1, relheight=1)
        for w in charts_ctrl_widgets:
            w.pack(side="left", padx=(0, 4))
        tooltip.place_forget()
        render_charts()

    def switch_to_macro():
        active_tab.set("MACRO")
        macro_btn.config(bg=C["btn_on"])
        charts_btn.config(bg=C["btn_off"])
        backtest_btn.config(bg=C["btn_off"])
        charts_frame.place_forget()
        backtest_frame.place_forget()
        macro_frame.place(relx=0, rely=0, relwidth=1, relheight=1)
        for w in charts_ctrl_widgets:
            w.pack_forget()
        tooltip.place_forget()
        render_macro()

    def switch_to_backtest():
        active_tab.set("BACKTEST")
        backtest_btn.config(bg=C["btn_on"])
        charts_btn.config(bg=C["btn_off"])
        macro_btn.config(bg=C["btn_off"])
        charts_frame.place_forget()
        macro_frame.place_forget()
        backtest_frame.place(relx=0, rely=0, relwidth=1, relheight=1)
        for w in charts_ctrl_widgets:
            w.pack_forget()
        tooltip.place_forget()
        render_backtest()

    charts_btn.config(command=switch_to_charts)
    macro_btn.config(command=switch_to_macro)
    backtest_btn.config(command=switch_to_backtest)

    # ── Bindings ───────────────────────────────────────────────────────────────

    dte_cb.bind("<<ComboboxSelected>>",
                lambda e: [_update_expiry_list(), render_charts()])
    expiry_cb.bind("<<ComboboxSelected>>",
                   lambda e: render_charts())
    range_cb.bind("<<ComboboxSelected>>",
                  lambda e: render_charts())

    _update_expiry_list()

    # ── Zoom ───────────────────────────────────────────────────────────────────

    zoom   = [1.0]
    base_w = [sw]
    base_h = [sh - 52]

    def on_scroll(event):
        if not (event.state & 0x4): return
        if active_tab.get() != "CHARTS": return
        zoom[0] = max(0.4, min(3.5,
                               zoom[0] * (0.88 if event.delta > 0 else 1.12)))
        nw = int(base_w[0] * zoom[0])
        nh = int(base_h[0] * zoom[0])
        fig.set_size_inches(nw / dpi, nh / dpi)
        charts_canvas.get_tk_widget().config(width=nw, height=nh)
        charts_canvas.draw()

    def on_key(event):
        if event.keysym.lower() == "r" and active_tab.get() == "CHARTS":
            zoom[0] = 1.0
            fig.set_size_inches(base_w[0] / dpi, base_h[0] / dpi)
            charts_canvas.get_tk_widget().config(
                width=base_w[0], height=base_h[0])
            render_charts()

    root.bind("<MouseWheel>", on_scroll)
    root.bind("<Key>", on_key)

    # ── Auto-refresh ───────────────────────────────────────────────────────────

    if not demo:
        _refresh_state = {"last_refresh": time.time(), "fetching": False}

        def _do_refresh():
            _refresh_state["fetching"] = True
            root.after(0, lambda: _set_indicator("red"))
            try:
                from auth import get_valid_access_token
                token            = get_valid_access_token(silent=True)
                result, vd       = fetch_live_data(token)
                if result:
                    with _data_lock:
                        _live_data["df"]   = result[0]
                        _live_data["spot"] = result[1]
                    _vix_state["data"] = vd
                    _refresh_state["last_refresh"] = time.time()
                    root.after(0, _update_expiry_list)
                    root.after(0, lambda vd=vd: _build_vix_str(vd))
                    if active_tab.get() == "CHARTS":
                        root.after(0, render_charts)
                    elif active_tab.get() == "MACRO":
                        root.after(0, render_macro)
                root.after(0, lambda: _set_indicator("green"))
            except Exception as e:
                print(f"  Auto-refresh failed: {e}")
                root.after(0, lambda: _set_indicator("green"))
            finally:
                _refresh_state["fetching"] = False

        def _tick():
            if not _refresh_state["fetching"]:
                elapsed   = time.time() - _refresh_state["last_refresh"]
                remaining = max(0, REFRESH_INTERVAL - elapsed)
                m = int(remaining) // 60
                s = int(remaining) % 60
                countdown_var.set(f"next {m}:{s:02d}")
                if remaining <= 30:
                    _set_indicator("yellow")
                if remaining <= 0:
                    threading.Thread(target=_do_refresh, daemon=True).start()
            else:
                countdown_var.set("fetching...")
            root.after(1000, _tick)

        _tick()

    render_charts()
    root.mainloop()

# ══════════════════════════════════════════════════════════════════════════════
# DEMO DATA
# ══════════════════════════════════════════════════════════════════════════════

DEMO_SPOT = 679.67

_SPY_OI_ANCHORS = {
    685: (28000, 4000), 690: (14000, 3000), 700: (10000, 2000),
    695: (5000,  1500), 680: (8000,  6000), 679: (3000,  3000),
    678: (2000,  2500), 675: (4000,  5000), 673: (3000,  6000),
    670: (2000, 18000), 668: (1000,  5000), 665: (1500, 12000),
    660: (1000, 14000), 655: (500,   4000),
}

def generate_demo_chain(spot):
    np.random.seed(42)
    rows  = []
    r     = RISK_FREE
    today = datetime.date.today()
    lo    = round(spot * (1 - STRIKE_PCT))
    hi    = round(spot * (1 + STRIKE_PCT))

    for dte in [0, 3, 7, 14, 21, 28, 45]:
        if dte > MAX_DTE: continue
        T        = max(dte, 0.5) / 365
        exp_date = (today + datetime.timedelta(days=dte)).strftime("%Y-%m-%d")
        dte_scale = {0:1.8, 3:1.4, 7:1.2, 14:1.0,
                     21:0.8, 28:0.6, 45:0.4}.get(dte, 0.5)

        for K in np.arange(lo, hi + 1, 1.0):
            Kr = round(K)
            for side, call in [("call", True), ("put", False)]:
                mn    = np.log(K / spot)
                skew  = -0.45 * mn if not call else -0.12 * mn
                sigma = max(0.10, 0.20 + abs(mn) * 0.35 + skew
                            + np.random.normal(0, 0.006))
                if Kr in _SPY_OI_ANCHORS:
                    base = _SPY_OI_ANCHORS[Kr][0 if call else 1]
                else:
                    dist     = abs(K - spot)
                    decay    = max(0.03, 1.0 - (dist/(spot*STRIKE_PCT))**1.6)
                    is_10    = (Kr % 10 == 0)
                    is_5     = (Kr % 5 == 0)
                    round_w  = 2.5 if is_10 else (1.4 if is_5 else 0.6)
                    side_bias = (1.0 if call else 1.6) if K < 673 else \
                                (1.6 if call else 1.0)
                    base = int(1200 * decay * round_w * side_bias)
                oi = max(0, int(np.random.poisson(max(10, base * dte_scale))))
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
                    "iv_raw":       sigma,
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

def main():
    demo = (CLIENT_ID == "YOUR_CLIENT_ID")

    if demo:
        print("DEMO mode — add credentials to .env for live data\n")
        df           = generate_demo_chain(DEMO_SPOT)
        initial_data = (df, DEMO_SPOT)
        vix_data     = None
    else:
        from auth import get_valid_access_token
        token        = get_valid_access_token()
        print("Fetching SPY data...")
        result, vix_data = fetch_live_data(token)
        if not result:
            print("No data loaded — check credentials and try again.")
            return
        initial_data = result
        print(f"  SPY ${initial_data[1]:.2f} — {len(initial_data[0])} rows")

    print("Launching dashboard...")
    launch_dashboard(initial_data, demo=demo, vix_data=vix_data)


if __name__ == "__main__":
    main()