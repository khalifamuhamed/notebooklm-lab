"""Render the Arabic right-to-left HTML report. Self-contained (inline CSS, no
external requests). Every dynamic value is HTML-escaped. Paths are RELATIVE to
the report so the whole run folder can be moved or zipped."""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, List

from .models import RunResult
from .sample_backend import SAMPLE_BANNER_AR, SAMPLE_BANNER_EN
from .storage import human_size

KIND_LABELS = {
    "briefing": "وثيقة موجزة (Briefing Doc)",
    "study_guide": "دليل دراسة (Study Guide)",
    "mind_map": "خريطة ذهنية (Mind Map)",
    "audio": "نظرة صوتية عامة / بودكاست (Audio Overview)",
    "quiz": "اختبار (Quiz)",
    "flashcards": "بطاقات تعليمية (Flashcards)",
    "slide_deck": "عرض شرائح (Slide Deck)",
}
SOURCE_LABELS = {"url": "رابط ويب", "youtube": "يوتيوب", "file": "ملف محلي"}

CSS = """
body{font-family:'Segoe UI',Tahoma,'Noto Naskh Arabic',Arial,sans-serif;background:#f5f6fa;color:#1d2433;margin:0;line-height:1.9}
.wrap{max-width:900px;margin:0 auto;padding:24px}
h1{margin:0 0 4px;font-size:28px}h2{border-bottom:2px solid #dde1ee;padding-bottom:6px;margin-top:32px}
.card{background:#fff;border-radius:12px;padding:16px 20px;margin:12px 0;box-shadow:0 1px 4px rgba(0,0,0,.08)}
.banner{background:#fff3cd;border:2px solid #e0a800;border-radius:10px;padding:12px 16px;font-weight:bold}
.badge{display:inline-block;padding:2px 10px;border-radius:99px;font-size:13px;background:#e8eaf6}
.ok{color:#1b7f3b}.bad{color:#b3261e}.muted{color:#667}
.cite{font-size:14px;color:#445;border-right:3px solid #c5cae9;padding-right:10px;margin:6px 0}
table{border-collapse:collapse;width:100%}td,th{padding:6px 8px;border-bottom:1px solid #eee;text-align:right}
code,pre{direction:ltr;text-align:left;background:#f0f1f6;border-radius:6px;padding:2px 6px}
pre{padding:10px;white-space:pre-wrap;max-height:320px;overflow:auto}
details{margin-top:8px}ul.tree{margin:0;padding-right:20px}
.en{direction:ltr;text-align:left;color:#556;font-size:14px}
"""


def _e(x: Any) -> str:
    return html.escape(str(x), quote=True)


def _tree(node: Any) -> str:
    if isinstance(node, dict):
        name = node.get("name") or node.get("title") or node.get("label") or ""
        kids = node.get("children") or []
        inner = "".join(f"<li>{_tree(k)}</li>" for k in kids) if isinstance(kids, list) else ""
        return _e(name) + (f"<ul class='tree'>{inner}</ul>" if inner else "")
    return _e(node)


def _preview(run_dir: Path, rel: str, kind: str) -> str:
    p = run_dir / rel
    try:
        if kind == "mind_map":
            data = json.loads(p.read_text(encoding="utf-8"))
            return f"<details open><summary>عرض الخريطة</summary><ul class='tree'><li>{_tree(data)}</li></ul></details>"
        if p.suffix.lower() in (".md", ".txt"):
            text = p.read_text(encoding="utf-8")
            more = "\n…" if len(text) > 4000 else ""
            return f"<details><summary>معاينة النص</summary><pre>{_e(text[:4000])}{more}</pre></details>"
    except Exception:
        return ""
    return ""


