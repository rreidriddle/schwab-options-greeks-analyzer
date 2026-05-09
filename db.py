"""
db.py — Backtest database read layer.

Read-only interface to greeks_history.db populated by collector.py.
Used exclusively by the BACKTEST tab. All other dashboard data is fetched
live from the Schwab API or Treasury.gov via macro.py and api.py.

Set GREEKS_DB_PATH in .env to point at the collector's database file.
The BACKTEST tab degrades gracefully if the database is not present.
"""

import os
import sqlite3
import datetime
import warnings
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.environ.get("GREEKS_DB_PATH", "greeks_history.db")

REGIME_STRONG_POS_THRESHOLD = 2e9
REGIME_WEAK_POS_THRESHOLD   = 0.0
REGIME_FLIP_ZONE_PCT        = 0.005
REGIME_WEAK_NEG_THRESHOLD   = -2e9

# ── Connection ─────────────────────────────────────────────────────────────────

def get_connection(path: str = None) -> sqlite3.Connection | None:
    db = path or DB_PATH
    if not os.path.exists(db):
        warnings.warn(
            f"db.py: database not found at '{db}'. "
            "Run collector.py to build history. BACKTEST tab will be unavailable.",
            stacklevel=2,
        )
        return None
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True,
                               check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as e:
        warnings.warn(f"db.py: could not connect: {e}", stacklevel=2)
        return None

# ── Empty frame helpers ────────────────────────────────────────────────────────

def _empty_summary() -> pd.DataFrame:
    return pd.DataFrame(columns=[
        "timestamp", "symbol", "spot",
        "net_GEX", "net_VannEX", "net_CharmEX",
        "gamma_flip", "call_wall", "put_wall", "max_pain",
        "total_oi", "total_volume", "iv_atm",
        "gex_0dte", "gex_1_7dte", "gex_8_30dte",
        "gex_31_90dte", "gex_91_180dte", "gex_180plus_dte",
        "regime",
    ])


def _empty_strikes() -> pd.DataFrame:
    return pd.DataFrame(columns=[
        "timestamp", "symbol", "spot", "strike", "dte", "dte_bucket",
        "GEX_call", "GEX_put", "GEX_net",
        "VannEX_call", "VannEX_put", "VannEX_net",
        "CharmEX_call", "CharmEX_put", "CharmEX_net",
        "total_oi", "total_volume", "iv_call", "iv_put",
    ])

# ── Regime classification ──────────────────────────────────────────────────────

def classify_regime(net_gex: float, spot: float,
                    gamma_flip: float | None,
                    flip_zone_pct: float = REGIME_FLIP_ZONE_PCT) -> str:
    if gamma_flip is not None and spot > 0:
        if abs(spot - gamma_flip) / spot <= flip_zone_pct:
            return "FLIP_ZONE"
    if net_gex >= REGIME_STRONG_POS_THRESHOLD: return "STRONG_POS"
    if net_gex >= REGIME_WEAK_POS_THRESHOLD:   return "WEAK_POS"
    if net_gex >= REGIME_WEAK_NEG_THRESHOLD:   return "WEAK_NEG"
    return "STRONG_NEG"

# ── Utility queries ────────────────────────────────────────────────────────────

def get_available_symbols() -> list[str]:
    conn = get_connection()
    if conn is None:
        return []
    try:
        return [row[0] for row in conn.execute(
            "SELECT DISTINCT symbol FROM summary ORDER BY symbol"
        ).fetchall()]
    except Exception as e:
        warnings.warn(f"db.py get_available_symbols: {e}", stacklevel=2)
        return []
    finally:
        conn.close()


def get_date_range(symbol: str) -> tuple[str | None, str | None]:
    conn = get_connection()
    if conn is None:
        return None, None
    try:
        row = conn.execute(
            "SELECT MIN(DATE(timestamp)), MAX(DATE(timestamp)) FROM summary WHERE symbol = ?",
            (symbol,)
        ).fetchone()
        return (row[0], row[1]) if row else (None, None)
    except Exception as e:
        warnings.warn(f"db.py get_date_range: {e}", stacklevel=2)
        return None, None
    finally:
        conn.close()


def get_pull_timestamps(symbol: str,
                        start_date: str | datetime.date,
                        end_date:   str | datetime.date) -> list[str]:
    conn = get_connection()
    if conn is None:
        return []
    try:
        return [row[0] for row in conn.execute(
            """
            SELECT DISTINCT timestamp FROM summary
            WHERE symbol = ?
              AND DATE(timestamp) BETWEEN DATE(?) AND DATE(?)
            ORDER BY timestamp
            """,
            (symbol, str(start_date), str(end_date))
        ).fetchall()]
    except Exception as e:
        warnings.warn(f"db.py get_pull_timestamps: {e}", stacklevel=2)
        return []
    finally:
        conn.close()

# ── Summary queries ────────────────────────────────────────────────────────────

