"""ONE question -> your Obsidian notes AND your NotebookLM notebooks -> ONE Arabic answer that cites both.

* Obsidian side: keyword/ranked search of the vault's Markdown files (`vault_search`), read-only. Each cited note is
  named by its file path (relative to the vault + full path) with an excerpt: [ملاحظة 1].
* NotebookLM side: the same cited chat as `ask-all` across all/filtered notebooks, each part named by its notebook: [2.1].
* The answer is assembled deterministically from those two sides - nothing is paraphrased, so nothing is invented.
  (An AI agent that calls this can synthesise a final reply from it.)
* If NotebookLM is not available (no login, error), the Obsidian part is still returned with a clear note, and the
  other way round. Only when NOTHING could be searched is it an error."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

from . import askall, obsidian, vault_search
from .backend import Backend

DEFAULT_NOTE_LIMIT = 5
DEFAULT_NOTEBOOK_LIMIT = 5
EXIT_OK, EXIT_USAGE, EXIT_LOGIN, EXIT_FAILED = 0, 2, 3, 4


@dataclass
class Combined:
    question: str
    mode: str
    created_at: str
    vault: str = ""
    vault_result: Optional[vault_search.SearchResult] = None
    vault_error: Optional[str] = None
    notebooks: Optional[askall.AskAllResult] = None
    notebooks_error: Optional[str] = None
    notebooks_login: bool = False  # the notebooks side failed because of the login
    report_dir: str = ""

    @property
    def has_notes(self) -> bool:
        return bool(self.vault_result and self.vault_result.hits)

    @property
    def has_notebook_answers(self) -> bool:
        return bool(self.notebooks and self.notebooks.useful)

    def to_dict(self) -> dict:
        return asdict(self)


def exit_code(c: Combined) -> int:
    """0 = at least one side was searched (zero matches is a valid answer); 3 = login missing and nothing else worked;
    2 = nothing could be searched because of settings/filters; 4 = real failures."""
    if c.has_notes or c.has_notebook_answers:
        return EXIT_OK
    if c.vault_result is not None or (c.notebooks is not None and any(a.ok for a in c.notebooks.answers)):
        return EXIT_OK
    if c.notebooks_login:
        return EXIT_LOGIN
    return EXIT_FAILED if (c.notebooks_error or (c.notebooks is not None and c.notebooks.answers)) else EXIT_USAGE


async def run_combined(question: str, *, backend_factory: Optional[Callable[[], Backend]], include_notebooks: bool = True,
                       include_vault: bool = True, data_dir: Optional[Path] = None, vault: Optional[str] = None,
                       folder: Optional[str] = None, note_limit: int = DEFAULT_NOTE_LIMIT,
                       flt: Optional[askall.Filters] = None, timeout_s: float = askall.DEFAULT_TIMEOUT_S, mode: str = "real",
                       say: Callable[[str], None] = lambda _m: None) -> Combined:
    """Searches both sides. Never raises for a side that fails: the failure is recorded in the result."""
    from .real_backend import LoginRequiredError

    c = Combined(question=question, mode=mode, created_at=datetime.now().strftime("%Y-%m-%d %H:%M"))
    if include_vault:
        try:
            target = obsidian.resolve_target(data_dir, vault)
            c.vault = str(target.vault)
            c.vault_result = vault_search.search(target.vault, question, limit=note_limit, folder=folder)
            say(f"Obsidian: فُحص {c.vault_result.files_scanned} ملف، {len(c.vault_result.hits)} ملاحظة مطابقة")
        except (obsidian.ObsidianError, ValueError) as exc:
            c.vault_error = str(exc)
        except OSError as exc:
            c.vault_error = f"تعذّرت قراءة الـ vault: {type(exc).__name__}: {exc}"
    if include_notebooks and backend_factory is not None:
        try:
            backend = backend_factory()
            async with backend:
                c.mode = backend.mode
                c.notebooks = await askall.ask_all(backend, question, flt or askall.Filters(limit=DEFAULT_NOTEBOOK_LIMIT),
                                                   timeout_s=timeout_s, say=say)
        except LoginRequiredError as exc:
            c.notebooks_login, c.notebooks_error = True, str(exc).splitlines()[0]
        except Exception as exc:
            if askall.looks_like_auth_problem(exc):
                c.notebooks_login, c.notebooks_error = True, "انتهت صلاحية تسجيل الدخول إلى NotebookLM"
            else:
                c.notebooks_error = f"{type(exc).__name__}: {str(exc)[:200]}"
    return c


# ------------------------------------------------------------------ rendering
def _note_block(i: int, h) -> List[str]:
    return [f"### [ملاحظة {i}] {h.title}", "", f"- **الملف:** `{h.path}`", f"- **المسار الكامل:** `{h.abs_path}`",
            f"- **آخر تعديل:** {h.modified}" + (f" · **وسوم:** {' '.join('#' + t for t in h.tags)}" if h.tags else ""),
            f"- **كلمات مطابقة:** {', '.join(h.matched)}", "", f"> {h.snippet or '(بلا مقتطف)'}", ""]


def render_markdown(c: Combined) -> str:
    notes = c.vault_result.hits if c.vault_result else []
    nb = c.notebooks
    L: List[str] = ["# إجابة مجمّعة من ملاحظات Obsidian ودفاتر NotebookLM", "", f"**السؤال:** {c.question}", ""]
    if c.mode == "sample":
        L += ["> ⚠ وضع تجريبي: دفاتر NotebookLM هنا بيانات مثال وليست حقيقية.", ""]
    parts = []
    if c.vault_result is not None:
        parts.append(f"Obsidian: {len(notes)} ملاحظة مطابقة من {c.vault_result.files_scanned} ملف")
    if nb is not None:
        parts.append("NotebookLM: " + askall.summary_line(nb))
    L += ["; ".join(parts) or "لم يُفحص أي مصدر.", ""]
    L += ["> تجميع حرفي من المصدرين دون إعادة صياغة: مقتطفات الملاحظات تُنسب إلى **مسار ملفها** `[ملاحظة n]`، وإجابات NotebookLM تُنسب إلى **اسم الدفتر** `[k.n]`.", ""]
    for what, err in (("Obsidian", c.vault_error), ("NotebookLM", c.notebooks_error)):
        if err:
            L += [f"> ⚠ **{what} لم يُفحص:** {err}", ""]
    L += ["## ١. من ملاحظاتك في Obsidian", ""]
    if c.vault_result is None:
        L += ["(لم يُفحص)", ""]
    elif not notes:
        L += [f"لا توجد ملاحظات تطابق كلمات السؤال ({'، '.join(c.vault_result.terms)}).", ""]
    for i, h in enumerate(notes, 1):
        L += _note_block(i, h)
    if c.vault_result and c.vault_result.truncated:
        L += [f"_تنبيه: الـ vault كبير جدًا؛ فُحص أول {vault_search.MAX_FILES} ملف فقط._", ""]
    L += ["## ٢. من دفاتر NotebookLM", ""]
    if nb is None:
        L += ["(لم يُفحص)", ""]
    else:
        if not nb.useful:
            L += ["لم يجب أي دفتر بمعلومات مفيدة عن هذا السؤال.", ""]
        L += askall.answers_markdown(nb, "###")
    L += [f"_أُنشئ في {c.created_at}. أداة غير رسمية مبنية فوق notebooklm-py، وغير مرتبطة بـ Google._", ""]
    return "\n".join(L)


def render_html(c: Combined) -> str:
    h = askall._h
    notes = c.vault_result.hits if c.vault_result else []
    nb = c.notebooks
    p: List[str] = ["<h1>إجابة مجمّعة من ملاحظات Obsidian ودفاتر NotebookLM</h1>", f"<div class='muted'>{h(c.created_at)}</div>"]
    if c.mode == "sample":
        p.append("<div class='banner'>⚠ وضع تجريبي: دفاتر NotebookLM هنا بيانات مثال وليست حقيقية.</div>")
    p.append(f"<div class='card'><b>السؤال:</b> {askall._para(c.question)}</div>")
    for what, err in (("Obsidian", c.vault_error), ("NotebookLM", c.notebooks_error)):
        if err:
            p.append(f"<div class='banner'>⚠ {what} لم يُفحص: {h(err)}</div>")
    p.append("<h2>١. من ملاحظاتك في Obsidian</h2>")
    if c.vault_result is None:
        p.append("<div class='card muted'>(لم يُفحص)</div>")
    elif not notes:
        p.append(f"<div class='card muted'>لا توجد ملاحظات تطابق: {h('، '.join(c.vault_result.terms))}</div>")
    for i, n in enumerate(notes, 1):
        p.append(f"<div class='card'><b>[ملاحظة {i}] {h(n.title)}</b><div class='muted'>الملف: <code>{h(n.path)}</code> · آخر تعديل {h(n.modified)}</div>"
                 f"<div class='muted'>المسار الكامل: <code>{h(n.abs_path)}</code></div><div class='cite'>{h(n.snippet)}</div></div>")
    p.append("<h2>٢. من دفاتر NotebookLM</h2>")
    if nb is None:
        p.append("<div class='card muted'>(لم يُفحص)</div>")
    else:
        p.append(f"<div class='card'>{h(askall.summary_line(nb))}</div>")
        if not nb.useful:
            p.append("<div class='card muted'>لم يجب أي دفتر بمعلومات مفيدة.</div>")
        p += askall.answers_html(nb)
    return askall.html_page("إجابة مجمّعة (Obsidian + NotebookLM)", p)


def reports_root(base: Optional[Path] = None, sample: bool = False) -> Path:
    from .config import data_dir

    return (Path(base).expanduser().resolve() if base else data_dir()) / ("ask-both-sample" if sample else "ask-both")


def save_report(c: Combined, root: Path, now: Optional[datetime] = None) -> Path:
    now = now or datetime.now()
    base = f"{now:%Y%m%d-%H%M%S}-{askall._slug(c.question)}"
    d, n = root / base, 1
    while d.exists():
        n += 1
        d = root / f"{base}-{n}"
    d.mkdir(parents=True)
    c.report_dir = str(d)
    (d / "report.md").write_text(render_markdown(c), encoding="utf-8")
    (d / "report.html").write_text(render_html(c), encoding="utf-8")
    (d / "answer.json").write_text(json.dumps(c.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return d
