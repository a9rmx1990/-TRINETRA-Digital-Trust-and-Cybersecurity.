"""API and persistence integration: the full journey plus every capture refusal path."""
from __future__ import annotations

import uuid

from app import clock
from app.config import settings

from .conftest import silent_pcm, voiced_pcm

ZERO = {"payments": 0, "cases": 0, "settlements": 0, "outbox": 0}


def _sub(c: dict) -> dict:
    return {k: c[k] for k in ZERO}


def test_fresh_start_is_empty(h):
    s = h.session()
    me = h.c.get("/api/v2/me", headers=s).json()
    assert me == {"accounts": [], "beneficiaries": []}
    assert h.c.get("/api/v2/payments", headers=s).json()["items"] == []
    a = h.analyst()
    assert h.c.get("/api/v2/soc/cases", headers=a).json()["total"] == 0
    an = h.c.get("/api/v2/soc/analytics", headers=a).json()
    assert an["volume"]["totals"]["total"] == 0 and an["volume"]["intervention_rate"] is None
    assert an["model_quality"]["adjudicated_cases"] == 0


def test_ownership_isolation(h):
    s1, s2 = h.session(), h.session()
    acct, ben = h.onboard(s1)
    assert h.c.get("/api/v2/me", headers=s2).json()["accounts"] == []
    cid = h.capture(s1)
    r = h.pay(s2, acct, ben, 100_00, cid)
    assert r.status_code == 404
    assert h.c.get(f"/api/v2/calls/{cid}", headers=s2).status_code == 404
    pid = h.pay(s1, acct, ben, 100_00, cid).json()["payment_id"]
    assert h.c.get(f"/api/v2/payments/{pid}", headers=s2).status_code == 404
    assert h.c.get("/api/v2/me").status_code == 401
    # Records survive reload with the same token.
    assert len(h.c.get("/api/v2/me", headers=s1).json()["accounts"]) == 1


def test_capture_refusals_create_nothing(h, fake_clock):
    s = h.session()
    acct, ben = h.onboard(s)
    before = _sub(h.counts())
    # omitted session id
    r = h.pay(s, acct, ben, 500_00, None)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "capture_required"
    # foreign session
    other = h.session()
    foreign = h.capture(other)
    assert h.pay(s, acct, ben, 500_00, foreign).json()["detail"]["code"] == "capture_not_found"
    # silence
    silent = h.capture(s, silent_pcm())
    st = h.c.get(f"/api/v2/calls/{silent}", headers=s).json()
    assert st["usable"] is False and st["quality_reason"] == "silence"
    assert h.pay(s, acct, ben, 500_00, silent).json()["detail"]["code"] == "capture_unusable"
    # unfinished
    open_call = h.c.post("/api/v2/calls", json={"consent": True}, headers=s).json()["id"]
    h.c.post(f"/api/v2/calls/{open_call}/pcm", content=voiced_pcm(), headers=s)
    assert h.pay(s, acct, ben, 500_00, open_call).json()["detail"]["code"] == "capture_unfinished"
    # expired (finished too long ago)
    old = h.capture(s)
    fake_clock.advance(settings.capture_fresh_ms + 1)
    assert h.pay(s, acct, ben, 500_00, old).json()["detail"]["code"] == "capture_expired"
    # no consent
    assert h.c.post("/api/v2/calls", json={"consent": False}, headers=s).status_code == 422
    assert _sub(h.counts()) == before == ZERO


