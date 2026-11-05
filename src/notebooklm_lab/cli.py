"""Command line entry point:  python -m notebooklm_lab <command>"""
from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from . import PINNED_NOTEBOOKLM_PY, __version__, agents, scheduler, secrets_scan, selfcheck, settings, storage
from .config import DEFAULT_LANGUAGE, DEFAULT_OUTPUTS, OUTPUT_KINDS, output_root, repo_root
from .pipeline import DEFAULT_QUESTIONS_AR, make_run_dir, run_digest
from .sources import SourceError, build_specs, read_links_file

DISCLAIMER = (
    "أداة غير رسمية ولا ترتبط بـ Google — Unofficial tool, not affiliated with Google. "
    "Built on notebooklm-py (MIT, Teng Lin)."
)


def _utf8_console() -> None:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass


def _split(csv: str) -> List[str]:
    return [x.strip() for x in csv.split(",") if x.strip()]


def _finish(result, run_dir: Path, open_report: bool) -> None:
    ok = sum(1 for o in result.outputs if o.ok)
    print(f"\n✔ تم / done  [{result.mode}]  مخرجات ناجحة / outputs ok: {ok}/{len(result.outputs)}")
    print(f"  المجلد / folder : {run_dir}")
    print(f"  التقرير / report: {run_dir / 'report.html'}")
    for w in result.warnings:
        print(f"  ! {w}")
    if open_report:
        print(storage.open_path(run_dir / "report.html"))


def cmd_demo(a) -> int:
    from .sample_backend import DEMO_SPECS, SampleBackend

    root = Path(a.out).resolve() if a.out else output_root()
    run_dir = make_run_dir(root, "sample-demo")
    print("⚠ الوضع التجريبي: بيانات مثال مكتوبة مسبقًا — ليست من NotebookLM. / SAMPLE MODE: pre-written example data, not from NotebookLM.")
    result = asyncio.run(
        run_digest(SampleBackend(), DEMO_SPECS, run_dir, "عينة تجريبية: ملخص لصانع المحتوى", DEFAULT_LANGUAGE,
                   outputs=("briefing", "study_guide", "mind_map", "audio", "quiz"), say=print)
    )
    _finish(result, run_dir, a.open)
    return 0


def cmd_digest(a) -> int:
    items: List[str] = list(a.links)
    if a.file:
        items += read_links_file(Path(a.file))
    if not items:
        print("أعطني رابطًا واحدًا على الأقل أو --file links.txt / give at least one link or --file links.txt")
        return 2
    try:
        specs = build_specs(items)
    except SourceError as exc:
        print(f"✘ {exc}")
        return 2
    outputs = _split(a.outputs)
    bad = [o for o in outputs if o not in OUTPUT_KINDS]
    if bad:
        print(f"✘ unknown outputs {bad}; choose from {', '.join(OUTPUT_KINDS)}")
        return 2
    title = a.title or "ملخص روابط صانع المحتوى"
    questions = a.question or list(DEFAULT_QUESTIONS_AR)
    root = Path(a.out).resolve() if a.out else output_root()
    if a.sample:
        from .sample_backend import SampleBackend

        backend = SampleBackend()
        print("⚠ الوضع التجريبي (--sample): لن يتم الاتصال بـ NotebookLM. / SAMPLE MODE: no NotebookLM call is made.")
    else:
        from .real_backend import RealBackend

        backend = RealBackend(profile=a.profile)
        print("الوضع الحقيقي: سيتم استخدام حسابك في NotebookLM (حصة Google). / REAL MODE: uses your NotebookLM account quota.")

    holder = {}

    async def go():
        async with backend:  # real mode: fails here, before any folder is made, if not logged in
            holder["dir"] = make_run_dir(root, title)
            return await run_digest(backend, specs, holder["dir"], title, a.language, outputs, questions, say=print)

    try:
        result = asyncio.run(go())
    except Exception as exc:
        from .real_backend import LoginRequiredError

        if isinstance(exc, LoginRequiredError):
            print(f"\n✘ {exc}")
            print("جرّب الوضع التجريبي بدون تسجيل دخول: add --sample")
            return 3
        raise
    _finish(result, holder["dir"], a.open)
    return 0


