"""Database layer: SQLite WAL (single host) and PostgreSQL (concurrent profile).

SQL is written with `?` placeholders and translated for psycopg. Writes go through
`Database.write(fn)` which retries transient conflicts with bounded backoff using the
same command inputs. PostgreSQL coordination is row-scoped: `Tx.lock_rows` takes
`FOR UPDATE` locks in a consistent order and `Tx.lock_keys` takes transaction-scoped
advisory locks keyed per entity (never a database-wide lock).
"""
from __future__ import annotations

import json
import random
import sqlite3
import threading
import time
import zlib
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterable, TypeVar

T = TypeVar("T")

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (k TEXT PRIMARY KEY, v TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS owners (
  id TEXT PRIMARY KEY,
  token_hash TEXT NOT NULL UNIQUE,
  created_ms BIGINT NOT NULL,
  legacy_demo INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS accounts (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL REFERENCES owners(id),
  display_name TEXT NOT NULL,
  account_ref TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL DEFAULT 'active',
  created_ms BIGINT NOT NULL,
  legacy_demo INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_accounts_owner ON accounts(owner_id, created_ms);

CREATE TABLE IF NOT EXISTS counterparties (
  id TEXT PRIMARY KEY,
  account_ref TEXT NOT NULL UNIQUE,
  sandbox_account_id TEXT REFERENCES accounts(id),
  created_ms BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS beneficiaries (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL REFERENCES owners(id),
  counterparty_id TEXT NOT NULL REFERENCES counterparties(id),
  display_name TEXT NOT NULL,
  account_ref TEXT NOT NULL,
  created_ms BIGINT NOT NULL,
  removed_ms BIGINT,
  legacy_demo INTEGER NOT NULL DEFAULT 0,
  UNIQUE (owner_id, account_ref)
);
CREATE INDEX IF NOT EXISTS ix_benef_owner ON beneficiaries(owner_id, created_ms);

CREATE TABLE IF NOT EXISTS restrictions (
  id TEXT PRIMARY KEY,
  scope_type TEXT NOT NULL,
  scope_id TEXT NOT NULL,
  reason TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  created_by TEXT NOT NULL,
  created_ms BIGINT NOT NULL,
  lifted_ms BIGINT,
  case_id TEXT
);
CREATE INDEX IF NOT EXISTS ix_restr_scope ON restrictions(scope_type, scope_id, active);

CREATE TABLE IF NOT EXISTS calls (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL REFERENCES owners(id),
  status TEXT NOT NULL,
  consent_ms BIGINT NOT NULL,
  created_ms BIGINT NOT NULL,
  finished_ms BIGINT,
  expires_ms BIGINT NOT NULL,
  duration_ms BIGINT NOT NULL DEFAULT 0,
  voiced_ms BIGINT NOT NULL DEFAULT 0,
  usable INTEGER NOT NULL DEFAULT 0,
  quality_reason TEXT,
  language TEXT,
  language_supported INTEGER,
  analysis TEXT,
  payment_id TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS ix_calls_owner ON calls(owner_id, created_ms);

CREATE TABLE IF NOT EXISTS payments (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL REFERENCES owners(id),
  account_id TEXT NOT NULL REFERENCES accounts(id),
  beneficiary_id TEXT NOT NULL REFERENCES beneficiaries(id),
  counterparty_id TEXT NOT NULL REFERENCES counterparties(id),
  amount_minor BIGINT NOT NULL CHECK (amount_minor > 0),
  currency TEXT NOT NULL,
  channel TEXT NOT NULL,
  direction TEXT NOT NULL DEFAULT 'outgoing' CHECK (direction IN ('outgoing', 'incoming')),
  remark TEXT,
  call_id TEXT NOT NULL REFERENCES calls(id),
  idem_key TEXT NOT NULL,
  fingerprint TEXT NOT NULL,
  decision TEXT NOT NULL,
  policy_version TEXT NOT NULL,
  state TEXT NOT NULL,
  reasons TEXT NOT NULL,
  signals TEXT NOT NULL,
  receipt TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  created_ms BIGINT NOT NULL,
  updated_ms BIGINT NOT NULL,
  legacy_demo INTEGER NOT NULL DEFAULT 0,
  UNIQUE (owner_id, idem_key)
);
CREATE INDEX IF NOT EXISTS ix_pay_owner ON payments(owner_id, created_ms);
CREATE INDEX IF NOT EXISTS ix_pay_created ON payments(created_ms);
CREATE INDEX IF NOT EXISTS ix_pay_cp ON payments(counterparty_id, created_ms);

CREATE TABLE IF NOT EXISTS settlements (
  id TEXT PRIMARY KEY,
  payment_id TEXT NOT NULL UNIQUE REFERENCES payments(id),
  account_id TEXT NOT NULL REFERENCES accounts(id),
  counterparty_id TEXT NOT NULL REFERENCES counterparties(id),
  owner_id TEXT NOT NULL,
  amount_minor BIGINT NOT NULL,
  created_ms BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_settle_cp ON settlements(counterparty_id, created_ms);
CREATE INDEX IF NOT EXISTS ix_settle_account ON settlements(account_id, created_ms);

CREATE TABLE IF NOT EXISTS challenges (
  id TEXT PRIMARY KEY,
  payment_id TEXT NOT NULL REFERENCES payments(id),
  owner_id TEXT NOT NULL,
  code_hash TEXT NOT NULL,
  salt TEXT NOT NULL,
  expires_ms BIGINT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL,
  status TEXT NOT NULL,
  issued_by TEXT NOT NULL,
  created_ms BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_chal_payment ON challenges(payment_id, status);

CREATE TABLE IF NOT EXISTS cases (
  id TEXT PRIMARY KEY,
  payment_id TEXT NOT NULL UNIQUE REFERENCES payments(id),
  owner_id TEXT NOT NULL,
  scope TEXT NOT NULL,
  state TEXT NOT NULL,
  severity TEXT NOT NULL,
  priority INTEGER NOT NULL,
  hold_active INTEGER NOT NULL DEFAULT 0,
  version INTEGER NOT NULL DEFAULT 1,
  verdict TEXT,
  verdict_source TEXT,
  report TEXT,
  created_ms BIGINT NOT NULL,
  updated_ms BIGINT NOT NULL,
  first_disposition_ms BIGINT,
  closed_ms BIGINT
);
CREATE INDEX IF NOT EXISTS ix_cases_state ON cases(scope, state, created_ms);

CREATE TABLE IF NOT EXISTS evidence (
  id TEXT PRIMARY KEY,
  payment_id TEXT,
  call_id TEXT,
  case_id TEXT,
  source TEXT NOT NULL,
  kind TEXT NOT NULL,
  status TEXT NOT NULL,
  model_id TEXT,
  revision TEXT,
  score_scale TEXT,
  score DOUBLE PRECISION,
  flagged INTEGER,
  review_only INTEGER NOT NULL DEFAULT 1,
  payload TEXT NOT NULL,
  created_ms BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ev_payment ON evidence(payment_id);
CREATE INDEX IF NOT EXISTS ix_ev_case ON evidence(case_id);

CREATE TABLE IF NOT EXISTS case_events (
  seq {SERIAL},
  id TEXT NOT NULL UNIQUE,
  case_id TEXT NOT NULL REFERENCES cases(id),
  payment_id TEXT NOT NULL,
  scope TEXT NOT NULL,
  type TEXT NOT NULL,
  actor TEXT NOT NULL,
  prev_state TEXT,
  new_state TEXT,
  case_version INTEGER NOT NULL,
  data TEXT NOT NULL,
  evidence_ids TEXT NOT NULL,
  created_ms BIGINT NOT NULL,
  delivery_seq BIGINT UNIQUE
);
CREATE INDEX IF NOT EXISTS ix_events_case ON case_events(case_id, seq);
CREATE INDEX IF NOT EXISTS ix_events_undelivered ON case_events(delivery_seq, seq);

CREATE TABLE IF NOT EXISTS delivery_counter (id INTEGER PRIMARY KEY, value BIGINT NOT NULL);

CREATE TABLE IF NOT EXISTS outbox (
  id TEXT PRIMARY KEY,
  trigger_key TEXT NOT NULL UNIQUE,
  case_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  case_version INTEGER NOT NULL,
  status TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 5,
  next_due_ms BIGINT NOT NULL,
  lease_token TEXT,
  lease_until_ms BIGINT,
  last_error TEXT,
  created_ms BIGINT NOT NULL,
  completed_ms BIGINT
);
CREATE INDEX IF NOT EXISTS ix_outbox_due ON outbox(status, next_due_ms);

CREATE TABLE IF NOT EXISTS proposals (
  id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL REFERENCES cases(id),
  action TEXT NOT NULL,
  params TEXT NOT NULL,
  rationale TEXT NOT NULL,
  evidence_ids TEXT NOT NULL,
  tier INTEGER NOT NULL,
  status TEXT NOT NULL,
  case_version INTEGER NOT NULL,
  created_by TEXT NOT NULL,
  created_ms BIGINT NOT NULL,
  reviewed_by TEXT,
  reviewed_ms BIGINT,
  review_rationale TEXT
);
CREATE INDEX IF NOT EXISTS ix_prop_case ON proposals(case_id, status);

CREATE TABLE IF NOT EXISTS watches (
  id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL UNIQUE REFERENCES cases(id),
  counterparty_id TEXT NOT NULL,
  status TEXT NOT NULL,
  horizon_ms BIGINT NOT NULL,
  interval_ms BIGINT NOT NULL,
  next_due_ms BIGINT NOT NULL,
  cursor_ms BIGINT NOT NULL,
  checks INTEGER NOT NULL DEFAULT 0,
  last_result TEXT,
  created_ms BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_watch_due ON watches(status, next_due_ms);

CREATE TABLE IF NOT EXISTS adjudications (
  id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL REFERENCES cases(id),
  payment_id TEXT NOT NULL,
  label TEXT NOT NULL,
  reviewer TEXT NOT NULL,
  rationale TEXT NOT NULL,
  supersedes TEXT,
  created_ms BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_adj_case ON adjudications(case_id, created_ms);

CREATE TABLE IF NOT EXISTS tool_audit (
  id TEXT PRIMARY KEY,
  case_id TEXT,
  actor TEXT NOT NULL,
  role TEXT NOT NULL,
  tool TEXT NOT NULL,
  args TEXT NOT NULL,
  outcome TEXT NOT NULL,
  created_ms BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_audit_case ON tool_audit(case_id, created_ms);

CREATE TABLE IF NOT EXISTS command_results (
  command_key TEXT PRIMARY KEY,
  actor TEXT NOT NULL,
  fingerprint TEXT NOT NULL,
  result TEXT NOT NULL,
  created_ms BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS analyst_workspace_runs (
  id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  case_version INTEGER NOT NULL,
  model TEXT NOT NULL,
  findings TEXT NOT NULL,
  created_ms BIGINT NOT NULL,
  traced INTEGER NOT NULL,
  disposition TEXT,
  note TEXT,
  reviewed_ms BIGINT,
  UNIQUE (case_id, case_version)
);
"""


class ConflictRetry(Exception):
    """Transient conflict (deadlock, serialization failure, busy database)."""


def dumps(v: Any) -> str:
    return json.dumps(v, separators=(",", ":"), sort_keys=True, default=str)


def loads(v: str | None, default: Any = None) -> Any:
    if v is None:
        return default
    return json.loads(v)


class Tx:
    def __init__(self, db: "Database", raw):
        self.db = db
        self.raw = raw

    def _sql(self, sql: str) -> str:
        if self.db.dialect == "postgres":
            return sql.replace("%", "%%").replace("?", "%s")
        return sql

    def execute(self, sql: str, params: Iterable[Any] = ()) -> Any:
        cur = self.raw.cursor()
        cur.execute(self._sql(sql), tuple(params))
        return cur

    def one(self, sql: str, params: Iterable[Any] = ()) -> dict | None:
        cur = self.execute(sql, params)
        row = cur.fetchone()
        return self._row(cur, row)

    def all(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        cur = self.execute(sql, params)
        return [self._row(cur, r) for r in cur.fetchall()]

    def scalar(self, sql: str, params: Iterable[Any] = ()) -> Any:
        row = self.execute(sql, params).fetchone()
        if row is None:
            return None
        if isinstance(row, dict):
            return next(iter(row.values()))
        return row[0]

    def rowcount(self, sql: str, params: Iterable[Any] = ()) -> int:
        return self.execute(sql, params).rowcount

    def _row(self, cur, row) -> dict | None:
        if row is None:
            return None
        if isinstance(row, dict):
            return row
        if isinstance(row, sqlite3.Row):
            return dict(row)
        return {d[0]: v for d, v in zip(cur.description, row)}

    def lock_rows(self, table: str, ids: Iterable[str]) -> None:
        """Row locks in sorted id order (PostgreSQL). SQLite holds the single writer lock already."""
        ids = sorted({i for i in ids if i})
        if self.db.dialect != "postgres" or not ids:
            return
        self.execute(f"SELECT id FROM {table} WHERE id = ANY(?) ORDER BY id FOR UPDATE", (ids,))

    def lock_keys(self, *keys: str) -> None:
        """Transaction-scoped keyed locks for entities that may not have a row yet."""
        if self.db.dialect != "postgres":
            return
        for k in sorted(set(keys)):
            self.execute("SELECT pg_advisory_xact_lock(?)", (zlib.crc32(k.encode()) - 2**31,))


class Database:
    def __init__(self, url: str):
        self.url = url
        self._local = threading.local()
        if url.startswith("sqlite:///"):
            self.dialect = "sqlite"
            self.path = url[len("sqlite:///"):]
            if self.path != ":memory:":
                Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        elif url.startswith(("postgresql://", "postgres://")):
            self.dialect = "postgres"
            import psycopg  # noqa: F401
        else:
            raise ValueError(f"unsupported database url: {url.split(':')[0]}")
        self.stats = {"retries": 0, "conflicts": 0}
        self._stats_lock = threading.Lock()

    # -- connections ---------------------------------------------------
    def _conn(self):
        c = getattr(self._local, "conn", None)
        if c is not None and self.dialect == "postgres" and (c.closed or c.broken):
            self._local.conn = None
            c = None
        if c is not None:
            return c
        if self.dialect == "sqlite":
            c = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False, timeout=10)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            c.execute("PRAGMA foreign_keys=ON")
            c.execute("PRAGMA busy_timeout=5000")
        else:
            import psycopg
            from psycopg.rows import dict_row
            c = psycopg.connect(self.url, autocommit=True, row_factory=dict_row)
        self._local.conn = c
        return c

    def close_thread(self) -> None:
        c = getattr(self._local, "conn", None)
        if c is not None:
            try:
                c.close()
            except Exception:  # noqa: BLE001
                pass
            finally:
                self._local.conn = None

    @contextmanager
    def tx(self, write: bool = True):
        c = self._conn()
        if self.dialect == "sqlite":
            c.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            try:
                yield Tx(self, c)
                c.execute("COMMIT")
            except BaseException:
                c.execute("ROLLBACK")
                raise
        else:
            import psycopg
            try:
                with c.transaction():
                    yield Tx(self, c)
            except psycopg.OperationalError:
                # Connection lost (e.g. database restart): discard it so the next attempt reconnects.
                self.close_thread()
                raise

    # -- error classification -----------------------------------------
    def is_integrity(self, e: BaseException) -> bool:
        if isinstance(e, sqlite3.IntegrityError):
            return True
        try:
            import psycopg
            return isinstance(e, psycopg.errors.IntegrityError)
        except ImportError:
            return False

    def is_transient(self, e: BaseException) -> bool:
        if isinstance(e, ConflictRetry):
            return True
        if isinstance(e, sqlite3.OperationalError) and "locked" in str(e).lower():
            return True
        try:
            import psycopg
            return isinstance(e, (psycopg.errors.DeadlockDetected, psycopg.errors.SerializationFailure,
                                  psycopg.errors.LockNotAvailable, psycopg.OperationalError))
        except ImportError:
            return False

    def write(self, fn: Callable[[Tx], T], retries: int = 6) -> T:
        """Run fn in a write transaction, retrying transient conflicts with bounded backoff."""
        delay = 0.01
        for attempt in range(retries + 1):
            try:
                with self.tx(write=True) as t:
                    return fn(t)
            except Exception as e:  # noqa: BLE001
                if attempt < retries and self.is_transient(e):
                    with self._stats_lock:
                        self.stats["retries"] += 1
                    time.sleep(delay + random.random() * delay)
                    delay = min(delay * 2, 0.5)
                    continue
                raise
        raise RuntimeError("unreachable")

    def read(self, fn: Callable[[Tx], T], retries: int = 2) -> T:
        for attempt in range(retries + 1):
            try:
                with self.tx(write=False) as t:
                    return fn(t)
            except Exception as e:  # noqa: BLE001
                if attempt < retries and self.is_transient(e):
                    time.sleep(0.05 * (attempt + 1))
                    continue
                raise
        raise RuntimeError("unreachable")

    # -- schema ---------------------------------------------------------
    def _upgrade_transfer_direction(self, t: Tx) -> None:
        def columns(table: str) -> set[str]:
            if self.dialect == "sqlite":
                return {r["name"] for r in t.all(f"PRAGMA table_info({table})")}
            return {r["column_name"] for r in t.all(
                "SELECT column_name FROM information_schema.columns"
                " WHERE table_schema = current_schema() AND table_name = ?", (table,))}

        payment_columns = columns("payments")
        if payment_columns and "direction" not in payment_columns:
            t.execute("ALTER TABLE payments ADD COLUMN direction TEXT NOT NULL DEFAULT 'outgoing'"
                      " CHECK (direction IN ('outgoing', 'incoming'))")
        if "from_account_id" in columns("settlements"):
            # The existing column always holds the account owned by the payment's customer.
            t.execute("ALTER TABLE settlements RENAME COLUMN from_account_id TO account_id")
            t.execute("DROP INDEX IF EXISTS ix_settle_from")

    def migrate(self) -> None:
        serial = "INTEGER PRIMARY KEY AUTOINCREMENT" if self.dialect == "sqlite" else "BIGSERIAL PRIMARY KEY"
        ddl = SCHEMA.replace("{SERIAL}", serial)
        if self.dialect == "sqlite":
            ddl = ddl.replace("DOUBLE PRECISION", "REAL")

        def _migrate(t: Tx):
            if self.dialect == "postgres":
                t.execute("SELECT pg_advisory_xact_lock(424242)")  # serialize concurrent migrations only
            self._upgrade_transfer_direction(t)
            for stmt in ddl.split(";"):
                if stmt.strip():
                    t.execute(stmt.strip())
            if self.dialect == "sqlite":
                t.execute("INSERT OR IGNORE INTO delivery_counter(id, value) VALUES (1, 0)")
                t.execute("INSERT OR REPLACE INTO schema_meta(k, v) VALUES ('version', ?)", (str(SCHEMA_VERSION),))
            else:
                t.execute("INSERT INTO delivery_counter(id, value) VALUES (1, 0) ON CONFLICT (id) DO NOTHING")
                t.execute("INSERT INTO schema_meta(k, v) VALUES ('version', ?) ON CONFLICT (k) DO UPDATE SET v = EXCLUDED.v",
                          (str(SCHEMA_VERSION),))
        self.write(_migrate)

    def reset_all(self) -> None:
        """Test helper: wipe every table."""
        tables = ["command_results", "tool_audit", "adjudications", "watches", "proposals", "outbox",
                  "case_events", "evidence", "challenges", "settlements", "cases", "payments", "calls",
                  "restrictions", "beneficiaries", "counterparties", "accounts", "owners"]
        def _wipe(t: Tx):
            for tb in tables:
                t.execute(f"DELETE FROM {tb}")
            t.execute("UPDATE delivery_counter SET value = 0")
        self.write(_wipe)


_db: Database | None = None


def get_db() -> Database:
    global _db
    if _db is None:
        from .config import settings
        _db = Database(settings.database_url)
        _db.migrate()
    return _db


def set_db(db: Database | None) -> None:
    global _db
    _db = db
