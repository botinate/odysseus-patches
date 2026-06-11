import json

from odysseus_patches import cli


def test_status_outputs_json(checkout, capsys):
    code = cli.main(["-C", str(checkout), "status"])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["patch_count"] == 0
    assert data["healthy"] is True
