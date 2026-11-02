from pathlib import Path

import pytest

from notebooklm_lab import storage


def make_session(home: Path):
    d = home / "profiles" / "default"
    (d / "browser_profile").mkdir(parents=True)
    (d / "browser_profile" / "junk").write_bytes(b"x" * 2048)
    (d / "storage_state.json").write_text("SECRET-CONTENT-MUST-NOT-BE-PRINTED", encoding="utf-8")
    return d


def test_no_session(isolated_home):
    assert not storage.has_session()
    assert "غير مسجّل" in storage.session_report()


def test_report_never_prints_contents(isolated_home):
    make_session(isolated_home)
    assert storage.has_session()
    rep = storage.session_report()
    assert "SECRET-CONTENT" not in rep and "storage_state.json" in rep


def test_delete_needs_yes_then_deletes(isolated_home):
    d = make_session(isolated_home)
    assert "--yes" in storage.delete_session(yes=False)
    assert (d / "storage_state.json").exists()
    storage.delete_session(yes=True)
    assert not (d / "storage_state.json").exists() and not (d / "browser_profile").exists()
    assert not storage.has_session()


def test_human_size():
    assert storage.human_size(10) == "10 B" and storage.human_size(2048) == "2.0 KB"


def test_outputs_list_and_delete(tmp_path):
    root = tmp_path / "o"
    for n in ("a", "b"):
        (root / n).mkdir(parents=True)
        (root / n / "run.json").write_text("{}", encoding="utf-8")
        (root / n / "f.bin").write_bytes(b"1" * 1000)
    (root / "not-a-run").mkdir()  # no run.json -> must be left alone
    assert [r.name for r in storage.list_runs(root)] == ["a", "b"]
    assert "--yes" in storage.delete_outputs(root, all_runs=True)
    assert (root / "a").exists()
    storage.delete_outputs(root, run="a", yes=True)
    assert not (root / "a").exists() and (root / "b").exists()
    storage.delete_outputs(root, all_runs=True, yes=True)
    assert (root / "not-a-run").exists() and not (root / "b").exists()
