"""Helpers that tell the user (in Arabic + English) WHERE the login session and
the generated outputs are stored, HOW BIG they are, and how to delete them.

Safety rules: this module never reads or prints the CONTENTS of the login file;
it only checks that it exists and how big it is. Deleting is only done inside the
known NotebookLM home folder / the lab's own outputs folder."""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import List, Optional, Tuple

LOGIN_HINT = (
    "لم يتم العثور على جلسة تسجيل دخول. شغّل مرة واحدة:  notebooklm login\n"
    "No saved login found. Run once on your own computer:  notebooklm login"
)


def human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"


def path_size(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    total = 0
    if p.is_dir():
        for root, _dirs, files in os.walk(p):
            for f in files:
                try:
                    total += (Path(root) / f).stat().st_size
                except OSError:
                    pass
    return total


# ---------------------------------------------------------------- session
def notebooklm_home() -> Path:
    """Same rule notebooklm-py uses: $NOTEBOOKLM_HOME or ~/.notebooklm."""
    env = os.environ.get("NOTEBOOKLM_HOME")
    return (Path(env).expanduser() if env else Path.home() / ".notebooklm").resolve()


def profile_name(profile: Optional[str] = None) -> str:
    return profile or os.environ.get("NOTEBOOKLM_PROFILE") or "default"


def profile_dir(profile: Optional[str] = None) -> Path:
    return notebooklm_home() / "profiles" / profile_name(profile)


def session_items(profile: Optional[str] = None) -> List[Tuple[str, Path]]:
    d = profile_dir(profile)
    return [
        ("login cookies / ملف جلسة الدخول", d / "storage_state.json"),
        ("browser profile / ملف المتصفح", d / "browser_profile"),
        ("master token (optional) / رمز اختياري", d / "master_token.json"),
    ]


def has_session(profile: Optional[str] = None, storage_path: Optional[str] = None) -> bool:
    if os.environ.get("NOTEBOOKLM_AUTH_JSON"):
        return True
    if storage_path:
        return Path(storage_path).expanduser().is_file()
    if (profile_dir(profile) / "storage_state.json").is_file():
        return True
    return (notebooklm_home() / "storage_state.json").is_file()  # legacy location


def session_report(profile: Optional[str] = None) -> str:
    lines = [
        f"مجلد NotebookLM / NotebookLM folder : {notebooklm_home()}",
        f"الملف الشخصي / profile              : {profile_name(profile)}",
        "",
    ]
    found = False
    for label, p in session_items(profile):
        if p.exists():
            found = True
            lines.append(f"  ✔ {label}\n      {p}\n      الحجم / size: {human_size(path_size(p))}")
        else:
            lines.append(f"  ✘ {label}: غير موجود / not found")
    lines.append("")
    lines.append(
        "حالة الدخول / login: " + ("موجودة (جلسة محفوظة على جهازك فقط) / a session is saved on THIS computer only"
                                  if found else "غير مسجّل / not logged in")
    )
    lines.append("للحذف / to delete:  python -m notebooklm_lab session delete --yes")
    lines.append("تحذير: هذه الملفات تعادل تسجيل الدخول لحسابك — لا ترسلها ولا ترفعها لأي مكان. "
                 "/ These files act like your Google login: never share or upload them.")
    return "\n".join(lines)


def delete_session(profile: Optional[str] = None, yes: bool = False) -> str:
    home = notebooklm_home()
    targets = [p for _l, p in session_items(profile) if p.exists()]
    if not targets:
        return "لا يوجد شيء للحذف / nothing to delete."
    if not yes:
        return "سيتم حذف / would delete:\n" + "\n".join(f"  {t}" for t in targets) + "\nأعد الأمر مع --yes للتأكيد / re-run with --yes to confirm."
    for t in targets:
        if home not in t.resolve().parents:  # hard safety check
            raise RuntimeError(f"refusing to delete outside {home}: {t}")
        shutil.rmtree(t) if t.is_dir() else t.unlink()
    return (
        "تم حذف جلسة الدخول المحلية / local login session deleted.\n"
        "ملاحظة: هذا يحذف النسخة على جهازك فقط. لإبطال الجلسة من جهة Google أيضًا، "
        "افتح https://myaccount.google.com/device-activity وسجّل الخروج من الأجهزة.\n"
        "Note: this removes the local copy only; to also revoke it on Google's side, sign out of devices at the page above."
    )


# ---------------------------------------------------------------- outputs
def list_runs(root: Path) -> List[Path]:
    if not root.is_dir():
        return []
    return sorted([d for d in root.iterdir() if d.is_dir() and (d / "run.json").is_file()])


def outputs_report(root: Path) -> str:
    runs = list_runs(root)
    total = sum(path_size(r) for r in runs)
    lines = [f"مجلد المخرجات / outputs folder: {root}", f"عدد التشغيلات / runs: {len(runs)}   الحجم الكلي / total size: {human_size(total)}", ""]
    for r in runs:
        lines.append(f"  • {r.name}   ({human_size(path_size(r))})   →  {r / 'report.html'}")
    if not runs:
        lines.append("  (لا شيء بعد / nothing yet)")
    lines += ["", "للعرض / to view:  python -m notebooklm_lab outputs open", "للحذف / to delete:  python -m notebooklm_lab outputs delete --all --yes"]
    return "\n".join(lines)


def delete_outputs(root: Path, run: Optional[str] = None, all_runs: bool = False, yes: bool = False) -> str:
    runs = list_runs(root)
    if run:
        runs = [r for r in runs if r.name == run]
    elif not all_runs:
        return "حدد --run NAME أو --all / specify --run NAME or --all"
    if not runs:
        return "لا يوجد شيء للحذف / nothing to delete."
    if not yes:
        return "سيتم حذف / would delete:\n" + "\n".join(f"  {r}  ({human_size(path_size(r))})" for r in runs) + "\nأعد الأمر مع --yes / re-run with --yes"
    for r in runs:
        if root.resolve() not in r.resolve().parents:
            raise RuntimeError(f"refusing to delete outside {root}: {r}")
        shutil.rmtree(r)
    return f"تم حذف {len(runs)} تشغيل / deleted {len(runs)} run(s)."


def open_path(p: Path) -> str:
    """Open a file/folder with the OS default app (Windows: Explorer / browser)."""
    import subprocess
    import sys

    try:
        if sys.platform.startswith("win"):
            os.startfile(str(p))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
        return f"opened: {p}"
    except Exception as exc:  # pragma: no cover
        return f"could not open automatically ({exc}); open this path manually: {p}"
