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
    _check_channels(a, paths)
    outcome = asyncio.run(run_morning(backend, paths, audio_timeout_min=a.audio_timeout, max_links=a.max_links, say=print))
    _post_actions(outcome, paths, a)
    if a.open and outcome.run_dir and (outcome.run_dir / "report.html").exists():
        print(storage.open_path(outcome.run_dir / "report.html"))
    return outcome.code


def _check_channels(a, paths) -> None:
    """Followed YouTube channels: new videos go into inbox.txt BEFORE the morning run reads it.
    On by default once you follow a channel; skipped in --sample mode unless --channels is given; never fatal."""
    from . import channels

    if (a.sample and a.channels is None) or not channels.auto_enabled(a.channels, paths.base):
        return
    channels.check_safely(paths.base, print)


def _post_actions(outcome, paths, a) -> None:
    """Opt-in deliveries (Telegram ...). They can never change the exit code of the morning run."""
    try:
        from .postrun import run_post_actions

        run_post_actions(outcome, paths, telegram=a.telegram, obsidian=a.obsidian, say=print)
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


def cmd_channels(a) -> int:
    from . import channels

    base = Path(a.data_dir) if a.data_dir else None
    try:
        if a.ch_cmd == "add":
            return channels.add(a.target, base, backfill=a.backfill)
        if a.ch_cmd == "remove":
            return channels.remove(a.target, base)
        if a.ch_cmd == "list":
            print(channels.list_text(base))
            return 0
        if a.max_per_channel <= 0:
            print("✘ --max-per-channel يجب أن يكون أكبر من صفر")
            return channels.EXIT_USAGE
        return channels.check(base, dry_run=a.dry_run, max_per_channel=a.max_per_channel)[0]
    except channels.ChannelError as exc:
        print(f"✘ {exc}")
        return channels.EXIT_USAGE


def _obsidian_search(a, base) -> int:
    from . import obsidian, vault_search

    try:
        target = obsidian.resolve_target(base, a.vault, None)
        res = vault_search.search(target.vault, " ".join(a.query), limit=a.limit, folder=a.folder)
    except (obsidian.ObsidianError, ValueError) as exc:
        print(f"✘ {exc}")
        return 2
    if a.json:
        import json as _json
        from dataclasses import asdict

        print(_json.dumps(asdict(res), ensure_ascii=False, indent=2))
        return 0
    print(f"فُحص {res.files_scanned} ملف؛ كلمات البحث: {'، '.join(res.terms)}")
    if not res.hits:
        print("لا توجد ملاحظات مطابقة.")
    for i, h in enumerate(res.hits, 1):
        print(f"\n[{i}] {h.title}   (درجة {h.score})\n    {h.path}\n    {h.snippet}")
    return 0


def cmd_obsidian(a) -> int:
    from . import deliver, obsidian

    base = Path(a.data_dir) if a.data_dir else None
    if a.ob_cmd == "setup-check":
        return obsidian.setup_check(base, a.vault, a.subfolder)
    if a.ob_cmd == "search":
        return _obsidian_search(a, base)
    try:
        target = obsidian.resolve_target(base, a.vault, a.subfolder)
    except obsidian.ObsidianError as exc:
        print(f"✘ {exc}")
        return 2
    paths = _morning_paths(a)
    d = deliver.from_run_dir(paths.outputs / a.run) if a.run else deliver.latest(paths.outputs)
    if d is None:
        print(f"✘ لا توجد نتيجة صباحية في {paths.outputs}")
        return 2
    rep = obsidian.save_deliverable(d, target, copy_audio=not a.no_audio)
    print(rep.summary())
    return 0 if rep.status in ("saved", "exists") else obsidian.EXIT_OBSIDIAN


