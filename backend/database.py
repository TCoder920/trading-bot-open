"""SQLite persistence layer for the trading bot."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")


def _et_session_day_str() -> str:
    """Current ET session day (calendar date in America/New_York).

    The daily ledger is keyed by the ET session day so it stays consistent with the
    risk engine (``SessionClock.session_day``). Keying by UTC would roll the ledger
    over at 19:00/20:00 ET — mid after-hours session — and split a single trading day.
    """
    return datetime.now(_ET).strftime("%Y-%m-%d")

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "trading_bot.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS strategies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    template TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 0,
    config_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS watchlist_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_class TEXT NOT NULL DEFAULT 'stocks',
    symbol TEXT NOT NULL,
    added_at TEXT NOT NULL,
    UNIQUE(asset_class, symbol)
);

CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    level TEXT NOT NULL DEFAULT 'info',
    category TEXT NOT NULL DEFAULT 'general',
    symbol TEXT,
    strategy TEXT,
    message TEXT NOT NULL,
    details_json TEXT
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity REAL,
    dollar_amount REAL,
    order_type TEXT NOT NULL DEFAULT 'market',
    time_in_force TEXT DEFAULT 'day',
    strategy TEXT,
    strategy_id TEXT,
    asset_class TEXT NOT NULL DEFAULT 'stocks',
    broker TEXT DEFAULT 'alpaca',
    broker_order_id TEXT,
    paper INTEGER DEFAULT 1,
    client_order_id TEXT,
    sizing_mode TEXT,
    notional REAL,
    limit_price REAL,
    stop_price REAL,
    underlying_symbol TEXT,
    option_type TEXT,
    strike REAL,
    expiration TEXT,
    premium REAL,
    quote_currency TEXT,
    risk_approved INTEGER,
    risk_status TEXT DEFAULT 'pending',
    risk_reason TEXT,
    review_status TEXT DEFAULT 'pending',
    review_details_json TEXT,
    execution_status TEXT DEFAULT 'proposed',
    execution_details_json TEXT,
    metadata_json TEXT,
    account TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER REFERENCES orders(id),
    timestamp TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity REAL,
    price REAL,
    dollar_amount REAL,
    strategy TEXT,
    pnl REAL,
    account TEXT
);

CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_at TEXT NOT NULL,
    symbol TEXT NOT NULL,
    quantity REAL NOT NULL,
    avg_cost REAL,
    market_value REAL,
    unrealised_pnl REAL,
    account TEXT,
    source TEXT DEFAULT 'local'
);

CREATE TABLE IF NOT EXISTS backtests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_name TEXT NOT NULL,
    symbols_json TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    starting_cash REAL NOT NULL DEFAULT 100000,
    data_source TEXT NOT NULL DEFAULT 'yahoo',
    status TEXT NOT NULL DEFAULT 'pending',
    result_json TEXT,
    report_path TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS daily_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date TEXT NOT NULL UNIQUE,
    trade_count INTEGER NOT NULL DEFAULT 0,
    realised_loss REAL NOT NULL DEFAULT 0.0,
    open_positions INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS config_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    key TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    source TEXT DEFAULT 'ui'
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS broker_order_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER REFERENCES orders(id),
    event_type TEXT NOT NULL,
    status TEXT,
    broker_order_id TEXT,
    client_order_id TEXT,
    payload_json TEXT,
    response_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reconciliation_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_type TEXT NOT NULL,
    status TEXT NOT NULL,
    summary_json TEXT,
    mismatches_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orb_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id TEXT NOT NULL DEFAULT 'stocks_in_play_orb_v1',
    strategy_name TEXT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL DEFAULT 'buy',
    setup_name TEXT,
    trade_date TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'simulation',
    run_id TEXT,
    timestamp TEXT,
    entry_type TEXT,
    proposed_entry REAL,
    stop_price REAL,
    target_price REAL,
    expected_r REAL,
    quantity REAL,
    risk_dollars REAL,
    risk_pct REAL,
    spread REAL,
    spread_check_status TEXT,
    rvol REAL,
    atr_14 REAL,
    vwap REAL,
    opening_range_high REAL,
    opening_range_low REAL,
    opening_range_open REAL,
    opening_range_close REAL,
    regime_state TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    is_simulation INTEGER DEFAULT 1,
    is_live INTEGER DEFAULT 0,
    invalidation_reason TEXT,
    rejection_reason TEXT,
    data_quality_flags_json TEXT,
    diagnostics_json TEXT,
    order_id INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orb_runtime_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    state_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(strategy_id, trade_date)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(_SCHEMA)
        _migrate(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS broker_order_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER REFERENCES orders(id),
            event_type TEXT NOT NULL,
            status TEXT,
            broker_order_id TEXT,
            client_order_id TEXT,
            payload_json TEXT,
            response_json TEXT,
            error TEXT,
            created_at TEXT NOT NULL
        )"""
    )
    order_cols = {r[1] for r in conn.execute("PRAGMA table_info(orders)").fetchall()}
    order_columns = {
        "notes": "TEXT",
        "time_in_force": "TEXT DEFAULT 'day'",
        "strategy_id": "TEXT",
        "broker": "TEXT DEFAULT 'alpaca'",
        "broker_order_id": "TEXT",
        "paper": "INTEGER DEFAULT 1",
        "client_order_id": "TEXT",
        "sizing_mode": "TEXT",
        "notional": "REAL",
        "limit_price": "REAL",
        "stop_price": "REAL",
        "underlying_symbol": "TEXT",
        "option_type": "TEXT",
        "strike": "REAL",
        "expiration": "TEXT",
        "premium": "REAL",
        "quote_currency": "TEXT",
        "risk_status": "TEXT DEFAULT 'pending'",
        "metadata_json": "TEXT",
    }
    for column, spec in order_columns.items():
        if column not in order_cols:
            conn.execute(f"ALTER TABLE orders ADD COLUMN {column} {spec}")
    _apply_versioned_migrations(conn)


