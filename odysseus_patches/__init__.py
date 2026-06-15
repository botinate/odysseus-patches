"""odysseus-patches — apply upstream PR patches to a self-hosted Odysseus install."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("odysseus-patches")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "0.0.0+unknown"
