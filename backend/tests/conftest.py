from __future__ import annotations

import os
import uuid

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import clock
from app.config import settings
from app.db import Database, set_db
from app.events import dispatch_once
from app.inference import Manifest, Runtime, set_runtime
from app.main import create_app
from app.soc.worker import run_once

settings.analyst_passcode = "test-passcode"
settings.soc_action_rate_per_min = 10_000

PG_URL = os.environ.get("TRINETRA_TEST_PG_URL")


def voiced_pcm(seconds: float = 3.0, seed: int = 7) -> bytes:
    """Deterministic speech-like signal: syllable-rate amplitude-modulated noise."""
    rng = np.random.default_rng(seed)
    n = int(16_000 * seconds)
    t = np.arange(n) / 16_000
    env = (0.5 + 0.5 * np.sin(2 * np.pi * 4 * t)) ** 2
    x = rng.normal(0, 0.25, n) * env + 0.1 * np.sin(2 * np.pi * 180 * t) * env
    return (np.clip(x, -1, 1) * 20_000).astype("<i2").tobytes()


def silent_pcm(seconds: float = 3.0) -> bytes:
    return np.zeros(int(16_000 * seconds), dtype="<i2").tobytes()


def _make_db(kind: str) -> Database:
    if kind == "sqlite":
        path = f"/tmp/trinetra-test-{uuid.uuid4().hex}.db"
        db = Database(f"sqlite:///{path}")
    else:
        if not PG_URL:
            pytest.skip("TRINETRA_TEST_PG_URL not set")
        db = Database(PG_URL)
    db.migrate()
    db.reset_all()
    return db


@pytest.fixture(params=["sqlite", "postgres"])
def db(request):
    d = _make_db(request.param)
    set_db(d)
    yield d
    set_db(None)


@pytest.fixture
def fake_clock():
    fc = clock.FakeClock()
    clock.set_source(fc)
    yield fc
    clock.reset()


@pytest.fixture
def runtime():
    rt = Runtime(Manifest({}))
    set_runtime(rt)
    yield rt
    set_runtime(None)


class Harness:
    def __init__(self, client: TestClient, db: Database):
        self.c = client
        self.db = db
        self._analyst = None

    # ---- customer
    def session(self) -> dict:
        tok = self.c.post("/api/v2/session").json()["token"]
        return {"Authorization": f"Bearer {tok}"}

    def onboard(self, h: dict, ref: str = "HDFC00012345", name: str = "Asha Rao") -> tuple[str, str]:
        acct = self.c.post("/api/v2/accounts", json={"display_name": "Primary"}, headers=h).json()["id"]
        ben = self.c.post("/api/v2/beneficiaries", json={"display_name": name, "account_ref": ref}, headers=h)
        assert ben.status_code == 201, ben.text
        return acct, ben.json()["id"]

    def capture(self, h: dict, pcm: bytes | None = None) -> str:
        cid = self.c.post("/api/v2/calls", json={"consent": True}, headers=h).json()["id"]
        pcm = voiced_pcm() if pcm is None else pcm
        for i in range(0, len(pcm), 32_000):
            r = self.c.post(f"/api/v2/calls/{cid}/pcm", content=pcm[i:i + 32_000], headers=h)
            assert r.status_code == 200, r.text
        r = self.c.post(f"/api/v2/calls/{cid}/finish", headers=h)
        assert r.status_code == 200, r.text
        return cid

    def pay(self, h: dict, acct: str, ben: str, amount: int, call_id: str | None, key: str | None = None,
            remark: str | None = None, channel: str = "IMPS"):
        body = {"account_id": acct, "beneficiary_id": ben, "amount_minor": amount, "channel": channel,
                "remark": remark, "call_id": call_id}
        return self.c.post("/api/v2/payments", json=body,
                           headers={**h, "Idempotency-Key": key or uuid.uuid4().hex})

    # ---- analyst
    def analyst(self) -> dict:
        if not self._analyst:
            tok = self.c.post("/api/v2/soc/login", json={"name": "analyst.one", "passcode": "test-passcode"}).json()["token"]
            self._analyst = {"Authorization": f"Bearer {tok}"}
        return self._analyst

    def drain(self, max_jobs: int = 100) -> int:
        n = 0
        while n < max_jobs and run_once(self.db, "test"):
            n += 1
        dispatch_once(self.db)
        return n

    def counts(self) -> dict:
        def _go(t):
            return {tb: int(t.scalar(f"SELECT COUNT(*) FROM {tb}")) for tb in
                    ("payments", "cases", "settlements", "outbox", "case_events", "evidence")}
        return self.db.read(_go)

    def case_for(self, pid: str) -> dict:
        cid = self.db.read(lambda t: t.scalar("SELECT id FROM cases WHERE payment_id = ?", (pid,)))
        return self.c.get(f"/api/v2/soc/cases/{cid}", headers=self.analyst()).json()


@pytest.fixture
def h(db, runtime):
    app = create_app(start_background=False)
    with TestClient(app) as client:
        yield Harness(client, db)