def _apply_versioned_migrations(conn: sqlite3.Connection) -> None:
    migrations = [
        ("20260614_001_order_indexes", _migration_order_indexes),
        ("20260614_002_broker_order_event_indexes", _migration_broker_order_event_indexes),
        ("20260614_003_reconciliation_runs", _migration_reconciliation_runs),
    ]
    applied = {
        r["version"] for r in conn.execute("SELECT version FROM schema_migrations").fetchall()
    }
    for version, migration in migrations:
        if version in applied:
            continue
        migration(conn)
        conn.execute(
            "INSERT INTO schema_migrations (version,applied_at) VALUES (?,?)",
            (version, _now()),
        )


def _migration_order_indexes(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_execution_status ON orders(execution_status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders(symbol)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_client_order_id ON orders(client_order_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_broker_order_id ON orders(broker_order_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_order_id ON trades(order_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_positions_symbol_source ON positions(symbol, source)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_category_timestamp ON logs(category, timestamp)")


def _migration_broker_order_event_indexes(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE INDEX IF NOT EXISTS idx_broker_events_order_id ON broker_order_events(order_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_broker_events_client_order_id ON broker_order_events(client_order_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_broker_events_broker_order_id ON broker_order_events(broker_order_id)")


def _migration_reconciliation_runs(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS reconciliation_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_type TEXT NOT NULL,
            status TEXT NOT NULL,
            summary_json TEXT,
            mismatches_json TEXT,
            created_at TEXT NOT NULL
        )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reconciliation_runs_type_created ON reconciliation_runs(run_type, created_at)")


@contextmanager
def get_conn() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def dict_row(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return dict(row)


def dict_rows(rows: list[sqlite3.Row]) -> list[dict]:
    return [dict(r) for r in rows]


# ── Schema / broker events ──────────────────────────────────────────────

def get_schema_migrations() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM schema_migrations ORDER BY applied_at").fetchall()
    return dict_rows(rows)


def backup_database(destination: Path | None = None) -> dict:
    backup_dir = DB_PATH.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = destination or backup_dir / f"trading_bot_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.db"
    with sqlite3.connect(str(DB_PATH)) as source, sqlite3.connect(str(target)) as backup:
        source.backup(backup)
    return {"path": str(target), "created_at": _now()}


def insert_broker_order_event(
    *,
    order_id: int | None,
    event_type: str,
    status: str | None = None,
    broker_order_id: str | None = None,
    client_order_id: str | None = None,
    payload: dict | None = None,
    response: dict | None = None,
    error: str | None = None,
) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO broker_order_events
            (order_id,event_type,status,broker_order_id,client_order_id,payload_json,response_json,error,created_at)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                order_id,
                event_type,
                status,
                broker_order_id,
                client_order_id,
                json.dumps(payload) if payload is not None else None,
                json.dumps(response) if response is not None else None,
                error,
                _now(),
            ),
        )
        return cur.lastrowid  # type: ignore[return-value]


def insert_reconciliation_run(
    *,
    run_type: str,
    status: str,
    summary: dict | None = None,
    mismatches: list[dict] | None = None,
) -> dict:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO reconciliation_runs
            (run_type,status,summary_json,mismatches_json,created_at)
            VALUES (?,?,?,?,?)""",
            (
                run_type,
                status,
                json.dumps(summary or {}),
                json.dumps(mismatches or []),
                _now(),
            ),
        )
        row = conn.execute("SELECT * FROM reconciliation_runs WHERE id=?", (cur.lastrowid,)).fetchone()
    return _reconciliation_row(row)


def get_reconciliation_runs(run_type: str | None = None, limit: int = 50) -> list[dict]:
    with get_conn() as conn:
        if run_type:
            rows = conn.execute(
                "SELECT * FROM reconciliation_runs WHERE run_type=? ORDER BY id DESC LIMIT ?",
                (run_type, limit),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM reconciliation_runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [_reconciliation_row(r) for r in rows]


def _reconciliation_row(row) -> dict:
    d = dict(row)
    d["summary"] = json.loads(d.pop("summary_json", "{}") or "{}")
    d["mismatches"] = json.loads(d.pop("mismatches_json", "[]") or "[]")
    return d


# ── Logs ────────────────────────────────────────────────────────────────

def insert_log(
    category: str, message: str, *,
    level: str = "info", symbol: str | None = None,
    strategy: str | None = None, details: dict | None = None,
) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO logs (timestamp,level,category,symbol,strategy,message,details_json) VALUES (?,?,?,?,?,?,?)",
            (_now(), level, category, symbol, strategy, message, json.dumps(details) if details else None),
        )
        return cur.lastrowid  # type: ignore[return-value]


def get_logs(
    *, category: str | None = None, symbol: str | None = None,
    strategy: str | None = None, search: str | None = None,
    limit: int = 200, offset: int = 0,
) -> list[dict]:
    clauses, params = [], []
    if category:
        clauses.append("category = ?"); params.append(category)
    if symbol:
        clauses.append("symbol = ?"); params.append(symbol)
    if strategy:
        clauses.append("strategy = ?"); params.append(strategy)
    if search:
        clauses.append("message LIKE ?"); params.append(f"%{search}%")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params += [limit, offset]
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM logs {where} ORDER BY id DESC LIMIT ? OFFSET ?", params
        ).fetchall()
    return dict_rows(rows)


# ── Strategies ──────────────────────────────────────────────────────────

def upsert_strategy(name: str, template: str, config: dict, enabled: bool = False) -> dict:
    now = _now()
    with get_conn() as conn:
        existing = conn.execute("SELECT id FROM strategies WHERE name=?", (name,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE strategies SET template=?,config_json=?,enabled=?,updated_at=? WHERE name=?",
                (template, json.dumps(config), int(enabled), now, name),
            )
        else:
            conn.execute(
                "INSERT INTO strategies (name,template,enabled,config_json,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                (name, template, int(enabled), json.dumps(config), now, now),
            )
        row = conn.execute("SELECT * FROM strategies WHERE name=?", (name,)).fetchone()
    return _strat_row(row)


def get_strategies() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM strategies ORDER BY name").fetchall()
    return [_strat_row(r) for r in rows]


def get_strategy(name: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM strategies WHERE name=?", (name,)).fetchone()
    return _strat_row(row) if row else None


def delete_strategy(name: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM strategies WHERE name=?", (name,))
    return cur.rowcount > 0


def set_active_strategy(name: str) -> dict | None:
    with get_conn() as conn:
        conn.execute("UPDATE strategies SET is_active=0")
        conn.execute("UPDATE strategies SET is_active=1, updated_at=? WHERE name=?", (_now(), name))
        row = conn.execute("SELECT * FROM strategies WHERE name=?", (name,)).fetchone()
    return _strat_row(row) if row else None


def get_active_strategy() -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM strategies WHERE is_active=1").fetchone()
    return _strat_row(row) if row else None


def _strat_row(row) -> dict:
    d = dict(row)
    d["config"] = json.loads(d.pop("config_json", "{}"))
    d["enabled"] = bool(d["enabled"])
    d["is_active"] = bool(d["is_active"])
    return d


# ── Watchlist ───────────────────────────────────────────────────────────

def get_watchlist(asset_class: str = "stocks") -> list[str]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT symbol FROM watchlist_items WHERE asset_class=? ORDER BY symbol",
            (asset_class,),
        ).fetchall()
    return [r["symbol"] for r in rows]


def add_watchlist_symbol(symbol: str, asset_class: str = "stocks") -> bool:
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO watchlist_items (asset_class,symbol,added_at) VALUES (?,?,?)",
                (asset_class, symbol.upper(), _now()),
            )
        return True
    except sqlite3.IntegrityError:
        return False


def remove_watchlist_symbol(symbol: str, asset_class: str = "stocks") -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM watchlist_items WHERE asset_class=? AND symbol=?",
            (asset_class, symbol.upper()),
        )
    return cur.rowcount > 0


def seed_watchlist(symbols: list[str], asset_class: str = "stocks") -> None:
    """Seed watchlist from config defaults if table is empty."""
    with get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) c FROM watchlist_items WHERE asset_class=?", (asset_class,)).fetchone()["c"]
        if count == 0:
            now = _now()
            conn.executemany(
                "INSERT OR IGNORE INTO watchlist_items (asset_class,symbol,added_at) VALUES (?,?,?)",
                [(asset_class, s.upper(), now) for s in symbols],
            )


# ── Orders ──────────────────────────────────────────────────────────────

def insert_order(
    symbol: str, side: str, quantity: float | None, dollar_amount: float | None,
    order_type: str = "market", strategy: str | None = None,
    asset_class: str = "stocks", account: str | None = None,
    broker: str = "alpaca", broker_order_id: str | None = None,
    paper: bool = True, client_order_id: str | None = None,
    sizing_mode: str | None = None, notional: float | None = None, time_in_force: str = "day",
    limit_price: float | None = None, stop_price: float | None = None,
    strategy_id: str | None = None, underlying_symbol: str | None = None,
    option_type: str | None = None, strike: float | None = None,
    expiration: str | None = None, premium: float | None = None,
    quote_currency: str | None = None, metadata: dict | None = None,
) -> dict:
    now = _now()
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO orders
            (timestamp,symbol,side,quantity,dollar_amount,order_type,time_in_force,strategy,strategy_id,
             asset_class,broker,broker_order_id,paper,client_order_id,sizing_mode,notional,limit_price,stop_price,
             underlying_symbol,option_type,strike,expiration,premium,quote_currency,metadata_json,
             account,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                now, symbol.upper(), side, quantity, dollar_amount, order_type, time_in_force,
                strategy, strategy_id or strategy, asset_class, broker, broker_order_id, int(paper),
                client_order_id, sizing_mode, notional, limit_price,
                stop_price, underlying_symbol, option_type, strike, expiration, premium,
                quote_currency, json.dumps(metadata) if metadata else None, account, now, now,
            ),
        )
        row = conn.execute("SELECT * FROM orders WHERE id=?", (cur.lastrowid,)).fetchone()
    return _order_row(row)


def update_order(order_id: int, **fields) -> dict | None:
    if not fields:
        return get_order(order_id)
    fields["updated_at"] = _now()
    sets = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [order_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE orders SET {sets} WHERE id=?", vals)
        row = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    return _order_row(row) if row else None


def get_order(order_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    return _order_row(row) if row else None


def get_orders(*, status: str | None = None, limit: int = 100) -> list[dict]:
    if status:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM orders WHERE execution_status=? ORDER BY id DESC LIMIT ?",
                (status, limit),
            ).fetchall()
    else:
        with get_conn() as conn:
            rows = conn.execute("SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [_order_row(r) for r in rows]


def get_order_by_client_order_id(client_order_id: str) -> dict | None:
    if not client_order_id:
        return None
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM orders WHERE client_order_id=? ORDER BY id DESC LIMIT 1",
            (client_order_id,),
        ).fetchone()
    return _order_row(row) if row else None


def get_orders_by_statuses(statuses: list[str], limit: int = 100) -> list[dict]:
    if not statuses:
        return []
    placeholders = ",".join("?" * len(statuses))
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM orders WHERE execution_status IN ({placeholders}) ORDER BY id DESC LIMIT ?",
            (*statuses, limit),
        ).fetchall()
    return [_order_row(r) for r in rows]


OPEN_EXPOSURE_STATUSES = (
    "risk_approved",
    "pending_broker_submission",
    "accepted",
    "paper_submitted",
    "live_submitted",
    "partially_filled",
)


def get_open_order_exposure(asset_class: str | None = None) -> float:
    placeholders = ",".join("?" * len(OPEN_EXPOSURE_STATUSES))
    params: list[object] = list(OPEN_EXPOSURE_STATUSES)
    sql = f"""
        SELECT COALESCE(SUM(ABS(COALESCE(notional, dollar_amount, 0))), 0) AS exposure
        FROM orders
        WHERE execution_status IN ({placeholders})
          AND LOWER(side) = 'buy'
    """
    if asset_class:
        sql += " AND asset_class=?"
        params.append(asset_class)
    with get_conn() as conn:
        row = conn.execute(sql, params).fetchone()
    return float(row["exposure"] or 0)


def _order_row(row) -> dict:
    d = dict(row)
    for jf in ("review_details_json", "execution_details_json", "metadata_json"):
        raw = d.pop(jf, None)
        d[jf.replace("_json", "")] = json.loads(raw) if raw else None
    d["risk_approved"] = bool(d["risk_approved"]) if d["risk_approved"] is not None else None
    if "paper" in d and d["paper"] is not None:
        d["paper"] = bool(d["paper"])
    return d


# ── Trades ──────────────────────────────────────────────────────────────

def insert_trade(
    order_id: int | None, symbol: str, side: str,
    quantity: float | None, price: float | None, dollar_amount: float | None,
    strategy: str | None = None, pnl: float | None = None, account: str | None = None,
) -> dict:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO trades (order_id,timestamp,symbol,side,quantity,price,dollar_amount,strategy,pnl,account) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (order_id, _now(), symbol.upper(), side, quantity, price, dollar_amount, strategy, pnl, account),
        )
        row = conn.execute("SELECT * FROM trades WHERE id=?", (cur.lastrowid,)).fetchone()
    return dict(row)


def get_trades(*, limit: int = 100) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return dict_rows(rows)


def trade_exists_for_order(order_id: int) -> bool:
    if order_id is None:
        return False
    with get_conn() as conn:
        row = conn.execute("SELECT 1 FROM trades WHERE order_id=? LIMIT 1", (order_id,)).fetchone()
    return row is not None


def get_last_filled_buy(symbol: str) -> dict | None:
    """Most recent filled BUY order for a symbol (used to match an exit to its entry)."""
    with get_conn() as conn:
        row = conn.execute(
            """SELECT * FROM orders
               WHERE UPPER(symbol)=? AND LOWER(side)='buy'
                 AND execution_status IN ('paper_filled','live_filled')
               ORDER BY id DESC LIMIT 1""",
            (symbol.upper(),),
        ).fetchone()
    return _order_row(row) if row else None


# ── Positions ───────────────────────────────────────────────────────────

def save_positions(positions: list[dict], source: str = "local") -> None:
    now = _now()
    with get_conn() as conn:
        conn.execute("DELETE FROM positions WHERE source=?", (source,))
        for p in positions:
            conn.execute(
                "INSERT INTO positions (snapshot_at,symbol,quantity,avg_cost,market_value,unrealised_pnl,account,source) VALUES (?,?,?,?,?,?,?,?)",
                (now, p["symbol"], p.get("quantity", 0), p.get("avg_cost"), p.get("market_value"), p.get("unrealised_pnl"), p.get("account"), source),
            )


def get_positions(source: str | None = None) -> list[dict]:
    with get_conn() as conn:
        if source:
            rows = conn.execute("SELECT * FROM positions WHERE source=? ORDER BY symbol", (source,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM positions ORDER BY symbol").fetchall()
    return dict_rows(rows)


def get_position_exposure(source: str | None = None) -> float:
    with get_conn() as conn:
        if source:
            row = conn.execute(
                "SELECT COALESCE(SUM(ABS(COALESCE(market_value, 0))), 0) AS exposure FROM positions WHERE source=?",
                (source,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COALESCE(SUM(ABS(COALESCE(market_value, 0))), 0) AS exposure FROM positions"
            ).fetchone()
    return float(row["exposure"] or 0)


# ── Backtests ───────────────────────────────────────────────────────────

def insert_backtest(
    strategy_name: str, symbols: list[str], start_date: str, end_date: str,
    starting_cash: float = 100000, data_source: str = "yahoo",
) -> dict:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO backtests (strategy_name,symbols_json,start_date,end_date,starting_cash,data_source,status,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (strategy_name, json.dumps(symbols), start_date, end_date, starting_cash, data_source, "pending", _now()),
        )
        row = conn.execute("SELECT * FROM backtests WHERE id=?", (cur.lastrowid,)).fetchone()
    return _bt_row(row)


def update_backtest(bt_id: int, **fields) -> dict | None:
    if not fields:
        return get_backtest(bt_id)
    sets = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [bt_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE backtests SET {sets} WHERE id=?", vals)
        row = conn.execute("SELECT * FROM backtests WHERE id=?", (bt_id,)).fetchone()
    return _bt_row(row) if row else None


def get_backtest(bt_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM backtests WHERE id=?", (bt_id,)).fetchone()
    return _bt_row(row) if row else None


def get_backtests(*, limit: int = 50) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM backtests ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [_bt_row(r) for r in rows]


def _bt_row(row) -> dict:
    d = dict(row)
    d["symbols"] = json.loads(d.pop("symbols_json", "[]"))
    raw = d.pop("result_json", None)
    d["result"] = json.loads(raw) if raw else None
    return d


# ── Daily ledger ────────────────────────────────────────────────────────

def get_daily_ledger(trade_date: str | None = None) -> dict:
    td = trade_date or _et_session_day_str()
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM daily_ledger WHERE trade_date=?", (td,)).fetchone()
    if row:
        return dict(row)
    return {"trade_date": td, "trade_count": 0, "realised_loss": 0.0, "open_positions": 0}


def update_daily_ledger(trade_count: int | None = None, realised_loss: float | None = None,
                        open_positions: int | None = None, trade_date: str | None = None) -> dict:
    td = trade_date or _et_session_day_str()
    now = _now()
    with get_conn() as conn:
        existing = conn.execute("SELECT * FROM daily_ledger WHERE trade_date=?", (td,)).fetchone()
        if existing:
            d = dict(existing)
            if trade_count is not None:
                d["trade_count"] = trade_count
            if realised_loss is not None:
                d["realised_loss"] = realised_loss
            if open_positions is not None:
                d["open_positions"] = open_positions
            conn.execute(
                "UPDATE daily_ledger SET trade_count=?,realised_loss=?,open_positions=?,updated_at=? WHERE trade_date=?",
                (d["trade_count"], d["realised_loss"], d["open_positions"], now, td),
            )
        else:
            conn.execute(
                "INSERT INTO daily_ledger (trade_date,trade_count,realised_loss,open_positions,updated_at) VALUES (?,?,?,?,?)",
                (td, trade_count or 0, realised_loss or 0.0, open_positions or 0, now),
            )
        row = conn.execute("SELECT * FROM daily_ledger WHERE trade_date=?", (td,)).fetchone()
    return dict(row)


def reset_daily_ledger() -> dict:
    return update_daily_ledger(trade_count=0, realised_loss=0.0, open_positions=0)


# ── Config history ──────────────────────────────────────────────────────

def log_config_change(key: str, old_value: Any, new_value: Any, source: str = "ui") -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO config_history (timestamp,key,old_value,new_value,source) VALUES (?,?,?,?,?)",
            (_now(), key, json.dumps(old_value), json.dumps(new_value), source),
        )


# ── ORB proposals & runtime state ───────────────────────────────────────

def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def insert_orb_proposal(proposal: dict, *, mode: str = "simulation",
                        run_id: str | None = None, trade_date: str | None = None) -> dict:
    """Persist an ORB proposal dict (as produced by Proposal.to_dict())."""
    td = trade_date or _today()
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO orb_proposals
            (strategy_id,strategy_name,symbol,side,setup_name,trade_date,mode,run_id,timestamp,
             entry_type,proposed_entry,stop_price,target_price,expected_r,quantity,risk_dollars,
             risk_pct,spread,spread_check_status,rvol,atr_14,vwap,opening_range_high,
             opening_range_low,opening_range_open,opening_range_close,regime_state,status,
             is_simulation,is_live,invalidation_reason,rejection_reason,
             data_quality_flags_json,diagnostics_json,order_id,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                proposal.get("strategy_id", "stocks_in_play_orb_v1"),
                proposal.get("strategy_name"),
                (proposal.get("symbol") or "").upper(),
                proposal.get("side", "buy"),
                proposal.get("setup_name"),
                td, mode, run_id,
                proposal.get("timestamp"),
                proposal.get("entry_type"),
                proposal.get("proposed_entry"),
                proposal.get("stop_price"),
                proposal.get("target_price"),
                proposal.get("expected_R"),
                proposal.get("quantity"),
                proposal.get("risk_dollars"),
                proposal.get("risk_pct"),
                proposal.get("spread"),
                proposal.get("spread_check_status"),
                proposal.get("rvol"),
                proposal.get("atr_14"),
                proposal.get("vwap"),
                proposal.get("opening_range_high"),
                proposal.get("opening_range_low"),
                proposal.get("opening_range_open"),
                proposal.get("opening_range_close"),
                proposal.get("regime_state"),
                proposal.get("status", "pending"),
                int(bool(proposal.get("is_simulation", True))),
                int(bool(proposal.get("is_live", False))),
                proposal.get("invalidation_reason"),
                proposal.get("rejection_reason"),
                json.dumps(proposal.get("data_quality_flags", [])),
                json.dumps(proposal.get("diagnostics", {})),
                proposal.get("order_id"),
                _now(),
            ),
        )
        row = conn.execute("SELECT * FROM orb_proposals WHERE id=?", (cur.lastrowid,)).fetchone()
    return _orb_row(row)


def update_orb_proposal(proposal_id: int, **fields) -> dict | None:
    if not fields:
        return get_orb_proposal(proposal_id)
    sets = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [proposal_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE orb_proposals SET {sets} WHERE id=?", vals)
        row = conn.execute("SELECT * FROM orb_proposals WHERE id=?", (proposal_id,)).fetchone()
    return _orb_row(row) if row else None


def get_orb_proposal(proposal_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM orb_proposals WHERE id=?", (proposal_id,)).fetchone()
    return _orb_row(row) if row else None


def get_orb_proposals(*, status: str | None = None, trade_date: str | None = None,
                      run_id: str | None = None, limit: int = 200) -> list[dict]:
    clauses, params = [], []
    if status:
        clauses.append("status=?"); params.append(status)
    if trade_date:
        clauses.append("trade_date=?"); params.append(trade_date)
    if run_id:
        clauses.append("run_id=?"); params.append(run_id)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM orb_proposals {where} ORDER BY id DESC LIMIT ?", params
        ).fetchall()
    return [_orb_row(r) for r in rows]


def _orb_row(row) -> dict:
    d = dict(row)
    d["data_quality_flags"] = json.loads(d.pop("data_quality_flags_json", None) or "[]")
    d["diagnostics"] = json.loads(d.pop("diagnostics_json", None) or "{}")
    d["is_simulation"] = bool(d.get("is_simulation"))
    d["is_live"] = bool(d.get("is_live"))
    return d


def set_orb_runtime_state(strategy_id: str, state: dict, trade_date: str | None = None) -> dict:
    td = trade_date or _today()
    now = _now()
    payload = json.dumps(state)
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM orb_runtime_state WHERE strategy_id=? AND trade_date=?",
            (strategy_id, td),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE orb_runtime_state SET state_json=?,updated_at=? WHERE id=?",
                (payload, now, existing["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO orb_runtime_state (strategy_id,trade_date,state_json,updated_at) VALUES (?,?,?,?)",
                (strategy_id, td, payload, now),
            )
        row = conn.execute(
            "SELECT * FROM orb_runtime_state WHERE strategy_id=? AND trade_date=?",
            (strategy_id, td),
        ).fetchone()
    d = dict(row)
    d["state"] = json.loads(d.pop("state_json"))
    return d


def get_orb_runtime_state(strategy_id: str, trade_date: str | None = None) -> dict | None:
    td = trade_date or _today()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM orb_runtime_state WHERE strategy_id=? AND trade_date=?",
            (strategy_id, td),
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["state"] = json.loads(d.pop("state_json"))
    return d


def reset_orb_state(strategy_id: str, trade_date: str | None = None) -> dict:
    """Clear today's ORB runtime state and pending proposals for the strategy."""
    td = trade_date or _today()
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM orb_runtime_state WHERE strategy_id=? AND trade_date=?",
            (strategy_id, td),
        )
        cur = conn.execute(
            "DELETE FROM orb_proposals WHERE strategy_id=? AND trade_date=? AND status='pending'",
            (strategy_id, td),
        )
        cleared = cur.rowcount
    return {"strategy_id": strategy_id, "trade_date": td, "cleared_pending_proposals": cleared}
