import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from notebooklm_lab import cli, inbox as ib, morning, scheduler, storage
from notebooklm_lab.models import SourceSpec
from notebooklm_lab.sample_backend import SampleBackend

DAY = "2026-11-03"


def _paths(tmp_path, sample=True):
    return morning.make_paths(tmp_path / "data", sample=sample)


def _write_inbox(paths, text):
    paths.inbox.parent.mkdir(parents=True, exist_ok=True)
    paths.inbox.write_text(text, encoding="utf-8")


def _run(backend, paths, **kw):
    return asyncio.run(morning.run_morning(backend, paths, today=DAY, say=lambda _m: None, **kw))


# ------------------------------------------------------------ inbox parsing + dedup
def test_inbox_parsing_comments_blank_and_inline_comment():
    text = "\ufeff# comment\n\n   \nhttps://example.com/a  # my note\n  https://youtu.be/ABC \n# https://skipped.example\n"
    entries, dups = ib.parse_inbox_text(text)
    assert [e.link for e in entries] == ["https://example.com/a", "https://youtu.be/ABC"]
    assert dups == 0
    assert [e.line for e in entries] == [4, 5]


def test_inbox_keeps_url_fragment_and_ignores_hash_without_space():
    entries, _ = ib.parse_inbox_text("https://example.com/page#section\n")
    assert entries[0].link == "https://example.com/page#section"


def test_inbox_dedup_exact_and_equivalent_links():
    text = "\n".join([
        "https://example.com/a", "https://example.com/a", "HTTPS://Example.com/a/", "https://www.example.com/a#x",
        "https://www.youtube.com/watch?v=VID1", "https://youtu.be/VID1", "https://m.youtube.com/watch?v=VID1&t=5",
        "https://youtu.be/VID2",
    ])
    entries, dups = ib.parse_inbox_text(text)
    assert [e.link for e in entries] == ["https://example.com/a", "https://www.youtube.com/watch?v=VID1", "https://youtu.be/VID2"]
    assert dups == 5


def test_different_query_strings_are_different_articles():
    entries, _ = ib.parse_inbox_text("https://example.com/p?id=1\nhttps://example.com/p?id=2\n")
    assert len(entries) == 2


def test_ensure_inbox_creates_template_once(tmp_path):
    p = tmp_path / "x" / "inbox.txt"
    assert ib.ensure_inbox(p) is True and ib.ensure_inbox(p) is False
    assert ib.read_inbox(p)[0] == []  # the template contains only comments


# ------------------------------------------------------------ processed-state file
def test_state_roundtrip_and_new_entries(tmp_path):
    sp = tmp_path / "st.json"
    st = ib.load_state(sp)
    assert st["processed"] == {}
    a, b = ib.parse_inbox_text("https://example.com/a\nhttps://example.com/b\n")[0]
    ib.mark_processed(st, a, "ok", DAY, "run1")
    ib.save_state(sp, st)
    assert not list(tmp_path.glob("*.tmp"))  # atomic write leaves no temp file
    st2 = ib.load_state(sp)
    assert st2["processed"][a.key]["status"] == "ok" and st2["processed"][a.key]["link"] == a.link
    assert ib.new_entries([a, b], st2) == [b]
    assert json.loads(sp.read_text(encoding="utf-8"))["version"] == 1


def test_corrupt_state_is_reported_not_silently_reset(tmp_path):
    sp = tmp_path / "st.json"
    sp.write_text("{not json", encoding="utf-8")
    with pytest.raises(ib.StateError):
        ib.load_state(sp)
    paths = _paths(tmp_path)
    paths.state.parent.mkdir(parents=True, exist_ok=True)
    paths.state.write_text("{not json", encoding="utf-8")
    _write_inbox(paths, "https://example.com/a\n")
    assert _run(SampleBackend(), paths).code == morning.EXIT_USAGE


# ------------------------------------------------------------ no-new-links path
def test_first_run_creates_inbox_and_exits_cleanly(tmp_path):
    paths = _paths(tmp_path)
    msgs = []
    o = asyncio.run(morning.run_morning(SampleBackend(), paths, today=DAY, say=msgs.append))
    assert o.code == 0 and paths.inbox.exists()
    assert not paths.outputs.exists()


