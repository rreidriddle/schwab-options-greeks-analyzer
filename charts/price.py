"""charts/price.py — Backtest candlestick price chart and volume panel."""

import matplotlib.dates as mdates
import matplotlib.ticker as mticker
import matplotlib.pyplot as plt
from .common import C, _title


def _draw_price_chart(ax, bars, selected_date, gamma_flip, max_pain, symbol, frequency):
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

    import pandas as pd
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
        ax.bar(idx, body_h, bottom=min(o, c), width=candle_w,
               color=color, linewidth=0, zorder=3)

    day_high = bars_et["High"].max()
    day_low  = bars_et["Low"].min()
    buf  = max((day_high - day_low) * 0.08, day_high * 0.005)
    y_lo = day_low  - buf
    y_hi = day_high + buf
    ax.set_ylim(y_lo, y_hi)
    ax.set_xlim(bars_et.index[0]  - candle_w,
                bars_et.index[-1] + candle_w)

    if gamma_flip and y_lo <= gamma_flip <= y_hi:
        ax.axhline(gamma_flip, color=C["spot"], linewidth=1.1,
                   linestyle="--", alpha=0.9, zorder=5)
        ax.text(bars_et.index[-1] + candle_w * 0.3, gamma_flip,
                f" flip ${gamma_flip:.0f}",
                color=C["spot"], fontsize=7.5,
                va="center", fontweight="bold", zorder=6, clip_on=False)

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

    import pandas as pd
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
        ax.axhline(vol_avg / n_bars, color=C["subtext"], linewidth=0.7,
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
