"""Case events, transactional outbox and post-commit delivery ordering.

Events and outbox rows are written in the same transaction as the state change.
`case_events.seq` is allocated before commit and may become visible out of order, so
clients never page by it. A single short serialized dispatcher assigns `delivery_seq`
to rows only after they are visible; clients resume from the last delivery_seq.
"""
from __future__ import annotations

import logging
import threading
from typing import Iterable

from . import clock
from .config import settings
from .db import Database, Tx, dumps
from .util import new_id

log = logging.getLogger("trinetra.events")


def append_event(t: Tx, *, case_id: str, payment_id: str, type: str, actor: str, case_version: int,
                 prev_state: str | None = None, new_state: str | None = None, data: dict | None = None,
                 evidence_ids: Iterable[str] = (), scope: str | None = None) -> str:
    eid = new_id("evt")
    t.execute("INSERT INTO case_events(id, case_id, payment_id, scope, type, actor, prev_state, new_state, case_version,"
              " data, evidence_ids, created_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
              (eid, case_id, payment_id, scope or settings.analyst_scope, type, actor, prev_state, new_state,
               case_version, dumps(data or {}), dumps(list(evidence_ids)), clock.now_ms()))
    return eid


def enqueue(t: Tx, *, case_id: str, kind: str, case_version: int, trigger_key: str, due_ms: int | None = None) -> str | None:
    jid = new_id("job")
    now = clock.now_ms()
    if t.db.dialect == "sqlite":
        sql = ("INSERT OR IGNORE INTO outbox(id, trigger_key, case_id, kind, case_version, status, next_due_ms, created_ms)"
               " VALUES (?,?,?,?,?,'pending',?,?)")
    else:
        sql = ("INSERT INTO outbox(id, trigger_key, case_id, kind, case_version, status, next_due_ms, created_ms)"
               " VALUES (?,?,?,?,?,'pending',?,?) ON CONFLICT (trigger_key) DO NOTHING")
    n = t.rowcount(sql, (jid, trigger_key, case_id, kind, case_version, due_ms or now, now))
    if n:
        _pending_hints.append(jid)
        return jid
    return None


# ---- optional Redis Streams hint (SQL stays authoritative) --------------------
_pending_hints: list[str] = []


def publish_hints() -> None:
    """Called after commit. Failure is harmless: workers poll SQL regardless."""
    if not _pending_hints:
        return
    ids = _pending_hints[:]
    _pending_hints.clear()
    if not settings.redis_url:
        return
    try:
        import redis
        r = redis.Redis.from_url(settings.redis_url, socket_timeout=0.5)
        for j in ids:
            r.xadd("trinetra:jobs", {"job_id": j}, maxlen=10_000, approximate=True)
    except Exception as e:  # noqa: BLE001
        log.info("redis hint skipped: %s", type(e).__name__)


# ---- delivery dispatcher ----------------------------------------------------
def dispatch_once(db: Database, limit: int = 500) -> int:
    def _go(t: Tx) -> int:
        if db.dialect == "postgres":
            cur = t.one("SELECT value FROM delivery_counter WHERE id = 1 FOR UPDATE")
        else:
            cur = t.one("SELECT value FROM delivery_counter WHERE id = 1")
        value = int(cur["value"])
        rows = t.all("SELECT seq FROM case_events WHERE delivery_seq IS NULL ORDER BY seq LIMIT ?", (limit,))
        for r in rows:
            value += 1
            t.execute("UPDATE case_events SET delivery_seq = ? WHERE seq = ?", (value, r["seq"]))
        if rows:
            t.execute("UPDATE delivery_counter SET value = ? WHERE id = 1", (value,))
        return len(rows)
    return db.write(_go)


class Dispatcher(threading.Thread):
    def __init__(self, db: Database, interval: float = 0.15):
        super().__init__(daemon=True, name="delivery-dispatcher")
        self.db = db
        self.interval = interval
        self.stop_evt = threading.Event()
        self.wake = threading.Event()

    def run(self) -> None:
        while not self.stop_evt.is_set():
            try:
                dispatch_once(self.db)
            except Exception as e:  # noqa: BLE001
                log.warning("dispatcher: %s", e)
            self.wake.wait(self.interval)
            self.wake.clear()
        self.db.close_thread()

    def stop(self) -> None:
        self.stop_evt.set()
        self.wake.set()
