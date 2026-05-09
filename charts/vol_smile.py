"""charts/vol_smile.py — Implied volatility smile chart."""

import numpy as np
import matplotlib.ticker as mticker
from scipy.ndimage import gaussian_filter1d
from .common import C, _style, _title, _legend


def draw_vol_smile(ax, smile_df, spot, symbol, expiry):
    _style(ax)
    if smile_df.empty:
        ax.text(0.5, 0.5, "No data for selected expiry",
                transform=ax.transAxes, ha="center", va="center",
                color=C["subtext"], fontsize=11)
        return None, None, None

    strikes   = smile_df["strike"].values
    call_iv   = smile_df["call_iv"].values * 100
    put_iv    = smile_df["put_iv"].values  * 100
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