def test_no_new_links_message_is_arabic_and_creates_nothing(tmp_path):
    paths = _paths(tmp_path)
    _write_inbox(paths, "# only comments\n\n")
    msgs = []
    o = asyncio.run(morning.run_morning(SampleBackend(), paths, today=DAY, say=msgs.append))
    assert o.code == 0
    assert "لا توجد روابط جديدة" in "\n".join(msgs)
    assert not paths.outputs.exists()


# ------------------------------------------------------------ sample-mode end to end
def test_sample_end_to_end_then_second_run_has_no_new_links(tmp_path):
    paths = _paths(tmp_path)
    _write_inbox(paths, "# my links\nhttps://example.com/a\nhttps://youtu.be/V1\nhttps://example.com/a\nftp://bad/link\n")
    o = _run(SampleBackend(), paths)
    assert o.code == 0 and o.processed == 2
    d = paths.outputs / DAY
    assert o.run_dir == d
    files = sorted(p.name for p in (d / "files").iterdir())
    assert any(f.startswith("briefing") for f in files) and any(f.startswith("audio") for f in files)
    run = json.loads((d / "run.json").read_text(encoding="utf-8"))
    assert run["title"] == f"ملخص صباحي {DAY}" and run["language"] == "ar_001" and run["mode"] == "sample"
    assert [x["kind"] for x in run["outputs"]] == ["briefing", "audio"]
    md = (d / "morning_report.md").read_text(encoding="utf-8")
    assert "ملخص صباحي" in md and "الملخص المكتوب" in md and "غير صالح" in md
    assert 'dir=\'rtl\'' in (d / "report.html").read_text(encoding="utf-8")
    st = json.loads(paths.state.read_text(encoding="utf-8"))
    assert sorted(v["status"] for v in st["processed"].values()) == ["invalid", "ok", "ok"]
    assert st["last_success"]["links_ok"] == 2

    msgs = []
    o2 = asyncio.run(morning.run_morning(SampleBackend(), paths, today=DAY, say=msgs.append))
    assert o2.code == 0 and "لا توجد روابط جديدة" in "\n".join(msgs)
    assert len(storage.list_runs(paths.outputs)) == 1  # no second folder

    # a new link appears -> new run, same day gets its own folder and title
    _write_inbox(paths, paths.inbox.read_text(encoding="utf-8") + "https://example.com/new\n")
    o3 = _run(SampleBackend(), paths)
    assert o3.processed == 1 and o3.run_dir.name == f"{DAY}-2"
    assert json.loads((o3.run_dir / "run.json").read_text(encoding="utf-8"))["title"] == f"ملخص صباحي {DAY} (2)"


def test_sample_state_is_separate_from_real_state(tmp_path):
    real, sample = _paths(tmp_path, sample=False), _paths(tmp_path, sample=True)
    assert real.state != sample.state and real.outputs != sample.outputs and real.inbox == sample.inbox
    _write_inbox(sample, "https://example.com/a\n")
    _run(SampleBackend(), sample)
    assert not real.state.exists()  # trying --sample never "uses up" the real links


def test_max_links_leaves_the_rest_for_next_run(tmp_path):
    paths = _paths(tmp_path)
    _write_inbox(paths, "\n".join(f"https://example.com/{i}" for i in range(5)))
    assert _run(SampleBackend(), paths, max_links=2).processed == 2
    assert _run(SampleBackend(), paths, max_links=2).processed == 2
    assert _run(SampleBackend(), paths, max_links=2).processed == 1


