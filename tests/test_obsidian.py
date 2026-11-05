import json
import re
from datetime import date
from pathlib import Path

import pytest

from notebooklm_lab import cli, deliver, obsidian
from notebooklm_lab.deliver import Deliverable


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ("OBSIDIAN_VAULT", "OBSIDIAN_SUBFOLDER", "NOTEBOOKLM_LAB_OBSIDIAN_AUTO", "NOTEBOOKLM_LAB_ENV_FILE",
              "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "NOTEBOOKLM_LAB_TELEGRAM_AUTO"):
        monkeypatch.delenv(k, raising=False)


def _vault(tmp_path):
    v = tmp_path / "My Vault"
    (v / ".obsidian").mkdir(parents=True)
    return v


def _d(tmp_path, title="ملخص صباحي 2026-11-03", audio="p.m4a", sample=False, sources=("https://example.com/a", 'https://example.com/q?x="1"')):
    a = None
    if audio:
        a = tmp_path / audio
        a.write_bytes(b"AUDIO")
    return Deliverable(title=title, day="2026-11-03", mode="sample" if sample else "real", summary_md="## أهم الأفكار\n\n- فكرة: أولى\n- فكرة #ثانية",
                       audio_path=a, sources=list(sources), notebook_id="nb-123", run_dir=tmp_path)


def _front(text):
    yaml = pytest.importorskip("yaml")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, text[:200]
    return yaml.safe_load(m.group(1))


# ------------------------------------------------------------------ target resolution
def test_vault_required_and_must_exist(tmp_path, monkeypatch):
    with pytest.raises(obsidian.ObsidianError, match="OBSIDIAN_VAULT"):
        obsidian.resolve_target(tmp_path / "d")
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path / "nope"))
    with pytest.raises(obsidian.ObsidianError, match="غير موجود"):
        obsidian.resolve_target(tmp_path / "d")
    assert not (tmp_path / "nope").exists()  # a typo never creates a new vault


def test_default_and_custom_subfolder_and_bad_subfolders(tmp_path, monkeypatch):
    v = _vault(tmp_path)
    monkeypatch.setenv("OBSIDIAN_VAULT", str(v))
    assert obsidian.resolve_target(tmp_path).subfolder == "NotebookLM"
    monkeypatch.setenv("OBSIDIAN_SUBFOLDER", "Inbox/Podcasts")
    assert obsidian.resolve_target(tmp_path).folder == v.resolve() / "Inbox" / "Podcasts"
    for bad in ("../outside", "a/../../x", "C:\\Windows", "a:b", "/", ".."):
        monkeypatch.setenv("OBSIDIAN_SUBFOLDER", bad)
        with pytest.raises(obsidian.ObsidianError):
            obsidian.resolve_target(tmp_path)