def test_gemini_analyst_verifies_and_settles_incoming_request(h, fake_clock, monkeypatch):
    from app.analyst import api, workflow
    from app.customer import issue_challenge

    from .e2e_app import offline_analysis

    monkeypatch.setenv("GOOGLE_API_KEY", "offline-test-key")
    monkeypatch.setattr(api, "missing_packages", lambda: False)
    monkeypatch.setattr(workflow, "analyze", offline_analysis)
    monkeypatch.setenv("TRINETRA_ANALYST_WORKSPACE_PASSWORD", "test-analyst-password")
    owner = h.session()
    payer = h.session()
    payer_account = h.c.post("/api/v2/accounts", headers=payer, json={"display_name": "Payer"}).json()
    account, beneficiary = h.onboard(owner, ref=payer_account["account_ref"])
    body = {"account_id": account, "beneficiary_id": beneficiary, "amount_minor": 25_000_00,
            "channel": "IMPS", "call_id": h.capture(owner)}
    submit_headers = {**owner, "Idempotency-Key": uuid.uuid4().hex}
    payment = h.c.post("/api/v2/payment-requests", headers=submit_headers, json=body)
    assert payment.status_code == 201
    assert payment.json()["direction"] == "incoming"
    replay = h.c.post("/api/v2/payment-requests", headers=submit_headers, json=body)
    assert replay.status_code == 200 and replay.json()["payment_id"] == payment.json()["payment_id"]
    assert h.c.post("/api/v2/payments", headers=submit_headers, json=body).status_code == 409
    receipt = f"/api/v2/payments/{payment.json()['payment_id']}"
    waiting = h.c.get(receipt, headers=owner).json()
    assert waiting["next_action"] == "wait_for_analyst"
    assert "challenge" not in waiting
    h.drain()
    fake_clock.advance(1)

    login = h.c.post("/api/v2/analyst/login", json={"username": "admin", "password": "test-analyst-password"})
    assert login.status_code == 200
    analyst = {"Authorization": f"Bearer {login.json()['token']}"}
    queue = h.c.get("/api/v2/analyst/cases", headers=analyst).json()
    case_url = f"/api/v2/analyst/cases/{queue['items'][0]['case_id']}"
    approval = f"{case_url}/verify"
    case = h.c.get(case_url, headers=analyst).json()
    assert case["payment"]["direction"] == "incoming"
    assert case["suspicion_level"] == "inconclusive"
    assert case["sender"]["account_id"] == payer_account["id"]
    assert case["customer"]["account_id"] == account
    soc_case = h.case_for(payment.json()["payment_id"])
    network = next(e["payload"] for e in soc_case["evidence"] if e["kind"] == "recipient_graph_snapshot")
    edge = next(e for e in network["edges"] if e["proposed"])
    assert edge["source"].startswith("cp:") and edge["target"] == f"acct:{account}"
    version = case["case"]["version"]
    approval_body = {"expected_version": version, "analysis_run_id": str(uuid.uuid4())}
    assert case["verification"]["available"] and case["verification"]["verified_run_id"] is None
    assert h.c.post(approval, headers=owner, json=approval_body).status_code == 401
    assert h.c.get(receipt, headers=payer).status_code == 404
    assert h.c.get(receipt, headers=analyst).status_code == 401
    stale = h.c.post(approval, headers=analyst, json={**approval_body, "expected_version": version - 1})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "stale_version"
    missing = h.c.post(approval, headers=analyst, json=approval_body)
    assert missing.status_code == 409 and missing.json()["detail"]["code"] == "analysis_required"
    assert h.counts()["settlements"] == 0

    # An incoming request left over from the previous workflow may have a live code.
    def legacy_challenge(t):
        row = t.one("SELECT * FROM payments WHERE id = ?", (payment.json()["payment_id"],))
        return issue_challenge(t, row, "legacy", deliver_to_receipt=True)

    code, challenge = h.db.write(legacy_challenge)
    assert "challenge" not in h.c.get(receipt, headers=owner).json()
    legacy = h.c.post(f"{receipt}/verify", headers=owner, json={"code": code})
    assert legacy.status_code == 409 and legacy.json()["detail"]["code"] == "analyst_verification_required"

    analysis = h.c.post(f"{case_url}/analysis", headers=analyst)
    assert analysis.status_code == 200, analysis.text
    approval_body["analysis_run_id"] = analysis.json()["id"]
    old_path = h.c.post(f"/api/v2/soc/cases/{case['case']['id']}/actions", headers=h.analyst(),
                        json={"action": "verify_incoming", "expected_version": version,
                              "rationale": "Reviewed evidence", "params": {"analysis_run_id": analysis.json()["id"]}})
    assert old_path.status_code == 403
    verified = h.c.post(approval, headers=analyst, json=approval_body)
    assert verified.status_code == 200 and verified.json()["payment_state"] == "SETTLED"
    assert h.c.post(approval, headers=analyst, json=approval_body).status_code == 409
    received = h.c.get(receipt, headers=owner).json()
    assert received["state"] == "SETTLED" and received["analyst_verified"] is True
    current = h.c.get(case_url, headers=analyst).json()
    assert current["verification"]["verified_run_id"] == analysis.json()["id"]
    assert h.db.read(lambda t: t.scalar("SELECT status FROM challenges WHERE id = ?",
                                        (challenge["challenge_id"],))) == "revoked"
    assert h.counts()["settlements"] == 1
    settlement = h.db.read(lambda t: t.one(
        "SELECT s.account_id, s.counterparty_id, p.direction FROM settlements s"
        " JOIN payments p ON p.id = s.payment_id WHERE p.id = ?", (payment.json()["payment_id"],)))
    assert settlement == {"account_id": account, "counterparty_id": edge["source"].removeprefix("cp:"),
                          "direction": "incoming"}
    established = {**body, "amount_minor": 1_000_00, "call_id": h.capture(owner)}
    next_request = h.c.post("/api/v2/payment-requests",
                            headers={**owner, "Idempotency-Key": uuid.uuid4().hex}, json=established)
    assert next_request.status_code == 201
    assert next_request.json()["state"] == "VERIFICATION_REQUIRED"
    assert next_request.json()["direction"] == "incoming"
    assert h.counts()["settlements"] == 1