def get_latest_summary(symbol: str) -> dict | None:
    conn = get_connection()
    if conn is None:
        return None
    try:
        row = conn.execute(
            "SELECT * FROM summary WHERE symbol = ? ORDER BY timestamp DESC LIMIT 1",
            (symbol,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["regime"] = classify_regime(d.get("net_GEX", 0), d.get("spot", 0), d.get("gamma_flip"))
        return d
    except Exception as e:
        warnings.warn(f"db.py get_latest_summary: {e}", stacklevel=2)
        return None
    finally:
        conn.close()


def get_max_pain(symbol: str, offset: int = 0) -> float | None:
    conn = get_connection()
    if conn is None:
        return None
    try:
        row = conn.execute(
            """
            SELECT max_pain FROM summary
            WHERE symbol = ? AND max_pain IS NOT NULL
            ORDER BY timestamp DESC LIMIT 1 OFFSET ?
            """,
            (symbol, offset)
        ).fetchone()
        return float(row[0]) if row else None
    except Exception as e:
        warnings.warn(f"db.py get_max_pain: {e}", stacklevel=2)
        return None
    finally:
        conn.close()


def get_summary_history(symbol: str,
                        start_date: str | datetime.date,
                        end_date:   str | datetime.date) -> pd.DataFrame:
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
        df["regime"] = df.apply(
            lambda r: classify_regime(r.get("net_GEX", 0), r.get("spot", 0), r.get("gamma_flip")),
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
    conn = get_connection()
    if conn is None:
        return None
    try:
        date_str = str(date)
        row = conn.execute(
            """
            SELECT * FROM summary
            WHERE symbol = ?
              AND DATE(timestamp) = DATE(?)
              AND TIME(timestamp) >= '13:30:00'
            ORDER BY timestamp ASC LIMIT 1
            """,
            (symbol, date_str)
        ).fetchone()
        if row is None:
            row = conn.execute(
                """
                SELECT * FROM summary
                WHERE symbol = ? AND DATE(timestamp) = DATE(?)
                ORDER BY timestamp ASC LIMIT 1
                """,
                (symbol, date_str)
            ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["regime"] = classify_regime(d.get("net_GEX", 0), d.get("spot", 0), d.get("gamma_flip"))
        return d
    except Exception as e:
        warnings.warn(f"db.py get_opening_snapshot: {e}", stacklevel=2)
        return None
    finally:
        conn.close()

# ── Strike-level queries ───────────────────────────────────────────────────────

def get_gex_surface(symbol: str,
                    timestamp: str | datetime.datetime) -> pd.DataFrame:
    conn = get_connection()
    if conn is None:
        return _empty_strikes()
    try:
        ts_str = (timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")
                  if isinstance(timestamp, datetime.datetime) else str(timestamp))
        row = conn.execute(
            """
            SELECT timestamp FROM strike_data
            WHERE symbol = ?
              AND ABS(strftime('%s', timestamp) - strftime('%s', ?)) <= 600
            ORDER BY ABS(strftime('%s', timestamp) - strftime('%s', ?))
            LIMIT 1
            """,
            (symbol, ts_str, ts_str)
        ).fetchone()
        if row is None:
            return _empty_strikes()
        df = pd.read_sql_query(
            "SELECT * FROM strike_data WHERE symbol = ? AND timestamp = ? ORDER BY strike",
            conn, params=(symbol, row[0]),
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


def get_session_summary(symbol: str,
                        start_date: str | datetime.date,
                        end_date:   str | datetime.date) -> pd.DataFrame:
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
            conn, params=(symbol, str(start_date), str(end_date)),
        )
        if df.empty:
            return pd.DataFrame()
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df["date"]      = df["timestamp"].dt.date
        rows = []
        for date, group in df.groupby("date"):
            group = group.sort_values("timestamp")
            first, last = group.iloc[0], group.iloc[-1]
            open_flip  = first.get("gamma_flip")
            open_spot  = first.get("spot", 0)
            close_spot = last.get("spot", 0)
            flip_tested = False
            if open_flip and open_flip > 0:
                flip_tested = any(
                    abs(s - open_flip) / open_flip <= 0.001
                    for s in group["spot"].values
                )
            rows.append({
                "date":               date,
                "symbol":             symbol,
                "open_spot":          open_spot,
                "open_net_gex":       first.get("net_GEX"),
                "open_gamma_flip":    open_flip,
                "open_max_pain":      first.get("max_pain"),
                "open_call_wall":     first.get("call_wall"),
                "open_put_wall":      first.get("put_wall"),
                "open_iv_atm":        first.get("iv_atm"),
                "open_regime":        classify_regime(first.get("net_GEX", 0), open_spot, open_flip),
                "close_spot":         close_spot,
                "close_net_gex":      last.get("net_GEX"),
                "close_gamma_flip":   last.get("gamma_flip"),
                "intraday_high_spot": group["spot"].max(),
                "intraday_low_spot":  group["spot"].min(),
                "closed_above_flip":  open_flip is not None and close_spot > open_flip,
                "flip_tested":        flip_tested,
            })
        return pd.DataFrame(rows).set_index("date")
    except Exception as e:
        warnings.warn(f"db.py get_session_summary: {e}", stacklevel=2)
        return pd.DataFrame()
    finally:
        conn.close()
