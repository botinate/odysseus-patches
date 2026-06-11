import json

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
    assert "sk-secret-abcdef" not in str(red)
    assert red["api_token"].endswith("cdef")
    assert red["odysseus_url"] == cfg.odysseus_url


def test_redacted_dict_empty_token(tmp_path):
    cfg = Config.load(tmp_path / "config.json")
    assert cfg.redacted_dict()["api_token"] == "(not set)"


def test_corrupt_file_raises(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{nope", encoding="utf-8")
    with pytest.raises(ConfigError):
        Config.load(path)
