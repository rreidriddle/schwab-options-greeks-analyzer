"""
macro.py — Live macro data for the dashboard.

Handles:
  - Treasury yield curve (fetched once at startup from Treasury.gov)
  - Bond futures front-month auto-detection (CME quarterly roll)
  - Futures price → implied yield conversion (/ZT, /ZN, /ZB)
  - Macro quotes: TLT, USO, VIX, $IRX
  - Macro regime classification and combined signal (computed live)

No database access. All data is fetched live from Schwab API or Treasury.gov.
"""

import datetime
import requests
import numpy as np
from scipy.optimize import brentq
from xml.etree import ElementTree

SCHWAB_BASE = "https://api.schwabapi.com/marketdata/v1"

TREASURY_XML_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/"
    "interest-rates/pages/xml?data=daily_treasury_yield_curve"
    "&field_tdr_date_value_month="
)

# CME quarterly expiry month codes
_FUTURES_MONTHS = [(3, "H"), (6, "M"), (9, "U"), (12, "Z")]

# Assumed maturities (years) per contract for yield inversion
_CONTRACT_MATURITIES = {
    "ZT": 2.0,
    "ZN": 10.0,
    "ZB": 30.0,
}

REGIME_THRESHOLDS = {
    "yield30_yellow": 4.50,
    "yield30_orange": 4.75,
    "yield30_red":    5.00,
    "tlt_52w_low":   83.30,
    "tlt_key":       84.76,
}

# ── CME front-month detection ──────────────────────────────────────────────────

def get_front_month_symbol(base: str) -> str:
    """
    Return the active front-month futures symbol for a CME Treasury contract.
    Rolls ~10 calendar days before the first notice day (last business day of
    the month preceding delivery).

    Examples: get_front_month_symbol("ZN") → "/ZNM26"
    """
    today = datetime.date.today()
    year  = today.year

    for _ in range(8):
        for month, code in _FUTURES_MONTHS:
            # First notice day ≈ last calendar day of month before delivery
            first_of_delivery = datetime.date(year, month, 1)
            last_of_prior     = first_of_delivery - datetime.timedelta(days=1)
            roll_date         = last_of_prior - datetime.timedelta(days=10)
            if today <= roll_date:
                return f"/{base}{code}{str(year)[-2:]}"
        year += 1

    return f"/{base}H{str(year)[-2:]}"

# ── Futures yield solver ───────────────────────────────────────────────────────

def futures_price_to_yield(price: float,
                           maturity_years: float,
                           coupon: float = 0.06) -> float | None:
    """
    Solve for the annual yield implied by a futures price.

    Uses the standard bond pricing formula with the CME notional coupon (6%)
    and the contract's assumed maturity. Price is expressed as % of par
    (e.g. 110.5 for a price of 110-16/32).

    Returns yield as a decimal (e.g. 0.0435 for 4.35%), or None on failure.
    """
    if price <= 0 or maturity_years <= 0:
        return None
    n = round(maturity_years * 2)   # semi-annual periods
    c = (coupon / 2) * 100          # semi-annual coupon on $100 face

    def bond_pv(y):
        r = y / 2
        if abs(r) < 1e-10:
            return c * n + 100 - price
        return c * (1 - (1 + r) ** (-n)) / r + 100 / (1 + r) ** n - price

    try:
        return brentq(bond_pv, 0.0001, 0.99)
    except Exception:
        return None

# ── Treasury yield curve ───────────────────────────────────────────────────────

def fetch_yield_curve(target_date: datetime.date | None = None) -> dict | None:
    """
    Fetch the most recent daily Treasury par yield curve from Treasury.gov.
    Returns a dict with keys: date, m3, m6, y1, y2, y5, y7, y10, y20, y30,
    spread_10_2, spread_10_3m.  Returns None on failure.

    Called once at dashboard startup — Treasury updates this once per business day.
    """
    base_date     = target_date or datetime.date.today()
    months_to_try = [
        base_date.strftime("%Y%m"),
        (base_date.replace(day=1) - datetime.timedelta(days=1)).strftime("%Y%m"),
    ]
    ns = {
        "m":    "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata",
        "d":    "http://schemas.microsoft.com/ado/2007/08/dataservices",
        "atom": "http://www.w3.org/2005/Atom",
    }

    for month_str in months_to_try:
        try:
            r = requests.get(TREASURY_XML_URL + month_str, timeout=20)
            r.raise_for_status()
            root    = ElementTree.fromstring(r.content)
            entries = root.findall("atom:entry/atom:content/m:properties", ns)
            if not entries:
                continue

            best    = entries[-1]   # Treasury returns oldest-first, newest-last
            date_el = best.find("d:NEW_DATE", ns)
            date    = date_el.text[:10] if (date_el is not None and date_el.text) else base_date.isoformat()

            def _val(tag):
                el = best.find(f"d:{tag}", ns)
                if el is not None and el.text:
                    try:    return float(el.text)
                    except: pass
                return None

            m3  = _val("BC_1MONTH") or _val("BC_3MONTH")
            m6  = _val("BC_6MONTH")
            y1  = _val("BC_1YEAR")
            y2  = _val("BC_2YEAR")
            y5  = _val("BC_5YEAR")
            y7  = _val("BC_7YEAR")
            y10 = _val("BC_10YEAR")
            y20 = _val("BC_20YEAR")
            y30 = _val("BC_30YEAR")

            return {
                "date":         date,
                "m3": m3, "m6": m6, "y1": y1,  "y2":  y2,
                "y5": y5, "y7": y7, "y10": y10, "y20": y20, "y30": y30,
                "spread_10_2":  round(y10 - y2,  4) if (y10 and y2)  else None,
                "spread_10_3m": round(y10 - m3,  4) if (y10 and m3)  else None,
            }
        except Exception:
            continue
    return None


