"""Bounded in-memory media capture with optional Redis evidence cache."""

import asyncio
import importlib.util
import json
import os
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from uuid import uuid4

import numpy as np
from fastapi import HTTPException

from .models import SAMPLE_RATE, acoustic_baseline, models

TTL = 120
WINDOW = SAMPLE_RATE * 2
STRIDE = SAMPLE_RATE
FRAME = 320
MAX_SESSIONS = 8
HAS_WEBRTC = importlib.util.find_spec("aiortc") is not None
POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="call-inference")


@dataclass
class Call:
    owner: str
    expires: float = field(default_factory=lambda: time.time() + TTL)
    samples: deque = field(default_factory=lambda: deque(maxlen=WINDOW))
    recent: deque = field(default_factory=lambda: deque(maxlen=4))
    history: deque = field(default_factory=lambda: deque(maxlen=6))
    received: int = 0
    processed: int = 0
    evidence: dict | None = None
    pending: asyncio.Task | None = None
    receiver: asyncio.Task | None = None
    peer: object = None
    state: str = "capturing"
    transport: str | None = None

    def public(self, snapshot=None):
        evidence = self.evidence if snapshot is None else snapshot
        return {
            "state": self.state, "received_ms": self.received * 1000 // SAMPLE_RATE,
            "evidence": evidence if self.state == "ready" else None,
        }