def _morning_paths(a):
    from .morning import make_paths

    return make_paths(Path(a.data_dir) if a.data_dir else None, sample=bool(getattr(a, "sample", False)))


def cmd_morning(a) -> int:
    from .morning import EXIT_USAGE, run_morning

    action = a.morning_cmd or "run"
    if action == "status":
        from .morning import status_text

        print(status_text(_morning_paths(a)))
        return 0
    if action in ("schedule", "unschedule"):
        return _morning_schedule(a, action)
    if a.audio_timeout <= 0 or a.max_links <= 0:
        print("✘ --audio-timeout و --max-links يجب أن يكونا أكبر من صفر / must be > 0")
        return EXIT_USAGE
    paths = _morning_paths(a)
    if a.sample:
        from .sample_backend import SampleBackend

        backend = SampleBackend()
    else:
        from .real_backend import RealBackend

        backend = RealBackend(profile=a.profile, timeouts={"audio": a.audio_timeout * 60.0})
    outcome = asyncio.run(run_morning(backend, paths, audio_timeout_min=a.audio_timeout, max_links=a.max_links, say=print))
    _post_actions(outcome, paths, a)
    if a.open and outcome.run_dir and (outcome.run_dir / "report.html").exists():
        print(storage.open_path(outcome.run_dir / "report.html"))
    return outcome.code


def _post_actions(outcome, paths, a) -> None:
    """Opt-in deliveries (Telegram ...). They can never change the exit code of the morning run."""
    try:
        from .postrun import run_post_actions

        run_post_actions(outcome, paths, telegram=a.telegram, say=print)
    except Exception as exc:  # pragma: no cover - run_post_actions already guards itself
        print(f"⚠ تعذّر تنفيذ التسليم الإضافي ({type(exc).__name__}); الملخص سليم. / post-run delivery failed; the digest is intact.")


def _morning_schedule(a, action: str) -> int:
    target = a.target or scheduler.default_target()
    try:
        if action == "unschedule":
            print(scheduler.remove(target))
            return 0
        data = _morning_paths(a).base
        python = a.python or sys.executable
        print(scheduler.describe(target, a.time, python, data))
        if a.install:
            print()
            print(scheduler.install(target, a.time, python, data))
        return 0
    except scheduler.ScheduleError as exc:
        print(f"✘ {exc}")
        return 2


def cmd_config(a) -> int:
    base = Path(a.data_dir) if a.data_dir else None
    if a.action == "init":
        path, created = settings.init_file(base)
        print(f"{'أنشأتُ' if created else 'موجود مسبقًا'} / {'created' if created else 'already exists'}: {path}")
        print("افتحه بالمفكرة (Notepad) واكتب القيم بعد علامة = ثم احفظ. لا ترفع هذا الملف إلى GitHub.")
        return 0
    print(settings.describe(base))
    return 0


def cmd_telegram(a) -> int:
    from . import telegram

    base = Path(a.data_dir) if a.data_dir else None
    if a.tg_cmd == "setup-check":
        return telegram.setup_check(base, send_test=a.send_test)
    if a.tg_cmd == "chat-id":
        return telegram.find_chat_ids(base)
    token, chat = telegram.credentials(base)
    if not token or not chat:
        print("✘ TELEGRAM_BOT_TOKEN و TELEGRAM_CHAT_ID مطلوبان. جرّب: python -m notebooklm_lab telegram setup-check")
        return 2
    if a.file:
        rep = telegram.send_file(token, chat, Path(a.file), a.caption or "")
    else:
        from . import deliver

        paths = _morning_paths(a)
        d = deliver.from_run_dir(paths.outputs / a.run) if a.run else deliver.latest(paths.outputs)
        if d is None:
            print(f"✘ لا توجد نتيجة صباحية في {paths.outputs} — مرّر ملفًا: telegram send <file>")
            return 2
        rep = telegram.send_deliverable(token, chat, d)
    print(rep.summary())
    return 0 if rep.ok else telegram.EXIT_TELEGRAM


def cmd_session(a) -> int:
    if a.action == "where":
        print(storage.session_report(a.profile))
    else:
        print(storage.delete_session(a.profile, a.yes))
    return 0