def fetch_yield_curves() -> tuple[dict | None, dict | None]:
    """
    Fetch the two most recent Treasury yield curves in a single HTTP call.
    Returns (today_curve, yesterday_curve). Either can be None.
    Called once at dashboard startup.
    """
    base_date     = datetime.date.today()
    months_to_try = [
        base_date.strftime("%Y%m"),
        (base_date.replace(day=1) - datetime.timedelta(days=1)).strftime("%Y%m"),
    ]
    ns = {
        "m":    "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata",
        "d":    "http://schemas.microsoft.com/ado/2007/08/dataservices",
        "atom": "http://www.w3.org/2005/Atom",
    }

    def _parse_entry(entry):
        def _val(tag):
            el = entry.find(f"d:{tag}", ns)
            if el is not None and el.text:
                try:    return float(el.text)
                except: pass
            return None
        date_el = entry.find("d:NEW_DATE", ns)
        date    = date_el.text[:10] if (date_el is not None and date_el.text) else ""
        m3  = _val("BC_1MONTH") or _val("BC_3MONTH")
        m6  = _val("BC_6MONTH"); y1  = _val("BC_1YEAR");  y2  = _val("BC_2YEAR")
        y5  = _val("BC_5YEAR");  y7  = _val("BC_7YEAR");  y10 = _val("BC_10YEAR")
        y20 = _val("BC_20YEAR"); y30 = _val("BC_30YEAR")
        return {
            "date": date,
            "m3": m3, "m6": m6, "y1": y1,  "y2":  y2,
            "y5": y5, "y7": y7, "y10": y10, "y20": y20, "y30": y30,
            "spread_10_2":  round(y10 - y2, 4) if (y10 and y2) else None,
            "spread_10_3m": round(y10 - m3, 4) if (y10 and m3) else None,
        }

    for month_str in months_to_try:
        try:
            r = requests.get(TREASURY_XML_URL + month_str, timeout=20)
            r.raise_for_status()
            root    = ElementTree.fromstring(r.content)
            entries = root.findall("atom:entry/atom:content/m:properties", ns)
            if not entries:
                continue
            today     = _parse_entry(entries[-1])
            yesterday = _parse_entry(entries[-2]) if len(entries) >= 2 else None
            return today, yesterday
        except Exception:
            continue
    return None, None

# ── Schwab API — macro quotes ──────────────────────────────────────────────────

def get_macro_quotes(token: str) -> dict:
    """
    Fetch TLT, USO, VIX, and $IRX (3-month T-bill yield index) in one call.
    Returns dict with all values; any failed field returns None.
    Note: $IRX is a CBOE index and updates periodically, not tick-by-tick.
    """
    result = {
        "tlt_price": None, "tlt_change": None, "tlt_chg_pct": None,
        "uso_price": None, "uso_change": None, "uso_chg_pct": None,
        "vix":       None, "vix_change": None, "vix_chg_pct": None,
        "irx_yield": None,
    }
    try:
        r = requests.get(
            f"{SCHWAB_BASE}/quotes",
            headers={"Authorization": f"Bearer {token}"},
            params={"symbols": "TLT,USO,$VIX,$IRX"},
            timeout=15,
        )
        r.raise_for_status()
        qd = r.json()

        def _extract(sym):
            inner = qd.get(sym, {})
            quote = inner.get("quote", inner)
            last  = quote.get("lastPrice") or quote.get("mark")
            prev  = quote.get("closePrice") or last
            if not last:
                return None, None, None
            chg     = last - (prev or last)
            chg_pct = (chg / prev * 100) if prev else 0
            return last, chg, chg_pct

        tlt_p, tlt_c, tlt_pct = _extract("TLT")
        uso_p, uso_c, uso_pct = _extract("USO")
        vix_p, vix_c, vix_pct = _extract("$VIX")

        result.update({
            "tlt_price": tlt_p, "tlt_change": tlt_c, "tlt_chg_pct": tlt_pct,
            "uso_price": uso_p, "uso_change": uso_c, "uso_chg_pct": uso_pct,
            "vix":       vix_p, "vix_change": vix_c, "vix_chg_pct": vix_pct,
        })

        # $IRX is quoted as yield * 10 (e.g. 44.4 = 4.44%)
        irx = qd.get("$IRX", {})
        irx_raw = irx.get("quote", irx).get("lastPrice") or irx.get("quote", irx).get("mark")
        if irx_raw:
            result["irx_yield"] = round(irx_raw / 10, 4)

    except Exception:
        pass

    return result


