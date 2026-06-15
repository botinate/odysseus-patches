"""Tool configuration: how to reach the user's running Odysseus instance.

Lives at <checkout>/data/patches/config.json, next to the manifest. The API
token is an Odysseus API token with the `chat` scope (Settings -> tokens);
it lets the review engine use the user's default model + endpoint fallbacks
without duplicating any model configuration here.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from ._fsutil import atomic_write_text

DEFAULT_URL = "http://127.0.0.1:8000"
KNOWN_KEYS = ("odysseus_url", "api_token")


class ConfigError(Exception):
    pass


def _validate_url(url: str) -> str:
    """The api_token is sent as a Bearer to this URL, so refuse anything that
    isn't a normal http(s) endpoint — blocks scheme smuggling (file://, data:,
    ...) and malformed values from a tampered config. Host is intentionally not
    pinned to loopback so real LAN/remote Odysseus installs keep working."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ConfigError(f"invalid odysseus_url {url!r} (must be http(s)://host[:port])")
    return url


@dataclass
class Config:
    path: Path
    odysseus_url: str = DEFAULT_URL
    api_token: str = ""

    @classmethod
    def load(cls, path: Path) -> "Config":
        path = Path(path)
        if not path.exists():
            return cls(path=path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            odysseus_url = str(data.get("odysseus_url", DEFAULT_URL))
            api_token = str(data.get("api_token", ""))
        except (ValueError, TypeError) as exc:
            raise ConfigError(f"Unreadable config at {path}: {exc}") from exc
        _validate_url(odysseus_url)
        return cls(path=path, odysseus_url=odysseus_url, api_token=api_token)

    def save(self) -> None:
        # The file holds an API token: write it owner-only (0600) with no window
        # where it is world-readable and no predictable temp name to race. We set
        # the file mode, not the directory's, so Docker bind-mounts where Odysseus
        # runs as another uid still work.
        payload = {"odysseus_url": self.odysseus_url, "api_token": self.api_token}
        atomic_write_text(self.path, json.dumps(payload, indent=2) + "\n")

    def set_value(self, key: str, value: str) -> None:
        if key not in KNOWN_KEYS:
            raise ConfigError(f"unknown config key {key!r} — known: {', '.join(KNOWN_KEYS)}")
        if key == "odysseus_url":
            _validate_url(value)
        setattr(self, key, value)

    def redacted_dict(self) -> dict:
        # Never echo any part of the token. Even the last few characters are
        # sensitive material and would leak into `config show` output and logs,
        # so we only report whether a token is configured.
        token = "(set)" if self.api_token else "(not set)"
        return {"odysseus_url": self.odysseus_url, "api_token": token}
