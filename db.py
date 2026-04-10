"""
db.py — Greeks Database Access Layer
=====================================
Read-only interface to greeks_history.db populated by collector.py.

All functions return clean pandas DataFrames or scalar values.
All functions return empty DataFrames / None gracefully when:
  - The database file does not exist
  - The requested symbol has no data
  - The date range contains no records
  - Any query or connection error occurs

This module is imported by:
  - gex-dashboard.py  (max pain line, key levels display)
  - backtest_engine.py (future — strategy simulation)
  - Any other tool that needs historical Greeks data

Architecture note:
  Data sources are intentionally separated. This module handles Greeks
  history from the collector database. Price history (OHLCV) lives in
  schwab_price.py. When a paid Greeks API is integrated later, add an
  adapter here that returns the same DataFrame schemas — the dashboard
  and backtest engine will not need to change.
"""

import os
import sqlite3
import datetime
import warnings
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

# ══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════════════════

DB_PATH = os.environ.get("GREEKS_DB_PATH", "greeks_history.db")

# Gamma regime thresholds — overridable per query for backtesting sensitivity
# analysis (e.g. "what if I use a tighter flip zone?")
REGIME_STRONG_POS_THRESHOLD  =  2e9   # net GEX > $2B  → STRONG_POS
REGIME_WEAK_POS_THRESHOLD    =  0.0   # net GEX > $0   → WEAK_POS
REGIME_FLIP_ZONE_PCT         =  0.005 # spot within 0.5% of flip → FLIP_ZONE
REGIME_WEAK_NEG_THRESHOLD    = -2e9   # net GEX > -$2B → WEAK_NEG
                                       # net GEX <= -$2B → STRONG_NEG

# ══════════════════════════════════════════════════════════════════════════════
# CONNECTION
# ══════════════════════════════════════════════════════════════════════════════

def get_connection(path: str = None) -> sqlite3.Connection | None:
    """
    Open a read-only SQLite connection to the Greeks database.
    Returns None if the database file does not exist.
    Caller is responsible for closing the connection.
    """
    db = path or DB_PATH
    if not os.path.exists(db):
        warnings.warn(f"db.py: database not found at '{db}'. "
                      "Start collector.py to begin building history.",
                      stacklevel=2)
        return None
    try:
        # uri=True allows read-only mode via SQLite URI
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True,
                               check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as e:
        warnings.warn(f"db.py: could not connect to database: {e}",
                      stacklevel=2)
        return None


def _empty_summary() -> pd.DataFrame:
    """Return an empty DataFrame matching the summary table schema."""
    cols = [
        "timestamp", "symbol", "spot",
        "net_GEX", "net_VannEX", "net_CharmEX",
        "gamma_flip", "call_wall", "put_wall", "max_pain",
        "total_oi", "total_volume", "iv_atm",
        "gex_0dte", "gex_1_7dte", "gex_8_30dte",
        "gex_31_90dte", "gex_91_180dte", "gex_180plus_dte",
        "regime",
    ]
    return pd.DataFrame(columns=cols)


def _empty_strikes() -> pd.DataFrame:
    """Return an empty DataFrame matching the strike_data table schema."""
    cols = [
        "timestamp", "symbol", "spot", "strike", "dte", "dte_bucket",
        "GEX_call", "GEX_put", "GEX_net",
        "VannEX_call", "VannEX_put", "VannEX_net",
        "CharmEX_call", "CharmEX_put", "CharmEX_net",
        "total_oi", "total_volume", "iv_call", "iv_put",
    ]
    return pd.DataFrame(columns=cols)

# ══════════════════════════════════════════════════════════════════════════════
# REGIME CLASSIFICATION
# ══════════════════════════════════════════════════════════════════════════════

