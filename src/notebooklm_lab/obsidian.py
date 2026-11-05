"""Save a morning result into an Obsidian vault as plain files - no Obsidian plugin, no Obsidian running.

* the Arabic summary becomes ONE Markdown note with YAML frontmatter (date, sources, notebook, tags ...);
* the podcast file is copied next to it and embedded with `![[...]]` (Obsidian plays it inline);
* nothing that already exists is ever overwritten or modified - an existing note is skipped, an audio file
  with a taken name gets a numbered name. Notes are created with exclusive-create, so even a race cannot overwrite.

Settings (env or the local settings file): OBSIDIAN_VAULT (required, the vault folder must already exist),
OBSIDIAN_SUBFOLDER (default `NotebookLM`), NOTEBOOKLM_LAB_OBSIDIAN_AUTO=1 for automatic saving after `morning`."""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from . import settings
from .deliver import Deliverable

DEFAULT_SUBFOLDER = "NotebookLM"
AUDIO_DIR = "audio"
TAGS = ["notebooklm", "morning-digest"]
EXIT_OBSIDIAN = 6
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class ObsidianError(RuntimeError):
    pass


@dataclass
class Target:
    vault: Path
    subfolder: str

    @property
    def folder(self) -> Path:
        return self.vault / self.subfolder


def safe_name(text: str, fallback: str = "note") -> str:
    """A file name that is valid on Windows, macOS and Linux."""
    name = _BAD_CHARS.sub("-", text).strip(" .-") or fallback
    return name[:120].rstrip(" .")


def resolve_target(base: Optional[Path] = None, vault: Optional[str] = None, subfolder: Optional[str] = None) -> Target:
    v = vault or settings.get("OBSIDIAN_VAULT", base)
    if not v:
        raise ObsidianError("OBSIDIAN_VAULT غير مضبوط: ضع مسار مجلد الـ vault في متغير البيئة أو في ملف الإعدادات (python -m notebooklm_lab config init).")
    root = Path(v).expanduser()
    if not root.is_dir():
        raise ObsidianError(f"مجلد الـ vault غير موجود: {root} — افتح Obsidian وأنشئ vault أولًا أو صحّح المسار (لن أنشئ vault جديدًا بالخطأ).")
    sub = (subfolder or settings.get("OBSIDIAN_SUBFOLDER", base) or DEFAULT_SUBFOLDER).strip().strip("/\\")
    parts = [p for p in re.split(r"[\\/]+", sub) if p]
    if not parts or any(p in (".", "..") or _BAD_CHARS.search(p) for p in parts) or re.match(r"^[A-Za-z]:", sub):
        raise ObsidianError(f"اسم المجلد الفرعي غير صالح: {sub!r} (استخدم اسمًا بسيطًا مثل NotebookLM أو مسارًا نسبيًا داخل الـ vault).")
    return Target(root.resolve(), "/".join(parts))


def _yaml_str(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)  # a JSON string is a valid YAML double-quoted scalar


def render_note(d: Deliverable, audio_rel: Optional[str], audio_note: str = "") -> str:
    tags = TAGS + (["sample"] if d.is_sample else [])
    fm = ["---", f"date: {d.day}", f"title: {_yaml_str(d.title)}", f"notebook: {_yaml_str(d.title)}"]
    if d.notebook_id:
        fm.append(f"notebook_id: {_yaml_str(d.notebook_id)}")
    fm.append("sources:" if d.sources else "sources: []")
    fm += [f"  - {_yaml_str(s)}" for s in d.sources]
    fm.append(f"mode: {d.mode}")
    if audio_rel:
        fm.append(f"audio: {_yaml_str(audio_rel)}")
    fm.append("tags:")
    fm += [f"  - {t}" for t in tags]
    fm += ["source_tool: notebooklm-lab", "---", ""]
    body: List[str] = [f"# {d.title}", ""]
    if d.is_sample:
        body += ["> ⚠ وضع تجريبي: بيانات مثال وليست من NotebookLM.", ""]
    if audio_rel:
        body += ["## 🎧 البودكاست", "", f"![[{audio_rel}]]", ""]
    elif audio_note:
        body += ["## 🎧 البودكاست", "", audio_note, ""]
    body += ["## الملخص", "", d.summary_md.strip() or "(لا يوجد ملخص مكتوب في هذا التشغيل)", ""]
    if d.sources:
        body += ["## المصادر", ""] + [f"- {s}" for s in d.sources] + [""]
    return "\n".join(fm + body)


