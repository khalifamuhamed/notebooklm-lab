"""Offline demo backend. EVERYTHING it produces is example data written by this
repo, NOT output from NotebookLM. Every file and the report are labelled so."""
from __future__ import annotations

import json
import math
import struct
import wave
from pathlib import Path
from typing import Dict, List, Optional

from .backend import Backend
from .models import QA, Citation, NotebookInfo, OutputFile, SourceInfo, SourceSpec

SAMPLE_BANNER_AR = "⚠ بيانات تجريبية: هذا المحتوى مثال مكتوب مسبقًا داخل المشروع، وليس ناتجًا من NotebookLM."
SAMPLE_BANNER_EN = "SAMPLE DATA - pre-written example content from this repo, NOT produced by NotebookLM."

DEMO_SPECS: List[SourceSpec] = [
    SourceSpec("url", "https://example.com/sample-article-1", "مقال تجريبي ١: لماذا تنجح القصص القصيرة؟"),
    SourceSpec("youtube", "https://www.youtube.com/watch?v=SAMPLE_ID_1", "فيديو تجريبي ٢: أسرار الهوك في أول ٣ ثوانٍ"),
    SourceSpec("file", "examples/sample_notes.md", "ملف محلي تجريبي: ملاحظات صانع المحتوى"),
]


def _tone_wav(path: Path, seconds: float = 2.0, rate: int = 8000) -> None:
    """A short, quiet 440 Hz tone - a stand-in so the demo has an 'audio' file."""
    frames = bytearray()
    for i in range(int(seconds * rate)):
        fade = min(1.0, i / 400, (seconds * rate - i) / 400)
        v = int(6000 * fade * math.sin(2 * math.pi * 440 * i / rate))
        frames += struct.pack("<h", v)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))


#: (id, title, sources, pre-written answer) - "existing notebooks" for the offline search-all demo. EXAMPLE DATA.
SAMPLE_NOTEBOOKS = [
    ("sample-nb-1", "[عينة] ملخص صباحي 2026-11-01", 3,
     "[عينة] تشير المصادر إلى أن البداية القوية في أول ثلاث ثوانٍ ترفع نسبة المشاهدة [1]."),
    ("sample-nb-2", "[عينة] أبحاث الخوارزميات", 5,
     "[عينة] لا تحتوي المصادر في هذا الدفتر على معلومات عن هذا الموضوع."),
    ("sample-nb-3", "[عينة] ملاحظات صانع المحتوى", 2,
     "[عينة] توصي الملاحظات بتحويل كل فكرة إلى سلسلة مقاطع قصيرة مع تكرار الرسالة الأساسية [1]."),
]