def classify_regime(net_gex: float, spot: float, gamma_flip: float | None,
                    flip_zone_pct: float = REGIME_FLIP_ZONE_PCT) -> str:
    """
    Classify the gamma regime for a single snapshot.

    Regimes:
      STRONG_POS  — net GEX strongly positive, spot above flip
      WEAK_POS    — net GEX positive but near flip or flip unavailable
      FLIP_ZONE   — spot within flip_zone_pct of the gamma flip level
      WEAK_NEG    — net GEX negative but not deeply so
      STRONG_NEG  — net GEX strongly negative

    These labels are the primary filters for backtesting:
      "only take this setup in STRONG_NEG regime"
    """
    if gamma_flip is not None and spot > 0:
        pct_from_flip = abs(spot - gamma_flip) / spot
        if pct_from_flip <= flip_zone_pct:
            return "FLIP_ZONE"

    if net_gex >= REGIME_STRONG_POS_THRESHOLD:
        return "STRONG_POS"
    elif net_gex >= REGIME_WEAK_POS_THRESHOLD:
        return "WEAK_POS"
    elif net_gex >= REGIME_WEAK_NEG_THRESHOLD:
        return "WEAK_NEG"
    else:
        return "STRONG_NEG"

# ══════════════════════════════════════════════════════════════════════════════
# UTILITY QUERIES
# ══════════════════════════════════════════════════════════════════════════════

def get_available_symbols() -> list[str]:
    """
    Return list of symbols that have data in the summary table.
    Returns empty list if database unavailable.
    """
    conn = get_connection()
    if conn is None:
        return []
    try:
        cur = conn.execute(
            "SELECT DISTINCT symbol FROM summary ORDER BY symbol"
        )
        return [row[0] for row in cur.fetchall()]
    except Exception as e:
        warnings.warn(f"db.py get_available_symbols: {e}", stacklevel=2)
        return []
    finally:
        conn.close()


def get_date_range(symbol: str) -> tuple[str | None, str | None]:
    """
    Return (earliest_date, latest_date) for a symbol as ISO date strings.
    Returns (None, None) if no data available.
    """
    conn = get_connection()
    if conn is None:
        return None, None
    try:
        cur = conn.execute(
            """
            SELECT MIN(DATE(timestamp)), MAX(DATE(timestamp))
            FROM summary
            WHERE symbol = ?
            """,
            (symbol,)
        )
        row = cur.fetchone()
        return (row[0], row[1]) if row else (None, None)
    except Exception as e:
        warnings.warn(f"db.py get_date_range: {e}", stacklevel=2)
        return None, None
    finally:
        conn.close()


def get_pull_timestamps(symbol: str,
                        start_date: str | datetime.date,
                        end_date:   str | datetime.date) -> list[str]:
    """
    Return all UTC timestamps where data exists for a symbol in a date range.
    Useful for backtesting to know exactly what intervals are available.
    Returns empty list if no data.
    """
    conn = get_connection()
    if conn is None:
        return []
    try:
        cur = conn.execute(
            """
            SELECT DISTINCT timestamp FROM summary
            WHERE symbol = ?
              AND DATE(timestamp) BETWEEN DATE(?) AND DATE(?)
            ORDER BY timestamp
            """,
            (symbol, str(start_date), str(end_date))
        )
        return [row[0] for row in cur.fetchall()]
    except Exception as e:
        warnings.warn(f"db.py get_pull_timestamps: {e}", stacklevel=2)
        return []
    finally:
        conn.close()

# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD QUERIES  (fast, single-row lookups)
# ══════════════════════════════════════════════════════════════════════════════

