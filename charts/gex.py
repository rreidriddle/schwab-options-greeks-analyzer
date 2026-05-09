"""charts/gex.py — Gamma Exposure bar chart."""

import matplotlib.ticker as mticker
from .common import C, _style, _title, _legend


def draw_gex(ax, agg, spot, symbol, max_pain=None):
    """
    Horizontal bar chart of GEX by strike.
    Returns computed_flip (float | None) for the price chart to consume.
    """
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
    return computed_flip