def cmd_ask_all(a) -> int:
    from . import askall
    from .real_backend import LoginRequiredError

    question = " ".join(a.question).strip()
    if not question or a.limit <= 0 or a.timeout <= 0:
        print("✘ اكتب سؤالًا، و--limit/--timeout أكبر من صفر / give a question; --limit and --timeout must be > 0")
        return askall.EXIT_USAGE
    if a.sample:
        from .sample_backend import SampleBackend

        backend = SampleBackend()
        print("⚠ الوضع التجريبي (--sample): دفاتر مثال، بدون اتصال بـ NotebookLM. / SAMPLE MODE", file=sys.stderr)
    else:
        from .real_backend import RealBackend

        backend = RealBackend(profile=a.profile)
    flt = askall.Filters(match=a.match or [], exclude=a.exclude or [], ids=a.id or [], morning_only=a.morning, limit=a.limit,
                         include_empty=a.include_empty)
    root = Path(a.out).resolve() if a.out else askall.reports_root(Path(a.data_dir) if a.data_dir else None, a.sample)
    log = (lambda m: print(m, file=sys.stderr)) if a.json else print
    try:
        res = asyncio.run(askall.run_ask_all(backend, question, flt, root, timeout_s=a.timeout, say=log))
    except Exception as exc:
        if isinstance(exc, LoginRequiredError) or askall.looks_like_auth_problem(exc):
            print(f"\n✘ {exc if isinstance(exc, LoginRequiredError) else 'انتهت صلاحية تسجيل الدخول'}\n"
                  "شغّل على جهازك:  python -m notebooklm_lab login   (أو جرّب --sample بدون حساب)")
            return askall.EXIT_LOGIN
        print(f"✘ فشل / failed: {type(exc).__name__}: {str(exc)[:300]}")
        return askall.EXIT_FAILED
    if not res.answers:
        print("لم يطابق أي دفتر الفلاتر (أو لا توجد دفاتر). جرّب --match بكلمة أخرى أو --include-empty. / No notebook matched.")
        return askall.EXIT_USAGE
    if a.json:
        import json as _json

        print(_json.dumps(res.to_dict(), ensure_ascii=False, indent=2))
    else:
        print("\n" + askall.render_markdown(res))
        print(f"التقرير المحفوظ / saved report: {Path(res.report_dir) / 'report.html'}  (+ report.md, answer.json)")
    if a.open and res.report_dir:
        print(storage.open_path(Path(res.report_dir) / "report.html"))
    return askall.exit_code(res)


def cmd_ask_both(a) -> int:
    from . import askall, askboth

    question = " ".join(a.question).strip()
    if not question or a.limit_notebooks <= 0 or a.limit_notes <= 0 or a.timeout <= 0:
        print("✘ اكتب سؤالًا، والحدود/المهلة أكبر من صفر / give a question; limits/timeout must be > 0")
        return askboth.EXIT_USAGE
    if a.no_vault and a.no_notebooks:
        print("✘ لا يمكن تعطيل المصدرين معًا / cannot disable both sources")
        return askboth.EXIT_USAGE
    if a.sample:
        from .sample_backend import SampleBackend

        factory = SampleBackend
        print("⚠ الوضع التجريبي (--sample): دفاتر NotebookLM مثال؛ ملاحظات Obsidian حقيقية إن ضبطتها. / SAMPLE notebooks", file=sys.stderr)
    else:
        from .real_backend import RealBackend

        def factory():
            return RealBackend(profile=a.profile)
    base = Path(a.data_dir) if a.data_dir else None
    log = (lambda m: print(m, file=sys.stderr)) if a.json else print
    c = asyncio.run(askboth.run_combined(
        question, backend_factory=factory, include_notebooks=not a.no_notebooks, include_vault=not a.no_vault, data_dir=base,
        vault=a.vault, folder=a.folder, note_limit=a.limit_notes, timeout_s=a.timeout, mode="sample" if a.sample else "real",
        flt=askall.Filters(match=a.match or [], exclude=a.exclude or [], morning_only=a.morning, limit=a.limit_notebooks), say=log))
    code = askboth.exit_code(c)
    for what, err in (("Obsidian", c.vault_error), ("NotebookLM", c.notebooks_error)):
        if err:
            print(f"⚠ {what}: {err}", file=sys.stderr if a.json else sys.stdout)
    if code in (askboth.EXIT_LOGIN, askboth.EXIT_FAILED, askboth.EXIT_USAGE) and not (c.has_notes or c.has_notebook_answers):
        if c.notebooks_login:
            print("شغّل على جهازك:  python -m notebooklm_lab login   (أو استعمل --no-notebooks للبحث في Obsidian فقط، أو --sample)")
        elif code == askboth.EXIT_USAGE:
            print("لم أفحص أي مصدر: اضبط OBSIDIAN_VAULT (python -m notebooklm_lab obsidian setup-check) أو غيّر فلاتر الدفاتر.")
        return code
    root = Path(a.out).resolve() if a.out else askboth.reports_root(base, a.sample)
    askboth.save_report(c, root)
    if a.json:
        import json as _json

        print(_json.dumps(c.to_dict(), ensure_ascii=False, indent=2))
    else:
        print("\n" + askboth.render_markdown(c))
        print(f"التقرير المحفوظ / saved report: {Path(c.report_dir) / 'report.html'}  (+ report.md, answer.json)")
    if a.open:
        print(storage.open_path(Path(c.report_dir) / "report.html"))
    return code


