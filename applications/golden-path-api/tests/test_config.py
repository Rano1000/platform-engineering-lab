import pytest

from golden_path_api.config import load_settings


def test_defaults_are_safe() -> None:
    settings = load_settings({})
    assert settings.name == "golden-path-api"
    assert settings.environment == "local"
    assert settings.log_level == "INFO"


def test_invalid_log_level_is_rejected() -> None:
    with pytest.raises(ValueError, match="APP_LOG_LEVEL"):
        load_settings({"APP_LOG_LEVEL": "verbose"})
