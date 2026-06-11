import json
import sqlite3
import sys

from odysseus_patches.installer import (
    MCP_SERVER_ID,
    register_mcp,
    unregister_mcp,
)


def _fake_app_db(tmp_path):
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    db = tmp_path / "data" / "app.db"
    con = sqlite3.connect(str(db))
    con.execute(
        """CREATE TABLE mcp_servers (id VARCHAR PRIMARY KEY, name VARCHAR NOT NULL,
           transport VARCHAR NOT NULL, command VARCHAR, args TEXT, env TEXT, url VARCHAR,
           is_enabled BOOLEAN, oauth_config TEXT, disabled_tools TEXT, oauth_tokens TEXT,
           created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"""
    )
    con.commit(); con.close()
    return tmp_path


def _row(tmp_path):
    con = sqlite3.connect(str(tmp_path / "data" / "app.db"))
    try:
        cur = con.execute("SELECT id,name,transport,command,args,is_enabled FROM mcp_servers WHERE id=?", (MCP_SERVER_ID,))
        return cur.fetchone()
    finally:
        con.close()


def test_register_inserts_row(tmp_path):
    root = _fake_app_db(tmp_path)
    assert register_mcp(root) is True
    r = _row(tmp_path)
    assert r is not None
    assert r[0] == MCP_SERVER_ID and r[2] == "stdio"
    assert r[3] == sys.executable
    args = json.loads(r[4])
    assert args == ["-m", "odysseus_patches.cli", "-C", str(root), "mcp"]
    assert r[5] == 1


def test_register_is_idempotent(tmp_path):
    root = _fake_app_db(tmp_path)
    register_mcp(root)
    register_mcp(root)
    con = sqlite3.connect(str(tmp_path / "data" / "app.db"))
    n = con.execute("SELECT COUNT(*) FROM mcp_servers WHERE id=?", (MCP_SERVER_ID,)).fetchone()[0]
    con.close()
    assert n == 1


def test_register_preserves_disabled_choice(tmp_path):
    root = _fake_app_db(tmp_path)
    register_mcp(root)
    con = sqlite3.connect(str(tmp_path / "data" / "app.db"))
    con.execute("UPDATE mcp_servers SET is_enabled=0 WHERE id=?", (MCP_SERVER_ID,)); con.commit(); con.close()
    register_mcp(root)  # re-register
    assert _row(tmp_path)[5] == 0  # still disabled — user's choice respected


def test_unregister_removes_row(tmp_path):
    root = _fake_app_db(tmp_path)
    register_mcp(root)
    assert unregister_mcp(root) is True
    assert _row(tmp_path) is None


def test_register_noop_without_db(tmp_path):
    (tmp_path / "data").mkdir()
    assert register_mcp(tmp_path) is False  # no app.db
