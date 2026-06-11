"""Tool configuration: how to reach the user's running Odysseus instance.

Lives at <checkout>/data/patches/config.json, next to the manifest. The API
token is an Odysseus API token with the `chat` scope (Settings -> tokens);
it lets the review engine use the user's default model + endpoint fallbacks
without duplicating any model configuration here.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_URL = "http://127.0.0.1:8000"
KNOWN_KEYS = ("odysseus_url", "api_token")


class ConfigError(Exception):
    pass


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
            return cls(
                path=path,
                odysseus_url=str(data.get("odysseus_url", DEFAULT_URL)),
                api_token=str(data.get("api_token", "")),
            )
        except (ValueError, TypeError) as exc:
            raise ConfigError(f"Unreadable config at {path}: {exc}") from exc

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"odysseus_url": self.odysseus_url, "api_token": self.api_token}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)

    def set_value(self, key: str, value: str) -> None:
        if key not in KNOWN_KEYS:
            raise ConfigError(f"unknown config key {key!r} — known: {', '.join(KNOWN_KEYS)}")
        setattr(self, key, value)

    def redacted_dict(self) -> dict:
        token = "(not set)"
        if self.api_token:
            token = "****" + self.api_token[-4:]
        return {"odysseus_url": self.odysseus_url, "api_token": token}
