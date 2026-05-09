"""charts/yield_curve.py — Treasury yield curve chart and data table."""

import matplotlib.ticker as mticker
from .common import C, MATURITIES, _style, _title, _legend


def draw_yield_curve(ax, today_curve: dict | None, yesterday_curve: dict | None):
    _style(ax)

    if today_curve is None:
        ax.text(0.5, 0.5,
                "No yield curve data available.",
                transform=ax.transAxes, ha="center", va="center",
                color=C["subtext"], fontsize=11)
        _title(ax, "U.S. Treasury Yield Curve")
        return

    x_pos    = list(range(len(MATURITIES)))
    x_labels = [m[0] for m in MATURITIES]
    db_keys  = [m[1] for m in MATURITIES]

    today_yields = [today_curve.get(k) for k in db_keys]
    valid_today  = [(x, y) for x, y in zip(x_pos, today_yields) if y is not None]
    if not valid_today:
        ax.text(0.5, 0.5, "Yield curve data incomplete.",
                transform=ax.transAxes, ha="center", va="center",
                color=C["subtext"], fontsize=11)
        return

    vx, vy = zip(*valid_today)

    if yesterday_curve:
        yest_yields = [yesterday_curve.get(k) for k in db_keys]
        valid_yest  = [(x, y) for x, y in zip(x_pos, yest_yields) if y is not None]
        if valid_yest:
            yx, yy = zip(*valid_yest)
            ax.plot(yx, yy, color=C["curve_yesterday"], linewidth=1.5,
                    linestyle="--", alpha=0.6, label="Yesterday", zorder=2)
            ax.fill_between(yx, yy, 0, alpha=0.04,
                            color=C["curve_yesterday"], zorder=1)

    ax.plot(vx, vy, color=C["curve_today"], linewidth=2.5,
            label=f"Today ({today_curve.get('date', '')})", zorder=4)
    ax.fill_between(vx, vy, 0, alpha=0.08, color=C["curve_today"], zorder=2)
    ax.scatter(vx, vy, color=C["curve_today"], s=40, zorder=5)

    for x, y in zip(vx, vy):
        ax.annotate(f"{y:.2f}%",
                    xy=(x, y), xytext=(0, 8),
                    textcoords="offset points",
                    color=C["text"], fontsize=7, ha="center", zorder=6)

    y_max = max(vy) * 1.15
    y_min = min(min(vy) * 0.85, 0)

    ax.axhline(5.0, color=C["curve_danger"], linewidth=1.0,
               linestyle="--", alpha=0.7, zorder=3)
    ax.text(len(MATURITIES) - 0.5, 5.0, " 5% danger zone",
            color=C["curve_danger"], fontsize=7.5,
            va="bottom", ha="right", zorder=6)

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
    ax.set_xlabel("Maturity",  color=C["subtext"], fontsize=8)
    ax.set_ylabel("Yield (%)", color=C["subtext"], fontsize=8)
    _title(ax, "U.S. Treasury Yield Curve")
    _legend(ax, "upper left")


