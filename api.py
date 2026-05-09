"""
api.py — Schwab live market data for the dashboard.

Covers real-time quotes needed each refresh cycle:
  - SPY spot price
  - SPY options chain
  - VIX quote
  - Concurrent fetch of chain + VIX

Macro quotes (TLT, USO, VIX, $IRX) and bond futures (/ZT, /ZN, /ZB)
are handled by macro.py.  Historical price bars are in schwab_price.py.
"""

import time
import datetime
import threading
import requests

SCHWAB_BASE = "https://api.schwabapi.com/marketdata/v1"
SYMBOL      = "SPY"
STRIKE_PCT  = 0.08
MAX_DTE     = 45

# ── Spot price ─────────────────────────────────────────────────────────────────

def fetch_spot(token: str, symbol: str = SYMBOL) -> float | None:
    try:
        r = requests.get(
            f"{SCHWAB_BASE}/quotes",
            headers={"Authorization": f"Bearer {token}"},
            params={"symbols": symbol},
            timeout=10,
        )
        r.raise_for_status()
        qd    = r.json()
        inner = qd.get(symbol, list(qd.values())[0] if qd else {})
        return (inner.get("quote", {}).get("lastPrice")
                or inner.get("lastPrice")
                or inner.get("mark"))
    except Exception:
        return None

# ── Options chain ──────────────────────────────────────────────────────────────

def get_options_chain(token: str, spot: float,
                      symbol: str     = SYMBOL,
                      strike_pct: float = STRIKE_PCT,
                      max_dte: int    = MAX_DTE) -> dict | None:
    headers   = {"Authorization": f"Bearer {token}"}
    from_date = datetime.date.today().strftime("%Y-%m-%d")
    to_date   = (datetime.date.today() +
                 datetime.timedelta(days=max_dte)).strftime("%Y-%m-%d")
    params = {
        "symbol":           symbol,
        "contractType":     "ALL",
        "includeQuotes":    "TRUE",
        "optionType":       "ALL",
        "range":            "ALL",
        "fromDate":         from_date,
        "toDate":           to_date,
        "strikePriceAbove": round(spot * (1 - strike_pct), 2),
        "strikePriceBelow": round(spot * (1 + strike_pct), 2),
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
            return None
        except Exception:
            return None
    return None

# ── VIX ────────────────────────────────────────────────────────────────────────

def fetch_vix(token: str) -> dict | None:
    try:
        r = requests.get(
            f"{SCHWAB_BASE}/quotes",
            headers={"Authorization": f"Bearer {token}"},
            params={"symbols": "$VIX"},
            timeout=10,
        )
        r.raise_for_status()
        inner = r.json().get("$VIX", {})
        quote = inner.get("quote", inner)
        last  = quote.get("lastPrice") or quote.get("mark") or quote.get("closePrice")
        prev  = quote.get("closePrice") or last
        if not last:
            return None
        change = last - (prev or last)
        return {
            "last":       last,
            "prev_close": prev,
            "change":     change,
            "change_pct": (change / prev * 100) if prev else 0,
        }
    except Exception:
        return None

# ── Concurrent fetch ───────────────────────────────────────────────────────────

def fetch_live_data(token: str) -> tuple[tuple[dict, float] | None, dict | None]:
    """
    Fetch SPY options chain and VIX concurrently.

    Returns ((chain, spot), vix_data).
    chain is the raw Schwab API response dict — call greeks.parse_chain(chain)
    to convert it to a DataFrame.
    Either element can be None on failure.
    """
    chain_result = [None]   # (chain_dict, spot)
    vix_result   = [None]

    def _fetch_spy():
        spot = fetch_spot(token)
        if not spot:
            return
        time.sleep(1)
        chain = get_options_chain(token, spot)
        if chain:
            chain_result[0] = (chain, spot)

    def _fetch_vix():
        vix_result[0] = fetch_vix(token)

    t1 = threading.Thread(target=_fetch_spy, daemon=True)
    t2 = threading.Thread(target=_fetch_vix, daemon=True)
    t1.start(); t2.start()
    t1.join();  t2.join()

    return chain_result[0], vix_result[0]
