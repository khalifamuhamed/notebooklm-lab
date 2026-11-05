"""Ask ONE question across all (or some) of your NotebookLM notebooks and get ONE combined Arabic answer in which
every part names the notebook it came from, plus a saved Markdown + HTML report (and answer.json).

How it works: it lists your notebooks, asks each of them the same question through NotebookLM's own cited chat
(so every answer is grounded in that notebook's sources), then assembles the answers. The assembling is
deterministic text, NOT another AI summary: nothing is paraphrased, so nothing can be invented. Citation markers
like [1] are renumbered per notebook ([2.1] = notebook 2, citation 1) so they stay unambiguous in the combined text.

Every question uses a slice of your Google quota, so by default at most 10 notebooks are asked (`--limit`)."""
from __future__ import annotations

import asyncio
import html
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

from .backend import Backend
from .config import DEFAULT_LANGUAGE
from .models import QA, NotebookInfo
from .report import CSS

DEFAULT_LIMIT = 10
DEFAULT_CONCURRENCY = 3
DEFAULT_TIMEOUT_S = 180.0
MORNING_PREFIX = "ملخص صباحي"
ARABIC_SUFFIX = (
    "\n\nأجب بالعربية، واذكر المصدر لكل معلومة. إذا لم تجد في مصادر هذا الدفتر ما يجيب عن السؤال فقل ذلك صراحةً بجملة قصيرة."
)
_NO_ANSWER_HINTS = (
    "لا تحتوي", "لا توجد معلومات", "لا يوجد ما", "لم أجد", "لا تتضمن", "لا تذكر", "غير متوفرة في", "لا تتناول",
    "does not contain", "do not contain", "no information", "not mentioned", "doesn't contain", "don't contain",
)
EXIT_OK, EXIT_USAGE, EXIT_LOGIN, EXIT_FAILED = 0, 2, 3, 4


@dataclass
class Filters:
    match: List[str] = field(default_factory=list)  # keep notebooks whose title contains ANY of these (case-insensitive)
    exclude: List[str] = field(default_factory=list)  # drop notebooks whose title contains any of these
    ids: List[str] = field(default_factory=list)  # keep only these notebook ids
    morning_only: bool = False  # only the daily «ملخص صباحي ...» notebooks
    limit: int = DEFAULT_LIMIT  # newest first
    include_empty: bool = False  # notebooks with 0 sources are skipped by default


def select_notebooks(notebooks: Sequence[NotebookInfo], f: Filters) -> Tuple[List[NotebookInfo], List[Tuple[NotebookInfo, str]]]:
    """Returns (chosen, [(skipped notebook, reason)]). Input order (recent first) is kept."""
    chosen: List[NotebookInfo] = []
    skipped: List[Tuple[NotebookInfo, str]] = []
    for nb in notebooks:
        low = nb.title.lower()
        if f.ids and nb.id not in f.ids:
            continue
        if f.morning_only and not nb.title.replace("[عينة] ", "").startswith(MORNING_PREFIX):
            continue
        if f.match and not any(m.lower() in low for m in f.match):
            continue
        if any(x.lower() in low for x in f.exclude):
            skipped.append((nb, "مستبعد بـ --exclude"))
            continue
        if nb.sources_count == 0 and not f.include_empty:
            skipped.append((nb, "لا يحتوي مصادر"))
            continue
        if len(chosen) >= f.limit:
            skipped.append((nb, f"تجاوز الحد --limit {f.limit}"))
            continue
        chosen.append(nb)
    return chosen, skipped


def looks_unanswered(answer: str) -> bool:
    """Heuristic: a SHORT answer saying the sources do not cover the question. Long answers are always kept."""
    a = answer.strip()
    return len(a) < 400 and any(h in a.lower() for h in _NO_ANSWER_HINTS)


@dataclass
class NotebookAnswer:
    notebook: NotebookInfo
    answer: str = ""
    citations: List[dict] = field(default_factory=list)  # {number, source_title, text}
    error: Optional[str] = None
    no_answer: bool = False

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class AskAllResult:
    question: str
    mode: str  # real | sample
    created_at: str
    answers: List[NotebookAnswer] = field(default_factory=list)
    skipped: List[Tuple[str, str]] = field(default_factory=list)  # (notebook title, reason)
    total_notebooks: int = 0
    report_dir: str = ""

    @property
    def useful(self) -> List[NotebookAnswer]:
        return [a for a in self.answers if a.ok and not a.no_answer]

    def to_dict(self) -> dict:
        return asdict(self)


def _short_err(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:300]


