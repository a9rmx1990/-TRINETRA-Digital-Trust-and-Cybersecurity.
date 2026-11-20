"""Customer-side services: accounts, beneficiaries, voice capture, payments, verification.

The gateway alone determines initial disposition and settles transfers.
"""
from __future__ import annotations

import asyncio
import re
import secrets
import threading
from typing import Any, Literal

import numpy as np

from . import clock, graph, policy
from .config import settings
from .db import Tx, dumps, get_db, loads
from .events import append_event, enqueue, publish_hints
from .inference import get_runtime, measure_capture
from .util import ApiError, const_eq, format_inr, hmac_hex, mask_ref, new_id, sha256

REF_RE = re.compile(r"^[A-Z0-9]{6,18}$")
CHANNELS = ("IMPS", "NEFT", "UPI", "RTGS")
MAX_AMOUNT_MINOR = 10_00_00_000_00  # ₹10 crore sandbox ceiling


# ============================================================== accounts
def _new_account_ref(t: Tx) -> str:
    while True:
        ref = "SBX" + "".join(secrets.choice("0123456789") for _ in range(11))
        if not t.one("SELECT 1 AS x FROM accounts WHERE account_ref = ?", (ref,)):
            return ref


def account_view(r: dict) -> dict:
    return {"id": r["id"], "display_name": r["display_name"], "account_ref_masked": mask_ref(r["account_ref"]),
            "status": r["status"], "created_ms": r["created_ms"]}


def create_account(owner_id: str, display_name: str) -> dict:
    name = display_name.strip()
    if not 2 <= len(name) <= 60:
        raise ApiError(422, "invalid_name", "Enter a display name between 2 and 60 characters.")
    def _go(t: Tx):
        aid = new_id("acc")
        ref = _new_account_ref(t)
        now = clock.now_ms()
        t.execute("INSERT INTO accounts(id, owner_id, display_name, account_ref, created_ms) VALUES (?,?,?,?,?)",
                  (aid, owner_id, name, ref, now))
        # If another customer already registered this reference as a beneficiary, link it.
        t.execute("UPDATE counterparties SET sandbox_account_id = ? WHERE account_ref = ?", (aid, ref))
        return t.one("SELECT * FROM accounts WHERE id = ?", (aid,))
    row = get_db().write(_go)
    return {**account_view(row), "account_ref": row["account_ref"]}


def list_accounts(owner_id: str) -> list[dict]:
    rows = get_db().read(lambda t: t.all(
        "SELECT * FROM accounts WHERE owner_id = ? AND legacy_demo = 0 ORDER BY created_ms", (owner_id,)))
    return [{**account_view(r), "account_ref": r["account_ref"]} for r in rows]


def _owned_account(t: Tx, owner_id: str, account_id: str) -> dict:
    r = t.one("SELECT * FROM accounts WHERE id = ? AND owner_id = ?", (account_id, owner_id))
    if not r:
        raise ApiError(404, "account_not_found", "Account not found.")
    return r


# ============================================================== beneficiaries
def benef_view(r: dict) -> dict:
    return {"id": r["id"], "display_name": r["display_name"], "account_ref_masked": mask_ref(r["account_ref"]),
            "created_ms": r["created_ms"]}


def add_beneficiary(owner_id: str, display_name: str, account_ref: str) -> dict:
    name = display_name.strip()
    ref = re.sub(r"[\s-]", "", account_ref).upper()
    if not 2 <= len(name) <= 60:
        raise ApiError(422, "invalid_name", "Enter a beneficiary name between 2 and 60 characters.", field="display_name")
    if not REF_RE.match(ref):
        raise ApiError(422, "invalid_reference", "Account reference must be 6 to 18 letters or digits.", field="account_ref")
    def _go(t: Tx):
        own = t.one("SELECT 1 AS x FROM accounts WHERE owner_id = ? AND account_ref = ?", (owner_id, ref))
        if own:
            raise ApiError(422, "own_account", "That reference is one of your own sandbox accounts.", field="account_ref")
        t.lock_keys(f"cp:{ref}")
        cp = t.one("SELECT id FROM counterparties WHERE account_ref = ?", (ref,))
        now = clock.now_ms()
        if not cp:
            cid = new_id("cp")
            linked = t.one("SELECT id FROM accounts WHERE account_ref = ?", (ref,))
            t.execute("INSERT INTO counterparties(id, account_ref, sandbox_account_id, created_ms) VALUES (?,?,?,?)",
                      (cid, ref, linked["id"] if linked else None, now))
        else:
            cid = cp["id"]
        existing = t.one("SELECT * FROM beneficiaries WHERE owner_id = ? AND account_ref = ?", (owner_id, ref))
        if existing and existing["removed_ms"] is None:
            raise ApiError(409, "duplicate_beneficiary", "This beneficiary is already saved.", field="account_ref")
        if existing:
            t.execute("UPDATE beneficiaries SET removed_ms = NULL, display_name = ? WHERE id = ?", (name, existing["id"]))
            return t.one("SELECT * FROM beneficiaries WHERE id = ?", (existing["id"],))
        bid = new_id("ben")
        t.execute("INSERT INTO beneficiaries(id, owner_id, counterparty_id, display_name, account_ref, created_ms)"
                  " VALUES (?,?,?,?,?,?)", (bid, owner_id, cid, name, ref, now))
        return t.one("SELECT * FROM beneficiaries WHERE id = ?", (bid,))
    return benef_view(get_db().write(_go))