def draw_yield_data_table(ax, macro: dict | None, futures: dict | None):
    """
    Data table panel on the Macro tab.

    Block 1 — TLT / USO  (from macro quotes)
    Block 2 — Bond yields: 3M ($IRX), 2Y (/ZT), 10Y (/ZN), 30Y (/ZB)
    Block 3 — Live spreads: 10Y-2Y and 10Y-3M (computed from futures yields)
    """
    ax.set_facecolor(C["panel"])
    ax.axis("off")

    if macro is None and futures is None:
        ax.text(0.5, 0.5, "No data available",
                transform=ax.transAxes, ha="center", va="center",
                color=C["subtext"], fontsize=10)
        return

    def _chg_str(chg, pct=None):
        if chg is None:
            return "—", C["subtext"]
        arrow = "▲" if chg >= 0 else "▼"
        color = C["ind_green"] if chg >= 0 else C["ind_red"]
        if pct is not None:
            return f"{arrow}{abs(chg):.2f}  ({abs(pct):.2f}%)", color
        return f"{arrow}{abs(chg):.3f}%", color

    # ── Block 1: TLT / USO ───────────────────────────────────────────────────
    if macro:
        tlt     = macro.get("tlt_price")
        tlt_chg = macro.get("tlt_change")
        tlt_pct = macro.get("tlt_chg_pct")
        uso     = macro.get("uso_price")
        uso_chg = macro.get("uso_change")
        uso_pct = macro.get("uso_chg_pct")

        if tlt is not None:
            chg_s, chg_c = _chg_str(tlt_chg, tlt_pct)
            ax.text(0.01, 0.72, "TLT", color=C["subtext"], fontsize=7.5,
                    transform=ax.transAxes, fontfamily="monospace")
            ax.text(0.08, 0.72, f"${tlt:.2f}", color=C["text"], fontsize=9,
                    transform=ax.transAxes, fontfamily="monospace", fontweight="bold")
            ax.text(0.18, 0.72, chg_s, color=chg_c, fontsize=7.5,
                    transform=ax.transAxes, fontfamily="monospace")

        if uso is not None:
            chg_s, chg_c = _chg_str(uso_chg, uso_pct)
            ax.text(0.01, 0.38, "USO", color=C["subtext"], fontsize=7.5,
                    transform=ax.transAxes, fontfamily="monospace")
            ax.text(0.08, 0.38, f"${uso:.2f}", color=C["text"], fontsize=9,
                    transform=ax.transAxes, fontfamily="monospace", fontweight="bold")
            ax.text(0.18, 0.38, chg_s, color=chg_c, fontsize=7.5,
                    transform=ax.transAxes, fontfamily="monospace")

    ax.plot([0.36, 0.36], [0.1, 0.95], color=C["border"], linewidth=0.5,
            transform=ax.transAxes, clip_on=False)

    # ── Block 2: Bond yields from futures + $IRX ─────────────────────────────
    irx_yield = macro.get("irx_yield") if macro else None
    zt_yield  = futures.get("zt_yield")  if futures else None
    zn_yield  = futures.get("zn_yield")  if futures else None
    zb_yield  = futures.get("zb_yield")  if futures else None

    yields = [
        ("3M ($IRX)", irx_yield, 0.39, 0.72),
        ("2Y  (/ZT)", zt_yield,  0.39, 0.38),
        ("10Y (/ZN)", zn_yield,  0.57, 0.72),
        ("30Y (/ZB)", zb_yield,  0.57, 0.38),
    ]

    for label, val, x, y in yields:
        ax.text(x, y, label, color=C["subtext"], fontsize=7.5,
                transform=ax.transAxes, fontfamily="monospace")
        if val is not None:
            val_color = (C["ind_red"]    if (label.startswith("30Y") and val >= 5.0)  else
                         C["ind_yellow"] if (label.startswith("30Y") and val >= 4.75) else
                         C["text"])
            ax.text(x + 0.10, y, f"{val:.3f}%", color=val_color,
                    fontsize=9, transform=ax.transAxes,
                    fontfamily="monospace", fontweight="bold")
        else:
            ax.text(x + 0.10, y, "—", color=C["subtext"], fontsize=8,
                    transform=ax.transAxes, fontfamily="monospace")

    ax.plot([0.72, 0.72], [0.1, 0.95], color=C["border"], linewidth=0.5,
            transform=ax.transAxes, clip_on=False)

    # ── Block 3: Live spreads (computed from futures yields) ──────────────────
    spread_10_2  = round(zn_yield - zt_yield,  3) if (zn_yield and zt_yield)  else None
    spread_10_3m = round(zn_yield - irx_yield, 3) if (zn_yield and irx_yield) else None

    spreads = [
        ("10Y - 2Y", spread_10_2,  0.72),
        ("10Y - 3M", spread_10_3m, 0.38),
    ]

    for label, val, y in spreads:
        ax.text(0.75, y, label, color=C["subtext"], fontsize=7.5,
                transform=ax.transAxes, fontfamily="monospace")
        if val is not None:
            inv       = val < 0
            val_color = C["ind_red"] if inv else C["text"]
            suffix    = "  ⚠" if inv else ""
            ax.text(0.88, y, f"{val:+.3f}%{suffix}",
                    color=val_color, fontsize=9,
                    transform=ax.transAxes, fontfamily="monospace",
                    fontweight="bold")
        else:
            ax.text(0.88, y, "—", color=C["subtext"], fontsize=8,
                    transform=ax.transAxes, fontfamily="monospace")

    ax.plot([0, 1], [0.08, 0.08], color=C["border"], linewidth=0.5,
            transform=ax.transAxes, clip_on=False)