# ------------------------------------------------------------ failures
class _Flaky(SampleBackend):
    def __init__(self, bad=(), audio_delay=0.0, audio_fail=False, auth_fail=False):
        super().__init__()
        self.bad, self.audio_delay, self.audio_fail, self.auth_fail = set(bad), audio_delay, audio_fail, auth_fail

    async def add_source(self, notebook_id, spec):
        if self.auth_fail:
            raise RuntimeError("Authentication expired - please login again")
        if spec.value in self.bad:
            raise RuntimeError("page could not be fetched")
        return await super().add_source(notebook_id, spec)

    async def generate(self, notebook_id, kind, language, dest_dir, instructions=None):
        if kind == "audio" and self.audio_delay:
            await asyncio.sleep(self.audio_delay)
        if kind == "audio" and self.audio_fail:
            raise RuntimeError("quota")
        return await super().generate(notebook_id, kind, language, dest_dir, instructions)


def test_one_bad_link_does_not_stop_the_others_and_is_retried_once(tmp_path):
    paths = _paths(tmp_path)
    _write_inbox(paths, "https://example.com/good\nhttps://example.com/bad\n")
    o = _run(_Flaky(bad={"https://example.com/bad"}), paths)
    assert o.code == 0 and o.processed == 1 and o.failed == 1
    st = json.loads(paths.state.read_text(encoding="utf-8"))
    assert [v["status"] for v in st["processed"].values()] == ["ok"]
    assert st["failed_attempts"] == {"https://example.com/bad": 1}
    # next day: only the bad link is new; with a working good link elsewhere it is tried once more, then given up
    _write_inbox(paths, paths.inbox.read_text(encoding="utf-8") + "https://example.com/good2\n")
    o2 = _run(_Flaky(bad={"https://example.com/bad"}), paths)
    assert o2.code == 0
    st = json.loads(paths.state.read_text(encoding="utf-8"))
    assert st["processed"]["https://example.com/bad"]["status"] == "failed"
    assert "https://example.com/bad" not in st["failed_attempts"]
    assert "لا توجد روابط جديدة" in _msg(paths)


def _msg(paths):
    out = []
    asyncio.run(morning.run_morning(SampleBackend(), paths, today=DAY, say=out.append))
    return "\n".join(out)


def test_slow_audio_times_out_but_summary_is_kept(tmp_path):
    paths = _paths(tmp_path)
    _write_inbox(paths, "https://example.com/a\n")
    o = _run(_Flaky(audio_delay=5), paths, audio_timeout_min=0.01)  # 0.6 s limit
    assert o.code == 0
    run = json.loads((o.run_dir / "run.json").read_text(encoding="utf-8"))
    by = {x["kind"]: x for x in run["outputs"]}
    assert by["briefing"]["ok"] and not by["audio"]["ok"] and "انتهت المهلة" in by["audio"]["error"]
    assert "✘ لم يُنشأ" in (o.run_dir / "report.html").read_text(encoding="utf-8")
    assert json.loads(paths.state.read_text(encoding="utf-8"))["last_success"]["outputs_failed"] == ["audio"]


def test_everything_failed_keeps_links_pending(tmp_path):
    paths = _paths(tmp_path)
    _write_inbox(paths, "https://example.com/a\n")
    o = _run(_Flaky(bad={"https://example.com/a"}), paths)
    assert o.code == morning.EXIT_FAILED
    st = json.loads(paths.state.read_text(encoding="utf-8"))
    assert st["processed"] == {} and st["failed_attempts"] == {}  # not counted against the link: could be a login problem
    assert _run(SampleBackend(), paths).code == 0 and _run(SampleBackend(), paths).code == 0  # retried and succeeded later


def test_all_outputs_failing_keeps_links_pending(tmp_path):
    class NoOutputs(SampleBackend):
        async def generate(self, *a, **k):
            raise RuntimeError("quota exceeded")

    paths = _paths(tmp_path)
    _write_inbox(paths, "https://example.com/a\n")
    assert _run(NoOutputs(), paths).code == morning.EXIT_FAILED
    assert json.loads(paths.state.read_text(encoding="utf-8"))["processed"] == {}