def test_full_journey_step_up_challenge_verify(h):
    s = h.session()
    acct, ben = h.onboard(s)
    cid = h.capture(s)
    key = uuid.uuid4().hex
    r = h.pay(s, acct, ben, 25_000_00, cid, key=key, remark="Tuition fee")
    assert r.status_code == 201, r.text
    rc = r.json()
    assert rc["state"] == "VERIFICATION_REQUIRED" and rc["amount_display"] == "₹25,000.00"
    assert h.counts()["settlements"] == 0 and h.counts()["cases"] == 1
    # SOC investigation
    assert h.drain() >= 1
    case = h.case_for(rc["payment_id"])
    assert case["case"]["report"]["verdict"] == "needs_customer_verification"
    assert {s["signal"] if "signal" in s else k for k, s in case["payment"]["signals"].items()} >= {
        "voice_authenticity", "speech_content", "typed_remark", "recipient_graph"}
    props = [p for p in case["proposals"] if p["status"] == "pending"]
    assert props and props[0]["action"] == "issue_challenge"
    ev_ids = {e["id"] for e in case["evidence"]}
    assert set(props[0]["evidence_ids"]) <= ev_ids
    assert case["watch"]["status"] == "active"
    # Analyst approves the proposal -> code shown once
    a = h.analyst()
    rv = h.c.post(f"/api/v2/soc/proposals/{props[0]['id']}/review", headers=a,
                  json={"decision": "approve", "expected_version": case["case"]["version"],
                        "rationale": "Called customer on registered number"})
    assert rv.status_code == 200, rv.text
    code = rv.json()["code"]
    assert len(code) == 6
    # Code is not stored in clear
    assert h.db.read(lambda t: t.scalar("SELECT COUNT(*) FROM challenges WHERE code_hash = ?", (code,))) == 0
    # Wrong code then correct code
    bad = "000000" if code != "000000" else "111111"
    w = h.c.post(f"/api/v2/payments/{rc['payment_id']}/verify", json={"code": bad}, headers=s).json()
    assert w["outcome"] == "incorrect" and w["payment"]["challenge"]["attempts_left"] == 4
    ok = h.c.post(f"/api/v2/payments/{rc['payment_id']}/verify", json={"code": code}, headers=s).json()
    assert ok["outcome"] == "verified" and ok["payment"]["state"] == "SETTLED"
    again = h.c.post(f"/api/v2/payments/{rc['payment_id']}/verify", json={"code": code}, headers=s).json()
    assert again["outcome"] == "not_required"
    assert h.counts()["settlements"] == 1
    # Identical retry after capture expiry replays the stored receipt, never a second settlement
    clock_now = clock.now_ms
    clock.set_source(lambda: clock_now() + settings.capture_fresh_ms + 60_000)
    try:
        rr = h.pay(s, acct, ben, 25_000_00, cid, key=key, remark="Tuition fee")
        assert rr.status_code == 200 and rr.json()["replayed"] and rr.json()["payment_id"] == rc["payment_id"]
    finally:
        clock.reset()
    conflict = h.pay(s, acct, ben, 26_000_00, cid, key=key, remark="Tuition fee")
    assert conflict.status_code == 409 and conflict.json()["detail"]["code"] == "idempotency_conflict"
    assert h.counts()["payments"] == 1 and h.counts()["settlements"] == 1
    # History and receipt agree with the ledger
    hist = h.c.get("/api/v2/payments", headers=s).json()["items"]
    assert [x["state"] for x in hist] == ["SETTLED"]
    # Timeline is append-only and ordered by cursor
    h.drain()
    case = h.case_for(rc["payment_id"])
    types = [e["type"] for e in case["timeline"]]
    assert types[0] == "payment_screened" and "investigation_completed" in types and "verified_settled" in types
    cursors = [e["cursor"] for e in case["timeline"]]
    assert all(c is not None for c in cursors) and cursors == sorted(cursors)