def list_beneficiaries(owner_id: str) -> list[dict]:
    rows = get_db().read(lambda t: t.all(
        "SELECT * FROM beneficiaries WHERE owner_id = ? AND removed_ms IS NULL AND legacy_demo = 0 ORDER BY created_ms",
        (owner_id,)))
    return [benef_view(r) for r in rows]


def remove_beneficiary(owner_id: str, bid: str) -> None:
    n = get_db().write(lambda t: t.rowcount(
        "UPDATE beneficiaries SET removed_ms = ? WHERE id = ? AND owner_id = ? AND removed_ms IS NULL",
        (clock.now_ms(), bid, owner_id)))
    if not n:
        raise ApiError(404, "beneficiary_not_found", "Beneficiary not found.")


# ============================================================== voice capture
class AudioBuffers:
    """Raw audio lives only in bounded process memory and is discarded at finish or expiry."""

    def __init__(self):
        self._b: dict[str, bytearray] = {}
        self._lock = threading.Lock()

    def append(self, cid: str, data: bytes) -> int:
        cap = settings.max_audio_seconds * 16_000 * 2
        with self._lock:
            buf = self._b.setdefault(cid, bytearray())
            if len(buf) + len(data) > cap:
                raise ApiError(413, "capture_too_long", f"Recording is limited to {settings.max_audio_seconds} seconds.")
            buf.extend(data)
            return len(buf)

    def pop(self, cid: str) -> bytes:
        with self._lock:
            return bytes(self._b.pop(cid, b""))

    def drop(self, cid: str) -> None:
        with self._lock:
            self._b.pop(cid, None)

    def size(self, cid: str) -> int:
        with self._lock:
            return len(self._b.get(cid, b""))


class RedisAudioBuffers:
    """Shared audio cache for multi-process API deployments. Raw audio expires after a TTL
    and is deleted at finish; it is configured separately from the job broker."""

    def __init__(self, url: str, ttl_s: int):
        import redis
        self.r = redis.Redis.from_url(url, socket_timeout=2)
        self.ttl = ttl_s

    def _k(self, cid: str) -> str:
        return f"trinetra:audio:{cid}"

    def append(self, cid: str, data: bytes) -> int:
        cap = settings.max_audio_seconds * 16_000 * 2
        k = self._k(cid)
        if (self.r.strlen(k) or 0) + len(data) > cap:
            raise ApiError(413, "capture_too_long", f"Recording is limited to {settings.max_audio_seconds} seconds.")
        pipe = self.r.pipeline()
        pipe.append(k, data)
        pipe.expire(k, self.ttl)
        n, _ = pipe.execute()
        return int(n)

    def pop(self, cid: str) -> bytes:
        pipe = self.r.pipeline()
        pipe.get(self._k(cid))
        pipe.delete(self._k(cid))
        data, _ = pipe.execute()
        return data or b""

    def drop(self, cid: str) -> None:
        self.r.delete(self._k(cid))

    def size(self, cid: str) -> int:
        return int(self.r.strlen(self._k(cid)) or 0)


audio = (RedisAudioBuffers(settings.audio_cache_url, settings.audio_cache_ttl_s)
         if settings.audio_cache_url else AudioBuffers())


def _expire_calls(t: Tx) -> None:
    now = clock.now_ms()
    rows = t.all("SELECT id FROM calls WHERE status = 'open' AND expires_ms < ?", (now,))
    for r in rows:
        audio.drop(r["id"])
    if rows:
        t.execute("UPDATE calls SET status = 'expired' WHERE status = 'open' AND expires_ms < ?", (now,))


