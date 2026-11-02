from pathlib import Path

from notebooklm_lab import secrets_scan
from notebooklm_lab.config import repo_root

# fake secrets are assembled at run time so this test file stays clean
FAKE_GH = "gh" + "p_" + "A" * 36
FAKE_PK = "-----BEGIN " + "RSA PRIVATE KEY-----"
FAKE_COOKIE = "__Secure-1PSID" + "=" + "g.a000" + "x" * 30
FAKE_PATH = "/home/" + "box/project"


def rules(tmp_path):
    return {f.rule for f in secrets_scan.scan(tmp_path)}


def test_clean_dir(tmp_path):
    (tmp_path / "a.py").write_text("print('hi')\npassword = os.environ['X']\n", encoding="utf-8")
    assert secrets_scan.scan(tmp_path) == []


def test_detects_each_kind(tmp_path):
    (tmp_path / "a.txt").write_text(f"{FAKE_GH}\n{FAKE_PK}\n{FAKE_COOKIE}\nlog at {FAKE_PATH}\n", encoding="utf-8")
    assert {"github-token", "private-key-block", "google-auth-cookie", "developer-machine-path"} <= rules(tmp_path)


def test_detects_playwright_storage_state_shape(tmp_path):
    state = '{"coo' + 'kies": [{"name": "a", "domain": ".goo' + 'gle.com", "value": "v"}]}'
    (tmp_path / "x.json").write_text(state, encoding="utf-8")
    assert "playwright-storage-state" in rules(tmp_path)


def test_forbidden_file_names(tmp_path):
    for n in ("storage_state.json", ".env", "x.pem", "x.key", "my_cookies.txt", "master_token.json"):
        (tmp_path / n).write_text("x", encoding="utf-8")
    (tmp_path / ".env.example").write_text("KEY=\n", encoding="utf-8")
    flagged = {f.path for f in secrets_scan.scan(tmp_path) if f.rule == "forbidden-file-name"}
    assert flagged == {"storage_state.json", ".env", "x.pem", "x.key", "my_cookies.txt", "master_token.json"}


def test_output_is_redacted(tmp_path):
    (tmp_path / "a.txt").write_text(FAKE_GH, encoding="utf-8")
    shown = str(secrets_scan.scan(tmp_path)[0])
    assert FAKE_GH not in shown and "redacted" in shown


def test_placeholders_are_not_flagged(tmp_path):
    (tmp_path / "a.md").write_text('api_key = "YOUR_API_KEY_HERE_123456"\n', encoding="utf-8")
    assert secrets_scan.scan(tmp_path) == []


def test_this_repo_is_clean():
    assert secrets_scan.scan(repo_root()) == []