def get_futures_yields(token: str) -> dict:
    """
    Fetch front-month /ZT (2Y), /ZN (10Y), /ZB (30Y) futures prices and
    convert each to an implied annual yield via the bond pricing equation.

    Returns dict with keys: zt_symbol, zn_symbol, zb_symbol,
    zt_yield, zn_yield, zb_yield (all as decimals, e.g. 0.0435 for 4.35%).
    Any failed value returns None.
    """
    zt_sym = get_front_month_symbol("ZT")
    zn_sym = get_front_month_symbol("ZN")
    zb_sym = get_front_month_symbol("ZB")

    result = {
        "zt_symbol": zt_sym, "zn_symbol": zn_sym, "zb_symbol": zb_sym,
        "zt_yield": None, "zn_yield": None, "zb_yield": None,
    }

    try:
        r = requests.get(
            f"{SCHWAB_BASE}/quotes",
            headers={"Authorization": f"Bearer {token}"},
            params={"symbols": f"{zt_sym},{zn_sym},{zb_sym}"},
            timeout=15,
        )
        r.raise_for_status()
        qd = r.json()

        for sym, base, key in [
            (zt_sym, "ZT", "zt_yield"),
            (zn_sym, "ZN", "zn_yield"),
            (zb_sym, "ZB", "zb_yield"),
        ]:
            inner = qd.get(sym, {})
            quote = inner.get("quote", inner)
            price = quote.get("lastPrice") or quote.get("mark")
            if price:
                maturity = _CONTRACT_MATURITIES[base]
                y = futures_price_to_yield(price, maturity)
                if y is not None:
                    result[key] = round(y * 100, 4)   # store as % (e.g. 4.35)

    except Exception:
        pass

    return result

# ── Regime classification ──────────────────────────────────────────────────────

def classify_macro_regime(tlt_price:  float | None,
                          zb_yield:   float | None,
                          tlt_prev:   float | None = None) -> str:
    """
    Classify macro environment using real-time inputs.

    tlt_price : current TLT price
    zb_yield  : 30Y yield derived from /ZB futures (as %, e.g. 4.85)
    tlt_prev  : TLT price from prior refresh cycle (optional momentum signal)
    """
    t = REGIME_THRESHOLDS

    if zb_yield and zb_yield >= t["yield30_red"]:
        return "RED"
    if tlt_price and tlt_price <= t["tlt_52w_low"] * 1.005:
        return "RED"

    if zb_yield and zb_yield >= t["yield30_orange"]:
        return "ORANGE"
    if tlt_price and tlt_prev and tlt_price < tlt_prev:
        return "ORANGE"

    if zb_yield and zb_yield >= t["yield30_yellow"]:
        return "YELLOW"

    return "GREEN"


def build_regime_reason(tlt_price: float | None,
                        zb_yield:  float | None,
                        zt_yield:  float | None = None,
                        zn_yield:  float | None = None) -> str:
    t     = REGIME_THRESHOLDS
    parts = []
    if zb_yield:
        if zb_yield >= t["yield30_red"]:
            parts.append(f"30Y {zb_yield:.2f}% — danger zone breach")
        elif zb_yield >= t["yield30_orange"]:
            parts.append(f"30Y {zb_yield:.2f}% approaching danger zone")
        else:
            parts.append(f"30Y {zb_yield:.2f}%")
    if zn_yield:
        parts.append(f"10Y {zn_yield:.2f}%")
    if zt_yield:
        parts.append(f"2Y {zt_yield:.2f}%")
    if tlt_price:
        if tlt_price <= t["tlt_52w_low"] * 1.005:
            parts.append(f"TLT ${tlt_price:.2f} near 52-week low")
        elif tlt_price <= t["tlt_key"]:
            parts.append(f"TLT ${tlt_price:.2f} below key level")
    return " | ".join(parts) if parts else "All macro indicators within normal range"


def build_combined_signal(macro_regime: str, gex_regime: str) -> str:
    gex_bearish = gex_regime in ("WEAK_NEG", "STRONG_NEG", "FLIP_ZONE")
    matrix = {
        ("GREEN",  True):  "LONG BIAS",
        ("GREEN",  False): "CONFLICTED — REDUCE SIZE",
        ("YELLOW", True):  "NEUTRAL — WAIT FOR CONFIRMATION",
        ("YELLOW", False): "NEUTRAL — WAIT FOR CONFIRMATION",
        ("ORANGE", True):  "SHORT BIAS",
        ("ORANGE", False): "CONFLICTED — MACRO VS GREEKS",
        ("RED",    True):  "HIGH CONVICTION SHORT",
        ("RED",    False): "CAUTION — MACRO FIGHTING GREEKS",
    }
    return matrix.get((macro_regime, gex_bearish), "NEUTRAL")
