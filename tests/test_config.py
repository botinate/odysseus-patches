import json
import os

import pytest

from odysseus_patches.config import Config, ConfigError

def test_missing_file_loads_defaults(tmp_path):
    cfg = Config.load(tmp_path / "config.json")
    assert cfg.odysseus_url == "http://127.0.0.1:8000"
    assert cfg.api_token == ""


def test_round_trip(tmp_path):
    path = tmp_path / "config.json"
    cfg = Config.load(path)
    cfg.set_value("api_token", "sk-test-123")
    cfg.set_value("odysseus_url", "http://127.0.0.1:9999")
    cfg.save()
    again = Config.load(path)
    assert again.api_token == "sk-test-123"
    assert again.odysseus_url == "http://127.0.0.1:9999"


def test_unknown_key_raises(tmp_path):
    cfg = Config.load(tmp_path / "config.json")
    with pytest.raises(ConfigError):
        cfg.set_value("nonsense", "x")


def test_redacted_dict_hides_token(tmp_path):
    cfg = Config.load(tmp_path / "config.json")
    cfg.set_value("api_token", "sk-secret-abcdef")
    red = cfg.redacted_dict()
    # No part of the token (not even the last 4 chars) may appear in output.
    assert "sk-secret-abcdef" not in str(red)
    assert "cdef" not in str(red)
    assert red["api_token"] == "(set)"
    assert red["odysseus_url"] == cfg.odysseus_url


def test_redacted_dict_empty_token(tmp_path):
    cfg = Config.load(tmp_path / "config.json")
    assert cfg.redacted_dict()["api_token"] == "(not set)"


def test_corrupt_file_raises(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{nope", encoding="utf-8")
    with pytest.raises(ConfigError):
        Config.load(path)


def test_rejects_non_http_url_on_load(tmp_path):
    # the api_token is sent as a Bearer to odysseus_url — refuse scheme smuggling
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"odysseus_url": "file:///etc/passwd", "api_token": "x"}), encoding="utf-8")
    with pytest.raises(ConfigError):
        Config.load(path)


def test_rejects_bad_url_on_set(tmp_path):
    cfg = Config.load(tmp_path / "config.json")
    with pytest.raises(ConfigError):
        cfg.set_value("odysseus_url", "javascript:alert(1)")


def test_accepts_lan_https_url(tmp_path):
    # host is intentionally not pinned to loopback — real remote installs work
    cfg = Config.load(tmp_path / "config.json")
    cfg.set_value("odysseus_url", "https://odysseus.lan:8443")
    cfg.save()
    assert Config.load(tmp_path / "config.json").odysseus_url == "https://odysseus.lan:8443"


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes")
def test_saved_config_is_owner_only(tmp_path):
    # the file holds an API token — no group/other bits
    path = tmp_path / "patches" / "config.json"
    cfg = Config.load(path)
    cfg.set_value("api_token", "sk-secret-token")
    cfg.save()
    assert path.stat().st_mode & 0o777 == 0o600, oct(path.stat().st_mode)
