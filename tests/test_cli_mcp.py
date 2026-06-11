from odysseus_patches import cli
from odysseus_patches import mcp_server


def test_mcp_subcommand_calls_serve_with_checkout(checkout, monkeypatch):
    seen = {}
    monkeypatch.setattr(mcp_server, "serve", lambda co: seen.setdefault("checkout", co) or 0)
    code = cli.main(["-C", str(checkout), "mcp"])
    assert code == 0
    assert seen["checkout"] == str(checkout)


def test_mcp_server_serve_handles_missing_mcp(monkeypatch, capsys):
    # if the 'mcp' package isn't importable, serve() must return 1 with a hint
    import builtins
    real_import = builtins.__import__
    def fake_import(name, *a, **k):
        if name == "mcp" or name.startswith("mcp."):
            raise ImportError("no mcp")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert mcp_server.serve("/tmp") == 1
    assert "mcp" in capsys.readouterr().err.lower()
