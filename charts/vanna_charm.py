"""charts/vanna_charm.py — Vanna and Charm exposure line charts."""

import numpy as np
import matplotlib.ticker as mticker
from scipy.ndimage import gaussian_filter1d
from .common import C, _style, _title, _legend, _fill_signed, _clip_ymx


def draw_vanna(ax, agg, spot, symbol, split):
    _style(ax)
    strikes = agg["strike"].values
    xlo = spot - 50; xhi = spot + 50
    ax.axhline(0, color=C["zero"], linewidth=0.8, zorder=3)

    if split:
        cv    = gaussian_filter1d(agg["VannEX_call"].values / 1e6, sigma=0.5)
        pv    = gaussian_filter1d(agg["VannEX_put"].values  / 1e6, sigma=0.5)
        all_v = np.concatenate([cv, pv])
        ax.plot(strikes, cv, color=C["vanna_call"], linewidth=2.0,
                label="Call Vanna", zorder=4)
        ax.plot(strikes, pv, color=C["vanna_put"],  linewidth=2.0,
                label="Put Vanna",  zorder=4)
        ax.fill_between(strikes, cv, 0, alpha=0.12, color=C["vanna_call"], zorder=2)
        ax.fill_between(strikes, pv, 0, alpha=0.12, color=C["vanna_put"],  zorder=2)
    else:
        nv    = agg["VannEX"].values / 1e6
        nv_s  = gaussian_filter1d(nv, sigma=0.5)
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


def draw_charm(ax, agg, spot, symbol, split):
    _style(ax)
    strikes = agg["strike"].values
    xlo = spot - 50; xhi = spot + 50
    ax.axhline(0, color=C["zero"], linewidth=0.8, zorder=3)

    if split:
        cc    = gaussian_filter1d(agg["CharmEX_call"].values / 1e6, sigma=0.5)
        pc    = gaussian_filter1d(agg["CharmEX_put"].values  / 1e6, sigma=0.5)
        all_v = np.concatenate([cc, pc])
        ax.plot(strikes, cc, color=C["charm_call"], linewidth=2.0,
                label="Call Charm", zorder=4)
        ax.plot(strikes, pc, color=C["charm_put"],  linewidth=2.0,
                label="Put Charm",  zorder=4)
        ax.fill_between(strikes, cc, 0, alpha=0.12, color=C["charm_call"], zorder=2)
        ax.fill_between(strikes, pc, 0, alpha=0.12, color=C["charm_put"],  zorder=2)
    else:
        nc    = agg["CharmEX"].values / 1e6
        nc_s  = gaussian_filter1d(nc, sigma=0.5)
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
