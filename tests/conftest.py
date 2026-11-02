import os
import pytest


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Never touch the developer's real NotebookLM login during tests."""
    home = tmp_path / "nb_home"
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(home))
    monkeypatch.delenv("NOTEBOOKLM_AUTH_JSON", raising=False)
    monkeypatch.delenv("NOTEBOOKLM_PROFILE", raising=False)
    monkeypatch.setenv("NOTEBOOKLM_LAB_OUTPUT", str(tmp_path / "outputs"))
    return home


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    """Morning digest data (inbox, state, outputs) never touches the real ~/NotebookLM-Lab."""
    monkeypatch.setenv("NOTEBOOKLM_LAB_DATA", str(tmp_path / "lab_data"))