def cmd_outputs(a) -> int:
    root = Path(a.out).resolve() if a.out else output_root()
    if a.action == "where":
        print(outputs_text(root))
    elif a.action == "open":
        runs = storage.list_runs(root)
        target = (runs[-1] / "report.html") if runs and not a.run else (root / a.run / "report.html" if a.run else root)
        print(storage.open_path(target))
    else:
        print(storage.delete_outputs(root, a.run, a.all, a.yes))
    return 0


def outputs_text(root: Path) -> str:
    return storage.outputs_report(root)


def _nb_cli(*args: str) -> int:
    return subprocess.call([sys.executable, "-m", "notebooklm", *args])


def cmd_login(a) -> int:
    print("سيفتح متصفح لتسجّل الدخول إلى حساب Google الخاص بك على هذا الجهاز. لا تُرسل كلمة السر لأحد.\n"
          "A browser will open so you sign in to YOUR OWN Google account on THIS computer.")
    return _nb_cli("login", *(["--browser", a.browser] if a.browser else []))


def cmd_login_check(_a) -> int:
    return _nb_cli("auth", "check", "--test")


def cmd_selfcheck(a) -> int:
    return selfcheck.run(with_mcp=a.mcp)


def cmd_secrets(a) -> int:
    return secrets_scan.run(Path(a.path).resolve() if a.path else repo_root())


