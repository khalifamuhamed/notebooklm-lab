"""The workflow: notebook -> sources -> questions -> outputs -> report."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Sequence

from .backend import Backend
from .config import DEFAULT_LANGUAGE, DEFAULT_OUTPUTS, OUTPUT_KINDS
from .models import OutputFile, RunResult, SourceInfo, SourceSpec
from .report import render_report

DEFAULT_QUESTIONS_AR: Sequence[str] = (
    "لخّص أهم الأفكار في هذه المصادر في نقاط واضحة، مع الإشارة إلى المصدر. أجب بالعربية.",
    "ما أبرز النقاط التي يمكن لصانع محتوى عربي تحويلها إلى فيديوهات قصيرة؟ أجب بالعربية.",
    "هل توجد اختلافات أو تناقضات بين المصادر؟ أجب بالعربية.",
)


def _slug(text: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return s[:30] or "run"


def make_run_dir(root: Path, title: str, now: Optional[datetime] = None) -> Path:
    now = now or datetime.now()
    d = root / f"{now:%Y%m%d-%H%M%S}-{_slug(title)}"
    n = 1
    while d.exists():
        n += 1
        d = root / f"{now:%Y%m%d-%H%M%S}-{_slug(title)}-{n}"
    (d / "files").mkdir(parents=True)
    return d


async def run_digest(
    backend: Backend,
    specs: Iterable[SourceSpec],
    run_dir: Path,
    title: str,
    language: str = DEFAULT_LANGUAGE,
    outputs: Sequence[str] = DEFAULT_OUTPUTS,
    questions: Optional[Sequence[str]] = None,
    say: Callable[[str], None] = lambda _m: None,
) -> RunResult:
    for k in outputs:
        if k not in OUTPUT_KINDS:
            raise ValueError(f"unknown output {k!r}; choose from {', '.join(OUTPUT_KINDS)}")
    result = RunResult(
        mode=backend.mode,
        title=title,
        language=language,
        created_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        run_dir=run_dir.name,
        library_version=backend.library_version,
    )
    files_dir = run_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)

    say("1/4 إنشاء دفتر الملاحظات … / creating notebook")
    result.notebook_id = await backend.create_notebook(title)

    say("2/4 إضافة المصادر … / adding sources")
    for spec in specs:
        try:
            info = await backend.add_source(result.notebook_id, spec)
        except Exception as exc:  # keep going: one bad link must not kill the run
            info = SourceInfo(id="", title=spec.title or spec.value, kind=spec.kind, value=spec.value, status="failed", error=_short(exc))
            result.warnings.append(f"فشل إضافة المصدر / source failed: {spec.value} ({_short(exc)})")
        result.sources.append(info)
        say(f"   - {info.status}: {info.title}")

    if not any(s.status == "ready" for s in result.sources):
        result.warnings.append("لا يوجد أي مصدر جاهز، تم تخطي الأسئلة والمخرجات. / no usable source; skipped questions and outputs.")
    else:
        say("3/4 طرح الأسئلة … / asking questions")
        for q in questions or DEFAULT_QUESTIONS_AR:
            try:
                result.qa.append(await backend.ask(result.notebook_id, q, language))
            except Exception as exc:
                result.warnings.append(f"فشل السؤال / question failed: {q[:40]}… ({_short(exc)})")

        say("4/4 إنشاء المخرجات وتنزيلها … / generating and downloading outputs")
        for kind in outputs:
            say(f"   - {kind}")
            try:
                out = await backend.generate(result.notebook_id, kind, language, files_dir)
                if out.ok and out.path:
                    out.path = f"files/{out.path}"
                    out.size_bytes = (run_dir / out.path).stat().st_size
            except Exception as exc:
                out = OutputFile(kind=kind, ok=False, error=_short(exc))
                result.warnings.append(f"فشل إنشاء / output failed: {kind} ({_short(exc)})")
            result.outputs.append(out)

    (run_dir / "run.json").write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "report.html").write_text(render_report(result, run_dir), encoding="utf-8")
    return result


def _short(exc: BaseException) -> str:
    msg = f"{type(exc).__name__}: {exc}".strip()
    return msg[:300]
