"""HTTP load profile against running API and worker processes.

    python tools/loadtest.py --base http://127.0.0.1:8000 --passcode ... --clients 20 --transfers 5 --dup 100

Each client creates its own account and beneficiary, then per transfer: opens a call,
streams 3 s of synthetic PCM, finishes it, and submits. Investigation latency is the time
until the SOC case report appears. Also fires `--dup` simultaneous retries of one key.
Prints p50/p95/p99 per stage, throughput, backlog drain and integrity checks as JSON.
"""
from __future__ import annotations

import argparse
import json
import statistics
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import httpx
import numpy as np


def pcm(seconds=3.0, seed=1) -> bytes:
    rng = np.random.default_rng(seed)
    n = int(16_000 * seconds)
    t = np.arange(n) / 16_000
    env = (0.5 + 0.5 * np.sin(2 * np.pi * 4 * t)) ** 2
    x = rng.normal(0, 0.25, n) * env + 0.1 * np.sin(2 * np.pi * 180 * t) * env
    return (np.clip(x, -1, 1) * 20_000).astype("<i2").tobytes()


def pct(xs, q):
    if not xs:
        return None
    s = sorted(xs)
    return round(s[min(len(s) - 1, int(round(q * (len(s) - 1))))], 1)


def summarize(xs):
    return {"n": len(xs), "p50_ms": pct(xs, .5), "p95_ms": pct(xs, .95), "p99_ms": pct(xs, .99),
            "mean_ms": round(statistics.mean(xs), 1) if xs else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--passcode", required=True)
    ap.add_argument("--clients", type=int, default=20)
    ap.add_argument("--transfers", type=int, default=5)
    ap.add_argument("--dup", type=int, default=100)
    a = ap.parse_args()
    audio = pcm()
    lat = {"capture_upload": [], "capture_finish": [], "policy_commit": [], "investigation": []}
    lock = threading.Lock()
    pids: list[str] = []
    errors: list[str] = []
    soc_tok = httpx.post(f"{a.base}/api/v2/soc/login", json={"name": "loadtest", "passcode": a.passcode}).json()["token"]
    soc_h = {"Authorization": f"Bearer {soc_tok}"}

    def client(i):
        c = httpx.Client(base_url=a.base, timeout=60)
        h = {"Authorization": f"Bearer {c.post('/api/v2/session').json()['token']}"}
        acct = c.post("/api/v2/accounts", json={"display_name": f"Load {i}"}, headers=h).json()["id"]
        ben = c.post("/api/v2/beneficiaries", json={"display_name": "Recipient", "account_ref": f"LOAD{i:06d}{uuid.uuid4().hex[:4].upper()}"}, headers=h).json()["id"]
        for k in range(a.transfers):
          try:
            t0 = time.perf_counter()
            cid = c.post("/api/v2/calls", json={"consent": True}, headers=h).json()["id"]
            for off in range(0, len(audio), 32_000):
                c.post(f"/api/v2/calls/{cid}/pcm", content=audio[off:off + 32_000], headers=h)
            t1 = time.perf_counter()
            st = c.post(f"/api/v2/calls/{cid}/finish", headers=h).json()
            t2 = time.perf_counter()
            if not st.get("usable"):
                errors.append(f"unusable capture {st}")
                continue
            r = c.post("/api/v2/payments", headers={**h, "Idempotency-Key": uuid.uuid4().hex},
                       json={"account_id": acct, "beneficiary_id": ben, "amount_minor": 1_000_00 + k, "channel": "IMPS",
                             "remark": None, "call_id": cid})
            t3 = time.perf_counter()
            if r.status_code != 201:
                errors.append(f"submit {r.status_code} {r.text[:120]}")
                continue
            with lock:
                lat["capture_upload"].append((t1 - t0) * 1000)
                lat["capture_finish"].append((t2 - t1) * 1000)
                lat["policy_commit"].append((t3 - t2) * 1000)
                pids.append((r.json()["payment_id"], time.perf_counter()))
          except Exception as e:  # noqa: BLE001  (in-flight failures during outage drills)
            errors.append(f"{type(e).__name__}: {str(e)[:100]}")
        return h, acct, ben

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=a.clients) as ex:
        setups = list(ex.map(client, range(a.clients)))
    submit_elapsed = time.perf_counter() - start

    # Investigation latency: poll until each case has a report.
    c = httpx.Client(base_url=a.base, timeout=30)
    pending = dict(pids)
    deadline = time.perf_counter() + 120
    backlog_samples = []
    while pending and time.perf_counter() < deadline:
        try:
            q = c.get("/api/v2/soc/cases", params={"state": "open", "limit": 200, "sort": "updated"}, headers=soc_h).json()
            an = c.get("/api/v2/soc/analytics", headers=soc_h).json()["worker"]
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
            continue
        backlog_samples.append(an["queued"] + an["leased"])
        for item in q["items"]:
            pid = item["payment_id"]
            if pid in pending:
                f = c.get(f"/api/v2/soc/cases/{item['case_id']}", headers=soc_h).json()
                if f["case"]["report"]:
                    lat["investigation"].append((time.perf_counter() - pending.pop(pid)) * 1000)
        time.sleep(0.25)
    drain_s = time.perf_counter() - start - submit_elapsed

    # Duplicate retries of one key.
    h, acct, ben = setups[0]
    dc = httpx.Client(base_url=a.base, timeout=60)
    cid = dc.post("/api/v2/calls", json={"consent": True}, headers=h).json()["id"]
    for off in range(0, len(audio), 32_000):
        dc.post(f"/api/v2/calls/{cid}/pcm", content=audio[off:off + 32_000], headers=h)
    dc.post(f"/api/v2/calls/{cid}/finish", headers=h)
    key = uuid.uuid4().hex
    body = {"account_id": acct, "beneficiary_id": ben, "amount_minor": 500_00, "channel": "IMPS", "remark": None, "call_id": cid}
    with ThreadPoolExecutor(max_workers=50) as ex:
        res = list(ex.map(lambda _: httpx.post(f"{a.base}/api/v2/payments", json=body,
                                                 headers={**h, "Idempotency-Key": key}, timeout=60), range(a.dup)))
    dup_status = {s: sum(1 for r in res if r.status_code == s) for s in {r.status_code for r in res}}
    dup_ids = {r.json().get("payment_id") for r in res if r.status_code in (200, 201)}

    out = {
        "clients": a.clients, "transfers_per_client": a.transfers, "submitted": len(pids), "errors": errors[:10],
        "throughput_submits_per_s": round(len(pids) / submit_elapsed, 2),
        "latency": {k: summarize(v) for k, v in lat.items()},
        "investigations_unfinished": len(pending), "backlog_peak": max(backlog_samples) if backlog_samples else None,
        "backlog_drain_s_after_submit": round(drain_s, 2),
        "duplicate_retries": {"requests": a.dup, "status_counts": dup_status, "distinct_payment_ids": len(dup_ids)},
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
