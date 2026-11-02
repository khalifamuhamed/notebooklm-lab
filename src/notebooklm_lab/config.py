"""Where things live. Nothing here is secret; paths are computed at run time."""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_LANGUAGE = "ar_001"  # NotebookLM's code for Arabic (see `notebooklm language list`)
ENV_OUTPUT_DIR = "NOTEBOOKLM_LAB_OUTPUT"

#: Output kinds this lab can produce, in the order they are generated.
OUTPUT_KINDS = ("briefing", "study_guide", "mind_map", "audio", "quiz", "flashcards", "slide_deck")
DEFAULT_OUTPUTS = ("briefing", "study_guide", "mind_map", "audio")


def repo_root() -> Path:
    """Folder that holds pyproject.toml when running from a source checkout."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return Path.cwd()


def output_root() -> Path:
    """Folder where every run is saved. Override with NOTEBOOKLM_LAB_OUTPUT."""
    env = os.environ.get(ENV_OUTPUT_DIR)
    if env:
        return Path(env).expanduser().resolve()
    return (Path.cwd() / "outputs").resolve()
