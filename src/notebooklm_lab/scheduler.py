"""Daily scheduling of `morning`: Windows Task Scheduler (schtasks) for the user's PC,
cron for a Linux VPS. By default we only PRINT the exact command; `--install` runs it.

Pure functions build the commands (easy to test); install/remove take a `runner` so tests
never touch the real scheduler."""
from __future__ import annotations

import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

TASK_NAME = "NotebookLM-Lab Morning"
CRON_MARK = "# notebooklm-lab-morning"

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


class ScheduleError(ValueError):
    pass


def parse_time(value: str) -> Tuple[int, int]:
    m = re.fullmatch(r"\s*([01]?\d|2[0-3]):([0-5]\d)\s*", value or "")
    if not m:
        raise ScheduleError(f"الوقت يجب أن يكون بصيغة HH:MM بنظام 24 ساعة، مثل 07:30 / time must be HH:MM (24h), got {value!r}")
    return int(m.group(1)), int(m.group(2))


def default_target() -> str:
    return "windows" if sys.platform.startswith("win") else "cron"


def morning_command(python: str, data_dir: Optional[Path] = None) -> List[str]:
    cmd = [python, "-m", "notebooklm_lab", "morning"]
    if data_dir is not None:
        cmd += ["--data-dir", str(data_dir)]
    return cmd


# ------------------------------------------------------------------ Windows
def windows_create_argv(time: str, python: str, data_dir: Optional[Path] = None) -> List[str]:
    h, m = parse_time(time)
    # the program path and data folder are always quoted: Windows user names/paths often contain spaces
    tr = f'"{python}" -m notebooklm_lab morning' + (f' --data-dir "{data_dir}"' if data_dir is not None else "")
    return ["schtasks", "/Create", "/SC", "DAILY", "/TN", TASK_NAME, "/TR", tr, "/ST", f"{h:02d}:{m:02d}", "/F"]


def windows_delete_argv() -> List[str]:
    return ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"]


def windows_query_argv() -> List[str]:
    return ["schtasks", "/Query", "/TN", TASK_NAME]


# ------------------------------------------------------------------ cron
def cron_line(time: str, python: str, data_dir: Path) -> str:
    h, m = parse_time(time)
    cmd = " ".join(shlex.quote(a) for a in morning_command(python, data_dir))
    log = shlex.quote(str(data_dir / "morning.cron.log"))
    return f"{m} {h} * * * {cmd} >> {log} 2>&1 {CRON_MARK}"


def cron_strip(crontab_text: str) -> str:
    """Remove our line(s); keep everything else untouched."""
    kept = [ln for ln in crontab_text.splitlines() if CRON_MARK not in ln]
    return ("\n".join(kept) + "\n") if kept else ""


def cron_add(crontab_text: str, line: str) -> str:
    base = cron_strip(crontab_text)
    return base + line + "\n"


# ------------------------------------------------------------------ describe / install / remove
def _cron_read(runner: Runner) -> str:
    p = runner(["crontab", "-l"], capture_output=True, text=True)
    if p.returncode != 0:
        if "no crontab" in (p.stderr or "").lower():
            return ""
        raise ScheduleError(f"crontab -l failed: {(p.stderr or '').strip()}")
    return p.stdout


def _cron_write(runner: Runner, text: str) -> None:
    p = runner(["crontab", "-"], input=text, capture_output=True, text=True)
    if p.returncode != 0:
        raise ScheduleError(f"crontab install failed: {(p.stderr or '').strip()}")


def describe(target: str, time: str, python: str, data_dir: Path) -> str:
    if target == "windows":
        argv = windows_create_argv(time, python, data_dir)
        return ("أمر Windows (يعمل في PowerShell أو CMD) / Windows command:\n  " + subprocess.list2cmdline(argv)
                + "\n\nللتثبيت تلقائيًا أضف --install · للإلغاء: python -m notebooklm_lab morning unschedule --target windows")
    line = cron_line(time, python, data_dir)
    return ("سطر cron لخادم لينكس / Linux cron line:\n  " + line
            + "\n\nللتثبيت تلقائيًا أضف --install · للإلغاء: python -m notebooklm_lab morning unschedule --target cron")


def install(target: str, time: str, python: str, data_dir: Path, runner: Runner = subprocess.run) -> str:
    if target == "windows":
        p = runner(windows_create_argv(time, python, data_dir), capture_output=True, text=True)
        if p.returncode != 0:
            raise ScheduleError(f"schtasks failed ({p.returncode}): {(p.stderr or p.stdout or '').strip()}")
        return f"✔ تم إنشاء المهمة اليومية «{TASK_NAME}» الساعة {time}. / scheduled daily at {time}."
    try:
        current = _cron_read(runner)
    except FileNotFoundError:
        raise ScheduleError("الأمر crontab غير مثبت على هذا الجهاز / `crontab` is not installed here (Linux: sudo apt install cron)") from None
    _cron_write(runner, cron_add(current, cron_line(time, python, data_dir)))
    return f"✔ تمت إضافة مهمة cron يوميًا الساعة {time}. / cron job installed for {time} daily. (تحقق: crontab -l)"


def remove(target: str, runner: Runner = subprocess.run) -> str:
    if target == "windows":
        p = runner(windows_delete_argv(), capture_output=True, text=True)
        if p.returncode != 0:
            msg = (p.stderr or p.stdout or "").strip()
            if "cannot find" in msg.lower() or "does not exist" in msg.lower() or "لا يمكن" in msg:
                return "لا توجد مهمة مجدولة لإزالتها. / no scheduled task to remove."
            raise ScheduleError(f"schtasks failed ({p.returncode}): {msg}")
        return f"✔ تم حذف المهمة «{TASK_NAME}». / task removed."
    try:
        current = _cron_read(runner)
    except FileNotFoundError:
        raise ScheduleError("الأمر crontab غير مثبت / `crontab` is not installed") from None
    if CRON_MARK not in current:
        return "لا توجد مهمة cron لإزالتها. / no cron job to remove."
    _cron_write(runner, cron_strip(current))
    return "✔ تمت إزالة مهمة cron. / cron job removed."