def cmd_agents(a) -> int:
    print(agents.render(a.name, a.python or ""))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="notebooklm_lab", description=DISCLAIMER)
    p.add_argument("--version", action="version", version=f"notebooklm-lab {__version__} (notebooklm-py=={PINNED_NOTEBOOKLM_PY})")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("demo", help="offline sample demo (no login needed)")
    d.add_argument("--out"), d.add_argument("--open", action="store_true", help="open the report when done")
    d.set_defaults(fn=cmd_demo)

    g = sub.add_parser("digest", help="links/files -> summary, cited answers, Arabic audio overview, mind map ...")
    g.add_argument("links", nargs="*", help="web or YouTube links, or local files")
    g.add_argument("--file", help="text file with one link/path per line (# for comments)")
    g.add_argument("--title")
    g.add_argument("--language", default=DEFAULT_LANGUAGE, help="NotebookLM output language code (default ar_001 = Arabic)")
    g.add_argument("--outputs", default=",".join(DEFAULT_OUTPUTS), help=f"comma list from: {','.join(OUTPUT_KINDS)}")
    g.add_argument("--question", action="append", help="custom question (repeatable)")
    g.add_argument("--sample", action="store_true", help="offline sample mode instead of real NotebookLM")
    g.add_argument("--profile", help="notebooklm-py login profile name")
    g.add_argument("--out"), g.add_argument("--open", action="store_true")
    g.set_defaults(fn=cmd_digest)

    m = sub.add_parser("morning", help="morning digest: new inbox links -> Arabic summary + podcast (schedule / status)")
    m.add_argument("--sample", action="store_true", help="offline sample mode (separate state; real links are not consumed)")
    m.add_argument("--data-dir", help="your data folder (default: ~/NotebookLM-Lab or $NOTEBOOKLM_LAB_DATA)")
    m.add_argument("--profile", help="notebooklm-py login profile name")
    m.add_argument("--audio-timeout", type=float, default=20.0, help="minutes to wait for the audio overview (default 20)")
    m.add_argument("--max-links", type=int, default=20, help="max new links per run (default 20; the rest wait for the next run)")
    m.add_argument("--open", action="store_true", help="open the report when done")
    m.add_argument("--telegram", action=argparse.BooleanOptionalAction, default=None,
                   help="send the summary + podcast to Telegram after a run (default: only if NOTEBOOKLM_LAB_TELEGRAM_AUTO=1)")
    m.set_defaults(fn=cmd_morning, morning_cmd=None)
    # sub-actions share --data-dir/--sample; SUPPRESS keeps values given before the action word
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data-dir", default=argparse.SUPPRESS)
    common.add_argument("--sample", action="store_true", default=argparse.SUPPRESS)
    msub = m.add_subparsers(dest="morning_cmd", metavar="{schedule,unschedule,status}")
    ms = msub.add_parser("schedule", parents=[common], help="print (or --install) a daily job")
    ms.add_argument("--time", default="07:30", help="HH:MM, 24h (default 07:30)")
    ms.add_argument("--target", choices=["windows", "cron"], help="default: windows on Windows, cron elsewhere")
    ms.add_argument("--install", action="store_true", help="actually create the job (default: only print the command)")
    ms.add_argument("--python", help="python executable the job should use (default: the current one)")
    mu = msub.add_parser("unschedule", parents=[common], help="remove the daily job")
    mu.add_argument("--target", choices=["windows", "cron"])
    msub.add_parser("status", parents=[common], help="last run, links processed, where the outputs are")

    cf = sub.add_parser("config", help="your private settings file (tokens, folders): init / show")
    cf.add_argument("action", choices=["show", "init"], nargs="?", default="show")
    cf.add_argument("--data-dir")
    cf.set_defaults(fn=cmd_config)

    tg = sub.add_parser("telegram", help="send the morning podcast + summary to Telegram (setup-check / chat-id / send)")
    tg.add_argument("--data-dir", default=None)
    tgs = tg.add_subparsers(dest="tg_cmd", required=True)
    dd = argparse.ArgumentParser(add_help=False)  # lets --data-dir come before or after the action word
    dd.add_argument("--data-dir", default=argparse.SUPPRESS)
    tgc = tgs.add_parser("setup-check", parents=[dd], help="verify TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID (optionally send a test message)")
    tgc.add_argument("--send-test", action="store_true", help="also send a short test message")
    tgs.add_parser("chat-id", parents=[dd], help="find your chat id after you message your bot")
    tgd = tgs.add_parser("send", parents=[dd], help="send a file (audio), or with no file the latest morning result (summary + podcast)")
    tgd.add_argument("file", nargs="?", help="audio/document to send; omit to send the latest morning run")
    tgd.add_argument("--caption", help="caption for the file (max ~1000 characters)")
    tgd.add_argument("--run", help="a morning run folder name such as 2026-11-03 (default: the latest)")
    tgd.add_argument("--sample", action="store_true", help="use the sample (demo) morning outputs")
    tg.set_defaults(fn=cmd_telegram, sample=False, run=None, file=None, caption=None, send_test=False)

    s = sub.add_parser("session", help="where is my Google login session stored / delete it")
    s.add_argument("action", choices=["where", "delete"]), s.add_argument("--yes", action="store_true"), s.add_argument("--profile")
    s.set_defaults(fn=cmd_session)

    o = sub.add_parser("outputs", help="where outputs are saved, size, open, delete")
    o.add_argument("action", choices=["where", "open", "delete"])
    o.add_argument("--run"), o.add_argument("--all", action="store_true"), o.add_argument("--yes", action="store_true"), o.add_argument("--out")
    o.set_defaults(fn=cmd_outputs)

    l = sub.add_parser("login", help="one-time Google sign-in (wraps `notebooklm login`)")
    l.add_argument("--browser", choices=["chromium", "chrome", "msedge"])
    l.set_defaults(fn=cmd_login)
    sub.add_parser("login-check", help="test that the saved login works (wraps `notebooklm auth check --test`)").set_defaults(fn=cmd_login_check)

    c = sub.add_parser("selfcheck", help="health checks (pin, sample mode, .gitignore, secrets)")
    c.add_argument("--mcp", action="store_true", help="also start the upstream MCP server and list its tools")
    c.set_defaults(fn=cmd_selfcheck)

    sc = sub.add_parser("secrets-scan", help="scan files that would be committed for secrets")
    sc.add_argument("path", nargs="?")
    sc.set_defaults(fn=cmd_secrets)

    ag = sub.add_parser("agents", help="print config for Claude Code / Codex / Hermes")
    ag.add_argument("name", choices=[*agents.AGENTS, "all"], nargs="?", default="all")
    ag.add_argument("--python", help="path of the Python that has this project installed (default: the current one)")
    ag.set_defaults(fn=cmd_agents)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    _utf8_console()
    args = build_parser().parse_args(argv)
    return int(args.fn(args) or 0)