async def ask_all(backend: Backend, question: str, flt: Optional[Filters] = None, *, concurrency: int = DEFAULT_CONCURRENCY,
                  timeout_s: float = DEFAULT_TIMEOUT_S, language: str = DEFAULT_LANGUAGE,
                  say: Callable[[str], None] = lambda _m: None) -> AskAllResult:
    """Must be called inside `async with backend`. A notebook that fails/times out is reported; the others still count."""
    flt = flt or Filters()
    notebooks = await backend.list_notebooks()
    chosen, skipped = select_notebooks(notebooks, flt)
    res = AskAllResult(question=question, mode=backend.mode, created_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
                       skipped=[(n.title, why) for n, why in skipped], total_notebooks=len(notebooks))
    say(f"عدد الدفاتر في حسابك: {len(notebooks)} — سأسأل {len(chosen)} منها. / asking {len(chosen)} notebook(s)")
    sem = asyncio.Semaphore(max(1, concurrency))
    q = question.strip() + ARABIC_SUFFIX

    async def one(nb: NotebookInfo) -> NotebookAnswer:
        async with sem:
            try:
                qa: QA = await asyncio.wait_for(backend.ask(nb.id, q, language), timeout_s)
            except asyncio.TimeoutError:
                return NotebookAnswer(nb, error=f"انتهت المهلة ({int(timeout_s)} ثانية)")
            except Exception as exc:  # one failing notebook must not lose the others
                return NotebookAnswer(nb, error=_short_err(exc))
            cites = [{"number": c.number, "source_title": c.source_title, "text": c.text} for c in qa.citations]
            ans = (qa.answer or "").strip()
            say(f"   ✔ {nb.title}")
            return NotebookAnswer(nb, answer=ans, citations=cites, no_answer=(not ans) or looks_unanswered(ans))

    res.answers = list(await asyncio.gather(*(one(nb) for nb in chosen)))
    return res


# ------------------------------------------------------------------ rendering
def renumber(answer: str, k: int) -> str:
    """[2] -> [k.2] so citation markers of different notebooks never collide."""
    return re.sub(r"\[(\d{1,3})\]", lambda m: f"[{k}.{m.group(1)}]", answer)


def _cite_line(k: int, c: dict) -> str:
    text = " ".join(str(c.get("text") or "").split())
    text = text[:200] + ("…" if len(text) > 200 else "")
    return f"[{k}.{c.get('number')}] {c.get('source_title')}" + (f" — «{text}»" if text else "")


def render_markdown(res: AskAllResult) -> str:
    L: List[str] = [f"# إجابة مجمّعة من دفاتر NotebookLM", "", f"**السؤال:** {res.question}", ""]
    if res.mode == "sample":
        L += ["> ⚠ وضع تجريبي: بيانات مثال وليست من NotebookLM.", ""]
    useful, ok_empty = res.useful, [a for a in res.answers if a.ok and a.no_answer]
    failed = [a for a in res.answers if not a.ok]
    L += [f"سُئل {len(res.answers)} دفتر من أصل {res.total_notebooks}: أجاب {len(useful)} بمعلومات، "
          f"{len(ok_empty)} بلا جواب مفيد، وفشل {len(failed)}.", ""]
    L += ["> هذا تجميع حرفي لإجابات NotebookLM كل دفتر على حدة (لم يُعَد تلخيصها). كل جزء منسوب إلى دفتره، "
          "ورقم الاستشهاد `[2.1]` = الدفتر 2 الاستشهاد 1.", ""]
    L += ["## الإجابة المجمّعة", ""]
    if not useful:
        L += ["لم يجب أي دفتر بمعلومات مفيدة عن هذا السؤال.", ""]
    for k, a in enumerate(res.answers, 1):
        if not a.ok or a.no_answer:
            continue
        L += [f"### {k}. من دفتر «{a.notebook.title}»", "", renumber(a.answer, k), ""]
        if a.citations:
            L += ["**المصادر:**"] + [f"- {_cite_line(k, c)}" for c in a.citations] + [""]
    if ok_empty or failed or res.skipped:
        L += ["## دفاتر لم تُفد", ""]
        for k, a in enumerate(res.answers, 1):
            if a.ok and a.no_answer:
                L.append(f"- {k}. «{a.notebook.title}» — لا تحتوي مصادره جوابًا عن السؤال")
            elif not a.ok:
                L.append(f"- {k}. «{a.notebook.title}» — فشل: {a.error}")
        L += [f"- «{t}» — لم يُسأل: {why}" for t, why in res.skipped]
        L.append("")
    L += [f"_أُنشئ في {res.created_at}. أداة غير رسمية مبنية فوق notebooklm-py، وغير مرتبطة بـ Google._", ""]
    return "\n".join(L)


def _h(x) -> str:
    return html.escape(str(x), quote=True)


def _para(text: str) -> str:
    return "<br>".join(_h(line) for line in text.splitlines())


