"""Plain data classes shared by the real and sample backends and the report."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SourceSpec:
    """What the user asked to add: a web link, a YouTube link or a local file."""

    kind: str  # "url" | "youtube" | "file"
    value: str  # the URL or the file path
    title: Optional[str] = None


@dataclass
class SourceInfo:
    id: str
    title: str
    kind: str
    value: str
    status: str = "ready"  # "ready" | "failed"
    error: Optional[str] = None


@dataclass
class NotebookInfo:
    """One of the user's existing notebooks (for questions across all notebooks)."""

    id: str
    title: str
    sources_count: int = 0


@dataclass
class Citation:
    number: int
    source_id: str
    source_title: str
    text: str


@dataclass
class QA:
    question: str
    answer: str
    citations: List[Citation] = field(default_factory=list)


@dataclass
class OutputFile:
    kind: str  # briefing | study_guide | mind_map | audio | quiz | flashcards | slide_deck
    path: Optional[str] = None  # relative to the run folder; None when failed
    size_bytes: int = 0
    ok: bool = True
    error: Optional[str] = None
    note: Optional[str] = None


@dataclass
class RunResult:
    mode: str  # "real" | "sample"
    title: str
    language: str
    created_at: str
    notebook_id: str = ""
    sources: List[SourceInfo] = field(default_factory=list)
    qa: List[QA] = field(default_factory=list)
    outputs: List[OutputFile] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    run_dir: str = ""
    library_version: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