def test_expired_login_during_run_is_friendly_and_records_nothing(tmp_path):
    paths = _paths(tmp_path)
    _write_inbox(paths, "https://example.com/a\n")
    msgs = []
    o = asyncio.run(morning.run_morning(_Flaky(auth_fail=True), paths, today=DAY, say=msgs.append))
    assert o.code == morning.EXIT_FAILED
    assert "login" in "\n".join(msgs) and "انتهت صلاحية تسجيل الدخول" in "\n".join(msgs)
    assert json.loads(paths.state.read_text(encoding="utf-8"))["processed"] == {}


def test_no_login_real_mode_exits_3_without_folder_or_state_change(tmp_path, capsys):
    data = tmp_path / "d"
    data.mkdir()
    (data / "inbox.txt").write_text("https://example.com/a\n", encoding="utf-8")
    assert cli.main(["morning", "--data-dir", str(data)]) == 3
    out = capsys.readouterr().out
    assert "login" in out
    assert not (data / "morning").exists()
    assert json.loads((data / "morning_state.json").read_text(encoding="utf-8"))["processed"] == {}


def test_crash_before_any_output_leaves_no_empty_dated_folder(tmp_path):
    class Boom(SampleBackend):
        async def create_notebook(self, title):
            raise RuntimeError("server error 500")

    paths = _paths(tmp_path)
    _write_inbox(paths, "https://example.com/a\n")
    assert _run(Boom(), paths).code == morning.EXIT_FAILED
    assert not (paths.outputs / DAY).exists()


def test_real_backend_accepts_audio_timeout_override():
    from notebooklm_lab.real_backend import RealBackend

    assert RealBackend(timeouts={"audio": 90.0})._timeouts["audio"] == 90.0
    assert RealBackend()._timeouts["audio"] == 1200.0


# ------------------------------------------------------------ CLI + status
def test_cli_morning_sample_twice_and_status(tmp_path, capsys):
    data = tmp_path / "d"
    data.mkdir()
    (data / "inbox.txt").write_text("https://example.com/a\n", encoding="utf-8")
    assert cli.main(["morning", "--sample", "--data-dir", str(data)]) == 0
    assert "روابط ناجحة: 1" in capsys.readouterr().out
    assert cli.main(["morning", "--sample", "--data-dir", str(data)]) == 0
    assert "لا توجد روابط جديدة" in capsys.readouterr().out
    assert cli.main(["morning", "status", "--sample", "--data-dir", str(data)]) == 0
    out = capsys.readouterr().out
    assert "آخر نجاح" in out and "morning-sample" in out and "links processed in total: 1" in out


def test_cli_status_before_any_run(tmp_path, capsys):
    assert cli.main(["morning", "status", "--data-dir", str(tmp_path / "nothing")]) == 0
    assert "never run" in capsys.readouterr().out


def test_default_data_dir_comes_from_env(tmp_path):
    assert morning.make_paths().base == (tmp_path / "lab_data").resolve()


# ------------------------------------------------------------ scheduling
def test_parse_time():
    assert scheduler.parse_time("07:30") == (7, 30) and scheduler.parse_time("7:05") == (7, 5) and scheduler.parse_time("23:59") == (23, 59)
    for bad in ("24:00", "7:5", "0730", "", "07:60", "abc"):
        with pytest.raises(scheduler.ScheduleError):
            scheduler.parse_time(bad)


def test_windows_command_generation():
    py = "C:\\Users\\Me Me\\AppData\\Local\\Programs\\Python\\Python312\\python.exe"
    argv = scheduler.windows_create_argv("07:30", py, "C:\\Users\\Me Me\\NotebookLM-Lab")
    assert argv[:2] == ["schtasks", "/Create"]
    assert argv[argv.index("/SC") + 1] == "DAILY" and argv[argv.index("/ST") + 1] == "07:30" and argv[-1] == "/F"
    assert argv[argv.index("/TN") + 1] == scheduler.TASK_NAME
    assert argv[argv.index("/TR") + 1] == f'"{py}" -m notebooklm_lab morning --data-dir "C:\\Users\\Me Me\\NotebookLM-Lab"'
    printed = scheduler.describe("windows", "07:30", py, Path("data"))
    assert 'schtasks /Create /SC DAILY /TN "NotebookLM-Lab Morning" /TR "\\"' in printed and "/ST 07:30 /F" in printed
    assert scheduler.windows_delete_argv() == ["schtasks", "/Delete", "/TN", scheduler.TASK_NAME, "/F"]


