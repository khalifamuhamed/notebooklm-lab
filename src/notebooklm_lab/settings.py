"""Settings and credentials: environment variables first, then a local, git-ignored
`notebooklm-lab.env` file in the data folder (simple KEY=VALUE lines, # for comments).

No secret is ever stored in the repository. `python -m notebooklm_lab config init` creates the local file with
EMPTY values; `config show` prints values masked. Nothing here needs a third-party package."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional

from .config import data_dir

ENV_FILE_NAME = "notebooklm-lab.env"
ENV_FILE_OVERRIDE = "NOTEBOOKLM_LAB_ENV_FILE"

#: name -> (is secret, Arabic description). Names only - there are no default values for secrets.
KNOWN: Dict[str, "tuple[bool, str]"] = {
    "TELEGRAM_BOT_TOKEN": (True, "توكن بوت تيليجرام من @BotFather"),
    "TELEGRAM_CHAT_ID": (False, "رقم المحادثة التي ستصلها الرسائل"),
    "NOTEBOOKLM_LAB_TELEGRAM_AUTO": (False, "1 = أرسل نتيجة `morning` إلى تيليجرام تلقائيًا"),
}

TEMPLATE_HEADER = """\
# notebooklm-lab: إعداداتك الخاصة (هذا الملف يبقى على جهازك — لا ترفعه إلى GitHub ولا ترسله لأحد).
# اكتب القيمة بعد علامة = بدون مسافات وبدون علامات اقتباس. الأسطر التي تبدأ بـ # ملاحظات.
# Your private settings. Keep this file on your PC only. Real environment variables override this file.
"""


def candidate_files(base: Optional[Path] = None) -> List[Path]:
    override = os.environ.get(ENV_FILE_OVERRIDE)
    if override:
        return [Path(override).expanduser()]
    root = Path(base).expanduser() if base else data_dir()
    return [root / ENV_FILE_NAME, root / ".env"]


def parse_env_text(text: str) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for raw in text.lstrip("\ufeff").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.lower().startswith("export "):
            line = line[7:].lstrip()
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        elif " #" in val:
            val = val.split(" #", 1)[0].rstrip()
        if key:
            values[key] = val
    return values


def file_values(base: Optional[Path] = None) -> Dict[str, str]:
    """Values from the first existing local settings file (a missing/unreadable file is simply empty)."""
    for p in candidate_files(base):
        try:
            if p.is_file():
                return parse_env_text(p.read_text(encoding="utf-8-sig"))
        except OSError:
            continue
    return {}


def get(name: str, base: Optional[Path] = None, default: str = "") -> str:
    env = os.environ.get(name)
    if env is not None and env.strip():
        return env.strip()
    return file_values(base).get(name, "").strip() or default


def flag(name: str, base: Optional[Path] = None) -> bool:
    return get(name, base).lower() in ("1", "true", "yes", "on", "y")


def mask(value: str) -> str:
    if not value:
        return "(غير مضبوط / not set)"
    return f"••••••({len(value)} chars)"


def init_file(base: Optional[Path] = None) -> "tuple[Path, bool]":
    """Create the local settings file with empty values if missing. Returns (path, created)."""
    path = candidate_files(base)[0]
    if path.exists():
        return path, False
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [TEMPLATE_HEADER]
    for name, (_secret, desc) in KNOWN.items():
        lines.append(f"# {desc}\n{name}=\n")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path, True


def describe(base: Optional[Path] = None) -> str:
    files = candidate_files(base)
    found = next((p for p in files if p.is_file()), None)
    lines = [f"ملف الإعدادات / settings file: {found or files[0]}  {'(موجود)' if found else '(غير موجود — أنشئه بـ: python -m notebooklm_lab config init)'}", ""]
    fv = file_values(base)
    for name, (secret, desc) in KNOWN.items():
        env_set = bool(os.environ.get(name, "").strip())
        val = get(name, base)
        shown = mask(val) if secret else (val or "(غير مضبوط / not set)")
        src = "متغير بيئة" if env_set else ("الملف" if fv.get(name) else "-")
        lines.append(f"  {name:<30} {shown:<24} [{src}]  {desc}")
    return "\n".join(lines)
