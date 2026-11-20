"""Concurrency and recovery. Runs on SQLite and, with TRINETRA_TEST_PG_URL, on live PostgreSQL."""
from __future__ import annotations

import asyncio
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from app import clock, customer
from app.config import settings
from app.events import append_event, dispatch_once, enqueue
from app.soc import actions
from app.soc.worker import FenceLost, claim, commit_investigation, investigate, run_once
from app.util import ApiError


def _submit(owner_id, key, body):
    try:
        return asyncio.run(customer.submit_payment(owner_id, key, body))
    except ApiError as e:
        return e.status_code, e.detail
    finally:
        from app.db import get_db
        get_db().close_thread()


def _owner_of(h, headers):
    from app.util import sha256
    return h.db.read(lambda t: t.scalar("SELECT id FROM owners WHERE token_hash = ?", (sha256(headers["Authorization"][7:]),)))


def _setup_payment(h, amount=50_000_00, ref="HDFC00012345"):
    s = h.session()
    acct, ben = h.onboard(s, ref=ref)
    cid = h.capture(s)
    return s, _owner_of(h, s), {"account_id": acct, "beneficiary_id": ben, "amount_minor": amount,
                                "channel": "IMPS", "remark": None, "call_id": cid}


def test_100_simultaneous_retries_one_key(h):
    s, owner, body = _setup_payment(h, amount=1_000_00)
    key = uuid.uuid4().hex
    with ThreadPoolExecutor(max_workers=20) as ex:
        results = list(ex.map(lambda _: _submit(owner, key, body), range(100)))
    statuses = [r[0] for r in results]
    assert set(statuses) <= {200, 201} and statuses.count(201) == 1, statuses
    assert len({r[1]["payment_id"] for r in results}) == 1
    c = h.counts()
    assert c["payments"] == 1 and c["settlements"] <= 1
    evals = h.db.read(lambda t: t.scalar("SELECT COUNT(*) FROM case_events WHERE type = 'payment_screened'"))
    assert evals <= 1 and c["outbox"] == evals


def test_20_independent_clients_and_4_workers(h):
    setups = [_setup_payment(h, amount=20_000_00 + i, ref=f"REF{i:09d}") for i in range(20)]
    with ThreadPoolExecutor(max_workers=20) as ex:
        res = list(ex.map(lambda s: _submit(s[1], uuid.uuid4().hex, s[2]), setups))
    assert all(r[0] == 201 for r in res), res
    assert h.counts()["payments"] == 20 and h.counts()["cases"] == 20

    def worker(i):
        n = 0
        try:
            while run_once(h.db, f"w{i}"):
                n += 1
        finally:
            h.db.close_thread()
        return n
    with ThreadPoolExecutor(max_workers=4) as ex:
        done = sum(ex.map(worker, range(4)))
    assert done == 20
    dup = h.db.read(lambda t: t.all("SELECT case_id, COUNT(*) AS n FROM case_events WHERE type = 'investigation_completed'"
                                    " GROUP BY case_id HAVING COUNT(*) > 1"))
    assert dup == []
    assert h.db.read(lambda t: t.scalar("SELECT COUNT(*) FROM outbox WHERE status = 'done'")) == 20


def _held_case(h):
    """A HELD payment via an enforced-signal shortcut: fan-in + coercion remark."""
    ref = f"MULE{uuid.uuid4().hex[:8].upper()}"
    a = h.analyst()
    for i in range(3):
        s = h.session()
        acct, ben = h.onboard(s, ref=ref)
        p = h.pay(s, acct, ben, 1_000_00, h.capture(s)).json()
        h.drain()
        case = h.case_for(p["payment_id"])
        code = h.c.post(f"/api/v2/soc/cases/{case['case']['id']}/actions", headers=a, json={
            "action": "issue_challenge", "expected_version": case["case"]["version"], "rationale": "callback done"}).json()["code"]
        h.c.post(f"/api/v2/payments/{p['payment_id']}/verify", json={"code": code}, headers=s)
    s = h.session()
    acct, ben = h.onboard(s, ref=ref)
    p = h.pay(s, acct, ben, 4_000_00, h.capture(s), remark="share otp urgently").json()
    assert p["state"] == "HELD"
    h.drain()
    return h.case_for(p["payment_id"])