def test_vault_and_subfolder_from_local_settings_file(tmp_path):
    v = _vault(tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    (data / "notebooklm-lab.env").write_text(f"OBSIDIAN_VAULT={v}\nOBSIDIAN_SUBFOLDER=Daily\n", encoding="utf-8")
    t = obsidian.resolve_target(data)
    assert t.vault == v.resolve() and t.subfolder == "Daily"


def test_safe_name_is_valid_on_windows():
    assert obsidian.safe_name('a:b/c\\d*e?"f<g>h|') == "a-b-c-d-e--f-g-h"
    assert obsidian.safe_name("  ...  ") == "note" and obsidian.safe_name("x.") == "x"
    assert len(obsidian.safe_name("ا" * 500)) <= 120


# ------------------------------------------------------------------ note content
def test_note_has_valid_frontmatter_audio_embed_and_body(tmp_path):
    v = _vault(tmp_path)
    t = obsidian.Target(v.resolve(), "NotebookLM")
    rep = obsidian.save_deliverable(_d(tmp_path), t)
    assert rep.status == "saved" and rep.note == v.resolve() / "NotebookLM" / "ملخص صباحي 2026-11-03.md"
    text = rep.note.read_text(encoding="utf-8")
    fm = _front(text)
    assert fm["date"] == date(2026, 11, 3) and fm["notebook"] == "ملخص صباحي 2026-11-03"
    assert fm["sources"] == ["https://example.com/a", 'https://example.com/q?x="1"']
    assert fm["tags"] == ["notebooklm", "morning-digest"] and fm["audio"] == "NotebookLM/audio/ملخص صباحي 2026-11-03.m4a"
    assert fm["notebook_id"] == "nb-123" and fm["mode"] == "real"
    assert "![[NotebookLM/audio/ملخص صباحي 2026-11-03.m4a]]" in text and "- فكرة: أولى" in text and "## المصادر" in text
    assert (v / "NotebookLM" / "audio" / "ملخص صباحي 2026-11-03.m4a").read_bytes() == b"AUDIO"
    assert "\r" not in text


def test_sample_note_is_labelled_and_tagged(tmp_path):
    t = obsidian.Target(_vault(tmp_path).resolve(), "NotebookLM")
    rep = obsidian.save_deliverable(_d(tmp_path, sample=True, audio="tone.wav"), t)
    text = rep.note.read_text(encoding="utf-8")
    assert "sample" in _front(text)["tags"] and "تجريبي" in text


def test_no_sources_and_no_audio(tmp_path):
    t = obsidian.Target(_vault(tmp_path).resolve(), "N")
    rep = obsidian.save_deliverable(_d(tmp_path, audio=None, sources=()), t)
    fm = _front(rep.note.read_text(encoding="utf-8"))
    assert fm["sources"] == [] and "audio" not in fm and rep.audio is None
    assert not (t.folder / "audio").exists()


def test_link_instead_of_copy(tmp_path):
    t = obsidian.Target(_vault(tmp_path).resolve(), "N")
    rep = obsidian.save_deliverable(_d(tmp_path), t, copy_audio=False)
    text = rep.note.read_text(encoding="utf-8")
    assert "file://" in text and "![[" not in text and not (t.folder / "audio").exists() and rep.messages


# ------------------------------------------------------------------ never overwrite
def test_existing_note_is_never_touched(tmp_path):
    t = obsidian.Target(_vault(tmp_path).resolve(), "NotebookLM")
    d = _d(tmp_path)
    t.folder.mkdir(parents=True)
    mine = t.folder / "ملخص صباحي 2026-11-03.md"
    mine.write_text("MY OWN EDITS", encoding="utf-8")
    rep = obsidian.save_deliverable(d, t)
    assert rep.status == "exists" and mine.read_text(encoding="utf-8") == "MY OWN EDITS"
    assert not (t.folder / "audio").exists()  # nothing else was written either


def test_second_save_is_a_skip_and_edits_survive(tmp_path):
    t = obsidian.Target(_vault(tmp_path).resolve(), "NotebookLM")
    d = _d(tmp_path)
    first = obsidian.save_deliverable(d, t)
    first.note.write_text(first.note.read_text(encoding="utf-8") + "\n\nMY NOTE\n", encoding="utf-8")
    again = obsidian.save_deliverable(d, t)
    assert again.status == "exists" and "MY NOTE" in first.note.read_text(encoding="utf-8")
    assert len(list((t.folder / "audio").iterdir())) == 1


def test_taken_audio_name_gets_a_number_not_overwritten(tmp_path):
    t = obsidian.Target(_vault(tmp_path).resolve(), "NotebookLM")
    (t.folder / "audio").mkdir(parents=True)
    theirs = t.folder / "audio" / "ملخص صباحي 2026-11-03.m4a"
    theirs.write_bytes(b"THEIRS")
    rep = obsidian.save_deliverable(_d(tmp_path), t)
    assert theirs.read_bytes() == b"THEIRS" and rep.audio.name == "ملخص صباحي 2026-11-03 (2).m4a" and rep.audio.read_bytes() == b"AUDIO"
    assert "(2).m4a]]" in rep.note.read_text(encoding="utf-8")


def test_subfolder_symlink_escaping_the_vault_is_refused(tmp_path):
    v = _vault(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (v / "NotebookLM").symlink_to(outside, target_is_directory=True)
    rep = obsidian.save_deliverable(_d(tmp_path), obsidian.Target(v.resolve(), "NotebookLM"))
    assert rep.status == "failed" and not list(outside.iterdir())


def test_write_error_is_reported_not_raised(tmp_path, monkeypatch):
    t = obsidian.Target(_vault(tmp_path).resolve(), "N")
    monkeypatch.setattr(obsidian.shutil, "copy2", lambda *a, **k: (_ for _ in ()).throw(PermissionError("denied")))
    rep = obsidian.save_deliverable(_d(tmp_path), t)
    assert rep.status == "failed" and "PermissionError" in rep.error and not list(t.folder.glob("*.md"))


# ------------------------------------------------------------------ CLI + morning integration
def _data(tmp_path):
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    (data / "inbox.txt").write_text("https://example.com/a\nhttps://youtu.be/V1\n", encoding="utf-8")
    return data


def test_morning_obsidian_flag_saves_note_and_remembers(tmp_path, monkeypatch, capsys):
    v = _vault(tmp_path)
    monkeypatch.setenv("OBSIDIAN_VAULT", str(v))
    data = _data(tmp_path)
    assert cli.main(["morning", "--sample", "--obsidian", "--data-dir", str(data)]) == 0
    notes = list((v / "NotebookLM").glob("*.md"))
    assert len(notes) == 1 and "sample" in _front(notes[0].read_text(encoding="utf-8"))["tags"]
    assert list((v / "NotebookLM" / "audio").iterdir())
    st = json.loads((data / "morning_state.sample.json").read_text(encoding="utf-8"))
    assert st["last_run"]["delivery"]["obsidian"]["status"] == "saved"
    capsys.readouterr()
    assert cli.main(["morning", "status", "--sample", "--data-dir", str(data)]) == 0
    assert "Obsidian: حُفظ" in capsys.readouterr().out


def test_morning_default_is_off_and_auto_env_turns_it_on(tmp_path, monkeypatch):
    v = _vault(tmp_path)
    monkeypatch.setenv("OBSIDIAN_VAULT", str(v))
    data = _data(tmp_path)
    assert cli.main(["morning", "--sample", "--data-dir", str(data)]) == 0
    assert not (v / "NotebookLM").exists()
    (data / "morning_state.sample.json").unlink()
    monkeypatch.setenv("NOTEBOOKLM_LAB_OBSIDIAN_AUTO", "1")
    assert cli.main(["morning", "--sample", "--no-obsidian", "--data-dir", str(data)]) == 0
    assert not (v / "NotebookLM").exists()
    (data / "morning_state.sample.json").unlink()
    assert cli.main(["morning", "--sample", "--data-dir", str(data)]) == 0
    assert list((v / "NotebookLM").glob("*.md"))


def test_morning_second_run_does_not_duplicate_and_unconfigured_is_soft(tmp_path, monkeypatch, capsys):
    data = _data(tmp_path)
    assert cli.main(["morning", "--sample", "--obsidian", "--data-dir", str(data)]) == 0  # no vault set
    assert "OBSIDIAN_VAULT" in capsys.readouterr().out
    v = _vault(tmp_path)
    monkeypatch.setenv("OBSIDIAN_VAULT", str(v))
    (data / "morning_state.sample.json").unlink()
    assert cli.main(["morning", "--sample", "--obsidian", "--data-dir", str(data)]) == 0
    (data / "inbox.txt").write_text((data / "inbox.txt").read_text(encoding="utf-8") + "https://example.com/new\n", encoding="utf-8")
    assert cli.main(["morning", "--sample", "--obsidian", "--data-dir", str(data)]) == 0
    names = sorted(p.name for p in (v / "NotebookLM").glob("*.md"))
    assert len(names) == 2 and len(set(names)) == 2  # every same-day run gets its own note (never an overwrite)
    assert names[0].endswith("(2).md") and names[1].endswith("(3).md")


def test_obsidian_failure_never_breaks_morning_and_telegram_still_runs(tmp_path, monkeypatch):
    from notebooklm_lab import telegram

    monkeypatch.setenv("OBSIDIAN_VAULT", str(_vault(tmp_path)))
    monkeypatch.setattr(obsidian, "save_deliverable", lambda *a, **k: 1 / 0)
    sent = []
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "1:" + "A" * 30)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "5")
    monkeypatch.setattr(telegram, "_post", lambda token, method, fields, file=None, timeout=60: sent.append(method) or {"ok": True, "result": {}})
    assert cli.main(["morning", "--sample", "--obsidian", "--telegram", "--data-dir", str(_data(tmp_path))]) == 0
    assert sent == ["sendMessage", "sendDocument"]


