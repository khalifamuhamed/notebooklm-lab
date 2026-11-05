"""The small interface the pipeline needs. Two implementations exist:
`RealBackend` (talks to NotebookLM through notebooklm-py) and `SampleBackend`
(offline, clearly labelled example data)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from typing import List

from .models import QA, NotebookInfo, OutputFile, SourceInfo, SourceSpec


class Backend:
    mode: str = "abstract"
    library_version: str = ""

    async def __aenter__(self) -> "Backend":
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def create_notebook(self, title: str) -> str:
        raise NotImplementedError

    async def list_notebooks(self) -> List[NotebookInfo]:
        """All notebooks of the account, most recent first."""
        raise NotImplementedError

    async def add_source(self, notebook_id: str, spec: SourceSpec) -> SourceInfo:
        raise NotImplementedError

    async def ask(self, notebook_id: str, question: str, language: str) -> QA:
        raise NotImplementedError

    async def generate(
        self, notebook_id: str, kind: str, language: str, dest_dir: Path, instructions: Optional[str] = None
    ) -> OutputFile:
        """Generate one output, download it into `dest_dir` and return its description
        (path relative to the run folder is filled in by the pipeline)."""
        raise NotImplementedError
