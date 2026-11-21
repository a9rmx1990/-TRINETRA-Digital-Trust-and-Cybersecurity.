"""Local inference: capture quality, model adapters, coercion rules.

Every signal returns an observation with explicit status and provenance. Model
checkpoints are loaded only from local directories listed in models/manifest.json and
verified by checksum at startup. Absent or unverified checkpoints yield status
`unavailable`; nothing is fabricated. Scores from models whose manifest entry has
`enforce: false` are review-only and never drive automatic holds.
"""
from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import logging
import os
import re
import threading
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import numpy as np

from . import realitydefender
from .config import settings

log = logging.getLogger("trinetra.inference")

SAMPLE_RATE = 16_000
FRAME_MS = 20
ONNX_VOICE_FILES = {"aasist_l_onnx": "aasist-l.onnx", "voiceguard_onnx": "model.onnx"}
ONNX_VOICE_WINDOW = 64_600
SUPPORTED_TEXT_LANGS_DEFAULT = ["en"]


# ---------------------------------------------------------------- capture quality
@dataclass
class CaptureQuality:
    duration_ms: int
    voiced_ms: int
    rms_dbfs: float
    clipped_ratio: float
    usable: bool
    reason: str | None
    frame_dbfs: list[float]


def measure_capture(pcm: np.ndarray) -> CaptureQuality:
    """Measured speech activity from 16 kHz mono int16 samples."""
    n = len(pcm)
    duration_ms = int(n * 1000 / SAMPLE_RATE)
    if n == 0:
        return CaptureQuality(0, 0, -120.0, 0.0, False, "no_audio", [])
    x = pcm.astype(np.float32) / 32768.0
    flen = SAMPLE_RATE * FRAME_MS // 1000
    nframes = n // flen
    frames = x[: nframes * flen].reshape(nframes, flen) if nframes else x.reshape(1, -1)
    rms = np.sqrt(np.mean(frames ** 2, axis=1) + 1e-12)
    dbfs = 20 * np.log10(rms)
    floor = float(np.percentile(dbfs, 10)) if len(dbfs) > 5 else float(dbfs.min())
    voiced = (dbfs > -45.0) & (dbfs > floor + 8.0)
    voiced_ms = int(voiced.sum() * FRAME_MS)
    overall = float(20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-12))
    clipped = float(np.mean(np.abs(pcm) >= 32700))
    reason = None
    if duration_ms < 1500:
        reason = "too_short"
    elif voiced_ms < 800:
        reason = "silence"
    elif clipped > 0.05:
        reason = "clipped"
    # Downsample the per-frame level series for storage (bounded evidence).
    step = max(1, len(dbfs) // 200)
    return CaptureQuality(duration_ms, voiced_ms, round(overall, 1), round(clipped, 4), reason is None, reason,
                          [round(float(v), 1) for v in dbfs[::step]])


# ---------------------------------------------------------------- coercion rules
RULESET_VERSION = "coercion-rules-2"
_SECRET = r"(?:otp|cvv|upi pin|atm pin|password|verification code)"
_RULES: dict[str, list[str]] = {
    "credential_request": [
        rf"\b(?:share|send|tell|read|give|provide|enter|confirm) (?:me |us )?(?:your |the )?{_SECRET}\b",
        rf"\bwhat is (?:your |the )?{_SECRET}\b",
        r"\b(?:code|otp) (?:batao|bhejo|do|heli|kodi)\b",
    ],
    "authority_impersonation": [r"\bpolice\b", r"\bcbi\b", r"\bcustoms\b", r"\brbi\b", r"income tax",
                                r"cyber ?cell", r"digital arrest", r"bank (officer|manager) (calling|speaking)"],
    "urgency": [r"\burgent(ly)?\b", r"\bimmediately\b", r"within \d+ (minutes|mins)", r"\bjaldi\b",
                r"\bturant\b", r"\babhi\b", r"\bbega\b"],
    "account_threat": [r"\bkyc\b", r"account (will be )?(blocked|suspended|frozen)", r"block ho (jayega|jaega)",
                       r"\brefund\b", r"\blottery\b", r"\bprize\b"],
    "remote_access": [r"\banydesk\b", r"\bteamviewer\b", r"screen ?share", r"\bquick ?support\b"],
}
_PROTECTIVE = [r"\b(?:never|do not|don't|dont) (?:share|send|tell|read|give|provide|enter|confirm)\b",
               r"kabhi (bhi )?share mat", r"share mat (karo|karna)"]


def coercion_rules(text: str | None) -> dict[str, Any]:
    """Deterministic lexical rules. Evidence for step-up only; never a model score."""
    if not text or not text.strip():
        return {"status": "unavailable", "hits": {}, "flagged": False, "protective": False}
    hits: dict[str, list[str]] = {}
    protective = False
    for sentence in re.split(r"[.!?\n।]+", text.lower()):
        prot = any(re.search(p, sentence) for p in _PROTECTIVE)
        protective = protective or prot
        for cat, pats in _RULES.items():
            if cat == "credential_request" and prot:
                continue
            for p in pats:
                m = re.search(p, sentence)
                if m:
                    hits.setdefault(cat, []).append(m.group(0))
    flagged = bool(hits.get("credential_request") or hits.get("remote_access") or
                   (hits.get("authority_impersonation") and (hits.get("urgency") or hits.get("account_threat"))))
    return {"status": "flagged" if flagged else "ok", "hits": hits, "flagged": flagged, "protective": protective}


# ---------------------------------------------------------------- manifest
@dataclass
class ModelEntry:
    signal: str
    kind: str
    enabled: bool
    path: str
    model_id: str
    revision: str
    license: str = ""
    task: str = ""
    languages: list[str] = field(default_factory=list)
    sample_rate: int | None = None
    positive_label: str | None = None
    threshold: float = 0.5
    clear_below: float | None = None
    window_s: float = 2.0
    enforce: bool = False
    label_mapping_verified: bool = True
    diagnostic_only: bool = False
    checksum_file: str | None = None
    sha256: str | None = None
    auxiliary_sha256: dict[str, str] = field(default_factory=dict)
    hypotheses: list[str] = field(default_factory=list)
    evaluation_report: str | None = None
    status: str = "unavailable"
    status_reason: str = "not verified"


class Manifest:
    def __init__(self, entries: dict[str, ModelEntry]):
        self.entries = entries

    @classmethod
    def load(cls, model_dir: Path) -> "Manifest":
        p = model_dir / "manifest.json"
        if not p.exists():
            return cls({})
        raw = json.loads(p.read_text())
        entries = {}
        for key, e in raw.get("models", {}).items():
            fields = {k: v for k, v in e.items() if k in ModelEntry.__dataclass_fields__ and k not in ("status", "status_reason")}
            entries[key] = ModelEntry(**fields)
        m = cls(entries)
        m.verify(model_dir)
        return m

    def verify(self, model_dir: Path) -> None:
        for e in self.entries.values():
            if not e.enabled:
                e.status, e.status_reason = "disabled", "disabled in active manifest"
                continue
            if e.clear_below is not None and not 0 <= e.clear_below < e.threshold <= 1:
                e.status, e.status_reason = "unavailable", "invalid voice score thresholds"
                continue
            if e.kind in ONNX_VOICE_FILES and e.checksum_file != ONNX_VOICE_FILES[e.kind]:
                e.status, e.status_reason = "unavailable", f"expected a pin for {ONNX_VOICE_FILES[e.kind]}"
                continue
            path = (model_dir / e.path) if not Path(e.path).is_absolute() else Path(e.path)
            if not path.exists():
                e.status, e.status_reason = "unavailable", "checkpoint not installed (run tools/fetch_models.py)"
                continue
            if e.checksum_file and e.sha256:
                f = path / e.checksum_file
                if not f.is_file():
                    e.status, e.status_reason = "unavailable", f"missing checkpoint file: {e.checksum_file}"
                    continue
                if _sha256_file(f) != e.sha256:
                    e.status, e.status_reason = "unavailable", "checksum mismatch"
                    continue
            elif not e.sha256:
                e.status, e.status_reason = "unavailable", "manifest entry is not pinned (missing sha256)"
                continue
            auxiliary_ok = all((path / name).is_file() and _sha256_file(path / name) == digest
                               for name, digest in e.auxiliary_sha256.items())
            if not auxiliary_ok:
                e.status, e.status_reason = "unavailable", "auxiliary model files failed checksum verification"
                continue
            e.status, e.status_reason = "available", "verified"

    def get(self, key: str) -> ModelEntry | None:
        return self.entries.get(key)

    def describe(self) -> list[dict]:
        out = []
        for key, e in self.entries.items():
            out.append({"key": key, "signal": e.signal, "model_id": e.model_id, "revision": e.revision,
                        "license": e.license, "languages": e.languages, "enforce": e.enforce,
                        "status": e.status, "reason": e.status_reason,
                        "threshold": None if e.diagnostic_only else e.threshold,
                        "clear_below": None if e.diagnostic_only else e.clear_below,
                        "label_mapping_verified": e.label_mapping_verified,
                        "diagnostic_only": e.diagnostic_only,
                        "evaluation_report": e.evaluation_report})
        return out


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- adapters
class Runtime:
    """Holds loaded models and bounds concurrent inference."""

    def __init__(self, manifest: Manifest, *, model_dir: Path | None = None):
        self.manifest = manifest
        self.model_dir = model_dir if model_dir is not None else settings.model_dir
        self._sem = asyncio.Semaphore(settings.inference_concurrency)
        self._load_lock = threading.Lock()
        self._loaded: dict[str, Any] = {}

    def _model_path(self, e: ModelEntry) -> str:
        return str(self.model_dir / e.path)

    def _load(self, key: str) -> Any:
        with self._load_lock:
            if key in self._loaded:
                return self._loaded[key]
            e = self.manifest.get(key)
            path = self._model_path(e)
            if e.kind == "faster_whisper":
                from faster_whisper import WhisperModel
                obj = WhisperModel(path, device="cpu", compute_type="int8", local_files_only=True)
            elif e.kind == "audio_classification":
                from transformers import AutoFeatureExtractor, AutoModelForAudioClassification
                obj = (AutoFeatureExtractor.from_pretrained(path, local_files_only=True),
                       AutoModelForAudioClassification.from_pretrained(path, local_files_only=True).eval())
            elif e.kind == "tropa_voice_mini":
                from safetensors.torch import load_file
                import torch

                model_dir = Path(path)
                spec = importlib.util.spec_from_file_location("tropa_voice_mini_detector", model_dir / "detector.py")
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                config = json.loads((model_dir / "config.json").read_text())
                head = json.loads((model_dir / "serving_head.json").read_text())
                # Memory-map the weights without first allocating a second full model.
                torch.set_num_threads(min(4, torch.get_num_threads()))
                with torch.device("meta"):
                    model = module.VoiceDetectorModel(config)
                model.load_state_dict(load_file(str(model_dir / e.checksum_file)), assign=True)
                obj = module.VoiceDetector(model, head, "cpu")
            elif e.kind in ONNX_VOICE_FILES:
                import onnxruntime as ort
                options = ort.SessionOptions()
                options.intra_op_num_threads = 2
                obj = ort.InferenceSession(str(Path(path) / ONNX_VOICE_FILES[e.kind]), sess_options=options,
                                           providers=["CPUExecutionProvider"])
            elif e.kind == "sequence_classification":
                from transformers import AutoModelForSequenceClassification, AutoTokenizer
                obj = (AutoTokenizer.from_pretrained(path, local_files_only=True),
                       AutoModelForSequenceClassification.from_pretrained(path, local_files_only=True).eval())
            elif e.kind == "zero_shot_nli":
                from transformers import pipeline
                obj = pipeline("zero-shot-classification", model=path, tokenizer=path, device=-1)
            else:
                raise RuntimeError(f"unknown adapter kind {e.kind}")
            self._loaded[key] = obj
            return obj

    def _entry(self, key: str) -> ModelEntry | None:
        e = self.manifest.get(key)
        return e if e and e.status == "available" else None

    async def _run(self, fn, *args):
        async with self._sem:
            return await asyncio.wait_for(asyncio.to_thread(fn, *args), timeout=settings.inference_timeout_s)

    @staticmethod
    def _unavailable(signal: str, e: ModelEntry | None, key: str, reason: str | None = None) -> dict:
        return {"signal": signal, "status": "unavailable", "review_only": True, "source": key,
                "model_id": e.model_id if e else None, "revision": e.revision if e else None,
                "score_scale": None, "score": None, "flagged": None, "points": [],
                "reason": reason or (e.status_reason if e else "no manifest entry")}

    # --- speech to text
    async def transcribe(self, audio: np.ndarray) -> dict:
        key = "asr"
        e = self._entry(key)
        if not e:
            return self._unavailable("transcript", self.manifest.get(key), key)
        def _go():
            model = self._load(key)
            segs, info = model.transcribe(audio.astype(np.float32) / 32768.0, beam_size=1, vad_filter=False)
            return [{"start_ms": int(s.start * 1000), "end_ms": int(s.end * 1000), "text": s.text.strip(),
                     "avg_logprob": round(s.avg_logprob, 3), "no_speech_prob": round(s.no_speech_prob, 3)}
                    for s in segs], info.language, float(info.language_probability)
        try:
            segments, lang, lang_p = await self._run(_go)
        except Exception as ex:  # noqa: BLE001
            log.warning("asr failed: %s", type(ex).__name__)
            return self._unavailable("transcript", e, key, f"inference error: {type(ex).__name__}")
        text = " ".join(s["text"] for s in segments).strip()
        return {"signal": "transcript", "status": "ok" if text else "inconclusive", "review_only": True,
                "source": key, "model_id": e.model_id, "revision": e.revision, "score_scale": None,
                "score": None, "flagged": None, "language": lang, "language_probability": round(lang_p, 3),
                "segments": segments, "text": text, "points": []}

    # --- voice authenticity
    @staticmethod
    def _voiceguard_scores(session: Any, audio: np.ndarray) -> tuple[float, list[dict]]:
        window = ONNX_VOICE_WINDOW
        if len(audio) <= window:
            starts = [0]
            audio = np.resize(audio, window)
        else:
            starts = list(range(0, len(audio) - window + 1, window // 2))
            if len(starts) > 8:
                indices = np.linspace(0, len(starts) - 1, 8).round().astype(int)
                starts = [starts[i] for i in indices]
        logits = []
        for start in starts:
            wav = audio[start:start + window].astype(np.float32) / 32768.0
            result = session.run(["spoof_logit"], {"waveform": wav[None, :]})[0]
            logits.append(float(np.asarray(result).item()))
        if not all(np.isfinite(logits)):
            raise ValueError("VoiceGuard returned a nonfinite spoof logit")
        scores = np.exp(-np.logaddexp(0, -np.asarray(logits)))
        points = [{"offset_ms": start * 1000 // SAMPLE_RATE, "window_ms": 4038, "score": round(float(score), 4)}
                  for start, score in zip(starts, scores)]
        # The publisher averages logits before converting to a score.
        return float(np.exp(-np.logaddexp(0, -np.mean(logits)))), points

    async def screen_voice(self, audio: np.ndarray) -> dict:
        provider = os.getenv("TRINETRA_VOICE_PROVIDER")
        if provider == "tropa-voice-mini":
            return await self._screen_tropa(audio)
        if provider == "local":
            return await self.spoof(audio)
        key = os.getenv("REALITY_DEFENDER_API_KEY", "").strip()
        reason = "Reality Defender is not configured"
        if key and provider == "realitydefender":
            try:
                async with self._sem:
                    return await realitydefender.detect(audio, key)
            except httpx.HTTPStatusError as exc:
                log.warning("Reality Defender voice screening returned HTTP %s", exc.response.status_code)
            except (httpx.RequestError, TimeoutError, ValueError, KeyError, TypeError, AttributeError) as exc:
                log.warning("Reality Defender voice screening failed: %s", type(exc).__name__)
            reason = "Reality Defender did not return a voice verdict"
        return self._unavailable("voice_authenticity", None, "realitydefender", reason)

    async def _screen_tropa(self, audio: np.ndarray) -> dict:
        key = "tropa_voice_mini"
        entry = self._entry(key)
        if not entry:
            return self._unavailable("voice_authenticity", self.manifest.get(key), key)
        if len(audio) < 2 * SAMPLE_RATE:
            return {**self._unavailable("voice_authenticity", entry, key, "at least two seconds of audio required"),
                    "status": "inconclusive"}

        def detect():
            return self._load(key)(audio.astype(np.float32) / 32768.0, batch_size=2)

        try:
            result = await self._run(detect)
            prediction = {"ai": "fake", "human": "real", "uncertain": "uncertain"}[result["verdict"]]
            score = result["ai_score"]
            points = [{"offset_ms": round(segment["start"] * 1000),
                       "window_ms": round((segment["end"] - segment["start"]) * 1000),
                       "score": segment["ai_score"]} for segment in result["segments"]]
            if not np.isfinite(score) or not all(np.isfinite(point["score"]) for point in points):
                raise ValueError("nonfinite tropa-voice-mini score")
        except Exception as exc:  # noqa: BLE001
            log.warning("tropa-voice-mini inference failed: %s", type(exc).__name__)
            return self._unavailable("voice_authenticity", entry, key, f"inference error: {type(exc).__name__}")
        return {
            **self._unavailable("voice_authenticity", entry, key, "Local voice prediction for analyst review"),
            "status": "inconclusive", "score": score, "score_scale": "AI voice score (0–1)",
            "prediction": prediction, "points": points,
        }

    async def spoof(self, audio: np.ndarray) -> dict:
        key = "spoof"
        e = self._entry(key)
        if not e:
            return self._unavailable("voice_authenticity", self.manifest.get(key), key)
        win = int(e.window_s * SAMPLE_RATE)
        windows = [(i, audio[i:i + win]) for i in range(0, max(1, len(audio) - win // 2), win)]
        def _go():
            if not len(audio):
                return None, []
            if e.kind == "voiceguard_onnx":
                return self._voiceguard_scores(self._load(key), audio)
            if e.kind == "aasist_l_onnx":
                # Match the published first-window evaluation and repeat short clips.
                clip = np.resize(audio, ONNX_VOICE_WINDOW).astype(np.float32) / 32768.0
                logits = self._load(key).run(["logits"], {"wav": clip[None, :]})[0][0]
                weights = np.exp(logits - logits.max())
                score = round(float(weights[0] / weights.sum()), 4)
                return score, [{"offset_ms": 0, "window_ms": 4038, "score": score}]
            import torch
            fx, model = self._load(key)
            labels = {v.lower(): int(k) for k, v in model.config.id2label.items()}
            pos = labels.get((e.positive_label or "").lower())
            if pos is None:
                raise RuntimeError("positive label not in model config")
            pts = []
            for off, w in windows:
                if len(w) < win // 2:
                    continue
                inp = fx(w.astype(np.float32) / 32768.0, sampling_rate=SAMPLE_RATE, return_tensors="pt",
                         padding="max_length", max_length=win, truncation=True)
                with torch.no_grad():
                    p = torch.softmax(model(**inp).logits, dim=-1)[0, pos].item()
                pts.append({"offset_ms": int(off * 1000 / SAMPLE_RATE), "window_ms": int(e.window_s * 1000),
                            "score": round(p, 4)})
            return max((p["score"] for p in pts), default=None), pts
        try:
            score, pts = await self._run(_go)
        except Exception as ex:  # noqa: BLE001
            return self._unavailable("voice_authenticity", e, key, f"inference error: {type(ex).__name__}")
        if score is None or not np.isfinite(score):
            return {**self._unavailable("voice_authenticity", e, key, "no valid spoof score"), "status": "inconclusive"}
        if not e.label_mapping_verified:
            return {**self._unavailable("voice_authenticity", e, key, "checkpoint class labels are unverified"),
                    "status": "inconclusive", "score": score, "points": pts,
                    "score_scale": "Raw model score, class label unverified"}
        prediction = "fake" if score >= e.threshold else "real"
        if e.diagnostic_only:
            return {**self._unavailable("voice_authenticity", e, key, "detector enabled for diagnostics only"),
                    "status": "inconclusive", "score": score, "points": pts, "prediction": prediction,
                    "score_scale": "Raw spoof score (0–1), uncalibrated"}
        if e.clear_below is not None and e.clear_below <= score < e.threshold:
            return {**self._unavailable("voice_authenticity", e, key, "score between decision thresholds"),
                    "status": "inconclusive", "score": score, "points": pts,
                    "score_scale": f"P({e.positive_label}) 0..1, uncalibrated"}
        flagged = prediction == "fake"
        return {"signal": "voice_authenticity", "status": "flagged" if flagged else "ok",
                "review_only": not e.enforce, "source": key, "model_id": e.model_id, "revision": e.revision,
                "score_scale": f"P({e.positive_label}) 0..1, uncalibrated", "score": score, "flagged": flagged,
                "threshold": e.threshold, "points": pts, "prediction": prediction}

    # --- spoken / typed coercion
    async def classify_text(self, signal: str, text: str | None, language: str | None) -> dict:
        rules = coercion_rules(text)
        base = {"signal": signal, "rules": {"version": RULESET_VERSION, **rules}}
        if not text or not text.strip():
            return {**base, **self._unavailable(signal, None, "text", "no text"), "rules": base["rules"]}
        other_script = language is None and any(
            char.isalpha() and "LATIN" not in unicodedata.name(char, "") for char in text
        )
        model_obs = None
        for key in ("text_scam", "text_nli"):
            e = self._entry(key)
            if not e:
                continue
            if language and e.languages and language not in e.languages:
                model_obs = {**self._unavailable(signal, e, key, f"language '{language}' not supported by model"),
                             "status": "unsupported_language"}
                continue
            if other_script and key == "text_scam":
                model_obs = {**self._unavailable(signal, e, key, "text contains a script outside the model's supported languages"),
                             "status": "unsupported_language"}
                continue
            try:
                model_obs = await self._run(self._text_score, key, e, text)
                break
            except Exception as ex:  # noqa: BLE001
                model_obs = self._unavailable(signal, e, key, f"inference error: {type(ex).__name__}")
        if model_obs is None:
            model_obs = self._unavailable(signal, None, "text_scam", "no text model installed")
        return {**model_obs, "signal": signal, "rules": base["rules"]}

    def _text_score(self, key: str, e: ModelEntry, text: str) -> dict:
        if e.kind == "sequence_classification":
            import torch
            tok, model = self._load(key)
            labels = {v.lower(): int(k) for k, v in model.config.id2label.items()}
            pos = labels[(e.positive_label or "").lower()]
            text = re.sub(r"https?://[^\s<>()]+",
                          lambda match: "[url] " + " ".join(re.findall(r"[\w]+", match.group().split("://", 1)[1])),
                          text[:2000], flags=re.IGNORECASE).replace("_", " ")
            inp = tok(text, truncation=True, max_length=128, return_tensors="pt")
            with torch.no_grad():
                score = torch.softmax(model(**inp).logits, dim=-1)[0, pos].item()
        else:
            clf = self._load(key)
            res = clf(text[:2000], candidate_labels=e.hypotheses, hypothesis_template="This message is {}.")
            score = float(dict(zip(res["labels"], res["scores"])).get(e.positive_label, 0.0))
        flagged = score >= e.threshold
        return {"status": "flagged" if flagged else "ok", "review_only": not e.enforce, "source": key,
                "model_id": e.model_id, "revision": e.revision, "score_scale": "P(coercion) 0..1, uncalibrated",
                "score": round(score, 4), "flagged": flagged, "threshold": e.threshold, "points": []}


_runtime: Runtime | None = None


def get_runtime() -> Runtime:
    global _runtime
    if _runtime is None:
        _runtime = Runtime(Manifest.load(settings.model_dir))
    return _runtime


def set_runtime(rt: Runtime | None) -> None:
    global _runtime
    _runtime = rt