def render_html(res: AskAllResult) -> str:
    useful, ok_empty = res.useful, [a for a in res.answers if a.ok and a.no_answer]
    failed = [a for a in res.answers if not a.ok]
    p: List[str] = ["<!doctype html><html lang='ar' dir='rtl'><head><meta charset='utf-8'>",
                    "<meta name='viewport' content='width=device-width, initial-scale=1'>",
                    f"<title>إجابة مجمّعة — NotebookLM Lab</title><style>{CSS}</style></head><body><div class='wrap'>",
                    "<h1>إجابة مجمّعة من دفاتر NotebookLM</h1>",
                    f"<div class='muted'>{_h(res.created_at)} · الوضع: <span class='badge'>{'تجريبي (Sample)' if res.mode == 'sample' else 'حقيقي (NotebookLM)'}</span></div>"]
    if res.mode == "sample":
        p.append("<div class='banner'>⚠ وضع تجريبي: بيانات مثال وليست من NotebookLM.</div>")
    p.append(f"<div class='card'><b>السؤال:</b> {_para(res.question)}</div>")
    p.append(f"<div class='card'>سُئل {len(res.answers)} دفتر من أصل {res.total_notebooks}: أجاب <b>{len(useful)}</b> بمعلومات، "
             f"{len(ok_empty)} بلا جواب مفيد، وفشل {len(failed)}.<div class='muted'>تجميع حرفي لإجابات NotebookLM لكل دفتر (لم يُعَد تلخيصها). "
             "رقم الاستشهاد [2.1] = الدفتر 2، الاستشهاد 1.</div></div><h2>الإجابة المجمّعة</h2>")
    if not useful:
        p.append("<div class='card muted'>لم يجب أي دفتر بمعلومات مفيدة عن هذا السؤال.</div>")
    for k, a in enumerate(res.answers, 1):
        if not a.ok or a.no_answer:
            continue
        p.append(f"<div class='card'><b>{k}. من دفتر «{_h(a.notebook.title)}»</b><p>{_para(renumber(a.answer, k))}</p>")
        for c in a.citations:
            p.append(f"<div class='cite'>{_h(_cite_line(k, c))}</div>")
        p.append("</div>")
    if ok_empty or failed or res.skipped:
        p.append("<h2>دفاتر لم تُفد</h2><div class='card'><ul>")
        for k, a in enumerate(res.answers, 1):
            if a.ok and a.no_answer:
                p.append(f"<li>{k}. «{_h(a.notebook.title)}» — لا تحتوي مصادره جوابًا عن السؤال</li>")
            elif not a.ok:
                p.append(f"<li>{k}. «{_h(a.notebook.title)}» — <span class='bad'>فشل: {_h(a.error)}</span></li>")
        p += [f"<li>«{_h(t)}» — لم يُسأل: {_h(why)}</li>" for t, why in res.skipped]
        p.append("</ul></div>")
    p.append("<div class='muted'>أداة غير رسمية مبنية فوق notebooklm-py، وغير مرتبطة بـ Google.</div></div></body></html>")
    return "".join(p)


def _slug(text: str) -> str:
    s = re.sub(r"[^A-Za-z0-9\u0621-\u064A]+", "-", text).strip("-")
    return s[:30] or "q"


def save_report(res: AskAllResult, root: Path, now: Optional[datetime] = None) -> Path:
    """root/<timestamp>-<question>/report.md|report.html|answer.json (a new folder each time; nothing is overwritten)."""
    now = now or datetime.now()
    base = f"{now:%Y%m%d-%H%M%S}-{_slug(res.question)}"
    d, n = root / base, 1
    while d.exists():
        n += 1
        d = root / f"{base}-{n}"
    d.mkdir(parents=True)
    res.report_dir = str(d)
    (d / "report.md").write_text(render_markdown(res), encoding="utf-8")
    (d / "report.html").write_text(render_html(res), encoding="utf-8")
    (d / "answer.json").write_text(json.dumps(res.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return d


def exit_code(res: AskAllResult) -> int:
    if not res.answers:
        return EXIT_USAGE  # nothing matched the filters
    return EXIT_OK if any(a.ok for a in res.answers) else EXIT_FAILED


# ------------------------------------------------------------------ one entry point for the CLI and the MCP tool
def reports_root(base: Optional[Path] = None, sample: bool = False) -> Path:
    from .config import data_dir

    return (Path(base).expanduser().resolve() if base else data_dir()) / ("ask-sample" if sample else "ask")


def looks_like_auth_problem(exc: BaseException) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return any(w in text for w in ("auth", "login", "sign in", "sign-in", "expired", "401", "403", "cookie", "csrf"))


async def run_ask_all(backend: Backend, question: str, flt: Optional[Filters], root: Path, *, timeout_s: float = DEFAULT_TIMEOUT_S,
                      say: Callable[[str], None] = lambda _m: None) -> AskAllResult:
    """Open the backend, ask, save the report. Raises LoginRequiredError (no login) or whatever listing notebooks raised."""
    async with backend:
        res = await ask_all(backend, question, flt, timeout_s=timeout_s, say=say)
    if res.answers:  # only keep a report when something was actually asked
        save_report(res, root)
    return res
