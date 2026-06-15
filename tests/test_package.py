from importlib.metadata import version

from odysseus_patches import __version__


def test_version_matches_installed_metadata():
    # __version__ is derived from the installed package metadata, so it should
    # track the real release version rather than a hardcoded literal.
    assert __version__ == version("odysseus-patches")
    assert __version__ != "0.0.0+unknown"  # metadata was actually found
