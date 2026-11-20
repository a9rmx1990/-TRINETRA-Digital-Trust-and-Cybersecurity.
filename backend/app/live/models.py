"""Local, versioned inference artifacts for the live payment gate."""

import json
import math
import os
from functools import cached_property, lru_cache
from pathlib import Path
from threading import Lock

import numpy as np

from app.engines.audio_engine import AudioForensicsEngine
from app.engines.nlp_engine import CoerciveContextEngine

SAMPLE_RATE = 16000
FUSION_FEATURES = ("voice", "voice_present", "text", "text_present", "graph", "graph_present")


def fusion_features(voice, text, graph):
    return [value for score in (voice, text, graph) for value in
            (score / 100 if score is not None else 0.0, float(score is not None))]


class Models:
    def __init__(self):
        self.audio = AudioForensicsEngine()
        self.nlp = CoerciveContextEngine()
        self.slots = {name: Lock() for name in ("spoof", "asr", "coercion", "graph")}

    @cached_property
    def manifest(self):
        path = os.getenv("TRINETRA_MODELS")
        return json.loads(Path(path).read_text()) if path else {}

    def configured(self, name):
        return name in self.manifest

    @cached_property
    def spoof(self):
        from transformers import AutoFeatureExtractor, AutoModelForAudioClassification

        entry = self.manifest["spoof"]
        path = entry["path"]
        classifier, loading = AutoModelForAudioClassification.from_pretrained(
            path, local_files_only=True, output_loading_info=True)
        if classifier.config.model_type not in {"wavlm", "wav2vec2"} or loading["missing_keys"]:
            raise ValueError("Expected trained WavLM or wav2vec2 spoof classifier weights")
        if classifier.config.num_labels != 2 or entry["positive_index"] not in (0, 1):
            raise ValueError("Expected a binary classifier and a valid spoof class index")
        return AutoFeatureExtractor.from_pretrained(path, local_files_only=True), classifier.eval()

    @cached_property
    def asr(self):
        from faster_whisper import WhisperModel

        return WhisperModel(self.manifest["asr"]["path"], device="cpu",
                            compute_type="int8", local_files_only=True)

    @cached_property
    def coercion(self):
        from transformers import AutoModelForSequenceClassification, AutoTokenizer, pipeline

        def load(name, task):
            path = self.manifest[name]["path"]
            classifier, loading = AutoModelForSequenceClassification.from_pretrained(
                path, local_files_only=True, output_loading_info=True)
            if loading["missing_keys"] or (name == "coercion" and classifier.config.model_type != "xlm-roberta"):
                raise ValueError(f"Expected trained weights for {name}")
            return pipeline(task, model=classifier.eval(),
                            tokenizer=AutoTokenizer.from_pretrained(path, local_files_only=True))

        return (load("coercion", "text-classification"),
                load("nli", "zero-shot-classification") if self.configured("nli") else None)

    @cached_property
    def graph(self):
        import torch
        return torch.jit.load(self.manifest["graph"]["path"], map_location="cpu").eval()

    def run(self, name, fn):
        entry = self.manifest.get(name)
        if not entry:
            return {"status": "missing"}
        version = entry["version"]
        with self.slots[name]:
            try:
                result = fn()
                if "score" in result and not (0 <= result["score"] <= 100):
                    raise ValueError("Model score out of bounds")
                return {"status": "ready", "version": version, **result}
            except Exception:
                import logging
                logging.getLogger(__name__).exception("Local %s model failed", name)
                return {"status": "unavailable", "version": version}

    def spoof_score(self, pcm):
        def predict():
            import torch

            extractor, model = self.spoof
            inputs = extractor(pcm, sampling_rate=SAMPLE_RATE, return_tensors="pt")
            with torch.inference_mode():
                logits = model(**inputs).logits[0]
                if len(logits) != 2:
                    raise ValueError("Spoof classifier must have two labels")
                score = logits.softmax(0)[self.manifest["spoof"]["positive_index"]].item()
            return {"score": 100 * score}

        return self.run("spoof", predict)

    def transcript(self, pcm):
        def predict():
            segments, info = self.asr.transcribe(pcm, beam_size=1, condition_on_previous_text=False)
            if info.language not in {"en", "hi", "kn"}:
                return {"status": "unsupported", "language": info.language}
            parts = [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in segments]
            return {"language": info.language, "confidence": info.language_probability,
                    "segments": parts, "text": " ".join(s["text"] for s in parts)}

        return self.run("asr", predict)

    def text_score(self, content, language=None):
        if not content.strip():
            return {"status": "missing"}

        def predict():
            classifier, nli = self.coercion
            labels = self.manifest["coercion"]["positive_labels"]
            classified = classifier(content, top_k=None, truncation=True)
            matches = [item for item in classified if item["label"] in labels]
            if not matches:
                raise ValueError("Coercion positive labels do not match the checkpoint")
            score = max(item["score"] for item in matches)
            result = {"score": 100 * score, "labels": matches}
            config = self.manifest.get("nli", {})
            if nli and language in config.get("languages", []) and score < config.get("fallback_below", 0.5):
                alternatives = nli(content[:1200], config["labels"], multi_label=True)
                result["nli"] = {"version": config["version"],
                                 "labels": alternatives["labels"], "scores": alternatives["scores"]}
                result["score"] = max(result["score"], 100 * max(alternatives["scores"]))
            return result

        return self.run("coercion", predict)

    def graph_score(self, node_features, edges):
        def predict():
            import torch

            with torch.inference_mode():
                logits = self.graph(torch.tensor(node_features, dtype=torch.float32),
                                    torch.tensor(edges, dtype=torch.long).reshape(-1, 2).T)
            return {"score": 100 * logits.flatten()[0].sigmoid().item(),
                    "review_only": self.manifest["graph"].get("review_only", False)}

        return self.run("graph", predict)

    def fusion(self, voice, coercion, graph):
        entry = self.manifest.get("fusion")
        if not entry:
            return {"status": "missing"}
        artifact = fusion_artifact(entry["path"])
        actual = tuple(self.manifest.get(name, {}).get("version") for name in ("spoof", "coercion", "graph"))
        if tuple(artifact["model_versions"]) != actual:
            return {"status": "unavailable", "version": entry["version"]}
        z = artifact["intercept"] + sum(w * x for w, x in zip(
            artifact["weights"], fusion_features(voice, coercion, graph), strict=True))
        return {"status": "ready", "version": entry["version"],
                "score": 100 / (1 + math.exp(-max(-80, min(80, z))))}


@lru_cache(maxsize=4)
def fusion_artifact(path):
    artifact = json.loads(Path(path).read_text())
    if tuple(artifact["features"]) != FUSION_FEATURES or not all(
        math.isfinite(x) for x in [artifact["intercept"], *artifact["weights"]]
    ) or len(artifact["weights"]) != len(FUSION_FEATURES):
        raise ValueError("Invalid fusion artifact")
    return artifact


models = Models()


def acoustic_baseline(pcm):
    raw = (np.clip(pcm, -1, 0.9999) * 32768).astype("<i2").tobytes()
    score, diagnostics, _ = models.audio.analyze(raw)
    spectrum = np.abs(np.fft.rfft(pcm[:1024] * np.hanning(1024))) ** 2
    bands = np.array_split(spectrum, 32)
    peak = max(max(band) for band in bands)
    return {"score": score, "diagnostics": diagnostics.model_dump(),
            "spectrum_db": [round(10 * math.log10(max(float(np.mean(band)) / max(peak, 1e-12), 1e-8)), 1)
                            for band in bands]}