def _act(case_id, action, version, actor="a1"):
    try:
        return actions.apply(actor=actor, role="analyst", case_id=case_id, action=action, expected_version=version,
                             rationale="concurrency test rationale")
    except ApiError as e:
        return e.detail
    finally:
        from app.db import get_db
        get_db().close_thread()


def test_release_vs_restriction_race(h):
    case = _held_case(h)
    cid, v = case["case"]["id"], case["case"]["version"]
    before = h.counts()["settlements"]
    barrier = threading.Barrier(2)
    def go(action):
        barrier.wait()
        return _act(cid, action, v)
    with ThreadPoolExecutor(max_workers=2) as ex:
        r = list(ex.map(go, ["release", "restrict_counterparty"]))
    ok = [x for x in r if "case_version" in x]
    assert len(ok) == 1, r
    final = h.case_for(case["payment"]["id"])["payment"]["state"]
    settled = h.counts()["settlements"] - before
    assert (final, settled) in (("SETTLED", 1), ("BLOCKED", 0))


def test_correct_code_vs_duplicate_verification(h):
    s, owner, body = _setup_payment(h)
    _, rc = _submit(owner, uuid.uuid4().hex, body)
    h.drain()
    case = h.case_for(rc["payment_id"])
    code = _act(case["case"]["id"], "issue_challenge", case["case"]["version"])["code"]
    def v(_):
        try:
            return customer.verify_payment(owner, rc["payment_id"], code)["outcome"]
        finally:
            from app.db import get_db
            get_db().close_thread()
    with ThreadPoolExecutor(max_workers=10) as ex:
        outs = list(ex.map(v, range(10)))
    assert outs.count("verified") == 1, outs
    assert h.db.read(lambda t: t.scalar("SELECT COUNT(*) FROM settlements WHERE payment_id = ?", (rc["payment_id"],))) == 1


def test_two_approvals_same_version(h):
    s, owner, body = _setup_payment(h)
    _, rc = _submit(owner, uuid.uuid4().hex, body)
    h.drain()
    case = h.case_for(rc["payment_id"])
    prop = next(p for p in case["proposals"] if p["status"] == "pending")
    barrier = threading.Barrier(2)
    def approve(actor):
        barrier.wait()
        try:
            return actions.review_proposal(actor=actor, proposal_id=prop["id"], decision="approve",
                                           expected_version=case["case"]["version"], rationale="approve in race")
        except ApiError as e:
            return e.detail
        finally:
            from app.db import get_db
            get_db().close_thread()
    with ThreadPoolExecutor(max_workers=2) as ex:
        r = list(ex.map(approve, ["a1", "a2"]))
    assert sum(1 for x in r if "case_version" in x) == 1, r
    assert h.db.read(lambda t: t.scalar("SELECT COUNT(*) FROM challenges WHERE payment_id = ?", (rc["payment_id"],))) == 1


def test_expired_lease_vs_replacement_worker(h, fake_clock):
    s, owner, body = _setup_payment(h)
    _submit(owner, uuid.uuid4().hex, body)
    job_a = claim(h.db, "A")
    assert job_a
    res_a = investigate(job_a)           # worker A "crashes" before committing
    fake_clock.advance(settings.lease_ms + 1)
    job_b = claim(h.db, "B")             # replacement worker takes over the expired lease
    assert job_b and job_b["id"] == job_a["id"] and job_b["lease_token"] != job_a["lease_token"]
    commit_investigation(h.db, job_b, investigate(job_b))
    with pytest.raises(FenceLost):
        commit_investigation(h.db, job_a, res_a)   # stale worker is fenced out
    n = h.db.read(lambda t: t.scalar("SELECT COUNT(*) FROM case_events WHERE type = 'investigation_completed'"))
    assert n == 1


