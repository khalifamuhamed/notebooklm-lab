"""Morning digest: new inbox links -> one dated Arabic notebook -> written summary +
Arabic audio overview -> downloaded into a dated folder + short Arabic report.

It reuses `pipeline.run_digest` (the same flow as the `digest` command) and the
same two backends (real NotebookLM through notebooklm-py, or offline sample)."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date as _date
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import inbox as ib
from .backend import Backend
from .config import DEFAULT_LANGUAGE, data_dir
from .models import OutputFile, RunResult, SourceInfo, SourceSpec
from .pipeline import run_digest
from .sources import SourceError, classify
from .storage import human_size, list_runs, path_size

MORNING_OUTPUTS = ("briefing", "audio")  # written Arabic summary + Arabic audio overview (podcast)
MORNING_QUESTIONS = ("لخّص أهم الأفكار في كل مصدر بنقاط قصيرة وواضحة، مع الإشارة إلى المصدر. أجب بالعربية.",)
TITLE_PREFIX = "ملخص صباحي"
DEFAULT_MAX_LINKS = 20  # NotebookLM allows a limited number of sources per notebook
DEFAULT_AUDIO_TIMEOUT_MIN = 20
SOURCE_TIMEOUT_S = 300.0
MAX_FAILED_ATTEMPTS = 2  # a link that fails this many runs (while others succeed) is given up on

EXIT_OK, EXIT_USAGE, EXIT_LOGIN, EXIT_FAILED = 0, 2, 3, 4


# ------------------------------------------------------------------ paths
@dataclass
class Paths:
    base: Path
    sample: bool = False

    @property
    def inbox(self) -> Path:
        return self.base / ib.INBOX_NAME

    @property
    def state(self) -> Path:
        return self.base / (ib.SAMPLE_STATE_NAME if self.sample else ib.STATE_NAME)

    @property
    def outputs(self) -> Path:
        return self.base / ("morning-sample" if self.sample else "morning")

    @property
    def log(self) -> Path:
        return self.base / "morning.log"


def make_paths(base: Optional[Path] = None, sample: bool = False) -> Paths:
    return Paths(Path(base).expanduser().resolve() if base else data_dir(), sample)


def dated_title(day: str, n: int = 1) -> str:
    return f"{TITLE_PREFIX} {day}" + (f" ({n})" if n > 1 else "")


def make_dated_dir(root: Path, day: str) -> "tuple[Path, int]":
    """root/2026-11-03 (a second run the same day gets -2, -3 ...)."""
    n = 1
    d = root / day
    while d.exists():
        n += 1
        d = root / f"{day}-{n}"
    (d / "files").mkdir(parents=True)
    return d, n


# ------------------------------------------------------------------ guarded backend
class GuardedBackend(Backend):
    """Wraps a backend so one hanging link or a slow audio generation can never block the
    whole run: every call has a time limit and a timeout becomes an ordinary, reported failure."""

    def __init__(self, inner: Backend, audio_timeout_s: float, source_timeout_s: float = SOURCE_TIMEOUT_S):
        self.inner, self.audio_timeout_s, self.source_timeout_s = inner, audio_timeout_s, source_timeout_s
        self.mode = inner.mode

    @property  # type: ignore[override]
    def library_version(self) -> str:  # real backend sets it on __aenter__
        return self.inner.library_version

    async def __aenter__(self):
        await self.inner.__aenter__()
        return self

    async def __aexit__(self, *exc):
        return await self.inner.__aexit__(*exc)

    async def create_notebook(self, title):
        return await self.inner.create_notebook(title)

    async def add_source(self, notebook_id, spec):
        try:
            return await asyncio.wait_for(self.inner.add_source(notebook_id, spec), self.source_timeout_s)
        except asyncio.TimeoutError:
            raise RuntimeError(f"انتهت المهلة ({int(self.source_timeout_s)} ثانية) / timed out") from None

    async def ask(self, notebook_id, question, language):
        return await asyncio.wait_for(self.inner.ask(notebook_id, question, language), self.source_timeout_s)

    async def generate(self, notebook_id, kind, language, dest_dir, instructions=None):
        limit = self.audio_timeout_s if kind == "audio" else 900.0
        try:
            return await asyncio.wait_for(self.inner.generate(notebook_id, kind, language, dest_dir, instructions), limit)
        except asyncio.TimeoutError:
            raise RuntimeError(f"انتهت المهلة بعد {int(limit // 60)} دقيقة / timed out after {int(limit // 60)} min") from None


# ------------------------------------------------------------------ the run
@dataclass
class MorningOutcome:
    code: int
    message: str
    run_dir: Optional[Path] = None
    processed: int = 0
    failed: int = 0
    warnings: List[str] = field(default_factory=list)


def _looks_like_auth_problem(exc: BaseException) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return any(w in text for w in ("auth", "login", "sign in", "sign-in", "expired", "401", "403", "cookie", "csrf"))


LOGIN_HELP = (
    "انتهت صلاحية تسجيل الدخول أو غير موجود. شغّل مرة أخرى على جهازك:  python -m notebooklm_lab login\n"
    "Login missing or expired. Run again on your computer:  python -m notebooklm_lab login"
)


def _log(paths: Paths, lines: List[str]) -> None:
    try:
        paths.base.mkdir(parents=True, exist_ok=True)
        if paths.log.exists() and paths.log.stat().st_size > 1_000_000:
            paths.log.replace(paths.log.with_suffix(".log.old"))
        with paths.log.open("a", encoding="utf-8") as f:
            f.write(f"--- {ib.now_iso()} {'(sample) ' if paths.sample else ''}---\n" + "\n".join(lines) + "\n")
    except OSError:
        pass


def write_morning_report(run_dir: Path, result: RunResult, day: str, failed_links: List[str]) -> Path:
    """A short Arabic Markdown report (the full RTL page is report.html next to it)."""
    ok_sources = [s for s in result.sources if s.status == "ready"]
    L: List[str] = [f"# {result.title}", ""]
    if result.mode == "sample":
        L += ["> ⚠ وضع تجريبي: بيانات مثال وليست من NotebookLM.", ""]
    L += [f"- التاريخ: {day}", f"- اللغة: `{result.language}`", f"- الروابط الناجحة: {len(ok_sources)} من {len(result.sources)}", "", "## الملفات"]
    for o in result.outputs:
        label = "الملخص المكتوب" if o.kind == "briefing" else "البودكاست الصوتي" if o.kind == "audio" else o.kind
        L.append(f"- {label}: `{o.path}` ({human_size(o.size_bytes)})" if o.ok else f"- {label}: ✘ لم يُنشأ — {o.error}")
    L += ["", "## الروابط"]
    for s in result.sources:
        L.append(f"- ✔ {s.value}" if s.status == "ready" else f"- ✘ {s.value} — {s.error}")
    for bad in failed_links:
        L.append(f"- ✘ {bad} — رابط غير صالح")
    if result.qa:
        L += ["", "## ملخص سريع", "", result.qa[0].answer]
    if result.warnings:
        L += ["", "## تنبيهات"] + [f"- {w}" for w in result.warnings]
    L += ["", f"التقرير الكامل: `report.html`", ""]
    p = run_dir / "morning_report.md"
    p.write_text("\n".join(L), encoding="utf-8")
    return p


async def run_morning(
    backend: Backend,
    paths: Paths,
    *,
    today: Optional[str] = None,
    audio_timeout_min: float = DEFAULT_AUDIO_TIMEOUT_MIN,
    max_links: int = DEFAULT_MAX_LINKS,
    language: str = DEFAULT_LANGUAGE,
    say: Callable[[str], None] = print,
) -> MorningOutcome:
    day = today or _date.today().isoformat()
    lines: List[str] = []

    def out(msg: str) -> None:
        lines.append(msg)
        say(msg)

    try:
        state = ib.load_state(paths.state)
    except ib.StateError as exc:
        out(f"✘ {exc}")
        return MorningOutcome(EXIT_USAGE, str(exc))

    if ib.ensure_inbox(paths.inbox):
        out(f"أنشأتُ ملف الروابط لأول مرة: {paths.inbox}\nأضف روابطك فيه (رابط في كل سطر) ثم شغّل الأمر مرة أخرى. / Created your inbox; add links and run again.")
        _log(paths, lines)
        return MorningOutcome(EXIT_OK, "inbox created")
    entries, dups = ib.read_inbox(paths.inbox)
    fresh = ib.new_entries(entries, state)
    if not fresh:
        msg = (f"لا توجد روابط جديدة اليوم ({day}). / No new links.\n"
               f"أضف روابط في الملف: {paths.inbox}  (عولج سابقًا: {len(entries)}، مكرر متجاهَل: {dups})")
        out(msg)
        state["last_run"] = {"at": ib.now_iso(), "date": day, "result": "no_new", "mode": backend.mode}
        ib.save_state(paths.state, state)
        _log(paths, lines)
        return MorningOutcome(EXIT_OK, "no new links")

    deferred = fresh[max_links:]
    fresh = fresh[:max_links]
    if deferred:
        out(f"⚠ سأعالج أول {max_links} رابطًا فقط الآن، وسيبقى {len(deferred)} للتشغيل القادم. / {len(deferred)} link(s) left for the next run.")

    # classify: lines that are not links/files can never succeed -> reported and never retried
    specs: List[SourceSpec] = []
    spec_entry: Dict[str, ib.InboxEntry] = {}
    invalid: List[ib.InboxEntry] = []
    for e in fresh:
        try:
            sp = classify(e.link)
        except SourceError as exc:
            invalid.append(e)
            out(f"⚠ سطر غير صالح (السطر {e.line}): {e.link} — {exc}")
            continue
        specs.append(sp)
        spec_entry[sp.value] = e
    if not specs:
        for e in invalid:
            ib.mark_processed(state, e, "invalid", day, "", "not a valid link")
        state["last_run"] = {"at": ib.now_iso(), "date": day, "result": "no_valid_links", "mode": backend.mode}
        ib.save_state(paths.state, state)
        out("لا توجد روابط صالحة. صحّح الأسطر المذكورة. / No valid links.")
        _log(paths, lines)
        return MorningOutcome(EXIT_OK, "no valid links", failed=len(invalid))

    guarded = GuardedBackend(backend, audio_timeout_s=audio_timeout_min * 60)
    run_dir: Optional[Path] = None
    try:
        async with guarded:
            run_dir, n = make_dated_dir(paths.outputs, day)
            title = dated_title(day, n)
            out(f"{'⚠ الوضع التجريبي (--sample): بيانات مثال بدون اتصال بـ NotebookLM.' if backend.mode == 'sample' else 'الوضع الحقيقي: سيُستخدم حسابك في NotebookLM.'}")
            out(f"روابط جديدة: {len(specs)} → دفتر «{title}»")
            result = await run_digest(
                guarded, specs, run_dir, title, language, MORNING_OUTPUTS, MORNING_QUESTIONS, say=out
            )
    except Exception as exc:
        from .real_backend import LoginRequiredError

        _cleanup_empty(run_dir)
        auth = isinstance(exc, LoginRequiredError) or _looks_like_auth_problem(exc)
        msg = LOGIN_HELP if auth else f"✘ فشل التشغيل / run failed: {type(exc).__name__}: {str(exc)[:300]}"
        out(f"\n✘ {exc}" if isinstance(exc, LoginRequiredError) else f"\n{msg}")
        state["last_run"] = {"at": ib.now_iso(), "date": day, "result": "login" if auth else "failed", "mode": backend.mode, "error": str(exc)[:200]}
        ib.save_state(paths.state, state)
        _log(paths, lines)
        return MorningOutcome(EXIT_LOGIN if auth else EXIT_FAILED, msg)

    ready = [s for s in result.sources if s.status == "ready"]
    ok_outputs = [o for o in result.outputs if o.ok]
    write_morning_report(run_dir, result, day, [e.link for e in invalid])  # type: ignore[arg-type]

    if not ready or not ok_outputs:
        # nothing usable came out: do NOT mark links done, so tomorrow's run tries again
        # (a source failure only counts against a link when other links did work)
        if ready:
            _count_failures(state, result.sources, spec_entry, day, run_dir.name)
        why = "لم ينجح أي رابط" if not ready else "لم يُنشأ أي ملف"
        hint = LOGIN_HELP if not ready and any(_auth_text(s.error) for s in result.sources if s.error) else ""
        out(f"\n✘ {why}؛ لم أسجّل الروابط كمعالَجة وسأعيد المحاولة في التشغيل القادم. / nothing usable; links stay pending.")
        if hint:
            out(hint)
        state["last_run"] = {"at": ib.now_iso(), "date": day, "result": "failed", "mode": backend.mode, "run": run_dir.name, "folder": str(run_dir)}
        ib.save_state(paths.state, state)
        _log(paths, lines)
        return MorningOutcome(EXIT_FAILED, why, run_dir, warnings=result.warnings)

    # success: record ready links; failed ones are retried once more, then given up on
    for s in result.sources:
        e = spec_entry.get(s.value)
        if e is None:
            continue
        if s.status == "ready":
            ib.mark_processed(state, e, "ok", day, run_dir.name)
    failed = _count_failures(state, result.sources, spec_entry, day, run_dir.name)
    for e in invalid:
        ib.mark_processed(state, e, "invalid", day, run_dir.name, "not a valid link")
    failed += len(invalid)
    state["last_run"] = {
        "at": ib.now_iso(), "date": day, "result": "ok", "mode": backend.mode, "run": run_dir.name, "folder": str(run_dir),
        "links_ok": len(ready), "links_failed": failed, "outputs_ok": [o.kind for o in ok_outputs],
        "outputs_failed": [o.kind for o in result.outputs if not o.ok],
    }
    state["last_success"] = state["last_run"]
    ib.save_state(paths.state, state)

    out(f"\n✔ انتهى الملخص الصباحي ({backend.mode}). روابط ناجحة: {len(ready)}، فاشلة/مرفوضة: {failed}")
    out(f"  المجلد / folder : {run_dir}")
    out(f"  التقرير القصير  : {run_dir / 'morning_report.md'}")
    out(f"  التقرير الكامل  : {run_dir / 'report.html'}")
    for o in result.outputs:
        out(f"  {'✔' if o.ok else '✘'} {o.kind}: {o.path if o.ok else o.error}")
    for w in result.warnings:
        out(f"  ! {w}")
    _log(paths, lines)
    return MorningOutcome(EXIT_OK, "done", run_dir, processed=len(ready), failed=failed, warnings=result.warnings)


def _auth_text(err: Optional[str]) -> bool:
    return bool(err) and any(w in err.lower() for w in ("auth", "login", "sign in", "expired", "401", "403", "cookie", "csrf"))


def _count_failures(state: Dict[str, Any], sources: List[SourceInfo], spec_entry: Dict[str, ib.InboxEntry], day: str, run: str) -> int:
    """Failed sources: count an attempt; after MAX_FAILED_ATTEMPTS mark them as failed for good."""
    n_failed = 0
    for s in sources:
        e = spec_entry.get(s.value)
        if e is None or s.status == "ready":
            continue
        n_failed += 1
        tries = state["failed_attempts"].get(e.key, 0) + 1
        if tries >= MAX_FAILED_ATTEMPTS:
            ib.mark_processed(state, e, "failed", day, run, s.error)
        else:
            state["failed_attempts"][e.key] = tries
    return n_failed


def _cleanup_empty(run_dir: Optional[Path]) -> None:
    """A run that crashed before producing anything leaves no empty dated folder behind."""
    if run_dir and run_dir.is_dir() and not (run_dir / "run.json").exists():
        import shutil

        shutil.rmtree(run_dir, ignore_errors=True)


# ------------------------------------------------------------------ status
def status_text(paths: Paths) -> str:
    try:
        state = ib.load_state(paths.state)
    except ib.StateError as exc:
        return f"✘ {exc}"
    last = state.get("last_run")
    lines = [f"الملخص الصباحي{' (تجريبي)' if paths.sample else ''} / Morning digest status", ""]
    lines.append(f"مجلد بياناتك / data folder : {paths.base}")
    lines.append(f"ملف الروابط / inbox         : {paths.inbox}  {'(موجود)' if paths.inbox.exists() else '(غير موجود بعد — سيُنشأ عند أول تشغيل)'}")
    lines.append(f"المخرجات / outputs         : {paths.outputs}")
    lines.append("")
    if not last:
        lines.append("آخر تشغيل / last run: لم يتم أي تشغيل بعد / never run")
    else:
        names = {"ok": "نجح ✔", "no_new": "لا روابط جديدة", "failed": "فشل ✘", "login": "يحتاج تسجيل دخول ✘", "no_valid_links": "لا روابط صالحة"}
        lines.append(f"آخر تشغيل / last run: {last.get('at')}  —  {names.get(last.get('result'), last.get('result'))}  [{last.get('mode')}]")
    succ = state.get("last_success")
    if succ:
        lines.append(f"آخر نجاح / last success: {succ.get('at')}  —  روابط ناجحة: {succ.get('links_ok', 0)}، فاشلة: {succ.get('links_failed', 0)}")
        lines.append(f"  المجلد / folder: {succ.get('folder')}")
        lines.append(f"  ملفات: {', '.join(succ.get('outputs_ok', [])) or '-'}" + (f"   لم تُنشأ: {', '.join(succ['outputs_failed'])}" if succ.get("outputs_failed") else ""))
    proc = state.get("processed", {})
    n_ok = sum(1 for v in proc.values() if v.get("status") == "ok")
    lines.append("")
    lines.append(f"روابط عولجت إجمالًا / links processed in total: {n_ok}  (فاشلة نهائيًا/غير صالحة: {len(proc) - n_ok})")
    if paths.inbox.exists():
        try:
            entries, _ = ib.read_inbox(paths.inbox)
            lines.append(f"روابط جديدة تنتظر / new links waiting: {len(ib.new_entries(entries, state))}")
        except OSError:
            pass
    runs = list_runs(paths.outputs)
    lines.append(f"عدد مجلدات المخرجات / output folders: {len(runs)}   الحجم / size: {human_size(sum(path_size(r) for r in runs))}")
    lines.append(f"للحذف / to delete: python -m notebooklm_lab outputs delete --all --yes --out \"{paths.outputs}\"")
    return "\n".join(lines)
