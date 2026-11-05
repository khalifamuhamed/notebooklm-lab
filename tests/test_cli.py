import json

from notebooklm_lab import cli, storage


def test_demo_command(tmp_path, capsys):
    out = tmp_path / "o"
    assert cli.main(["demo", "--out", str(out)]) == 0
    runs = storage.list_runs(out)
    assert len(runs) == 1 and (runs[0] / "report.html").is_file()
    assert "SAMPLE MODE" in capsys.readouterr().out


def test_digest_sample_with_links_file(tmp_path):
    links = tmp_path / "l.txt"
    links.write_text("# hi\nhttps://example.com/a\nhttps://youtu.be/xyz\n", encoding="utf-8")
    out = tmp_path / "o"
    assert cli.main(["digest", "--file", str(links), "--sample", "--out", str(out), "--outputs", "briefing,audio"]) == 0
    data = json.loads((storage.list_runs(out)[0] / "run.json").read_text(encoding="utf-8"))
    assert data["mode"] == "sample" and len(data["sources"]) == 2 and len(data["outputs"]) == 2


def test_digest_real_without_login_is_friendly_and_makes_no_folder(tmp_path, capsys):
    out = tmp_path / "o"
    assert cli.main(["digest", "https://example.com/a", "--out", str(out)]) == 3
    assert "notebooklm login" in capsys.readouterr().out
    assert not out.exists() or not list(out.iterdir())


def test_digest_bad_input(tmp_path, capsys):
    assert cli.main(["digest", "ftp://x/y", "--sample"]) == 2
    assert cli.main(["digest", "https://a.org", "--sample", "--outputs", "nope"]) == 2
    assert cli.main(["digest", "--sample"]) == 2


def test_session_and_outputs_commands(tmp_path, capsys):
    assert cli.main(["session", "where"]) == 0
    assert cli.main(["session", "delete"]) == 0
    assert cli.main(["outputs", "where"]) == 0
    assert cli.main(["outputs", "delete"]) == 0
    assert "NOTEBOOKLM" in capsys.readouterr().out.upper()


def test_agents_snippets_cover_all_three():
    from notebooklm_lab import agents

    txt = agents.render("all", python="/opt/venv/bin/python")
    for needle in ("claude mcp add notebooklm", "codex mcp add notebooklm", "[mcp_servers.notebooklm]", "mcp_servers:", "notebooklm.mcp",
                   "--transport stdio --env NOTEBOOKLM_LAB_DATA=", "notebooklm_lab -- /opt/venv/bin/python", "[mcp_servers.notebooklm_lab.env]", "ask_vault_and_notebooks", "[mcp_servers.notebooklm_lab]", "notebooklm_lab:", "notebooklm_lab.mcp_server"):
        assert needle in txt