def test_cli_save_and_setup_check(tmp_path, monkeypatch, capsys):
    data = _data(tmp_path)
    v = _vault(tmp_path)
    assert cli.main(["obsidian", "setup-check", "--data-dir", str(data)]) == 2  # nothing configured
    assert cli.main(["obsidian", "save", "--sample", "--data-dir", str(data)]) == 2
    monkeypatch.setenv("OBSIDIAN_VAULT", str(v))
    assert cli.main(["obsidian", "save", "--sample", "--data-dir", str(data)]) == 2  # no morning result yet
    assert cli.main(["morning", "--sample", "--data-dir", str(data)]) == 0
    assert cli.main(["obsidian", "setup-check", "--data-dir", str(data), "--subfolder", "Podcasts"]) == 0
    assert cli.main(["obsidian", "save", "--sample", "--subfolder", "Podcasts", "--data-dir", str(data)]) == 0
    assert list((v / "Podcasts").glob("*.md"))
    assert cli.main(["obsidian", "save", "--sample", "--subfolder", "Podcasts", "--data-dir", str(data)]) == 0  # skip
    assert "موجودة مسبقًا" in capsys.readouterr().out
    assert cli.main(["obsidian", "save", "--sample", "--vault", str(tmp_path / "missing"), "--data-dir", str(data)]) == 2
    assert cli.main(["obsidian", "save", "--sample", "--subfolder", "L", "--no-audio", "--run", "nonexistent", "--data-dir", str(data)]) == 2


def test_setup_check_reports_unwritable_vault(tmp_path, monkeypatch):
    v = _vault(tmp_path)
    monkeypatch.setenv("OBSIDIAN_VAULT", str(v))
    monkeypatch.setattr(Path, "write_text", lambda *a, **k: (_ for _ in ()).throw(PermissionError("ro")))
    out = []
    assert obsidian.setup_check(tmp_path, say=out.append) == obsidian.EXIT_OBSIDIAN
