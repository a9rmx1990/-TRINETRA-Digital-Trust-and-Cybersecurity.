from app import clock

ROOT = "/api/v2/analyst/intelligence"


def analyst(h, monkeypatch):
    monkeypatch.setenv("TRINETRA_ANALYST_WORKSPACE_PASSWORD", "test-intelligence-password")
    login = h.c.post("/api/v2/analyst/login", json={"username": "admin", "password": "test-intelligence-password"})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['token']}"}


def pay_and_settle(h, customer, account, beneficiary):
    response = h.pay(customer, account, beneficiary, 1_000_00, h.capture(customer))
    assert response.status_code == 201
    receipt = response.json()
    if receipt["state"] == "VERIFICATION_REQUIRED":
        h.drain()
        case = h.case_for(receipt["payment_id"])["case"]
        challenge = h.c.post(f"/api/v2/soc/cases/{case['id']}/actions", headers=h.analyst(), json={
            "action": "issue_challenge", "expected_version": case["version"], "rationale": "Verified test contact",
        })
        assert challenge.status_code == 200, challenge.text
        verification = h.c.post(f"/api/v2/payments/{receipt['payment_id']}/verify", headers=customer,
                                json={"code": challenge.json()["code"]})
        assert verification.json()["outcome"] == "verified", verification.text
    else:
        assert receipt["state"] == "SETTLED"
    return receipt["payment_id"]


def test_payment_persists_one_review_score_and_keeps_gateway_disposition(h, monkeypatch):
    auth = analyst(h, monkeypatch)
    customer = h.session()
    account, beneficiary = h.onboard(customer)
    capture = h.capture(customer)
    key = "risk-idempotency"
    first = h.pay(customer, account, beneficiary, 50_000_00, capture, key=key)
    assert first.status_code == 201
    assert first.json()["state"] == "VERIFICATION_REQUIRED"
    repeat = h.pay(customer, account, beneficiary, 50_000_00, capture, key=key)
    assert repeat.status_code == 200
    pid = first.json()["payment_id"]
    assert repeat.json()["payment_id"] == pid
    assert h.c.get(f"{ROOT}/risk/{pid}", headers=customer).status_code == 401
    risk = h.c.get(f"{ROOT}/risk/{pid}", headers=auth).json()
    assert (risk["score"], risk["band"]) == (20, "LOW")
    assert risk["baseline"]["average_minor"] is None
    assert risk["signals"][0]["evidence"]["beneficiary_id"] == beneficiary
    assert risk["signals"][0]["code"] == "new_beneficiary_high_value"
    listed = h.c.get(f"{ROOT}/risk", headers=auth, params={"account_id": account, "band": "LOW"}).json()
    assert listed["summary"]["total"] == 1
    assert [row["payment_id"] for row in listed["items"]] == [pid]
    assert h.c.get(f"{ROOT}/risk", headers=auth, params={"alerts_only": True}).json()["items"] == []
    case_id = h.case_for(pid)["case"]["id"]
    case = h.c.get(f"/api/v2/analyst/cases/{case_id}", headers=auth).json()
    assert case["risk_assessment"]["score"] == 20


def test_settled_common_beneficiary_alert_deduplicates_and_can_be_reviewed(h, fake_clock, monkeypatch):
    auth = analyst(h, monkeypatch)
    recipient = h.session()
    account = h.c.post("/api/v2/accounts", headers=recipient, json={"display_name": "Recipient"}).json()
    senders = []
    for _ in range(3):
        customer = h.session()
        senders.append((customer, *h.onboard(customer, ref=account["account_ref"])))
    payment_ids = [pay_and_settle(h, *sender) for sender in senders]
    assert h.c.get(f"{ROOT}/aml", headers=auth).json()["total"] == 0

    payment_ids.append(pay_and_settle(h, *senders[0]))
    listing = h.c.get(f"{ROOT}/aml", headers=auth).json()
    assert listing["total"] == 1
    alert = listing["items"][0]
    assert alert["recipient_key"] == "acct:" + account["id"]
    assert alert["pattern"] == "COMMON_BENEFICIARY_PATTERN"
    assert alert["status"] == "NEW"
    assert alert["evidence"]["sender_count"] == 3
    assert alert["evidence"]["total_minor"] == 4_000_00
    assert {row["payment_id"] for row in alert["evidence"]["transactions"]} == set(payment_ids)
    case_id = h.case_for(payment_ids[0])["case"]["id"]
    case = h.c.get(f"/api/v2/analyst/cases/{case_id}", headers=auth).json()
    assert case["aml_alerts"][0]["id"] == alert["id"]

    url = f"{ROOT}/aml/{alert['id']}"
    assert h.c.get(url, headers=recipient).status_code == 401
    review = {"status": "UNDER_REVIEW", "expected_status": "NEW", "note": "Review the settled transfers"}
    assert h.c.post(url + "/review", json=review, headers=auth).status_code == 200
    assert h.c.post(url + "/review", json=review, headers=auth).status_code == 409
    assert h.c.get(url, headers=auth).json()["reviews"][0]["note"] == review["note"]
    pay_and_settle(h, *senders[1])
    assert h.c.get(f"{ROOT}/aml", headers=auth).json()["total"] == 1

    fake_clock.advance(8 * clock.DAY)
    h._analyst = None
    for sender in [*senders, senders[0]]:
        pay_and_settle(h, *sender)
    refreshed = analyst(h, monkeypatch)
    assert h.c.get(f"{ROOT}/aml", headers=refreshed).json()["total"] == 2
