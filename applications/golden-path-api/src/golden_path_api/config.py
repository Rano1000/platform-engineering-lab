"""Environment-backed application configuration."""

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    name: str
    environment: str
    log_level: str
    version: str
    revision: str


def load_settings(environ: dict[str, str] | None = None) -> Settings:
    source = os.environ if environ is None else environ
    log_level = source.get("APP_LOG_LEVEL", "INFO").upper()
    if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError("APP_LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL")

    return Settings(
        name=source.get("APP_NAME", "golden-path-api"),
        environment=source.get("APP_ENVIRONMENT", "local"),
        log_level=log_level,
        version=source.get("APP_VERSION", "0.1.0"),
        revision=source.get("APP_REVISION", "unknown"),
    )