def test_restart_after_commit_before_ack_and_duplicate_delivery(h):
    s, owner, body = _setup_payment(h)
    _submit(owner, uuid.uuid4().hex, body)
    cid = h.db.read(lambda t: t.scalar("SELECT id FROM cases"))
    # Duplicate broker delivery / duplicate enqueue of the same trigger collapses to one durable job.
    def dup(t):
        return enqueue(t, case_id=cid, kind="investigate", case_version=1, trigger_key=f"investigate:{cid}:1")
    assert h.db.write(dup) is None
    assert run_once(h.db, "w") is True
    assert run_once(h.db, "w") is False    # redelivery after durable completion does nothing
    # Broker outage: SQL remains authoritative.
    old = settings.redis_url
    settings.redis_url = "redis://127.0.0.1:1/0"
    try:
        s2, owner2, body2 = _setup_payment(h, ref="REDISDOWN01")
        st, _ = _submit(owner2, uuid.uuid4().hex, body2)
        assert st == 201
        assert run_once(h.db, "w") is True
    finally:
        settings.redis_url = old


def test_out_of_order_commit_delivery(h):
    """A transaction that allocates its event first but commits last is delivered after the earlier commit."""
    s, owner, body = _setup_payment(h)
    _, rc = _submit(owner, uuid.uuid4().hex, body)
    dispatch_once(h.db)
    cid = h.db.read(lambda t: t.scalar("SELECT id FROM cases"))
    if h.db.dialect == "sqlite":
        pytest.skip("SQLite serializes writers; overlapping commits cannot occur (recorded as serialized)")
    started, release = threading.Event(), threading.Event()
    def slow():
        def _go(t):
            append_event(t, case_id=cid, payment_id=rc["payment_id"], type="slow", actor="t", case_version=1)
            started.set()
            release.wait(5)
        h.db.write(_go)
        h.db.close_thread()
    th = threading.Thread(target=slow)
    th.start()
    started.wait(5)
    def fast(t):
        append_event(t, case_id=cid, payment_id=rc["payment_id"], type="fast", actor="t", case_version=1)
    h.db.write(fast)
    dispatch_once(h.db)
    release.set()
    th.join()
    dispatch_once(h.db)
    rows = h.db.read(lambda t: t.all("SELECT type, seq, delivery_seq FROM case_events WHERE type IN ('slow','fast')"))
    by = {r["type"]: r for r in rows}
    assert by["slow"]["seq"] < by["fast"]["seq"]                    # allocated first
    assert by["slow"]["delivery_seq"] > by["fast"]["delivery_seq"]  # delivered after its later commit
    seqs = h.db.read(lambda t: [r["delivery_seq"] for r in t.all("SELECT delivery_seq FROM case_events ORDER BY delivery_seq")])
    assert seqs == list(range(1, len(seqs) + 1))                    # gap-free cursor


def test_independent_write_progresses_while_unrelated_payment_locked(h):
    s, owner, body = _setup_payment(h)
    _, rc = _submit(owner, uuid.uuid4().hex, body)
    s2, owner2, body2 = _setup_payment(h, ref="UNRELATED001")
    if h.db.dialect == "sqlite":
        pytest.skip("SQLite allows one writer at a time (recorded as serialized)")
    locked, release = threading.Event(), threading.Event()
    def holder():
        def _go(t):
            t.lock_rows("payments", [rc["payment_id"]])
            t.lock_rows("cases", [h.db.read(lambda t2: t2.scalar("SELECT id FROM cases WHERE payment_id = ?", (rc["payment_id"],)))])
            locked.set()
            release.wait(10)
        h.db.write(_go)
        h.db.close_thread()
    th = threading.Thread(target=holder)
    th.start()
    locked.wait(5)
    t0 = time.monotonic()
    st, out = _submit(owner2, uuid.uuid4().hex, body2)
    elapsed = time.monotonic() - t0
    release.set()
    th.join()
    assert st == 201 and elapsed < 3.0, (st, elapsed)