def test_second_small_transfer_to_established_recipient_settles(h):
    s = h.session()
    acct, ben = h.onboard(s)
    p1 = h.pay(s, acct, ben, 2_000_00, h.capture(s)).json()
    assert p1["state"] == "VERIFICATION_REQUIRED"  # first transfer: spoken content unscreened, new recipient
    a = h.analyst()
    h.drain()
    case = h.case_for(p1["payment_id"])
    code = h.c.post(f"/api/v2/soc/cases/{case['case']['id']}/actions", headers=a, json={
        "action": "issue_challenge", "expected_version": case["case"]["version"], "rationale": "identity confirmed"}).json()["code"]
    assert h.c.post(f"/api/v2/payments/{p1['payment_id']}/verify", json={"code": code}, headers=s).json()["outcome"] == "verified"
    p2 = h.pay(s, acct, ben, 1_500_00, h.capture(s))
    assert p2.status_code == 201 and p2.json()["state"] == "SETTLED"
    assert h.counts()["settlements"] == 2


def test_capture_reuse_rejected(h):
    s = h.session()
    acct, ben = h.onboard(s)
    cid = h.capture(s)
    assert h.pay(s, acct, ben, 100_00, cid).status_code == 201
    r = h.pay(s, acct, ben, 100_00, cid)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "capture_already_used"


def test_restriction_blocks_and_hold_with_fan_in(h):
    # Three other customers settle to the same recipient, then a fourth sends with a coercive remark.
    a = h.analyst()
    ref = "MULE00098765"
    for i in range(3):
        s = h.session()
        acct, ben = h.onboard(s, ref=ref, name=f"Recipient {i}")
        p = h.pay(s, acct, ben, 1_000_00, h.capture(s)).json()
        h.drain()
        case = h.case_for(p["payment_id"])
        code = h.c.post(f"/api/v2/soc/cases/{case['case']['id']}/actions", headers=a, json={
            "action": "issue_challenge", "expected_version": case["case"]["version"], "rationale": "checked by phone"}).json()["code"]
        assert h.c.post(f"/api/v2/payments/{p['payment_id']}/verify", json={"code": code}, headers=s).json()["outcome"] == "verified"
    s = h.session()
    acct, ben = h.onboard(s, ref=ref)
    r = h.pay(s, acct, ben, 4_000_00, h.capture(s), remark="bank officer said share OTP urgently").json()
    assert r["state"] == "HELD"
    h.drain()
    case = h.case_for(r["payment_id"])
    assert case["case"]["report"]["verdict"] == "likely_fraud"
    g = next(e for e in case["evidence"] if e["kind"] == "recipient_graph_snapshot")["payload"]
    assert g["features"]["recent_distinct_other_senders"] == 3
    assert any(e["proposed"] for e in g["edges"])
    assert sum(len(e["transfers"]) for e in g["edges"] if not e["proposed"]) == 3
    # Restrict the recipient through the proposal; a later transfer is BLOCKED.
    prop = next(p for p in case["proposals"] if p["action"] == "restrict_counterparty")
    rv = h.c.post(f"/api/v2/soc/proposals/{prop['id']}/review", headers=a, json={
        "decision": "approve", "expected_version": case["case"]["version"], "rationale": "mule pattern confirmed"})
    assert rv.status_code == 200 and rv.json()["payment_state"] == "BLOCKED"
    s5 = h.session()
    acct5, ben5 = h.onboard(s5, ref=ref)
    blocked = h.pay(s5, acct5, ben5, 100_00, h.capture(s5)).json()
    assert blocked["state"] == "BLOCKED" and h.counts()["settlements"] == 3