def call_view(r: dict) -> dict:
    a = loads(r.get("analysis"), {}) or {}
    now = clock.now_ms()
    fresh = r["status"] == "finished" and r["finished_ms"] and now - r["finished_ms"] <= settings.capture_fresh_ms
    return {"id": r["id"], "status": r["status"], "created_ms": r["created_ms"], "expires_ms": r["expires_ms"],
            "finished_ms": r["finished_ms"], "duration_ms": r["duration_ms"], "voiced_ms": r["voiced_ms"],
            "usable": bool(r["usable"]), "quality_reason": r["quality_reason"], "language": r["language"],
            "language_supported": None if r["language_supported"] is None else bool(r["language_supported"]),
            "transcript_status": (a.get("transcript") or {}).get("status"),
            "fresh_for_submission": bool(fresh and r["usable"] and not r["payment_id"]),
            "used_by_payment": bool(r["payment_id"]),
            "bytes_buffered": audio.size(r["id"]) if r["status"] == "open" else 0}


def start_call(owner_id: str, consent: bool) -> dict:
    if not consent:
        raise ApiError(422, "consent_required", "Consent to voice screening is required before recording.")
    def _go(t: Tx):
        _expire_calls(t)
        now = clock.now_ms()
        cid = new_id("call")
        t.execute("INSERT INTO calls(id, owner_id, status, consent_ms, created_ms, expires_ms) VALUES (?,?,'open',?,?,?)",
                  (cid, owner_id, now, now, now + settings.call_ttl_ms))
        return t.one("SELECT * FROM calls WHERE id = ?", (cid,))
    return call_view(get_db().write(_go))


def _owned_call(t: Tx, owner_id: str, cid: str) -> dict:
    r = t.one("SELECT * FROM calls WHERE id = ?", (cid,))
    if not r or r["owner_id"] != owner_id:
        raise ApiError(404, "call_not_found", "Recording session not found.")
    return r


