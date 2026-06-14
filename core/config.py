"""Environment-backed Settings for the Digital Equity Analyst.

This module loads environment variables from a `.env` file (via
`python-dotenv`) and provides a typed `Settings` dataclass instance called
`settings` that other modules can import as `from core.config import settings`.

On import the module validates that required variables are present and will
raise `EnvironmentError` naming the missing variables if any are absent.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional

from dotenv import load_dotenv


# Load .env into the process environment. This is idempotent and safe to call
# at import time for small CLI and service processes.
load_dotenv()


@dataclass
class Settings:
    """Typed settings container populated from environment variables.

    All fields are public and represent configuration used across the
    pipeline. Types are annotated and lightweight conversions are applied
    where necessary.
    """

    # External LLMs
    ANTHROPIC_API_KEY: str
    OLLAMA_HOST: str
    OLLAMA_MODEL: str

    # Infrastructure
    REDIS_URL: str
    AIDER_DATABASE_URL: str

    # Data providers
    FRED_API_KEY: str
    SEC_USER_AGENT: str

    # Git audit
    GIT_REPO_PATH: str
    GIT_AUTHOR_NAME: str
    GIT_AUTHOR_EMAIL: str

    # SMTP
    SMTP_HOST: str
    SMTP_PORT: int
    SMTP_USER: Optional[str]
    SMTP_PASSWORD: Optional[str]
    SMTP_FROM: str
    SMTP_TO: List[str]
    SLACK_WEBHOOK_URL: Optional[str]
    ALERT_MAX_RETRIES: int
    ALERT_RETRY_BASE_SECONDS: int
    RUN_ALERT_STALE_MINUTES: int

    # Report binary storage
    REPORT_S3_BUCKET: Optional[str]
    REPORT_S3_PREFIX: str
    REPORT_S3_REGION: Optional[str]
    REPORT_S3_ENDPOINT_URL: Optional[str]
    REPORT_S3_ACCESS_KEY_ID: Optional[str]
    REPORT_S3_SECRET_ACCESS_KEY: Optional[str]
    REPORT_S3_USE_SSL: bool

    # Pipeline behaviour
    DLQ_STREAM: str
    MAX_REVISION_ITERATIONS: int
    DAILY_CLAUDE_SPEND_LIMIT_USD: float
    CONFIDENCE_THRESHOLD: float

    # Environment
    ENV: str


def _get_env(name: str, default: Optional[str] = None) -> Optional[str]:
    """Return environment variable `name` or `default`.

    This wrapper centralizes value access and simplifies tests.
    """

    return os.getenv(name, default)


def _parse_int(value: Optional[str], default: int = 0) -> int:
    """Parse `value` as int, returning `default` if parsing fails or value is None."""

    try:
        return int(value) if value is not None else default
    except (ValueError, TypeError):
        return default


def _parse_float(value: Optional[str], default: float = 0.0) -> float:
    """Parse `value` as float, returning `default` if parsing fails or value is None."""

    try:
        return float(value) if value is not None else default
    except (ValueError, TypeError):
        return default


def _parse_bool(value: Optional[str], default: bool = False) -> bool:
    """Parse common truthy strings into a boolean."""

    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _parse_csv(value: Optional[str]) -> List[str]:
    """Parse a comma-separated string into a list of trimmed strings.

    Returns an empty list for `None` or empty input.
    """

    if not value:
        return []
    return [p.strip() for p in value.split(",") if p.strip()]


# Required variables that must be present in the environment
_REQUIRED_VARS = [
    "ANTHROPIC_API_KEY",
    "AIDER_DATABASE_URL",
    "REDIS_URL",
    "FRED_API_KEY",
    "SEC_USER_AGENT",
]


def _validate_required() -> None:
    """Validate required environment variables are present.

    Raises:
        EnvironmentError: if any required variable is missing or empty.
    """

    missing: List[str] = []
    for name in _REQUIRED_VARS:
        val = _get_env(name)
        if val is None or val == "":
            missing.append(name)
    if missing:
        raise EnvironmentError(f"Missing required environment variables: {', '.join(missing)}")


# Perform validation on import
_validate_required()


# Build the `settings` instance
settings = Settings(
    ANTHROPIC_API_KEY=_get_env("ANTHROPIC_API_KEY", ""),
    OLLAMA_HOST=_get_env("OLLAMA_HOST", "http://localhost:11434"),
    OLLAMA_MODEL=_get_env("OLLAMA_MODEL", "gemma4:e4b"),
    REDIS_URL=_get_env("REDIS_URL", "redis://localhost:6379"),
    AIDER_DATABASE_URL=_get_env("AIDER_DATABASE_URL", ""),
    FRED_API_KEY=_get_env("FRED_API_KEY", ""),
    SEC_USER_AGENT=_get_env("SEC_USER_AGENT", ""),
    GIT_REPO_PATH=_get_env("GIT_REPO_PATH", "./reports_audit"),
    GIT_AUTHOR_NAME=_get_env("GIT_AUTHOR_NAME", "Digital Analyst"),
    GIT_AUTHOR_EMAIL=_get_env("GIT_AUTHOR_EMAIL", "analyst@localhost"),
    SMTP_HOST=_get_env("SMTP_HOST", "mailhog"),
    SMTP_PORT=_parse_int(_get_env("SMTP_PORT", "1025"), 1025),
    SMTP_USER=_get_env("SMTP_USER", None),
    SMTP_PASSWORD=_get_env("SMTP_PASSWORD", None),
    SMTP_FROM=_get_env("SMTP_FROM", "analyst@localhost"),
    SMTP_TO=_parse_csv(_get_env("SMTP_TO", "")),
    SLACK_WEBHOOK_URL=_get_env("SLACK_WEBHOOK_URL", None),
    ALERT_MAX_RETRIES=_parse_int(_get_env("ALERT_MAX_RETRIES", "3"), 3),
    ALERT_RETRY_BASE_SECONDS=_parse_int(_get_env("ALERT_RETRY_BASE_SECONDS", "5"), 5),
    RUN_ALERT_STALE_MINUTES=_parse_int(_get_env("RUN_ALERT_STALE_MINUTES", "60"), 60),
    REPORT_S3_BUCKET=_get_env("REPORT_S3_BUCKET", None),
    REPORT_S3_PREFIX=_get_env("REPORT_S3_PREFIX", "reports"),
    REPORT_S3_REGION=_get_env("REPORT_S3_REGION", None),
    REPORT_S3_ENDPOINT_URL=_get_env("REPORT_S3_ENDPOINT_URL", None),
    REPORT_S3_ACCESS_KEY_ID=_get_env("REPORT_S3_ACCESS_KEY_ID", None),
    REPORT_S3_SECRET_ACCESS_KEY=_get_env("REPORT_S3_SECRET_ACCESS_KEY", None),
    REPORT_S3_USE_SSL=_parse_bool(_get_env("REPORT_S3_USE_SSL", None), True),
    DLQ_STREAM=_get_env("DLQ_STREAM", "dlq:failed"),
    MAX_REVISION_ITERATIONS=_parse_int(_get_env("MAX_REVISION_ITERATIONS", "3"), 3),
    DAILY_CLAUDE_SPEND_LIMIT_USD=_parse_float(_get_env("DAILY_CLAUDE_SPEND_LIMIT_USD", "10.00"), 10.0),
    CONFIDENCE_THRESHOLD=_parse_float(_get_env("CONFIDENCE_THRESHOLD", "0.75"), 0.75),
    ENV=_get_env("ENV", "development"),
)