def cmd_mcp_server(a) -> int:
    from . import mcp_server

    return mcp_server.main(["--sample"] if a.sample else [])


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
    m.add_argument("--obsidian", action=argparse.BooleanOptionalAction, default=None,
                   help="save the summary + podcast into your Obsidian vault after a run (default: only if NOTEBOOKLM_LAB_OBSIDIAN_AUTO=1)")
    m.add_argument("--channels", action=argparse.BooleanOptionalAction, default=None,
                   help="check followed YouTube channels first (default: on if you follow any; off in --sample; NOTEBOOKLM_LAB_CHANNELS_AUTO=0 disables)")
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

    ch = sub.add_parser("channels", help="follow YouTube channels: new videos are added to inbox.txt (add / list / remove / check)")
    ch.add_argument("--data-dir", default=None)
    chs = ch.add_subparsers(dest="ch_cmd", required=True)
    cdd = argparse.ArgumentParser(add_help=False)
    cdd.add_argument("--data-dir", default=argparse.SUPPRESS)
    ca = chs.add_parser("add", parents=[cdd], help="follow a channel by @handle, channel URL or UC… id")
    ca.add_argument("target", help="@handle, https://www.youtube.com/@name, https://www.youtube.com/channel/UC…")
    ca.add_argument("--backfill", type=int, default=0, help="also queue this many of the channel's latest videos now (default 0: only future videos)")
    chs.add_parser("list", parents=[cdd], help="show followed channels")
    cr = chs.add_parser("remove", parents=[cdd], help="stop following (by @handle, id, URL or part of the title)")
    cr.add_argument("target")
    cc = chs.add_parser("check", parents=[cdd], help="find new videos and append their links to inbox.txt")
    cc.add_argument("--dry-run", action="store_true", help="show what would be added; write nothing")
    cc.add_argument("--max-per-channel", type=int, default=5, help="max new videos taken per channel per check (default 5; older ones are skipped)")
    ch.set_defaults(fn=cmd_channels, target=None, backfill=0, dry_run=False, max_per_channel=5)

    ob = sub.add_parser("obsidian", help="save the morning summary + podcast into an Obsidian vault (setup-check / save)")
    ob.add_argument("--data-dir", default=None)
    obs = ob.add_subparsers(dest="ob_cmd", required=True)
    odd = argparse.ArgumentParser(add_help=False)
    odd.add_argument("--data-dir", default=argparse.SUPPRESS)
    odd.add_argument("--vault", help="vault folder (default: $OBSIDIAN_VAULT)")
    odd.add_argument("--subfolder", help="sub-folder inside the vault (default: $OBSIDIAN_SUBFOLDER or NotebookLM)")
    obs.add_parser("setup-check", parents=[odd], help="check the vault folder is there and writable")
    ose = obs.add_parser("search", parents=[odd], help="ranked keyword search of the vault's Markdown notes (read-only, no login)")
    ose.add_argument("query", nargs="+")
    ose.add_argument("--limit", type=int, default=5)
    ose.add_argument("--folder", help="search only this sub-folder of the vault")
    ose.add_argument("--json", action="store_true")
    osv = obs.add_parser("save", parents=[odd], help="save the latest (or --run) morning result as a Markdown note; never overwrites")
    osv.add_argument("--run", help="a morning run folder name such as 2026-11-03 (default: the latest)")
    osv.add_argument("--sample", action="store_true", help="use the sample (demo) morning outputs")
    osv.add_argument("--no-audio", action="store_true", help="do not copy the podcast into the vault (link to the original file)")
    ob.set_defaults(fn=cmd_obsidian, sample=False, run=None, no_audio=False, vault=None, subfolder=None, json=False, folder=None, limit=5)

    aa = sub.add_parser("ask-all", help="ask ONE question across all (or filtered) notebooks -> one combined Arabic answer + HTML/MD report")
    aa.add_argument("question", nargs="+", help="the question (quotes optional)")
    aa.add_argument("--match", action="append", help="only notebooks whose title contains this text (repeatable)")
    aa.add_argument("--exclude", action="append", help="skip notebooks whose title contains this text (repeatable)")
    aa.add_argument("--id", action="append", help="only this notebook id (repeatable)")
    aa.add_argument("--morning", action="store_true", help="only the daily «ملخص صباحي» notebooks")
    aa.add_argument("--limit", type=int, default=10, help="max notebooks to ask, newest first (default 10; each uses your Google quota)")
    aa.add_argument("--include-empty", action="store_true", help="also ask notebooks that have no sources")
    aa.add_argument("--timeout", type=float, default=180.0, help="seconds to wait per notebook (default 180)")
    aa.add_argument("--sample", action="store_true", help="offline sample notebooks instead of your real account")
    aa.add_argument("--profile", help="notebooklm-py login profile name")
    aa.add_argument("--data-dir", help="data folder; reports go to <data>/ask/")
    aa.add_argument("--out", help="folder for the report (default: <data>/ask)")
    aa.add_argument("--json", action="store_true", help="print the structured answer as JSON (for agents/scripts)")
    aa.add_argument("--open", action="store_true", help="open the HTML report when done")
    aa.set_defaults(fn=cmd_ask_all)

    ab = sub.add_parser("ask-both", help="ONE question -> your Obsidian notes + your NotebookLM notebooks -> one Arabic answer citing both")
    ab.add_argument("question", nargs="+")
    ab.add_argument("--vault", help="Obsidian vault folder (default: $OBSIDIAN_VAULT / settings file)")
    ab.add_argument("--folder", help="search only this sub-folder of the vault")
    ab.add_argument("--limit-notes", type=int, default=5, help="max notes to cite (default 5)")
    ab.add_argument("--limit-notebooks", type=int, default=5, help="max notebooks to ask, newest first (default 5; each uses Google quota)")
    ab.add_argument("--match", action="append", help="only notebooks whose title contains this text (repeatable)")
    ab.add_argument("--exclude", action="append", help="skip notebooks whose title contains this text (repeatable)")
    ab.add_argument("--morning", action="store_true", help="only the daily «ملخص صباحي» notebooks")
    ab.add_argument("--no-notebooks", action="store_true", help="search only Obsidian (no login, no Google quota)")
    ab.add_argument("--no-vault", action="store_true", help="ask only NotebookLM")
    ab.add_argument("--timeout", type=float, default=180.0, help="seconds to wait per notebook")
    ab.add_argument("--sample", action="store_true", help="offline sample notebooks (the Obsidian part is still your real vault)")
    ab.add_argument("--profile", help="notebooklm-py login profile name")
    ab.add_argument("--data-dir"), ab.add_argument("--out", help="folder for the report (default: <data>/ask-both)")
    ab.add_argument("--json", action="store_true", help="print the structured answer as JSON")
    ab.add_argument("--open", action="store_true", help="open the HTML report")
    ab.set_defaults(fn=cmd_ask_both)

    ms_ = sub.add_parser("mcp-server", help="start this project's own MCP server (stdio): tool ask_all_notebooks")
    ms_.add_argument("--sample", action="store_true", help="offline sample notebooks")
    ms_.set_defaults(fn=cmd_mcp_server)

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
