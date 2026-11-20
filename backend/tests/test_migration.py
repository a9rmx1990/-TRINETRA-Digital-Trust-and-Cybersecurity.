"""SQLite -> PostgreSQL migration rehearsal with settled transfers, run when a test PG is available."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.db import Database

from .conftest import PG_URL

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))


@pytest.mark.parametrize("db", ["sqlite"], indirect=True)
def test_migrate_sqlite_to_postgres_preserves_ledger(h):
    if not PG_URL:
        pytest.skip("TRINETRA_TEST_PG_URL not set")
    import migrate_sqlite_to_postgres as mig
    a = h.analyst()
    for i in range(3):
        s = h.session()
        acct, ben = h.onboard(s, ref=f"MIGR{i:08d}")
        p = h.pay(s, acct, ben, (i + 1) * 1_000_00, h.capture(s)).json()
        h.drain()
        case = h.case_for(p["payment_id"])
        code = h.c.post(f"/api/v2/soc/cases/{case['case']['id']}/actions", headers=a, json={
            "action": "issue_challenge", "expected_version": case["case"]["version"], "rationale": "callback done"}).json()["code"]
        assert h.c.post(f"/api/v2/payments/{p['payment_id']}/verify", json={"code": code}, headers=s).json()["outcome"] == "verified"
    h.drain()
    target = Database(PG_URL)
    target.migrate()
    target.reset_all()
    assert mig.main(h.db.path, PG_URL) == 0
    total = target.read(lambda t: t.scalar("SELECT SUM(amount_minor) FROM settlements"))
    assert total == 6_000_00
    # The migrated database keeps working: new events get the next cursor values.
    from app.events import dispatch_once
    assert dispatch_once(target) == 0
    target.reset_all()