@dataclass
class SaveReport:
    status: str  # saved | exists | failed
    note: Optional[Path] = None
    audio: Optional[Path] = None
    messages: List[str] = field(default_factory=list)
    error: Optional[str] = None

    def summary(self) -> str:
        if self.status == "saved":
            return f"✔ Obsidian: حُفظت الملاحظة {self.note}" + (f" + الصوت {self.audio}" if self.audio else "") + ("".join(f"\n   {m}" for m in self.messages))
        if self.status == "exists":
            return f"ℹ Obsidian: الملاحظة موجودة مسبقًا فلم ألمسها (لا أستبدل تعديلاتك): {self.note}"
        return f"✘ Obsidian: {self.error}"


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    n = 2
    while True:
        cand = path.with_name(f"{path.stem} ({n}){path.suffix}")
        if not cand.exists():
            return cand
        n += 1


def save_deliverable(d: Deliverable, target: Target, copy_audio: bool = True) -> SaveReport:
    """Write the note (and copy the audio). Never overwrites, never raises (errors come back in the report)."""
    try:
        folder = target.folder
        note_path = folder / f"{safe_name(d.title)}.md"
        if note_path.exists():
            return SaveReport("exists", note=note_path)
        if target.vault not in folder.resolve().parents:  # e.g. a symlinked sub-folder pointing elsewhere
            raise ObsidianError("المجلد الفرعي يخرج من الـ vault")
        folder.mkdir(parents=True, exist_ok=True)
        rep = SaveReport("saved", note=note_path)
        audio_rel, audio_note = None, ""
        if d.audio_path and d.audio_path.is_file():
            if copy_audio:
                adir = folder / AUDIO_DIR
                adir.mkdir(exist_ok=True)
                dest = _unique(adir / f"{safe_name(d.title)}{d.audio_path.suffix.lower()}")
                shutil.copy2(d.audio_path, dest)
                rep.audio = dest
                audio_rel = dest.relative_to(target.vault).as_posix()
            else:
                audio_note = f"[{d.audio_path.name}]({d.audio_path.resolve().as_uri()})"
                rep.messages.append("الصوت لم يُنسخ إلى الـ vault؛ الملاحظة تحتوي رابطًا للملف الأصلي.")
        text = render_note(d, audio_rel, audio_note)
        try:
            with open(note_path, "x", encoding="utf-8", newline="\n") as f:  # exclusive create: cannot overwrite
                f.write(text)
        except FileExistsError:
            if rep.audio:
                rep.audio.unlink(missing_ok=True)
            return SaveReport("exists", note=note_path)
        return rep
    except ObsidianError as exc:
        return SaveReport("failed", error=str(exc))
    except OSError as exc:
        return SaveReport("failed", error=f"تعذّرت الكتابة في الـ vault: {type(exc).__name__}: {exc}")


def deliver_safely(d: Optional[Deliverable], base: Optional[Path], say: Callable[[str], None]) -> Dict[str, str]:
    """Used by `morning`: never raises and never changes the exit code."""
    if d is None:
        return {"status": "skipped"}
    try:
        target = resolve_target(base)
    except ObsidianError as exc:
        say(f"⚠ Obsidian مفعّل لكن: {exc} (تخطّيتُ الحفظ؛ الملخص سليم). جرّب: python -m notebooklm_lab obsidian setup-check")
        return {"status": "not_configured", "error": str(exc)[:200]}
    rep = save_deliverable(d, target)
    say(rep.summary())
    out = {"status": rep.status}
    if rep.note:
        out["note"] = str(rep.note)
    if rep.error:
        out["error"] = rep.error[:200]
    return out


def setup_check(base: Optional[Path] = None, vault: Optional[str] = None, subfolder: Optional[str] = None,
                say: Callable[[str], None] = print) -> int:
    try:
        t = resolve_target(base, vault, subfolder)
    except ObsidianError as exc:
        say(f"✘ {exc}")
        return 2
    say(f"✔ الـ vault موجود: {t.vault}")
    say(f"  المجلد الفرعي للحفظ: {t.folder}  {'(موجود)' if t.folder.is_dir() else '(سيُنشأ عند أول حفظ)'}")
    probe_dir = t.folder if t.folder.is_dir() else t.vault
    probe = probe_dir / ".notebooklm-lab-write-test"
    try:
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        say(f"✘ لا أستطيع الكتابة داخل المجلد: {exc}")
        return EXIT_OBSIDIAN
    say("✔ الكتابة ممكنة. لن أستبدل أي ملاحظة موجودة.")
    say(f"الحفظ التلقائي بعد morning: {'مفعّل' if settings.flag('NOTEBOOKLM_LAB_OBSIDIAN_AUTO', base) else 'غير مفعّل (فعّله بـ NOTEBOOKLM_LAB_OBSIDIAN_AUTO=1 أو morning --obsidian)'}")
    return 0
