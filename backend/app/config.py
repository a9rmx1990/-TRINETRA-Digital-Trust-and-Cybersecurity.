"""Runtime configuration from environment variables. No secrets have defaults."""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _secret() -> str:
    """Env first; else a secret generated once and shared by every process via the data dir."""
    if os.environ.get("TRINETRA_SERVER_SECRET"):
        return os.environ["TRINETRA_SERVER_SECRET"]
    d = Path(os.environ.get("TRINETRA_DATA_DIR", BACKEND_DIR / "data"))
    d.mkdir(parents=True, exist_ok=True)
    f = d / "server-secret"
    try:
        fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(secrets.token_hex(32))
    except FileExistsError:
        pass
    return f.read_text().strip()


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


@dataclass
class Settings:
    database_url: str = field(default_factory=lambda: os.environ.get(
        "TRINETRA_DATABASE_URL", f"sqlite:///{BACKEND_DIR / 'data' / 'trinetra.db'}"))
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("TRINETRA_DATA_DIR", BACKEND_DIR / "data")))
    model_dir: Path = field(default_factory=lambda: Path(os.environ.get("TRINETRA_MODEL_DIR", BACKEND_DIR / "models")))
    redis_url: str | None = field(default_factory=lambda: os.environ.get("TRINETRA_REDIS_URL") or None)
    # Separate Redis config for the optional audio cache; unused unless set.
    audio_cache_url: str | None = field(default_factory=lambda: os.environ.get("TRINETRA_AUDIO_CACHE_URL") or None)
    audio_cache_ttl_s: int = field(default_factory=lambda: _int("TRINETRA_AUDIO_CACHE_TTL_S", 300))

    analyst_passcode: str | None = field(default_factory=lambda: os.environ.get("TRINETRA_ANALYST_PASSCODE") or None)
    server_secret: str = field(default_factory=_secret)
    analyst_scope: str = field(default_factory=lambda: os.environ.get("TRINETRA_ANALYST_SCOPE", "sandbox"))

    in_process_workers: int = field(default_factory=lambda: _int("TRINETRA_WORKERS", 2))
    soc_tier: int = field(default_factory=lambda: _int("TRINETRA_SOC_TIER", 0))
    soc_kill_switch: bool = field(default_factory=lambda: os.environ.get("TRINETRA_SOC_KILL_SWITCH", "0") == "1")
    soc_action_rate_per_min: int = field(default_factory=lambda: _int("TRINETRA_SOC_ACTION_RATE", 30))

    call_ttl_ms: int = field(default_factory=lambda: _int("TRINETRA_CALL_TTL_MS", 10 * 60_000))
    capture_fresh_ms: int = field(default_factory=lambda: _int("TRINETRA_CAPTURE_FRESH_MS", 10 * 60_000))
    max_audio_seconds: int = field(default_factory=lambda: _int("TRINETRA_MAX_AUDIO_S", 60))
    inference_concurrency: int = field(default_factory=lambda: _int("TRINETRA_INFERENCE_CONCURRENCY", 2))
    inference_timeout_s: float = field(default_factory=lambda: float(os.environ.get("TRINETRA_INFERENCE_TIMEOUT_S", "20")))
    lease_ms: int = field(default_factory=lambda: _int("TRINETRA_LEASE_MS", 30_000))
    watch_days: int = 30
    serve_frontend: Path | None = field(default_factory=lambda: (
        Path(os.environ["TRINETRA_FRONTEND_DIST"]) if os.environ.get("TRINETRA_FRONTEND_DIST") else None))


settings = Settings()
