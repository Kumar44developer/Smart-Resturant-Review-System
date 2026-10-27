"""Application configuration loaded from environment / .env (stdlib only).

A dependency-free .env loader is used on purpose: pydantic-settings pulls in
python-dotenv and this build keeps the runtime to pure-Python modules that are
verified to import under the local security policy.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        values[key.strip()] = val.strip().strip('"').strip("'")
    return values


_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
_DOTENV = _load_dotenv(_ENV_FILE)


def _get(key: str, default: str = "") -> str:
    # Real environment wins over .env so deployments/CI can override.
    return os.environ.get(key, _DOTENV.get(key, default))


@dataclass(frozen=True)
class Settings:
    app_env: str = field(default_factory=lambda: _get("APP_ENV", "dev"))
    secret_key: str = field(default_factory=lambda: _get("SECRET_KEY", "dev-insecure-secret-change-me"))
    database_path: str = field(default_factory=lambda: _get("DATABASE_PATH", "./data/app.db"))
    jwt_expiry_minutes: int = field(default_factory=lambda: int(_get("JWT_EXPIRY_MINUTES", "720")))

    cors_origins: list[str] = field(default_factory=lambda: [o for o in _get("CORS_ORIGINS", "http://localhost:8000").split(",") if o])

    ai_provider: str = field(default_factory=lambda: _get("AI_PROVIDER", "demo"))
    ai_base_url: str = field(default_factory=lambda: _get("AI_BASE_URL", "https://api.groq.com/openai/v1"))
    ai_api_key: str = field(default_factory=lambda: _get("AI_API_KEY", ""))
    ai_chat_model: str = field(default_factory=lambda: _get("AI_CHAT_MODEL", "llama-3.3-70b-versatile"))
    ai_embedding_model: str = field(default_factory=lambda: _get("AI_EMBEDDING_MODEL", ""))
    ai_timeout_seconds: int = field(default_factory=lambda: int(_get("AI_TIMEOUT_SECONDS", "30")))

    max_upload_mb: int = field(default_factory=lambda: int(_get("MAX_UPLOAD_MB", "5")))
    rate_limit_per_min: int = field(default_factory=lambda: int(_get("RATE_LIMIT_PER_MIN", "120")))
    max_request_bytes: int = field(default_factory=lambda: int(_get("MAX_REQUEST_BYTES", "1048576")))

    smtp_host: str = field(default_factory=lambda: _get("SMTP_HOST", ""))
    smtp_port: int = field(default_factory=lambda: int(_get("SMTP_PORT", "587")))
    smtp_user: str = field(default_factory=lambda: _get("SMTP_USER", ""))
    smtp_password: str = field(default_factory=lambda: _get("SMTP_PASSWORD", ""))
    smtp_from: str = field(default_factory=lambda: _get("SMTP_FROM", ""))

    @property
    def demo_mode(self) -> bool:
        """True when no real LLM credentials are configured."""
        return self.ai_provider != "openai_compat" or not self.ai_api_key

    @property
    def is_prod(self) -> bool:
        return self.app_env.lower() == "prod"


settings = Settings()
