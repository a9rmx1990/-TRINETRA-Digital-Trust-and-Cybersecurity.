"""Download published checkpoints into backend/models and pin them in the manifest.

    pip install -r requirements-models.txt
    python tools/fetch_models.py            # all enabled entries
    python tools/fetch_models.py asr spoof  # selected entries

For each entry the resolved commit hash replaces `revision` and the sha256 of the
checksum file is written. After this, inference runs offline from local storage
(set HF_HUB_OFFLINE=1 to verify). Review each model card's license before use.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

MODELS = Path(__file__).resolve().parent.parent / "models"


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def main(keys: list[str]) -> None:
    from huggingface_hub import HfApi, snapshot_download
    mf = MODELS / "manifest.json"
    data = json.loads(mf.read_text())
    api = HfApi()
    for key, e in data["models"].items():
        if keys and key not in keys:
            continue
        if not e.get("enabled") or e.get("kind") == "graph":
            print(f"skip {key} (disabled)")
            continue
        info = api.model_info(e["model_id"], revision=e.get("revision") or "main")
        target = MODELS / e["path"]
        allow_patterns = None
        if e["kind"] == "aasist_l_onnx":
            allow_patterns = [e["checksum_file"], "LICENSE"]
        auxiliary = e.get("auxiliary_sha256", {})
        if auxiliary:
            allow_patterns = [e["checksum_file"], *auxiliary]
        snapshot_download(e["model_id"], revision=info.sha, local_dir=target, allow_patterns=allow_patterns)
        f = target / e["checksum_file"]
        if not f.exists():
            raise SystemExit(f"{key}: expected {f.name} in snapshot; update checksum_file in manifest")
        e["revision"] = info.sha
        digest = sha256_file(f)
        if (e["kind"] == "aasist_l_onnx" or auxiliary) and e.get("sha256") != digest:
            raise SystemExit(f"{key}: checkpoint SHA-256 differs from the release pin")
        for filename, expected in auxiliary.items():
            if sha256_file(target / filename) != expected:
                raise SystemExit(f"{key}: {filename} SHA-256 differs from the release pin")
        e["sha256"] = digest
        print(f"pinned {key}: {e['model_id']}@{info.sha[:12]} sha256={e['sha256'][:12]}")
    mf.write_text(json.dumps(data, indent=2) + "\n")


if __name__ == "__main__":
    main(sys.argv[1:])
