import re
import subprocess
from importlib import metadata

import pytest

from notebooklm_lab import PINNED_NOTEBOOKLM_PY, selfcheck
from notebooklm_lab.config import repo_root

ROOT = repo_root()


def test_pin_is_declared_everywhere():
    assert selfcheck.check_pins_declared(ROOT)[1]
    assert (ROOT / "requirements.txt").read_text(encoding="utf-8").count(f"notebooklm-py[browser,mcp]=={PINNED_NOTEBOOKLM_PY}") == 1


def test_installed_version_matches_pin():
    assert metadata.version("notebooklm-py") == PINNED_NOTEBOOKLM_PY


def test_gitignore_covers_required_paths():
    if not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    assert selfcheck.check_gitignore(ROOT)[1], selfcheck.check_gitignore(ROOT)[2]


def test_no_vendored_upstream_code():
    # We depend on notebooklm-py; nothing from it may be copied into this repo.
    for p in (ROOT / "src").rglob("*.py"):
        assert not re.search(r"^from notebooklm\.(_|rpc)", p.read_text(encoding="utf-8"), re.M), p
    assert not (ROOT / "src" / "notebooklm").exists()


def test_readme_credits_and_disclaimers():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for needle in ("https://github.com/teng-lin/notebooklm-py", "Teng Lin", "MIT", "unofficial", "not affiliated with Google", "غير رسمي"):
        assert needle.lower() in text.lower(), needle


def test_git_identity_if_commits_exist():
    if not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    r = subprocess.run(["git", "-C", str(ROOT), "log", "--format=%an <%ae>"], capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        pytest.skip("no commits yet")
    assert set(r.stdout.strip().splitlines()) == {"muhamed khalifa <217306854+khalifamuhamed@users.noreply.github.com>"}