def test_stale_version_and_unauthorized_reads(h):
    s = h.session()
    acct, ben = h.onboard(s)
    p = h.pay(s, acct, ben, 50_000_00, h.capture(s)).json()
    h.drain()
    case = h.case_for(p["payment_id"])
    cid, v = case["case"]["id"], case["case"]["version"]
    a = h.analyst()
    ok = h.c.post(f"/api/v2/soc/cases/{cid}/actions", headers=a,
                  json={"action": "place_hold", "expected_version": v, "rationale": "pending callback"})
    assert ok.status_code == 200
    stale = h.c.post(f"/api/v2/soc/cases/{cid}/actions", headers=a,
                     json={"action": "reject_transfer", "expected_version": v, "rationale": "pending callback"})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "stale_version"
    # customer token cannot read SOC; no token cannot read; bad token cannot read
    assert h.c.get(f"/api/v2/soc/cases/{cid}", headers=s).status_code == 401
    assert h.c.get("/api/v2/soc/cases").status_code == 401
    assert h.c.post("/api/v2/soc/login", json={"name": "x1", "passcode": "nope"}).status_code == 401
    # every attempted action leaves an audit record (applied and denied)
    outcomes = h.db.read(lambda t: [r["outcome"] for r in t.all("SELECT outcome FROM tool_audit WHERE tool LIKE 'action.%'")])
    assert "applied" in outcomes and any(o.startswith("denied") for o in outcomes)


def test_verify_expiry_and_attempt_cap(h, fake_clock):
    s = h.session()
    acct, ben = h.onboard(s)
    p = h.pay(s, acct, ben, 50_000_00, h.capture(s)).json()
    h.drain()
    case = h.case_for(p["payment_id"])
    a = h.analyst()
    code = h.c.post(f"/api/v2/soc/cases/{case['case']['id']}/actions", headers=a, json={
        "action": "issue_challenge", "expected_version": case["case"]["version"], "rationale": "callback done"}).json()["code"]
    fake_clock.advance(16 * clock.MINUTE)
    assert h.c.post(f"/api/v2/payments/{p['payment_id']}/verify", json={"code": code}, headers=s).json()["outcome"] == "expired"
    case = h.case_for(p["payment_id"])
    code = h.c.post(f"/api/v2/soc/cases/{case['case']['id']}/actions", headers=a, json={
        "action": "issue_challenge", "expected_version": case["case"]["version"], "rationale": "re-issued after expiry"}).json()["code"]
    bad = "123456" if code != "123456" else "654321"
    outs = [h.c.post(f"/api/v2/payments/{p['payment_id']}/verify", json={"code": bad}, headers=s).json()["outcome"]
            for _ in range(5)]
    assert outs[-1] == "locked"
    assert h.c.post(f"/api/v2/payments/{p['payment_id']}/verify", json={"code": code}, headers=s).json()["outcome"] == "locked"
    assert h.counts()["settlements"] == 0