def append_pcm(owner_id: str, cid: str, data: bytes) -> dict:
    if len(data) % 2:
        raise ApiError(422, "bad_pcm", "PCM must be 16-bit little-endian mono samples.")
    r = get_db().read(lambda t: _owned_call(t, owner_id, cid))
    if r["status"] != "open":
        raise ApiError(409, "call_not_open", "This recording has ended. Start a new recording.", status=r["status"])
    if r["expires_ms"] < clock.now_ms():
        get_db().write(_expire_calls)
        raise ApiError(410, "call_expired", "The recording session expired. Start a new recording.")
    n = audio.append(cid, data)
    return {"bytes": n, "duration_ms": n // 32}


def get_call(owner_id: str, cid: str) -> dict:
    def _go(t: Tx):
        _expire_calls(t)
        return _owned_call(t, owner_id, cid)
    return call_view(get_db().write(_go))


async def finish_call(owner_id: str, cid: str) -> dict:
    db = get_db()
    r = db.read(lambda t: _owned_call(t, owner_id, cid))
    if r["status"] == "finished":
        return call_view(r)
    if r["status"] != "open":
        raise ApiError(409, "call_not_open", "This recording has ended. Start a new recording.", status=r["status"])
    if r["expires_ms"] < clock.now_ms():
        db.write(_expire_calls)
        raise ApiError(410, "call_expired", "The recording session expired. Start a new recording.")
    pcm = np.frombuffer(audio.pop(cid), dtype="<i2")
    q = measure_capture(pcm)
    analysis: dict[str, Any] = {"quality": {"duration_ms": q.duration_ms, "voiced_ms": q.voiced_ms,
                                            "rms_dbfs": q.rms_dbfs, "clipped_ratio": q.clipped_ratio,
                                            "frame_ms": 20 * max(1, (q.duration_ms // 20) // 200 or 1),
                                            "levels_dbfs": q.frame_dbfs, "reason": q.reason}}
    language = None
    lang_ok = None
    if q.usable:
        rt = get_runtime()
        spoof_obs, asr_obs = await asyncio.gather(rt.spoof(pcm), rt.transcribe(pcm))
        language = asr_obs.get("language")
        speech_obs = await rt.classify_text("speech_content", asr_obs.get("text"), language)
        if speech_obs.get("status") == "unsupported_language":
            lang_ok = False
        elif language:
            lang_ok = True
        analysis.update({"voice_authenticity": spoof_obs, "transcript": asr_obs, "speech_content": speech_obs})
    del pcm  # raw audio is not persisted
    now = clock.now_ms()
    def _store(t: Tx):
        cur = _owned_call(t, owner_id, cid)
        if cur["status"] != "open":
            return cur
        t.execute("UPDATE calls SET status = 'finished', finished_ms = ?, duration_ms = ?, voiced_ms = ?, usable = ?,"
                  " quality_reason = ?, language = ?, language_supported = ?, analysis = ? WHERE id = ?",
                  (now, q.duration_ms, q.voiced_ms, 1 if q.usable else 0, q.reason, language,
                   None if lang_ok is None else int(lang_ok), dumps(analysis), cid))
        return t.one("SELECT * FROM calls WHERE id = ?", (cid,))
    return call_view(db.write(_store))


def delete_call(owner_id: str, cid: str) -> None:
    def _go(t: Tx):
        r = _owned_call(t, owner_id, cid)
        audio.drop(cid)
        if r["payment_id"]:
            # Evidence linked to a submitted payment is retained; drop only the raw-derived level series.
            return
        t.execute("UPDATE calls SET status = 'deleted', analysis = NULL WHERE id = ?", (cid,))
    get_db().write(_go)


# ============================================================== payments
STATE_FOR = {"ALLOW": "SETTLED", "STEP_UP": "VERIFICATION_REQUIRED", "HOLD": "HELD", "BLOCK": "BLOCKED"}
NEXT_ACTION = {
    "SETTLED": ("Transfer settled.", "view_history"),
    "VERIFICATION_REQUIRED": ("Additional verification is required before this transfer can settle.", "enter_code"),
    "HELD": ("This transfer is on hold while our team reviews it.", "check_status"),
    "BLOCKED": ("This transfer is blocked because of an account restriction.", "contact_support"),
    "REJECTED": ("This transfer was not completed after review. No money moved.", "view_history"),
}
WAIT_FOR_ANALYST = ("Waiting for analyst verification.", "wait_for_analyst")


def fingerprint(body: dict, direction: Literal["outgoing", "incoming"] = "outgoing") -> str:
    keys = ("account_id", "beneficiary_id", "amount_minor", "channel", "remark", "call_id")
    fields = {k: body.get(k) for k in keys}
    if direction == "incoming":
        fields["direction"] = direction
    return sha256(dumps(fields))


def receipt_for(p: dict, benef: dict) -> dict:
    msg, nxt = (WAIT_FOR_ANALYST if p["direction"] == "incoming" and p["state"] == "VERIFICATION_REQUIRED"
                else NEXT_ACTION[p["state"]])
    return {"payment_id": p["id"], "reference": p["id"][-10:].upper(), "state": p["state"],
            "amount_minor": p["amount_minor"], "amount_display": format_inr(p["amount_minor"]),
            "currency": p["currency"], "channel": p["channel"], "direction": p["direction"],
            "beneficiary_name": benef["display_name"],
            "beneficiary_masked": mask_ref(benef["account_ref"]), "created_ms": p["created_ms"],
            "updated_ms": p["updated_ms"], "message": msg, "next_action": nxt}


def payment_view(t: Tx, p: dict, *, full_receipt: bool = False) -> dict:
    b = t.one("SELECT * FROM beneficiaries WHERE id = ?", (p["beneficiary_id"],))
    v = receipt_for(p, b)
    if p["direction"] == "incoming":
        if full_receipt and p["state"] == "SETTLED":
            v["analyst_verified"] = bool(t.scalar(
                "SELECT 1 FROM cases c JOIN case_events e ON e.case_id = c.id"
                " WHERE c.payment_id = ? AND e.type = 'action_verify_incoming' LIMIT 1", (p["id"],)))
    elif p["state"] == "VERIFICATION_REQUIRED":
        ch = t.one("SELECT salt, expires_ms, attempts, max_attempts, status FROM challenges"
                   " WHERE payment_id = ? AND owner_id = ? ORDER BY created_ms DESC LIMIT 1",
                   (p["id"], p["owner_id"]))
        v["challenge"] = None
        if ch:
            status = challenge_status(ch)
            v["challenge"] = {"status": status, "expires_ms": ch["expires_ms"],
                              "attempts_left": max(0, ch["max_attempts"] - ch["attempts"])}
            if full_receipt and status == "active" and is_receipt_challenge(ch):
                v["challenge"]["delivery_code"] = _receipt_challenge_code(ch["salt"])
    return v


def active_restrictions(t: Tx, account_id: str, counterparty_id: str) -> list[dict]:
    cp = t.one("SELECT sandbox_account_id FROM counterparties WHERE id = ?", (counterparty_id,))
    ids = [("account", account_id), ("counterparty", counterparty_id)]
    if cp and cp["sandbox_account_id"]:
        ids.append(("account", cp["sandbox_account_id"]))
    out = []
    for st, sid in ids:
        out.extend(t.all("SELECT id, scope_type, scope_id, reason FROM restrictions WHERE scope_type = ? AND scope_id = ?"
                         " AND active = 1", (st, sid)))
    return out


def sender_account_id(t: Tx, payment: dict) -> str | None:
    if payment["direction"] == "outgoing":
        return payment["account_id"]
    return t.scalar("SELECT sandbox_account_id FROM counterparties WHERE id = ?", (payment["counterparty_id"],))


def _replay(t: Tx, owner_id: str, key: str, fp: str) -> dict | None:
    p = t.one("SELECT * FROM payments WHERE owner_id = ? AND idem_key = ?", (owner_id, key))
    if not p:
        return None
    if p["fingerprint"] != fp:
        raise ApiError(409, "idempotency_conflict", "This submission key was already used for a different transfer.")
    stored = loads(p["receipt"])
    if p["direction"] == "incoming" and stored["state"] == "VERIFICATION_REQUIRED":
        stored["message"], stored["next_action"] = WAIT_FOR_ANALYST
    return {**stored, "direction": p["direction"], "replayed": True}


async def submit_payment(owner_id: str, idem_key: str | None, body: dict, *,
                         direction: Literal["outgoing", "incoming"] = "outgoing") -> tuple[int, dict]:
    db = get_db()
    if not idem_key or not re.match(r"^[A-Za-z0-9_\-]{8,80}$", idem_key):
        raise ApiError(422, "idempotency_key_required", "An Idempotency-Key header (8-80 chars) is required.")
    fp = fingerprint(body, direction)
    prior = db.read(lambda t: _replay(t, owner_id, idem_key, fp))
    if prior:
        return 200, prior

    amount = body.get("amount_minor")
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0 or amount > MAX_AMOUNT_MINOR:
        raise ApiError(422, "invalid_amount", "Enter an amount greater than zero, in whole paise.", field="amount")
    if body.get("channel") not in CHANNELS:
        raise ApiError(422, "invalid_channel", "Choose a payment channel.", field="channel")
    remark = (body.get("remark") or "").strip()[:140] or None
    call_id = body.get("call_id")
    if not call_id:
        raise ApiError(422, "capture_required", "Record the voice confirmation before submitting.")

    def _validate(t: Tx):
        acct = _owned_account(t, owner_id, body.get("account_id") or "")
        b = t.one("SELECT * FROM beneficiaries WHERE id = ? AND owner_id = ? AND removed_ms IS NULL",
                  (body.get("beneficiary_id") or "", owner_id))
        if not b:
            raise ApiError(404, "beneficiary_not_found", "Choose one of your saved beneficiaries.", field="beneficiary_id")
        c = t.one("SELECT * FROM calls WHERE id = ?", (call_id,))
        _check_call(c, owner_id)
        return acct, b, c
    try:
        acct, benef, call = db.read(_validate)
    except ApiError:
        # A concurrent identical request may have committed between our first check and validation.
        prior = db.read(lambda t: _replay(t, owner_id, idem_key, fp))
        if prior:
            return 200, prior
        raise

    analysis = loads(call["analysis"], {}) or {}
    rt = get_runtime()
    now = clock.now_ms()
    proposed = {"payment_id": None, "amount_minor": amount, "created_ms": now, "proposed": True}

    def _graph_snapshot():
        return db.read(lambda t: (graph.watermark(t), graph.build(
            t, owner_id=owner_id, account_id=acct["id"], counterparty_id=benef["counterparty_id"], at_ms=now, direction=direction,
            proposed=proposed)))
    remark_obs, (wm, gr) = await asyncio.gather(
        rt.classify_text("typed_remark", remark, None), asyncio.to_thread(_graph_snapshot))

    def _commit(t: Tx):
        replay = _replay(t, owner_id, idem_key, fp)
        if replay:
            return 200, replay
        t.lock_rows("accounts", [acct["id"]])
        t.lock_rows("counterparties", [benef["counterparty_id"]])
        t.lock_rows("calls", [call_id])
        c = t.one("SELECT * FROM calls WHERE id = ?", (call_id,))
        _check_call(c, owner_id)
        nonlocal gr
        if graph.watermark(t) != wm:  # freshness recheck before policy evaluation
            gr = graph.build(t, owner_id=owner_id, account_id=acct["id"], counterparty_id=benef["counterparty_id"],
                             at_ms=now, direction=direction, proposed=proposed)
        restricted = active_restrictions(t, acct["id"], benef["counterparty_id"])
        signals = {
            "voice_authenticity": analysis.get("voice_authenticity") or {"status": "unavailable", "review_only": True},
            "speech_content": analysis.get("speech_content") or {"status": "unavailable", "review_only": True},
            "typed_remark": remark_obs if remark else {"signal": "typed_remark", "status": "not_provided",
                                                       "review_only": True, "reason": "no remark entered"},
            "recipient_graph": graph.signal_from_graph(gr),
        }
        d = policy.evaluate(amount_minor=amount, restricted=restricted, signals=signals, direction=direction)
        pid = new_id("pay")
        state = STATE_FOR[d.decision]
        p = {"id": pid, "owner_id": owner_id, "account_id": acct["id"], "beneficiary_id": benef["id"],
             "counterparty_id": benef["counterparty_id"], "amount_minor": amount, "currency": "INR",
             "channel": body["channel"], "direction": direction, "remark": remark, "call_id": call_id, "idem_key": idem_key,
             "fingerprint": fp, "decision": d.decision, "policy_version": d.policy_version, "state": state,
             "created_ms": now, "updated_ms": now}
        receipt = receipt_for(p, benef)
        t.execute("INSERT INTO payments(id, owner_id, account_id, beneficiary_id, counterparty_id, amount_minor, currency,"
                  " channel, direction, remark, call_id, idem_key, fingerprint, decision, policy_version, state, reasons, signals,"
                  " receipt, created_ms, updated_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (pid, owner_id, acct["id"], benef["id"], benef["counterparty_id"], amount, "INR", body["channel"], direction,
                   remark, call_id, idem_key, fp, d.decision, d.policy_version, state, dumps(d.reasons),
                   dumps(d.signal_status), dumps(receipt), now, now))
        if t.rowcount("UPDATE calls SET payment_id = ? WHERE id = ? AND payment_id IS NULL", (pid, call_id)) != 1:
            raise ApiError(409, "capture_already_used", "This recording was already used. Record again for a new transfer.")
        ev_ids = _store_evidence(t, pid, call_id, signals, gr, analysis)
        if d.decision == "ALLOW":
            settle(t, p)
        else:
            _open_case(t, p, d, ev_ids, gr)
        return 201, receipt

    try:
        status, result = db.write(_commit)
    except ApiError:
        prior = db.read(lambda t: _replay(t, owner_id, idem_key, fp))
        if prior:
            return 200, prior
        raise
    except Exception as e:
        if db.is_integrity(e):
            # A concurrent identical submission committed first.
            prior = db.read(lambda t: _replay(t, owner_id, idem_key, fp))
            if prior:
                return 200, prior
            raise ApiError(409, "capture_already_used",
                           "This recording was already used. Record again for a new transfer.") from e
        raise
    publish_hints()
    return status, result


def _check_call(c: dict | None, owner_id: str) -> None:
    if not c or c["owner_id"] != owner_id:
        raise ApiError(422, "capture_not_found", "Voice confirmation not found for this session. Record again.")
    if c["status"] != "finished":
        raise ApiError(422, "capture_unfinished", "Finish the voice recording before submitting.")
    if not c["usable"]:
        raise ApiError(422, "capture_unusable", "The recording did not contain usable speech. Record again.",
                       reason=c["quality_reason"])
    if c["payment_id"]:
        raise ApiError(409, "capture_already_used", "This recording was already used. Record again for a new transfer.")
    if clock.now_ms() - (c["finished_ms"] or 0) > settings.capture_fresh_ms:
        raise ApiError(422, "capture_expired", "The voice confirmation expired. Record again.")


def _store_evidence(t: Tx, pid: str, call_id: str, signals: dict, gr: dict, analysis: dict) -> list[str]:
    now = clock.now_ms()
    ids = []
    rows = [("call", "capture_quality", {"status": "ok", "review_only": False, "model_id": "measured:rms-vad",
                                         "revision": "1", "score_scale": "dBFS", **(analysis.get("quality") or {})})]
    if analysis.get("transcript"):
        rows.append(("call", "transcript", analysis["transcript"]))
    for name in ("voice_authenticity", "speech_content", "typed_remark", "recipient_graph"):
        rows.append(("signal", name, signals[name]))
    rows.append(("graph", "recipient_graph_snapshot", {"status": "ok", "review_only": False,
                                                       "model_id": "deterministic:networkx", "revision": gr["method"], **gr}))
    for source, kind, obs in rows:
        eid = new_id("ev")
        ids.append(eid)
        t.execute("INSERT INTO evidence(id, payment_id, call_id, source, kind, status, model_id, revision, score_scale,"
                  " score, flagged, review_only, payload, created_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (eid, pid, call_id, source, kind, obs.get("status") or "unknown", obs.get("model_id"),
                   obs.get("revision"), obs.get("score_scale"),
                   obs.get("score") if isinstance(obs.get("score"), (int, float)) else None,
                   None if obs.get("flagged") is None else int(bool(obs.get("flagged"))),
                   1 if obs.get("review_only", True) else 0, dumps(obs), now))
    return ids


def settle(t: Tx, p: dict) -> None:
    sid = new_id("stl")
    t.execute("INSERT INTO settlements(id, payment_id, account_id, counterparty_id, owner_id, amount_minor, created_ms)"
              " VALUES (?,?,?,?,?,?,?)", (sid, p["id"], p["account_id"], p["counterparty_id"], p["owner_id"],
                                          p["amount_minor"], clock.now_ms()))


def _open_case(t: Tx, p: dict, d: policy.Decision, ev_ids: list[str], gr: dict) -> None:
    sev = {"HOLD": "high", "BLOCK": "high"}.get(d.decision, "high" if gr["fan_in"] else "medium")
    prio = {"high": 1, "medium": 2, "low": 3}[sev]
    cid = new_id("case")
    now = p["created_ms"]
    t.execute("UPDATE evidence SET case_id = ? WHERE payment_id = ?", (cid, p["id"]))
    t.execute("INSERT INTO cases(id, payment_id, owner_id, scope, state, severity, priority, hold_active, version,"
              " created_ms, updated_ms) VALUES (?,?,?,?,'open',?,?,?,1,?,?)",
              (cid, p["id"], p["owner_id"], settings.analyst_scope, sev, prio, 1 if d.decision == "HOLD" else 0, now, now))
    append_event(t, case_id=cid, payment_id=p["id"], type="payment_screened", actor="gateway", case_version=1,
                 new_state="open", data={"decision": d.decision, "policy_version": d.policy_version,
                                         "payment_state": p["state"], "direction": p["direction"], "reasons": d.reasons}, evidence_ids=ev_ids)
    enqueue(t, case_id=cid, kind="investigate", case_version=1, trigger_key=f"investigate:{cid}:1")


# ---- history / status ----------------------------------------------------
def list_payments(owner_id: str, limit: int = 50, before_ms: int | None = None) -> dict:
    limit = max(1, min(limit, 100))
    def _go(t: Tx):
        q = "SELECT * FROM payments WHERE owner_id = ? AND legacy_demo = 0"
        args: list[Any] = [owner_id]
        if before_ms:
            q += " AND created_ms < ?"
            args.append(before_ms)
        rows = t.all(q + " ORDER BY created_ms DESC LIMIT ?", (*args, limit + 1))
        items = [payment_view(t, r) for r in rows[:limit]]
        return {"items": items, "next_before_ms": rows[limit - 1]["created_ms"] if len(rows) > limit else None}
    return get_db().read(_go)


def get_payment(owner_id: str, pid: str) -> dict:
    def _go(t: Tx):
        p = t.one("SELECT * FROM payments WHERE id = ? AND owner_id = ?", (pid, owner_id))
        if not p:
            raise ApiError(404, "payment_not_found", "Transfer not found.")
        return payment_view(t, p, full_receipt=True)
    return get_db().read(_go)


def get_payment_by_key(owner_id: str, key: str) -> dict:
    def _go(t: Tx):
        p = t.one("SELECT * FROM payments WHERE idem_key = ? AND owner_id = ?", (key, owner_id))
        if not p:
            raise ApiError(404, "payment_not_found", "No transfer was recorded for that attempt. It is safe to submit.")
        return payment_view(t, p)
    return get_db().read(_go)


# ---- verification ----------------------------------------------------------
CHALLENGE_TTL_MS = 15 * clock.MINUTE
CHALLENGE_MAX_ATTEMPTS = 5
RECEIPT_CHALLENGE_PREFIX = "receipt:v1:"


def hash_code(code: str, salt: str) -> str:
    return hmac_hex(salt, code)


def challenge_status(ch: dict) -> str:
    if ch["status"] == "active" and ch["expires_ms"] < clock.now_ms():
        return "expired"
    return ch["status"]


def is_receipt_challenge(ch: dict) -> bool:
    return ch["salt"].startswith(RECEIPT_CHALLENGE_PREFIX)


def _receipt_challenge_code(salt: str) -> str:
    # The authenticated sandbox receipt can recover its code without storing plaintext.
    digest = hmac_hex(settings.server_secret, f"payment-verification:{salt}")
    return f"{int(digest, 16) % 1_000_000:06d}"


def issue_challenge(t: Tx, p: dict, actor: str, *, deliver_to_receipt: bool = False) -> tuple[str, dict]:
    latest = t.one("SELECT salt, status, expires_ms, created_ms FROM challenges WHERE payment_id = ?"
                   " ORDER BY created_ms DESC LIMIT 1", (p["id"],))
    if deliver_to_receipt and latest and is_receipt_challenge(latest) and challenge_status(latest) == "active":
        raise ApiError(409, "verification_code_active", "A valid code is already in the customer's receipt.")
    t.execute("UPDATE challenges SET status = 'revoked' WHERE payment_id = ? AND status = 'active'", (p["id"],))
    salt = secrets.token_hex(16)
    if deliver_to_receipt:
        salt = RECEIPT_CHALLENGE_PREFIX + salt
    code = _receipt_challenge_code(salt) if deliver_to_receipt else f"{secrets.randbelow(1_000_000):06d}"
    chid = new_id("chl")
    now = clock.now_ms()
    exp = now + CHALLENGE_TTL_MS
    created = max(now, latest["created_ms"] + 1) if latest else now
    t.execute("INSERT INTO challenges(id, payment_id, owner_id, code_hash, salt, expires_ms, max_attempts, status,"
              " issued_by, created_ms) VALUES (?,?,?,?,?,?,?,'active',?,?)",
              (chid, p["id"], p["owner_id"], hash_code(code, salt), salt, exp, CHALLENGE_MAX_ATTEMPTS, actor, created))
    return code, {"challenge_id": chid, "expires_ms": exp, "max_attempts": CHALLENGE_MAX_ATTEMPTS}


def verify_payment(owner_id: str, pid: str, code: str) -> dict:
    code = (code or "").strip()
    if not re.fullmatch(r"\d{6}", code):
        raise ApiError(422, "invalid_code_format", "Enter the 6-digit code.")
    def _go(t: Tx):
        t.lock_rows("payments", [pid])
        p = t.one("SELECT * FROM payments WHERE id = ? AND owner_id = ?", (pid, owner_id))
        if not p:
            raise ApiError(404, "payment_not_found", "Transfer not found.")
        if p["direction"] == "incoming":
            raise ApiError(409, "analyst_verification_required", "The analyst verifies incoming requests in the workspace.")
        if p["state"] != "VERIFICATION_REQUIRED":
            return {"outcome": "not_required", "payment": payment_view(t, p)}
        ch = t.one("SELECT * FROM challenges WHERE payment_id = ? AND owner_id = ? ORDER BY created_ms DESC LIMIT 1",
                   (pid, owner_id))
        if not ch:
            return {"outcome": "no_challenge", "payment": payment_view(t, p)}
        if ch["status"] == "used":
            return {"outcome": "used", "payment": payment_view(t, p)}
        if ch["status"] in ("locked", "revoked"):
            return {"outcome": ch["status"], "payment": payment_view(t, p)}
        if ch["expires_ms"] < clock.now_ms():
            t.execute("UPDATE challenges SET status = 'expired' WHERE id = ? AND status = 'active'", (ch["id"],))
            return {"outcome": "expired", "payment": payment_view(t, p)}
        if ch["status"] == "expired":
            return {"outcome": "expired", "payment": payment_view(t, p)}
        if not const_eq(hash_code(code, ch["salt"]), ch["code_hash"]):
            attempts = ch["attempts"] + 1
            st = "locked" if attempts >= ch["max_attempts"] else "active"
            t.execute("UPDATE challenges SET attempts = ?, status = ? WHERE id = ?", (attempts, st, ch["id"]))
            return {"outcome": "locked" if st == "locked" else "incorrect", "payment": payment_view(t, p)}
        # Correct code: consume once, recheck restrictions and holds, then settle.
        if t.rowcount("UPDATE challenges SET status = 'used' WHERE id = ? AND status = 'active'", (ch["id"],)) != 1:
            return {"outcome": "used", "payment": payment_view(t, p)}
        case = t.one("SELECT * FROM cases WHERE payment_id = ?", (pid,))
        if case:
            t.lock_rows("cases", [case["id"]])
            case = t.one("SELECT * FROM cases WHERE id = ?", (case["id"],))
        restricted = active_restrictions(t, p["account_id"], p["counterparty_id"])
        now = clock.now_ms()
        if restricted:
            new_state, ev = "BLOCKED", "verification_blocked"
        elif case and case["hold_active"]:
            new_state, ev = "HELD", "verification_held"
        else:
            new_state, ev = "SETTLED", "verified_settled"
        t.execute("UPDATE payments SET state = ?, version = version + 1, updated_ms = ? WHERE id = ? AND state = 'VERIFICATION_REQUIRED'",
                  (new_state, now, pid))
        p = t.one("SELECT * FROM payments WHERE id = ?", (pid,))
        if new_state == "SETTLED":
            settle(t, p)
        if case:
            v = case["version"] + 1
            t.execute("UPDATE cases SET version = ?, updated_ms = ?, first_disposition_ms = COALESCE(first_disposition_ms, ?)"
                      " WHERE id = ?", (v, now, now, case["id"]))
            append_event(t, case_id=case["id"], payment_id=pid, type=ev, actor="customer", case_version=v,
                         prev_state="VERIFICATION_REQUIRED", new_state=new_state, data={"challenge_id": ch["id"]})
        return {"outcome": "verified" if new_state == "SETTLED" else new_state.lower(), "payment": payment_view(t, p)}
    return get_db().write(_go)
