"""
charts/common.py — Shared constants and style helpers for all chart modules.
"""

import numpy as np
import matplotlib.ticker as mticker

# ── Color palette ──────────────────────────────────────────────────────────────

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
    "regime_green":  "#22c55e",
    "regime_yellow": "#f59e0b",
    "regime_orange": "#f97316",
    "regime_red":    "#dc2626",
    "curve_today":     "#17A2B8",
    "curve_yesterday": "#333355",
    "curve_danger":    "#dc2626",
    "curve_inversion": "#3a1a1a",
}

# Yield curve maturity labels and dict keys
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

# ── Shared axis helpers ────────────────────────────────────────────────────────

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