def get_latest_summary(symbol: str) -> dict | None:
    """
    Return the most recent summary row for a symbol as a dict.
    Includes all key levels: gamma_flip, call_wall, put_wall, max_pain,
    net_GEX, net_VannEX, net_CharmEX, iv_atm, per-bucket GEX.
    Returns None if no data available.

    Used by the dashboard to overlay key levels without re-computing them.
    """
    conn = get_connection()
    if conn is None:
        return None
    try:
        cur = conn.execute(
            """
            SELECT * FROM summary
            WHERE symbol = ?
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (symbol,)
        )
        row = cur.fetchone()
        if row is None:
            return None
        d = dict(row)
        d["regime"] = classify_regime(
            d.get("net_GEX", 0),
            d.get("spot", 0),
            d.get("gamma_flip"),
        )
        return d
    except Exception as e:
        warnings.warn(f"db.py get_latest_summary: {e}", stacklevel=2)
        return None
    finally:
        conn.close()


def get_max_pain(symbol: str, offset: int = 0) -> float | None:
    """
    Return the max pain strike from the summary table.
    offset=0  → most recent pull
    offset=1  → second most recent (previous pull cycle)
    Returns None if unavailable.

    The dashboard uses offset=1 so the displayed max pain is from the
    last completed collector cycle rather than a potentially mid-cycle value.
    """
    conn = get_connection()
    if conn is None:
        return None
    try:
        cur = conn.execute(
            """
            SELECT max_pain FROM summary
            WHERE symbol = ?
              AND max_pain IS NOT NULL
            ORDER BY timestamp DESC
            LIMIT 1 OFFSET ?
            """,
            (symbol, offset)
        )
        row = cur.fetchone()
        return float(row[0]) if row else None
    except Exception as e:
        warnings.warn(f"db.py get_max_pain: {e}", stacklevel=2)
        return None
    finally:
        conn.close()

# ══════════════════════════════════════════════════════════════════════════════
# BACKTESTING QUERIES  (range queries returning DataFrames)
# ══════════════════════════════════════════════════════════════════════════════

def get_summary_history(symbol: str,
                        start_date: str | datetime.date,
                        end_date:   str | datetime.date) -> pd.DataFrame:
    """
    Return all summary rows for a symbol in a date range.
    One row per collector pull cycle (~15 min intervals during market hours).

    Columns include all summary fields plus a derived 'regime' column.
    The 'timestamp' column is parsed as UTC datetime and set as the index.

    This is the primary input for backtesting:
      df = get_summary_history("SPY", "2025-01-01", "2025-06-01")
      opens = df.between_time("09:30", "09:45")  # opening snapshots

    Returns empty DataFrame if no data available.
    """
    conn = get_connection()
    if conn is None:
        return _empty_summary()
    try:
        df = pd.read_sql_query(
            """
            SELECT * FROM summary
            WHERE symbol = ?
              AND DATE(timestamp) BETWEEN DATE(?) AND DATE(?)
            ORDER BY timestamp
            """,
            conn,
            params=(symbol, str(start_date), str(end_date)),
        )
        if df.empty:
            return _empty_summary()

        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.set_index("timestamp").sort_index()

        # Derive regime for every row
        df["regime"] = df.apply(
            lambda r: classify_regime(
                r.get("net_GEX", 0),
                r.get("spot", 0),
                r.get("gamma_flip"),
            ),
            axis=1,
        )
        return df
    except Exception as e:
        warnings.warn(f"db.py get_summary_history: {e}", stacklevel=2)
        return _empty_summary()
    finally:
        conn.close()


def get_opening_snapshot(symbol: str,
                         date: str | datetime.date) -> dict | None:
    """
    Return the first summary row after 9:30am ET for a given date.
    This is the "opening gamma level" — the primary signal for
    intraday gamma strategy backtesting.

    Returns a dict with all summary fields + regime label.
    Returns None if no data for that date.
    """
    conn = get_connection()
    if conn is None:
        return None
    try:
        # 9:30am ET = 13:30 UTC (EST) or 14:30 UTC (EDT)
        # Query both offsets and take the earliest result after open
        date_str = str(date)
        cur = conn.execute(
            """
            SELECT * FROM summary
            WHERE symbol = ?
              AND DATE(timestamp) = DATE(?)
              AND (
                  TIME(timestamp) >= '13:30:00'
              )
            ORDER BY timestamp ASC
            LIMIT 1
            """,
            (symbol, date_str)
        )
        row = cur.fetchone()
        if row is None:
            # Try EDT offset (14:30 UTC) as fallback
            cur = conn.execute(
                """
                SELECT * FROM summary
                WHERE symbol = ?
                  AND DATE(timestamp) = DATE(?)
                ORDER BY timestamp ASC
                LIMIT 1
                """,
                (symbol, date_str)
            )
            row = cur.fetchone()
        if row is None:
            return None
        d = dict(row)
        d["regime"] = classify_regime(
            d.get("net_GEX", 0),
            d.get("spot", 0),
            d.get("gamma_flip"),
        )
        return d
    except Exception as e:
        warnings.warn(f"db.py get_opening_snapshot: {e}", stacklevel=2)
        return None
    finally:
        conn.close()


def get_strike_history(symbol: str,
                       strike: float,
                       start_date: str | datetime.date,
                       end_date:   str | datetime.date,
                       dte_bucket: str | None = None) -> pd.DataFrame:
    """
    Return per-strike Greeks history for a specific strike over a date range.
    Optionally filter by DTE bucket (e.g. '0DTE', '1-7DTE').

    Useful for analyzing how positioning at a specific level evolved over time.
    E.g. "how did GEX at the 580 strike change in the week before OPEX?"

    Returns empty DataFrame if no data.
    """
    conn = get_connection()
    if conn is None:
        return _empty_strikes()
    try:
        params = [symbol, strike, str(start_date), str(end_date)]
        bucket_clause = ""
        if dte_bucket:
            bucket_clause = "AND dte_bucket = ?"
            params.append(dte_bucket)

        df = pd.read_sql_query(
            f"""
            SELECT * FROM strike_data
            WHERE symbol = ?
              AND strike = ?
              AND DATE(timestamp) BETWEEN DATE(?) AND DATE(?)
              {bucket_clause}
            ORDER BY timestamp
            """,
            conn,
            params=params,
        )
        if df.empty:
            return _empty_strikes()
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.set_index("timestamp").sort_index()
        return df
    except Exception as e:
        warnings.warn(f"db.py get_strike_history: {e}", stacklevel=2)
        return _empty_strikes()
    finally:
        conn.close()


def get_gex_surface(symbol: str,
                    timestamp: str | datetime.datetime) -> pd.DataFrame:
    """
    Return the full GEX profile across all strikes at a single timestamp.
    Reconstructs the exact state of the GEX chart at any historical moment.

    Useful for the backtest tab: "show me the GEX surface at 9:30am on April 3rd"

    timestamp should be an ISO UTC string or datetime, e.g.:
      "2025-04-03T13:30:00Z"

    Finds the closest available timestamp within 10 minutes of the requested time.
    Returns empty DataFrame if nothing found within that window.
    """
    conn = get_connection()
    if conn is None:
        return _empty_strikes()
    try:
        ts_str = (timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")
                  if isinstance(timestamp, datetime.datetime)
                  else str(timestamp))

        # Find closest timestamp within ±10 minutes
        cur = conn.execute(
            """
            SELECT timestamp FROM strike_data
            WHERE symbol = ?
              AND ABS(strftime('%s', timestamp) - strftime('%s', ?)) <= 600
            ORDER BY ABS(strftime('%s', timestamp) - strftime('%s', ?))
            LIMIT 1
            """,
            (symbol, ts_str, ts_str)
        )
        row = cur.fetchone()
        if row is None:
            return _empty_strikes()

        closest_ts = row[0]
        df = pd.read_sql_query(
            """
            SELECT * FROM strike_data
            WHERE symbol = ? AND timestamp = ?
            ORDER BY strike
            """,
            conn,
            params=(symbol, closest_ts),
        )
        if df.empty:
            return _empty_strikes()
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        return df
    except Exception as e:
        warnings.warn(f"db.py get_gex_surface: {e}", stacklevel=2)
        return _empty_strikes()
    finally:
        conn.close()


def get_regime_history(symbol: str,
                       start_date: str | datetime.date,
                       end_date:   str | datetime.date,
                       flip_zone_pct: float = REGIME_FLIP_ZONE_PCT) -> pd.DataFrame:
    """
    Return summary history with regime classification for every row.
    Thin wrapper around get_summary_history that makes the regime column
    the primary focus — useful for filtering backtests by regime.

    Returns DataFrame with columns: spot, net_GEX, gamma_flip, regime
    plus all other summary columns. Timestamp is the index.

    Example usage:
      regimes = get_regime_history("SPY", "2025-01-01", "2025-06-01")
      neg_days = regimes[regimes["regime"].isin(["WEAK_NEG", "STRONG_NEG"])]
    """
    df = get_summary_history(symbol, start_date, end_date)
    if df.empty:
        return df
    # Recompute regime with custom flip_zone_pct if provided
    if flip_zone_pct != REGIME_FLIP_ZONE_PCT:
        df["regime"] = df.apply(
            lambda r: classify_regime(
                r.get("net_GEX", 0),
                r.get("spot", 0),
                r.get("gamma_flip"),
                flip_zone_pct=flip_zone_pct,
            ),
            axis=1,
        )
    return df


def get_session_summary(symbol: str,
                        start_date: str | datetime.date,
                        end_date:   str | datetime.date) -> pd.DataFrame:
    """
    Return one row per trading day with opening and closing snapshot values.
    Pre-computes the most common backtesting joins so strategies don't
    need to reconstruct them from raw 15-minute data every run.

    Columns:
      date, symbol,
      open_spot, open_net_gex, open_gamma_flip, open_max_pain, open_regime,
      open_call_wall, open_put_wall,
      close_spot, close_net_gex, close_gamma_flip,
      intraday_high_spot, intraday_low_spot,
      closed_above_flip  (bool — did price close above the opening gamma flip?)
      flip_tested        (bool — did price touch within 0.1% of gamma flip?)

    Returns empty DataFrame if insufficient data.
    This is the primary input for daily gamma strategy backtesting.
    """
    conn = get_connection()
    if conn is None:
        return pd.DataFrame()
    try:
        df = pd.read_sql_query(
            """
            SELECT * FROM summary
            WHERE symbol = ?
              AND DATE(timestamp) BETWEEN DATE(?) AND DATE(?)
            ORDER BY timestamp
            """,
            conn,
            params=(symbol, str(start_date), str(end_date)),
        )
        if df.empty:
            return pd.DataFrame()

        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df["date"]      = df["timestamp"].dt.date

        rows = []
        for date, group in df.groupby("date"):
            group = group.sort_values("timestamp")
            first = group.iloc[0]
            last  = group.iloc[-1]

            open_flip = first.get("gamma_flip")
            open_spot = first.get("spot", 0)
            close_spot = last.get("spot", 0)

            flip_tested = False
            if open_flip and open_flip > 0:
                spots = group["spot"].values
                flip_tested = any(abs(s - open_flip) / open_flip <= 0.001
                                  for s in spots)

            rows.append({
                "date":               date,
                "symbol":             symbol,
                # Opening values
                "open_spot":          open_spot,
                "open_net_gex":       first.get("net_GEX"),
                "open_gamma_flip":    open_flip,
                "open_max_pain":      first.get("max_pain"),
                "open_call_wall":     first.get("call_wall"),
                "open_put_wall":      first.get("put_wall"),
                "open_iv_atm":        first.get("iv_atm"),
                "open_regime":        classify_regime(
                                          first.get("net_GEX", 0),
                                          open_spot,
                                          open_flip,
                                      ),
                # Closing values
                "close_spot":         close_spot,
                "close_net_gex":      last.get("net_GEX"),
                "close_gamma_flip":   last.get("gamma_flip"),
                # Intraday range
                "intraday_high_spot": group["spot"].max(),
                "intraday_low_spot":  group["spot"].min(),
                # Derived flags
                "closed_above_flip":  (open_flip is not None
                                       and close_spot > open_flip),
                "flip_tested":        flip_tested,
            })

        result = pd.DataFrame(rows).set_index("date")
        return result
    except Exception as e:
        warnings.warn(f"db.py get_session_summary: {e}", stacklevel=2)
        return pd.DataFrame()
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# QUICK TEST
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("db.py — Greeks Database Access Layer")
    print(f"Database path: {DB_PATH}")
    print()

    syms = get_available_symbols()
    if not syms:
        print("No data found. Run collector.py to begin building history.")
    else:
        print(f"Available symbols: {syms}")
        for sym in syms:
            start, end = get_date_range(sym)
            print(f"  {sym}: {start} → {end}")

        sym = syms[0]
        print(f"\nLatest summary for {sym}:")
        s = get_latest_summary(sym)
        if s:
            print(f"  Spot:       ${s.get('spot', 0):.2f}")
            print(f"  Net GEX:    ${s.get('net_GEX', 0)/1e9:.3f}B")
            print(f"  Gamma Flip: ${s.get('gamma_flip', 0):.2f}")
            print(f"  Max Pain:   ${s.get('max_pain', 0):.2f}")
            print(f"  Regime:     {s.get('regime')}")

        print(f"\nMax pain (offset=1) for {sym}: {get_max_pain(sym, offset=1)}")

        start, end = get_date_range(sym)
        if start and end:
            print(f"\nSummary history ({sym}, {start} → {end}):")
            hist = get_summary_history(sym, start, end)
            print(f"  {len(hist)} rows, {hist['regime'].value_counts().to_dict()}")

            print(f"\nSession summary ({sym}):")
            sess = get_session_summary(sym, start, end)
            if not sess.empty:
                print(sess[["open_spot", "open_regime",
                             "closed_above_flip", "flip_tested"]].to_string())