def test_hold_blocks_verification_settlement(h):
    s = h.session()
    acct, ben = h.onboard(s)
    p = h.pay(s, acct, ben, 50_000_00, h.capture(s)).json()
    h.drain()
    case = h.case_for(p["payment_id"])
    a = h.analyst()
    cid = case["case"]["id"]
    code = h.c.post(f"/api/v2/soc/cases/{cid}/actions", headers=a, json={
        "action": "issue_challenge", "expected_version": case["case"]["version"], "rationale": "callback done"}).json()["code"]
    v = h.case_for(p["payment_id"])["case"]["version"]
    h.c.post(f"/api/v2/soc/cases/{cid}/actions", headers=a, json={"action": "place_hold", "expected_version": v,
                                                                  "rationale": "new indicator found"})
    out = h.c.post(f"/api/v2/payments/{p['payment_id']}/verify", json={"code": code}, headers=s).json()
    assert out["payment"]["state"] == "HELD" and h.counts()["settlements"] == 0
    v = h.case_for(p["payment_id"])["case"]["version"]
    rel = h.c.post(f"/api/v2/soc/cases/{cid}/actions", headers=a, json={"action": "release", "expected_version": v,
                                                                        "rationale": "indicator cleared"})
    assert rel.json()["payment_state"] == "SETTLED" and h.counts()["settlements"] == 1


def test_verdict_override_keeps_immutable_trail_and_feeds_quality(h):
    s = h.session()
    acct, ben = h.onboard(s)
    p = h.pay(s, acct, ben, 50_000_00, h.capture(s)).json()
    h.drain()
    a = h.analyst()
    cid = h.case_for(p["payment_id"])["case"]["id"]
    for label in ("fraud", "legitimate"):
        v = h.case_for(p["payment_id"])["case"]["version"]
        r = h.c.post(f"/api/v2/soc/cases/{cid}/actions", headers=a, json={
            "action": "record_verdict", "expected_version": v, "rationale": f"reviewed as {label}", "params": {"label": label}})
        assert r.status_code == 200, r.text
    case = h.case_for(p["payment_id"])
    assert len(case["adjudications"]) == 2 and case["case"]["verdict"] == "legitimate"
    assert "verdict_override" in [e["type"] for e in case["timeline"]]
    q = h.c.get("/api/v2/soc/analytics", headers=a).json()["model_quality"]
    assert q["adjudicated_cases"] == 1
    graph_row = next(r for r in q["rows"] if r["signal"] == "recipient_graph")
    assert graph_row["tn"] == 1 and graph_row["n"] == 1


def test_watch_reopens_case_on_new_evidence(h, fake_clock):
    a = h.analyst()
    ref = "WATCH0001234"
    s = h.session()
    acct, ben = h.onboard(s, ref=ref)
    p = h.pay(s, acct, ben, 50_000_00, h.capture(s)).json()
    h.drain()
    case = h.case_for(p["payment_id"])
    cid = case["case"]["id"]
    h.c.post(f"/api/v2/soc/cases/{cid}/actions", headers=a, json={
        "action": "reject_transfer", "expected_version": case["case"]["version"], "rationale": "customer declined"})
    v = h.case_for(p["payment_id"])["case"]["version"]
    h.c.post(f"/api/v2/soc/cases/{cid}/actions", headers=a, json={"action": "close_case", "expected_version": v,
                                                                  "rationale": "closed pending watch"})
    assert h.case_for(p["payment_id"])["case"]["state"] == "monitoring"
    # Another customer settles to the same recipient later.
    fake_clock.advance(clock.MINUTE)
    s2 = h.session()
    acct2, ben2 = h.onboard(s2, ref=ref)
    p2 = h.pay(s2, acct2, ben2, 1_000_00, h.capture(s2)).json()
    h.drain()
    c2 = h.case_for(p2["payment_id"])
    code = h.c.post(f"/api/v2/soc/cases/{c2['case']['id']}/actions", headers=a, json={
        "action": "issue_challenge", "expected_version": c2["case"]["version"], "rationale": "callback ok"}).json()["code"]
    h.c.post(f"/api/v2/payments/{p2['payment_id']}/verify", json={"code": code}, headers=s2)
    fake_clock.advance(clock.DAY + 1)
    h._analyst = None  # the 12 h analyst credential expired with the simulated day
    from app.soc.worker import schedule_due_watches
    assert schedule_due_watches(h.db) >= 1
    h.drain()
    case = h.case_for(p["payment_id"])
    assert case["case"]["state"] == "open"
    assert case["payment"]["state"] == "REJECTED"  # transfer stays terminal
    assert "watch_alert" in [e["type"] for e in case["timeline"]]