def test_cron_line_generation_and_quoting():
    line = scheduler.cron_line("07:30", "/usr/bin/python3", Path("/home/u/My Data"))
    assert line.startswith("30 7 * * * /usr/bin/python3 -m notebooklm_lab morning --data-dir '/home/u/My Data' >> ")
    assert line.endswith("2>&1 " + scheduler.CRON_MARK)
    assert scheduler.cron_line("00:05", "p", Path("/d")).startswith("5 0 * * * ")


def test_cron_add_and_strip_keep_other_jobs_and_never_duplicate():
    other = "5 4 * * * echo mine\n"
    one = scheduler.cron_add(other, scheduler.cron_line("07:30", "py", Path("/d")))
    two = scheduler.cron_add(one, scheduler.cron_line("08:00", "py", Path("/d")))
    assert two.count(scheduler.CRON_MARK) == 1 and "0 8 * * *" in two and "30 7 * * *" not in two
    assert scheduler.cron_strip(two) == other
    assert scheduler.cron_strip(scheduler.cron_add("", "x " + scheduler.CRON_MARK)) == ""


class _FakeCrontab:
    def __init__(self, text=""):
        self.text, self.calls = text, []

    def __call__(self, argv, input=None, **kw):
        self.calls.append(argv)
        if argv == ["crontab", "-l"]:
            if not self.text:
                return subprocess.CompletedProcess(argv, 1, "", "no crontab for me")
            return subprocess.CompletedProcess(argv, 0, self.text, "")
        if argv == ["crontab", "-"]:
            self.text = input
            return subprocess.CompletedProcess(argv, 0, "", "")
        raise AssertionError(argv)


def test_install_and_remove_cron_with_fake_runner():
    fake = _FakeCrontab("5 4 * * * echo mine\n")
    scheduler.install("cron", "07:30", "py", Path("/d"), runner=fake)
    assert scheduler.CRON_MARK in fake.text and "echo mine" in fake.text
    scheduler.remove("cron", runner=fake)
    assert fake.text == "5 4 * * * echo mine\n"
    assert "no cron job" in scheduler.remove("cron", runner=fake)
    empty = _FakeCrontab()
    scheduler.install("cron", "07:30", "py", Path("/d"), runner=empty)
    scheduler.remove("cron", runner=empty)
    assert empty.text == ""


def test_install_windows_runs_schtasks_and_reports_failure():
    calls = []

    def ok(argv, **kw):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "SUCCESS", "")

    scheduler.install("windows", "07:30", "py", Path("d"), runner=ok)
    assert calls[0][:2] == ["schtasks", "/Create"]
    scheduler.remove("windows", runner=ok)
    assert calls[1][:2] == ["schtasks", "/Delete"]

    def fail(argv, **kw):
        return subprocess.CompletedProcess(argv, 1, "", "ERROR: Access is denied.")

    with pytest.raises(scheduler.ScheduleError):
        scheduler.install("windows", "07:30", "py", Path("d"), runner=fail)

    def missing(argv, **kw):
        return subprocess.CompletedProcess(argv, 1, "", "ERROR: The system cannot find the file specified.")

    assert "no scheduled task" in scheduler.remove("windows", runner=missing)


def test_missing_crontab_binary_is_a_clean_error():
    def nope(argv, **kw):
        raise FileNotFoundError("crontab")

    with pytest.raises(scheduler.ScheduleError):
        scheduler.install("cron", "07:30", "py", Path("/d"), runner=nope)


def test_cli_schedule_prints_without_installing(tmp_path, capsys):
    assert cli.main(["morning", "schedule", "--time", "07:30", "--target", "windows", "--python", "C:\\py\\python.exe"]) == 0
    out = capsys.readouterr().out
    assert "schtasks /Create" in out and "07:30" in out
    assert cli.main(["morning", "schedule", "--time", "99:00", "--target", "cron"]) == 2
