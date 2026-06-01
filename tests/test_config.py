"""Tests for settings + logging config."""

from __future__ import annotations

import pytest
from src.quant_marketdata_engine.config.errors import CookieConfigError
from src.quant_marketdata_engine.config.settings import Settings, get_settings
from src.quant_marketdata_engine.logging_config import configure_logging


def _settings(**kw: object) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[call-arg, arg-type]


def test_defaults_are_public_and_cookieless() -> None:
    s = _settings()
    assert s.public_mode is True
    assert s.has_cookie is False
    assert s.host_port == 8300


def test_tvkit_cookies_valid() -> None:
    s = _settings(tvkit_auth_token='{"sessionid": "abc", "device_t": "d"}')
    assert s.has_cookie is True
    cookies = s.tvkit_cookies()
    assert cookies == {"sessionid": "abc", "device_t": "d"}


def test_tvkit_cookies_missing_raises() -> None:
    with pytest.raises(CookieConfigError, match="not set"):
        _settings().tvkit_cookies()


def test_tvkit_cookies_bad_json_raises_without_value() -> None:
    s = _settings(tvkit_auth_token="not json")
    with pytest.raises(CookieConfigError) as exc:
        s.tvkit_cookies()
    assert "not valid JSON" in str(exc.value)
    assert "not json" not in str(exc.value)  # value never leaked


def test_tvkit_cookies_not_object_raises() -> None:
    s = _settings(tvkit_auth_token='["a", "b"]')
    with pytest.raises(CookieConfigError, match="must be a JSON object"):
        s.tvkit_cookies()


def test_tvkit_cookies_missing_sessionid_raises() -> None:
    s = _settings(tvkit_auth_token='{"device_t": "d"}')
    with pytest.raises(CookieConfigError, match="sessionid"):
        s.tvkit_cookies()


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()


def test_configure_logging_idempotent() -> None:
    import src.quant_marketdata_engine.logging_config as lc

    lc._CONFIGURED = False
    configure_logging("DEBUG")
    assert lc._CONFIGURED is True
    configure_logging("INFO")  # second call hits the early-return branch
    assert lc._CONFIGURED is True