def render_report(result: RunResult, run_dir: Path) -> str:
    sample = result.mode == "sample"
    parts: List[str] = []
    a = parts.append
    a("<!doctype html><html lang='ar' dir='rtl'><head><meta charset='utf-8'>")
    a("<meta name='viewport' content='width=device-width, initial-scale=1'>")
    a(f"<title>{_e(result.title)} — تقرير NotebookLM Lab</title><style>{CSS}</style></head><body><div class='wrap'>")
    a(f"<h1>{_e(result.title)}</h1>")
    a(
        f"<div class='muted'>تاريخ الإنشاء: {_e(result.created_at)} · اللغة: <code>{_e(result.language)}</code> · "
        f"الوضع: <span class='badge'>{'تجريبي (Sample)' if sample else 'حقيقي (NotebookLM)'}</span></div>"
    )
    if sample:
        a(f"<div class='banner'>{_e(SAMPLE_BANNER_AR)}<div class='en'>{_e(SAMPLE_BANNER_EN)}</div></div>")
    a("<div class='card'>تقرير تلخيصي لما أُنشئ. أداة غير رسمية مبنية فوق مكتبة notebooklm-py، وليست مرتبطة بـ Google.")
    a("<div class='en'>Unofficial tool built on notebooklm-py; not affiliated with Google.</div></div>")

    ok_out = [o for o in result.outputs if o.ok]
    a("<h2>ملخص سريع</h2><div class='card'><table>")
    a(f"<tr><td>عدد المصادر</td><td>{sum(1 for s in result.sources if s.status == 'ready')} / {len(result.sources)}</td></tr>")
    a(f"<tr><td>أسئلة مُجابة</td><td>{len(result.qa)}</td></tr>")
    a(f"<tr><td>مخرجات ناجحة</td><td>{len(ok_out)} / {len(result.outputs)}</td></tr>")
    a(f"<tr><td>مجلد التشغيل</td><td><code>{_e(Path(result.run_dir).name or '.')}</code></td></tr>")
    a(f"<tr><td>المكتبة</td><td><code>{_e(result.library_version)}</code></td></tr></table></div>")

    if result.warnings:
        a("<h2>تنبيهات</h2><div class='card'><ul>" + "".join(f"<li>{_e(w)}</li>" for w in result.warnings) + "</ul></div>")

    a("<h2>المصادر</h2><div class='card'><table><tr><th>#</th><th>العنوان</th><th>النوع</th><th>الحالة</th></tr>")
    for i, s in enumerate(result.sources, 1):
        state = "<span class='ok'>جاهز</span>" if s.status == "ready" else f"<span class='bad'>فشل: {_e(s.error or '')}</span>"
        link = f"<br><code>{_e(s.value)}</code>" if s.kind != "file" else f"<br><code>{_e(Path(s.value).name)}</code>"
        a(f"<tr><td>{i}</td><td>{_e(s.title)}{link}</td><td>{_e(SOURCE_LABELS.get(s.kind, s.kind))}</td><td>{state}</td></tr>")
    a("</table></div>")

    a("<h2>أسئلة وأجوبة مع الاستشهادات</h2>")
    for qa in result.qa:
        a(f"<div class='card'><b>س: {_e(qa.question)}</b><p>{_e(qa.answer)}</p>")
        for c in qa.citations:
            a(f"<div class='cite'>[{c.number}] <b>{_e(c.source_title)}</b><br>{_e(c.text)}</div>")
        a("</div>")
    if not result.qa:
        a("<div class='card muted'>لا توجد أسئلة.</div>")

    a("<h2>المخرجات والتنزيلات</h2>")
    for o in result.outputs:
        label = KIND_LABELS.get(o.kind, o.kind)
        if o.ok and o.path:
            href = _e(o.path)
            extra = f"<audio controls src='{href}'></audio>" if o.kind == "audio" and o.path.endswith((".wav", ".m4a", ".mp3")) else ""
            note = f"<div class='muted'>{_e(o.note)}</div>" if o.note else ""
            a(
                f"<div class='card'><b>{_e(label)}</b> <span class='ok'>✔</span><br>"
                f"<a href='{href}'>{_e(o.path)}</a> <span class='muted'>({human_size(o.size_bytes)})</span>{note}{extra}"
                f"{_preview(run_dir, o.path, o.kind)}</div>"
            )
        else:
            a(f"<div class='card'><b>{_e(label)}</b> <span class='bad'>✘ لم يُنشأ</span><div class='muted'>{_e(o.error or '')}</div></div>")

    a("<h2>أين تُحفظ الملفات؟</h2><div class='card'>كل شيء داخل مجلد هذا التشغيل (روابط نسبية). لحذفه: "
      "<code>python -m notebooklm_lab outputs delete --run &lt;اسم المجلد&gt; --yes</code></div>")
    a("</div></body></html>")
    return "".join(parts)