class SampleBackend(Backend):
    mode = "sample"
    library_version = "sample (notebooklm-py not used)"

    def __init__(self) -> None:
        self._sources: Dict[str, SourceInfo] = {}

    async def create_notebook(self, title: str) -> str:
        return "sample-notebook-0001"

    async def list_notebooks(self) -> List[NotebookInfo]:
        return [NotebookInfo(nid, title, n) for nid, title, n, _a in SAMPLE_NOTEBOOKS]

    async def add_source(self, notebook_id: str, spec: SourceSpec) -> SourceInfo:
        n = len(self._sources) + 1
        title = spec.title or spec.value
        info = SourceInfo(id=f"sample-src-{n}", title=f"[عينة] {title}", kind=spec.kind, value=spec.value)
        self._sources[info.id] = info
        return info

    def _cite(self, n: int, text: str) -> Citation:
        ids = list(self._sources)
        sid = ids[(n - 1) % len(ids)] if ids else "sample-src-1"
        title = self._sources[sid].title if sid in self._sources else "[عينة]"
        return Citation(number=n, source_id=sid, source_title=title, text=text)

    async def ask(self, notebook_id: str, question: str, language: str) -> QA:
        known = {nid: (title, ans) for nid, title, _n, ans in SAMPLE_NOTEBOOKS}
        if notebook_id in known:  # a pre-written "existing notebook" for the search-all demo
            title, ans = known[notebook_id]
            src = f"[عينة] مصدر في «{title}»"
            return QA(question=question, answer=ans, citations=[Citation(1, f"{notebook_id}-src", src, "(مقتطف تجريبي) نص مثال من المصدر.")] if "[1]" in ans else [])
        answer = (
            "[عينة] هذه إجابة تجريبية مكتوبة مسبقًا. تُظهر الأفكار الرئيسية في المصادر أن الجمهور "
            "يتفاعل مع البدايات القوية [1] وأن التكرار المنظّم للرسالة يرفع التذكّر [2]، "
            "وأن تحويل الملاحظات إلى سلسلة محتوى يوفّر وقتًا كبيرًا [3]."
        )
        cites = [
            self._cite(1, "(مقتطف تجريبي) البداية القوية تحدد قرار المشاهد بالاستمرار."),
            self._cite(2, "(مقتطف تجريبي) كرّر الفكرة الأساسية بصيغ مختلفة."),
            self._cite(3, "(مقتطف تجريبي) حوّل كل ملاحظة إلى منشور أو مقطع قصير."),
        ]
        return QA(question=question, answer=answer, citations=cites)

    async def generate(
        self, notebook_id: str, kind: str, language: str, dest_dir: Path, instructions: Optional[str] = None
    ) -> OutputFile:
        dest_dir.mkdir(parents=True, exist_ok=True)
        titles = "\n".join(f"- {s.title}" for s in self._sources.values()) or "- (لا مصادر)"
        if kind in ("briefing", "study_guide"):
            name = "briefing_sample.md" if kind == "briefing" else "study_guide_sample.md"
            head = "ملخص تنفيذي" if kind == "briefing" else "دليل دراسة"
            body = (
                f"# {head} (عينة)\n\n> {SAMPLE_BANNER_AR}\n> {SAMPLE_BANNER_EN}\n\n"
                "## الأفكار الرئيسية\n- ابدأ بجملة جذابة في أول ثوانٍ.\n- كرّر الرسالة الأساسية بصيغ مختلفة.\n"
                "- حوّل الملاحظات إلى سلسلة محتوى قصيرة.\n\n## المصادر المستخدمة\n" + titles + "\n"
            )
            (dest_dir / name).write_text(body, encoding="utf-8")
            return OutputFile(kind=kind, path=name, note="sample")
        if kind == "mind_map":
            name = "mind_map_sample.json"
            data = {
                "sample": True,
                "notice": SAMPLE_BANNER_EN,
                "name": "صناعة المحتوى (عينة)",
                "children": [
                    {"name": "البداية القوية", "children": [{"name": "الهوك"}, {"name": "السؤال المثير"}]},
                    {"name": "التكرار المنظم", "children": [{"name": "صيغ متعددة"}]},
                    {"name": "إعادة التدوير", "children": [{"name": "منشورات"}, {"name": "مقاطع قصيرة"}]},
                ],
            }
            (dest_dir / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return OutputFile(kind=kind, path=name, note="sample")
        if kind == "audio":
            name = "audio_overview_SAMPLE_tone.wav"
            _tone_wav(dest_dir / name)
            return OutputFile(
                kind=kind, path=name, note="sample: a 2-second tone placeholder, not a real podcast"
            )
        if kind in ("quiz", "flashcards"):
            name = f"{kind}_sample.md"
            (dest_dir / name).write_text(
                f"# {kind} (عينة)\n\n> {SAMPLE_BANNER_AR}\n\n1. ما أهم عنصر في أول ثلاث ثوانٍ؟\n   - الجواب: الهوك.\n",
                encoding="utf-8",
            )
            return OutputFile(kind=kind, path=name, note="sample")
        if kind == "slide_deck":
            return OutputFile(kind=kind, ok=False, error="slide_deck is not simulated in sample mode")
        raise ValueError(f"unknown output kind: {kind}")
