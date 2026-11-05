"""Real mode: drives NotebookLM through the third-party `notebooklm-py` library
(https://github.com/teng-lin/notebooklm-py, MIT, unofficial). The library is
imported, never copied. Needs a one-time login on the user's own computer.

STATUS: written against notebooklm-py 0.8.6's documented/inspected API, but NOT
yet exercised against a live Google account (the dev box has no login)."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from .backend import Backend
from typing import List

from .models import QA, Citation, NotebookInfo, OutputFile, SourceInfo, SourceSpec


class LoginRequiredError(RuntimeError):
    """Raised when no saved NotebookLM login session exists."""


AUDIO_INSTRUCTIONS_AR = "اجعل الحوار بالعربية الفصحى المبسطة، وموجّهًا لصنّاع المحتوى العرب، مع أمثلة عملية."

# kind -> (file name, wait timeout seconds)
_FILES = {
    "briefing": "briefing_doc.md",
    "study_guide": "study_guide.md",
    "mind_map": "mind_map.json",
    "audio": "audio_overview.m4a",
    "quiz": "quiz.md",
    "flashcards": "flashcards.md",
    "slide_deck": "slide_deck.pdf",
}
_TIMEOUTS = {"audio": 1200.0, "slide_deck": 900.0}


class RealBackend(Backend):
    mode = "real"

    def __init__(
        self, profile: Optional[str] = None, storage_path: Optional[str] = None, timeouts: Optional[Dict[str, float]] = None
    ) -> None:
        self._timeouts = {**_TIMEOUTS, **(timeouts or {})}
        self.profile = profile
        self.storage_path = storage_path
        self._ctx = None
        self._client = None
        self._titles: Dict[str, str] = {}

    async def __aenter__(self) -> "RealBackend":
        from . import storage

        if not storage.has_session(self.profile, self.storage_path):
            raise LoginRequiredError(storage.LOGIN_HINT)
        import notebooklm
        from notebooklm import NotebookLMClient

        self.library_version = f"notebooklm-py {notebooklm.__version__}"
        self._ctx = NotebookLMClient.from_storage(path=self.storage_path, profile=self.profile)
        self._client = await self._ctx.__aenter__()
        return self

    async def __aexit__(self, *exc) -> None:
        if self._ctx is not None:
            await self._ctx.__aexit__(*exc)
            self._ctx = self._client = None

    # --- notebook + sources ------------------------------------------------
    async def create_notebook(self, title: str) -> str:
        nb = await self._client.notebooks.create(title)
        return nb.id

    async def list_notebooks(self) -> List[NotebookInfo]:
        nbs = await self._client.notebooks.list()
        return [NotebookInfo(id=n.id, title=getattr(n, "title", "") or n.id, sources_count=int(getattr(n, "sources_count", 0) or 0)) for n in nbs]

    async def _load_titles(self, notebook_id: str) -> None:
        """Titles of an existing notebook's sources, so citations can name them (best effort)."""
        try:
            for src in await self._client.sources.list(notebook_id):
                self._titles.setdefault(src.id, getattr(src, "title", None) or src.id)
        except Exception:
            pass

    async def add_source(self, notebook_id: str, spec: SourceSpec) -> SourceInfo:
        sources = self._client.sources
        if spec.kind == "file":
            src = await sources.add_file(notebook_id, Path(spec.value), wait=True, title=spec.title)
        else:  # url + youtube: add_url auto-detects YouTube
            src = await sources.add_url(notebook_id, spec.value, wait=True)
        title = getattr(src, "title", None) or spec.title or spec.value
        self._titles[src.id] = title
        return SourceInfo(id=src.id, title=title, kind=spec.kind, value=spec.value)

    # --- chat --------------------------------------------------------------
    async def ask(self, notebook_id: str, question: str, language: str) -> QA:
        result = await self._client.chat.ask(notebook_id, question)
        if any((getattr(r, "source_id", "") or "") not in self._titles for r in getattr(result, "references", None) or []):
            await self._load_titles(notebook_id)
        citations = []
        for ref in getattr(result, "references", None) or []:
            sid = getattr(ref, "source_id", "") or ""
            citations.append(
                Citation(
                    number=int(getattr(ref, "citation_number", 0) or 0),
                    source_id=sid,
                    source_title=self._titles.get(sid, sid),
                    text=getattr(ref, "cited_text", "") or "",
                )
            )
        return QA(question=question, answer=result.answer, citations=citations)

    # --- studio outputs ----------------------------------------------------
    async def _await_done(self, notebook_id: str, status, timeout: float) -> None:
        if status is None or not getattr(status, "task_id", None) or getattr(status, "is_failed", False):
            detail = getattr(status, "error", None) or "generation did not start (quota/rate limit?)"
            raise RuntimeError(str(detail))
        final = await self._client.artifacts.wait_for_completion(notebook_id, status.task_id, timeout=timeout)
        if getattr(final, "is_failed", False):
            raise RuntimeError(str(getattr(final, "error", None) or "generation failed"))

    async def generate(
        self, notebook_id: str, kind: str, language: str, dest_dir: Path, instructions: Optional[str] = None
    ) -> OutputFile:
        from notebooklm import ReportFormat

        if kind not in _FILES:
            raise ValueError(f"unknown output kind: {kind}")
        art = self._client.artifacts
        dest_dir.mkdir(parents=True, exist_ok=True)
        out = str(dest_dir / _FILES[kind])
        timeout = self._timeouts.get(kind, 600.0)

        if kind in ("briefing", "study_guide"):
            fmt = ReportFormat.BRIEFING_DOC if kind == "briefing" else ReportFormat.STUDY_GUIDE
            st = await art.generate_report(notebook_id, report_format=fmt, language=language, extra_instructions=instructions)
            await self._await_done(notebook_id, st, timeout)
            await art.download_report(notebook_id, out)
        elif kind == "mind_map":
            res = await art.generate_mind_map(notebook_id, language=language, instructions=instructions)
            try:
                await art.download_mind_map(notebook_id, out, getattr(res, "note_id", None))
            except Exception:
                # fall back to saving the structure the generate call returned
                import json

                mm = getattr(res, "mind_map", None)
                if not isinstance(mm, dict):
                    raise
                Path(out).write_text(json.dumps(mm, ensure_ascii=False, indent=2), encoding="utf-8")
        elif kind == "audio":
            st = await art.generate_audio(
                notebook_id, language=language, instructions=instructions or AUDIO_INSTRUCTIONS_AR
            )
            await self._await_done(notebook_id, st, timeout)
            await art.download_audio(notebook_id, out)
        elif kind == "quiz":
            st = await art.generate_quiz(notebook_id, instructions=instructions or "اكتب الأسئلة والإجابات بالعربية.")
            await self._await_done(notebook_id, st, timeout)
            await art.download_quiz(notebook_id, out, output_format="markdown")
        elif kind == "flashcards":
            st = await art.generate_flashcards(notebook_id, instructions=instructions or "اكتب البطاقات بالعربية.")
            await self._await_done(notebook_id, st, timeout)
            await art.download_flashcards(notebook_id, out, output_format="markdown")
        elif kind == "slide_deck":
            st = await art.generate_slide_deck(notebook_id, language=language, instructions=instructions)
            await self._await_done(notebook_id, st, timeout)
            await art.download_slide_deck(notebook_id, out, output_format="pdf")
        return OutputFile(kind=kind, path=Path(out).name)