def test_chart_bucket_reconciles_to_sql(h):
    s = h.session()
    acct, ben = h.onboard(s)
    pids = [h.pay(s, acct, ben, amt, h.capture(s)).json()["payment_id"] for amt in (1_000_00, 2_000_00)]
    a = h.analyst()
    an = h.c.get("/api/v2/soc/analytics", headers=a).json()
    assert an["volume"]["totals"]["total"] == 2
    b = next(x for x in an["volume"]["buckets"] if x["total"])
    rows = h.c.get("/api/v2/soc/analytics/rows", headers=a,
                   params={"from_ms": b["start_ms"], "to_ms": b["end_ms"]}).json()["items"]
    assert sorted(r["id"] for r in rows) == sorted(pids)
    sql = h.db.read(lambda t: sorted(r["id"] for r in t.all("SELECT id FROM payments WHERE created_ms >= ? AND created_ms < ?",
                                                          (b["start_ms"], b["end_ms"]))))
    assert sql == sorted(pids)
    assert sum(x["total"] for x in an["volume"]["buckets"] if not x["total"]) == 0


def test_mcp_roles_and_audit(h):
    s = h.session()
    acct, ben = h.onboard(s)
    p = h.pay(s, acct, ben, 50_000_00, h.capture(s)).json()
    cid = h.db.read(lambda t: t.scalar("SELECT id FROM cases WHERE payment_id = ?", (p["payment_id"],)))
    a = h.analyst()
    lst = h.c.post("/api/v2/soc/mcp", headers=a, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).json()
    names = {t["name"] for t in lst["result"]["tools"]}
    assert "proposal.create" not in names and "graph.get" in names
    denied = h.c.post("/api/v2/soc/mcp", headers=a, json={"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                                         "params": {"name": "proposal.create", "arguments": {"case_id": cid}}}).json()
    assert denied["error"]["code"] == -32003
    ok = h.c.post("/api/v2/soc/mcp", headers=a, json={"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                                     "params": {"name": "case.get", "arguments": {"case_id": cid}}}).json()
    assert "result" in ok
    n = h.db.read(lambda t: t.scalar("SELECT COUNT(*) FROM tool_audit WHERE actor = 'analyst.one'"))
    assert n >= 2


def test_event_replay_resumes_after_cursor(h):
    s = h.session()
    acct, ben = h.onboard(s)
    h.pay(s, acct, ben, 50_000_00, h.capture(s))
    h.drain()
    a = h.analyst()
    allv = h.c.get("/api/v2/soc/events", headers=a, params={"after": 0}).json()["notices"]
    assert len(allv) >= 2
    rest = h.c.get("/api/v2/soc/events", headers=a, params={"after": allv[0]["cursor"]}).json()["notices"]
    assert [n["cursor"] for n in rest] == [n["cursor"] for n in allv[1:]]


def test_websocket_requires_auth_and_streams(h):
    s = h.session()
    acct, ben = h.onboard(s)
    h.pay(s, acct, ben, 50_000_00, h.capture(s))
    h.drain()
    with h.c.websocket_connect("/api/v2/soc/stream") as ws:
        ws.send_json({"type": "auth", "token": "bad"})
        assert ws.receive_json()["type"] == "error"
    tok = h.analyst()["Authorization"][7:]
    with h.c.websocket_connect("/api/v2/soc/stream") as ws:
        ws.send_json({"type": "auth", "token": tok, "after": 0})
        assert ws.receive_json()["type"] == "ready"
        first = ws.receive_json()
        assert first["type"] == "notice" and first["cursor"] == 1