class CallSessions:
    def __init__(self):
        self.calls = {}
        self.redis = None

    async def start(self):
        self.redis = None
        if url := os.getenv("TRINETRA_REDIS_URL"):
            from redis.asyncio import Redis
            self.redis = Redis.from_url(url, socket_connect_timeout=0.2, socket_timeout=0.2)

    def key(self, sid):
        return f"trinetra:sandbox:call:{sid}"

    async def cache(self, sid, evidence, expires):
        if self.redis:
            from redis.exceptions import RedisError
            try:
                await self.redis.set(self.key(sid), json.dumps(evidence), ex=max(1, int(expires - time.time())))
            except RedisError:
                return

    async def expire(self):
        now = time.time()
        for sid, call in list(self.calls.items()):
            if call.expires <= now:
                self.calls.pop(sid, None)
                if call.pending and not call.pending.done():
                    call.pending.cancel()
                await self.close(call)

    async def shutdown(self):
        for call in list(self.calls.values()):
            call.state = "closed"
            if call.pending and not call.pending.done():
                call.pending.cancel()
            await self.close(call)
        self.calls.clear()
        if self.redis:
            await self.redis.aclose()

    async def create(self, owner):
        await self.expire()
        if len(self.calls) >= MAX_SESSIONS:
            raise HTTPException(429, "Call capacity reached. Try again shortly.")
        sid = uuid4().hex
        self.calls[sid] = Call(owner)
        return {"session_id": sid, "expires_in": TTL, "webrtc": HAS_WEBRTC}

    def get(self, sid, owner):
        call = self.calls.get(sid)
        if not call or call.owner != owner or call.expires <= time.time():
            raise HTTPException(404, "Call session unavailable")
        return call

    async def close(self, call):
        if call.receiver and not call.receiver.done():
            call.receiver.cancel()
            await asyncio.gather(call.receiver, return_exceptions=True)
        if call.peer:
            await call.peer.close()
        call.samples.clear()

    def append(self, sid, call, pcm):
        if call.state != "capturing" or call.expires <= time.time():
            return
        if call.received + len(pcm) > SAMPLE_RATE * TTL:
            raise HTTPException(429, "Audio limit reached")
        call.samples.extend(pcm)
        call.received += len(pcm)
        if len(call.samples) >= WINDOW and call.received - call.processed >= STRIDE:
            self.schedule(sid, call)

    def schedule(self, sid, call):
        if call.pending and not call.pending.done():
            return False
        pcm = np.asarray(call.samples, dtype=np.float32)
        if len(pcm) < SAMPLE_RATE:
            return False
        call.processed = call.received
        call.pending = asyncio.create_task(self.infer(sid, call, pcm, call.processed))
        return True

    async def infer(self, sid, call, pcm, cursor):
        frames = pcm[:len(pcm) // FRAME * FRAME].reshape(-1, FRAME)
        voiced = float(np.mean(np.sqrt(np.mean(frames ** 2, axis=1)) > 0.009))
        if voiced < 0.15:
            return
        loop = asyncio.get_running_loop()
        try:
            baseline, spoof, asr = await asyncio.gather(
                loop.run_in_executor(POOL, acoustic_baseline, pcm),
                loop.run_in_executor(POOL, models.spoof_score, pcm),
                loop.run_in_executor(POOL, models.transcript, pcm),
            )
            text = await loop.run_in_executor(POOL, models.text_score, asr.get("text", ""), asr.get("language"))
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Call evidence failed")
            return
        if call.expires <= time.time():
            return
        window = {
            "evidence_id": uuid4().hex, "start_ms": (cursor - len(pcm)) * 1000 // SAMPLE_RATE,
            "end_ms": cursor * 1000 // SAMPLE_RATE, "voiced_fraction": round(voiced, 3),
            "baseline": baseline, "spoof": spoof, "asr": asr, "coercion": text,
        }
        call.recent.append(window)
        call.history.append({key: window[key] for key in ("evidence_id", "start_ms", "end_ms")}
                            | {"score": spoof.get("score"), "status": spoof["status"]})
        # Keep a bounded recent peak and retain the exact window behind each signal.
        acoustic = max(call.recent, key=lambda item: (
            item["spoof"].get("score", -1) if item["voiced_fraction"] >= 0.35 else -1,
            item["end_ms"],
        ))
        coercion = max(call.recent, key=lambda item: item["coercion"].get("score", -1))
        call.evidence = {"latest": window, "acoustic": acoustic, "coercion": coercion,
                         "history": list(call.history), "transport": call.transport, "computed_at": time.time()}
        await self.cache(sid, call.evidence, call.expires)

    async def finish(self, sid, call):
        if call.state != "capturing":
            return
        call.state = "processing"
        try:
            await asyncio.wait_for(self.finalize(sid, call), timeout=8)
        except TimeoutError:
            call.state = "timeout"
        finally:
            await self.close(call)

    async def finalize(self, sid, call):
        if call.pending:
            await asyncio.shield(call.pending)
        if call.received > call.processed and self.schedule(sid, call):
            await asyncio.shield(call.pending)
        if call.evidence and call.received * 1000 // SAMPLE_RATE - call.evidence["latest"]["end_ms"] <= 2500:
            call.state = "ready"
        else:
            call.state = "insufficient_audio"

    async def snapshot(self, sid, call):
        if call.state != "ready":
            return None
        if self.redis:
            from redis.exceptions import RedisError
            try:
                if raw := await self.redis.get(self.key(sid)):
                    return json.loads(raw)
            except RedisError:
                pass
        return call.evidence

    async def offer(self, sid, call, sdp):
        if not HAS_WEBRTC:
            raise HTTPException(503, "WebRTC dependencies unavailable")
        if call.transport or call.state != "capturing":
            raise HTTPException(409, "Call already negotiated")
        from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription

        servers = json.loads(os.getenv("TRINETRA_ICE_SERVERS", "[]"))
        call.peer = RTCPeerConnection(RTCConfiguration(iceServers=[RTCIceServer(**item) for item in servers]))
        call.transport = "webrtc"

        @call.peer.on("track")
        def on_track(track):
            if track.kind == "audio" and call.receiver is None:
                call.receiver = asyncio.create_task(self.receive(sid, call, track))

        async def negotiate():
            await call.peer.setRemoteDescription(RTCSessionDescription(sdp, "offer"))
            await call.peer.setLocalDescription(await call.peer.createAnswer())

        try:
            await asyncio.wait_for(negotiate(), 10)
        except Exception as exc:
            await self.close(call)
            call.state = "disconnected"
            raise HTTPException(400, "WebRTC negotiation failed") from exc
        return {"type": "answer", "sdp": call.peer.localDescription.sdp}

    async def receive(self, sid, call, track):
        import av
        from aiortc.mediastreams import MediaStreamError

        resampler = av.AudioResampler(format="fltp", layout="mono", rate=SAMPLE_RATE)
        try:
            while call.state == "capturing":
                for frame in resampler.resample(await track.recv()):
                    self.append(sid, call, frame.to_ndarray()[0])
        except (MediaStreamError, HTTPException, ValueError):
            if call.state == "capturing":
                call.state = "disconnected"


sessions = CallSessions()
