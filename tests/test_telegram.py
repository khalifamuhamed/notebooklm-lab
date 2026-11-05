import json
import shutil
import subprocess
import urllib.error
from pathlib import Path

import pytest

from notebooklm_lab import cli, deliver, settings, telegram
from notebooklm_lab.deliver import Deliverable

TOKEN = "123456789:AAEhBP0av28dummyTOKENdummyTOKEN0000"
CHAT = "424242"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "NOTEBOOKLM_LAB_TELEGRAM_AUTO", "NOTEBOOKLM_LAB_ENV_FILE"):
        monkeypatch.delenv(k, raising=False)


class FakeAPI:
    """Stands in for Telegram: records every call, answers like the Bot API."""

    def __init__(self, replies=None):
        self.calls = []
        self.replies = replies or {}

    def __call__(self, token, method, fields, file=None, timeout=60.0):
        self.calls.append({"token": token, "method": method, "fields": dict(fields), "file": file})
        r = self.replies.get(method)
        if callable(r):
            r = r(len(self.calls))
        if isinstance(r, Exception):
            raise r
        return r if r is not None else {"ok": True, "result": {"username": "my_lab_bot", "id": 1, "type": "private", "first_name": "Muhamed"}}

    def methods(self):
        return [c["method"] for c in self.calls]


def _deliverable(tmp_path, audio_name="audio.m4a", audio_bytes=b"x" * 100, summary="# ملخص\n\n- **نقطة** أولى\n- نقطة ثانية", sample=False):
    audio = None
    if audio_name:
        audio = tmp_path / audio_name
        audio.write_bytes(audio_bytes)
    return Deliverable(title="ملخص صباحي 2026-11-03", day="2026-11-03", mode="sample" if sample else "real",
                       summary_md=summary, audio_path=audio, sources=["https://example.com/a"])


# ------------------------------------------------------------------ settings file + env
def test_settings_env_beats_file_and_file_is_fallback(tmp_path, monkeypatch):
    base = tmp_path / "d"
    base.mkdir()
    (base / settings.ENV_FILE_NAME).write_text("\ufeff# c\nTELEGRAM_BOT_TOKEN = \"abc\"\nTELEGRAM_CHAT_ID=77 # note\nexport NOTEBOOKLM_LAB_TELEGRAM_AUTO=1\n", encoding="utf-8")
    assert settings.get("TELEGRAM_BOT_TOKEN", base) == "abc"
    assert settings.get("TELEGRAM_CHAT_ID", base) == "77"
    assert settings.flag("NOTEBOOKLM_LAB_TELEGRAM_AUTO", base) is True
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "from-env")
    assert settings.get("TELEGRAM_BOT_TOKEN", base) == "from-env"
    assert settings.get("MISSING", base, "dflt") == "dflt"


def test_config_init_creates_empty_template_once_and_show_masks_secret(tmp_path, capsys):
    base = tmp_path / "d"
    assert cli.main(["config", "init", "--data-dir", str(base)]) == 0
    f = base / settings.ENV_FILE_NAME
    text = f.read_text(encoding="utf-8")
    assert "TELEGRAM_BOT_TOKEN=\n" in text and TOKEN not in text
    f.write_text(text.replace("TELEGRAM_BOT_TOKEN=\n", f"TELEGRAM_BOT_TOKEN={TOKEN}\n"), encoding="utf-8")
    assert cli.main(["config", "init", "--data-dir", str(base)]) == 0  # never overwrites
    assert TOKEN in f.read_text(encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["config", "show", "--data-dir", str(base)]) == 0
    out = capsys.readouterr().out
    assert TOKEN not in out and "TELEGRAM_BOT_TOKEN" in out and "chars" in out


# ------------------------------------------------------------------ text helpers
def test_split_text_respects_limit_and_keeps_all_words():
    text = "\n\n".join(f"فقرة رقم {i} " + "كلمة " * 120 for i in range(12))
    chunks = telegram.split_text(text, 1000)
    assert all(len(c) <= 1000 for c in chunks) and len(chunks) > 1
    assert " ".join("".join(chunks).split()).count("فقرة") == 12
    assert telegram.split_text("short") == ["short"]
    assert all(len(c) <= 50 for c in telegram.split_text("x" * 500, 50))  # no spaces at all -> hard cut


def test_markdown_to_plain():
    md = "# عنوان\n\n- **مهم** جدًا\n* نقطة [رابط](https://e.com/x)\n\n\n\n`code` و __قوي__"
    plain = deliver.markdown_to_plain(md)
    assert plain == "عنوان\n\n• مهم جدًا\n• نقطة رابط (https://e.com/x)\n\ncode و قوي"


def test_scrub_removes_token_and_token_shaped_text():
    assert TOKEN not in telegram.scrub(f"failed https://api.telegram.org/bot{TOKEN}/sendMessage", TOKEN)
    assert TOKEN not in telegram.scrub(f"failed bot{TOKEN}/x", "")


# ------------------------------------------------------------------ network layer
def test_multipart_contains_fields_and_file_bytes(tmp_path):
    f = tmp_path / "a b.m4a"
    f.write_bytes(b"\x00\x01DATA")
    body, ctype = telegram._multipart({"chat_id": "1", "caption": "عنوان"}, "audio", f)
    boundary = ctype.split("boundary=")[1]
    assert body.count(f"--{boundary}".encode()) == 4 and body.endswith(f"--{boundary}--\r\n".encode())
    assert b'name="chat_id"\r\n\r\n1' in body and "عنوان".encode() in body
    assert b'name="audio"; filename="a b.m4a"' in body and b"\x00\x01DATA" in body


def test_network_error_never_leaks_token(monkeypatch):
    def boom(req, timeout=None):
        raise urllib.error.URLError(f"cannot reach https://api.telegram.org/bot{TOKEN}/getMe")

    monkeypatch.setattr(telegram.urllib.request, "urlopen", boom)
    with pytest.raises(telegram.TelegramError) as ei:
        telegram._post(TOKEN, "getMe", {})
    assert TOKEN not in str(ei.value)


def test_http_error_body_is_decoded(monkeypatch):
    import io

    def err(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, io.BytesIO(b'{"ok":false,"error_code":401,"description":"Unauthorized"}'))

    monkeypatch.setattr(telegram.urllib.request, "urlopen", err)
    assert telegram._post(TOKEN, "getMe", {})["error_code"] == 401


def test_rate_limit_is_retried_once():
    slept = []
    seq = [{"ok": False, "error_code": 429, "description": "Too Many Requests", "parameters": {"retry_after": 2}}, {"ok": True, "result": 1}]
    api = FakeAPI({"sendMessage": lambda n: seq[n - 1]})
    assert telegram.call(TOKEN, "sendMessage", {"chat_id": CHAT, "text": "x"}, post=api, sleep=slept.append) == 1
    assert slept == [3] and len(api.calls) == 2
    always = FakeAPI({"sendMessage": {"ok": False, "error_code": 429, "description": "Too Many Requests", "parameters": {"retry_after": 1}}})
    with pytest.raises(telegram.TelegramError):
        telegram.call(TOKEN, "sendMessage", {}, post=always, sleep=lambda s: None)
    assert len(always.calls) == 2


def test_error_explanations_are_helpful_arabic():
    assert "BotFather" in telegram.explain({"error_code": 401, "description": "Unauthorized"})
    assert "chat-id" in telegram.explain({"error_code": 400, "description": "Bad Request: chat not found"})


# ------------------------------------------------------------------ setup-check / chat-id
def test_setup_check_ok_with_test_message(tmp_path, monkeypatch):
    base = tmp_path / "d"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CHAT)
    api, out = FakeAPI(), []
    assert telegram.setup_check(base, send_test=True, post=api, say=out.append) == 0
    assert api.methods() == ["getMe", "getChat", "sendMessage"]
    text = "\n".join(out)
    assert "@my_lab_bot" in text and TOKEN not in text


def test_setup_check_missing_token_and_chat_and_bad_token(tmp_path, monkeypatch):
    base = tmp_path / "d"
    out = []
    assert telegram.setup_check(base, post=FakeAPI(), say=out.append) == 2
    assert "config init" in "\n".join(out)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    api = FakeAPI()
    assert telegram.setup_check(base, post=api, say=out.append) == 2 and api.methods() == ["getMe"]  # no chat id
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CHAT)
    bad = FakeAPI({"getMe": {"ok": False, "error_code": 401, "description": "Unauthorized"}})
    out.clear()
    assert telegram.setup_check(base, post=bad, say=out.append) == telegram.EXIT_TELEGRAM
    assert TOKEN not in "\n".join(out)
    nochat = FakeAPI({"getChat": {"ok": False, "error_code": 400, "description": "Bad Request: chat not found"}})
    assert telegram.setup_check(base, post=nochat, say=out.append) == telegram.EXIT_TELEGRAM


def test_find_chat_ids_lists_ids_and_names_but_never_message_text(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    upd = {"ok": True, "result": [
        {"update_id": 1, "message": {"text": "SECRET WORDS", "chat": {"id": 555, "first_name": "Muhamed", "type": "private"}}},
        {"update_id": 2, "message": {"text": "again", "chat": {"id": 555, "first_name": "Muhamed", "type": "private"}}},
        {"update_id": 3, "message": {"chat": {"id": -100123, "title": "Group", "type": "supergroup"}}},
    ]}
    out = []
    assert telegram.find_chat_ids(post=FakeAPI({"getUpdates": upd}), say=out.append) == 0
    text = "\n".join(out)
    assert "TELEGRAM_CHAT_ID=555" in text and "TELEGRAM_CHAT_ID=-100123" in text and "SECRET WORDS" not in text
    assert text.count("=555") == 1
    out.clear()
    assert telegram.find_chat_ids(post=FakeAPI({"getUpdates": {"ok": True, "result": []}}), say=out.append) == 1


# ------------------------------------------------------------------ sending
def test_send_deliverable_text_then_audio_with_short_caption(tmp_path):
    api = FakeAPI()
    rep = telegram.send_deliverable(TOKEN, CHAT, _deliverable(tmp_path), post=api)
    assert rep.ok and rep.sent_audio and rep.sent_text == 1
    assert api.methods() == ["sendMessage", "sendAudio"]
    assert "نقطة أولى" in api.calls[0]["fields"]["text"] and "**" not in api.calls[0]["fields"]["text"]
    assert api.calls[1]["fields"]["chat_id"] == CHAT and api.calls[1]["file"][0] == "audio"
    assert "🎧" in api.calls[1]["fields"]["caption"] and len(api.calls[1]["fields"]["caption"]) <= 1024


def test_wav_goes_as_document_and_sample_is_labelled(tmp_path):
    api = FakeAPI()
    telegram.send_deliverable(TOKEN, CHAT, _deliverable(tmp_path, "tone.wav", sample=True), post=api)
    assert api.methods() == ["sendMessage", "sendDocument"]
    assert "تجريبي" in api.calls[0]["fields"]["text"] and "تجريبي" in api.calls[1]["fields"]["caption"]


def test_long_summary_is_split_and_capped(tmp_path):
    api = FakeAPI()
    long = "\n\n".join("فقرة " + "كلمة " * 150 for _ in range(60))
    rep = telegram.send_deliverable(TOKEN, CHAT, _deliverable(tmp_path, summary=long), post=api)
    texts = [c["fields"]["text"] for c in api.calls if c["method"] == "sendMessage"]
    assert len(texts) == telegram.MAX_MESSAGES + 1 and all(len(t) <= 4096 for t in texts) and rep.ok
    assert "قُصّ" in " ".join(rep.notes)


def test_no_audio_still_sends_summary(tmp_path):
    api = FakeAPI()
    rep = telegram.send_deliverable(TOKEN, CHAT, _deliverable(tmp_path, audio_name=None), post=api)
    assert rep.ok and api.methods() == ["sendMessage"] and not rep.sent_audio


def test_text_failure_stops_before_upload(tmp_path):
    api = FakeAPI({"sendMessage": {"ok": False, "error_code": 400, "description": "Bad Request: chat not found"}})
    rep = telegram.send_deliverable(TOKEN, CHAT, _deliverable(tmp_path), post=api)
    assert not rep.ok and api.methods() == ["sendMessage"] and "chat not found" in rep.error


def test_audio_failure_is_reported_not_raised(tmp_path):
    api = FakeAPI({"sendAudio": telegram.TelegramError("timed out")})
    rep = telegram.send_deliverable(TOKEN, CHAT, _deliverable(tmp_path), post=api)
    assert not rep.ok and rep.sent_text == 1 and "timed out" in rep.error


def test_too_big_without_ffmpeg_sends_note_instead(tmp_path):
    api = FakeAPI()
    rep = telegram.send_deliverable(TOKEN, CHAT, _deliverable(tmp_path, audio_bytes=b"x" * 5000), post=api, limit=1000, which=lambda n: None)
    assert api.methods() == ["sendMessage", "sendMessage"] and not rep.sent_audio
    assert "50MB" in api.calls[1]["fields"]["text"] and rep.notes and not rep.ok


def test_too_big_uses_ffmpeg_when_available_and_cleans_up(tmp_path):
    made = []

    def fake_run(argv, **kw):
        out = Path(argv[-1])
        kbps = int(argv[argv.index("-b:a") + 1][:-1])
        out.write_bytes(b"y" * (200 if kbps <= 48 else 5000))  # 64k still too big, 48k fits
        made.append(out)
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    api = FakeAPI()
    rep = telegram.send_deliverable(TOKEN, CHAT, _deliverable(tmp_path, audio_bytes=b"x" * 9000), post=api, limit=1000,
                                    which=lambda n: "/usr/bin/ffmpeg", runner=fake_run)
    assert rep.ok and rep.sent_audio and "48kbps" in " ".join(rep.notes)
    assert api.methods() == ["sendMessage", "sendAudio"] and api.calls[1]["file"][1].suffix == ".m4a"
    assert made and not made[0].parent.exists()  # temp folder removed
    assert (tmp_path / "audio.m4a").read_bytes() == b"x" * 9000  # original untouched


def test_ffmpeg_failure_and_never_small_enough_fall_back_to_note(tmp_path):
    def bad(argv, **kw):
        return subprocess.CompletedProcess(argv, 1, b"", b"err")

    d = _deliverable(tmp_path, audio_bytes=b"x" * 9000)
    api = FakeAPI()
    rep = telegram.send_deliverable(TOKEN, CHAT, d, post=api, limit=1000, which=lambda n: "ff", runner=bad)
    assert not rep.sent_audio and api.methods() == ["sendMessage", "sendMessage"]

    def big(argv, **kw):
        Path(argv[-1]).write_bytes(b"z" * 5000)
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    api2 = FakeAPI()
    rep2 = telegram.send_deliverable(TOKEN, CHAT, d, post=api2, limit=1000, which=lambda n: "ff", runner=big)
    assert not rep2.sent_audio and "الحد" in " ".join(rep2.notes)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed here")
def test_real_ffmpeg_shrinks_a_wav(tmp_path):
    from notebooklm_lab.sample_backend import _tone_wav

    wav = tmp_path / "t.wav"
    _tone_wav(wav, seconds=20, rate=16000)  # ~640 KB
    out, note = telegram.shrink_audio(wav, limit=300_000)
    assert out is not None and out.suffix == ".m4a" and out.stat().st_size <= 300_000 and "kbps" in note
    shutil.rmtree(out.parent)


def test_send_file_missing_file_is_a_clean_failure(tmp_path):
    rep = telegram.send_file(TOKEN, CHAT, tmp_path / "nope.m4a", post=FakeAPI())
    assert not rep.ok and "غير موجود" in rep.error


def test_real_http_roundtrip_against_a_local_fake_telegram_server(tmp_path, monkeypatch):
    """The real _post code (JSON + multipart) talks to a tiny local HTTP server that imitates api.telegram.org."""
    import threading
    from email.parser import BytesParser
    from email.policy import default
    from http.server import BaseHTTPRequestHandler, HTTPServer

    seen = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            ctype = self.headers["Content-Type"]
            if ctype.startswith("multipart"):
                msg = BytesParser(policy=default).parsebytes(b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + body)
                parts = {p.get_param("name", header="content-disposition"): p.get_payload(decode=True) for p in msg.iter_parts()}
                seen.append((self.path, parts))
            else:
                seen.append((self.path, json.loads(body)))
            out = b'{"ok":true,"result":{"message_id":1}}'
            self.send_response(200)
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(telegram, "API", f"http://127.0.0.1:{srv.server_port}")
    try:
        f = tmp_path / "p.m4a"
        f.write_bytes(b"AUDIO-BYTES")
        rep = telegram.send_deliverable(TOKEN, CHAT, _deliverable(tmp_path, summary="نص عربي"), post=None)
    finally:
        srv.shutdown()
    assert rep.ok
    (p1, j), (p2, parts) = seen
    assert p1 == f"/bot{TOKEN}/sendMessage" and "نص عربي" in j["text"]
    assert p2 == f"/bot{TOKEN}/sendAudio" and parts["chat_id"] == CHAT.encode() and parts["audio"] == b"x" * 100
    assert "🎧".encode() in parts["caption"]


# ------------------------------------------------------------------ deliverable from a real sample run
def _sample_morning(tmp_path, extra=()):
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    (data / "inbox.txt").write_text("https://example.com/a\nhttps://youtu.be/V1\n", encoding="utf-8")
    return data


def test_deliverable_from_sample_run_dir(tmp_path):
    data = _sample_morning(tmp_path)
    assert cli.main(["morning", "--sample", "--data-dir", str(data)]) == 0
    d = deliver.latest(data / "morning-sample")
    assert d and d.is_sample and d.day and d.audio_path and d.audio_path.is_file() and "ملخص" in d.summary_md
    assert d.sources == ["https://example.com/a", "https://youtu.be/V1"]
    assert deliver.from_run_dir(tmp_path) is None


# ------------------------------------------------------------------ CLI + morning integration
def _configure(monkeypatch, api):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CHAT)
    monkeypatch.setattr(telegram, "_post", api)


def test_morning_without_flag_sends_nothing(tmp_path, monkeypatch):
    api = FakeAPI()
    _configure(monkeypatch, api)
    assert cli.main(["morning", "--sample", "--data-dir", str(_sample_morning(tmp_path))]) == 0
    assert api.calls == []


def test_morning_telegram_flag_sends_summary_and_audio(tmp_path, monkeypatch, capsys):
    api = FakeAPI()
    _configure(monkeypatch, api)
    data = _sample_morning(tmp_path)
    assert cli.main(["morning", "--sample", "--telegram", "--data-dir", str(data)]) == 0
    assert api.methods() == ["sendMessage", "sendDocument"]  # sample audio is a .wav
    out = capsys.readouterr().out
    assert "تيليجرام" in out and TOKEN not in out
    state = json.loads((data / "morning_state.sample.json").read_text(encoding="utf-8"))
    assert state["last_run"]["delivery"]["telegram"]["status"] == "sent"
    # second run: no new links -> nothing is sent again
    api.calls.clear()
    assert cli.main(["morning", "--sample", "--telegram", "--data-dir", str(data)]) == 0
    assert api.calls == []


def test_morning_auto_env_flag_and_no_telegram_override(tmp_path, monkeypatch):
    api = FakeAPI()
    _configure(monkeypatch, api)
    monkeypatch.setenv("NOTEBOOKLM_LAB_TELEGRAM_AUTO", "1")
    data = _sample_morning(tmp_path)
    assert cli.main(["morning", "--sample", "--no-telegram", "--data-dir", str(data)]) == 0
    assert api.calls == []
    (data / "morning_state.sample.json").unlink()
    assert cli.main(["morning", "--sample", "--data-dir", str(data)]) == 0
    assert api.methods() == ["sendMessage", "sendDocument"]


def test_telegram_failure_never_breaks_the_morning_run(tmp_path, monkeypatch, capsys):
    api = FakeAPI({"sendMessage": telegram.TelegramError("network down")})
    _configure(monkeypatch, api)
    data = _sample_morning(tmp_path)
    assert cli.main(["morning", "--sample", "--telegram", "--data-dir", str(data)]) == 0
    assert "✘ تيليجرام" in capsys.readouterr().out
    state = json.loads((data / "morning_state.sample.json").read_text(encoding="utf-8"))
    assert state["last_success"]["delivery"]["telegram"]["status"] == "failed"
    assert list((data / "morning-sample").iterdir())  # run output kept
    capsys.readouterr()
    assert cli.main(["morning", "status", "--sample", "--data-dir", str(data)]) == 0
    assert "تيليجرام: فشل" in capsys.readouterr().out


def test_unexpected_exception_inside_telegram_is_swallowed(tmp_path, monkeypatch):
    _configure(monkeypatch, FakeAPI())
    monkeypatch.setattr(telegram, "send_deliverable", lambda *a, **k: 1 / 0)
    assert cli.main(["morning", "--sample", "--telegram", "--data-dir", str(_sample_morning(tmp_path))]) == 0


def test_telegram_flag_without_credentials_is_a_soft_warning(tmp_path, capsys):
    assert cli.main(["morning", "--sample", "--telegram", "--data-dir", str(_sample_morning(tmp_path))]) == 0
    assert "TELEGRAM_BOT_TOKEN" in capsys.readouterr().out


def test_credentials_can_come_from_the_local_settings_file(tmp_path, monkeypatch):
    api = FakeAPI()
    monkeypatch.setattr(telegram, "_post", api)
    data = _sample_morning(tmp_path)
    (data / settings.ENV_FILE_NAME).write_text(f"TELEGRAM_BOT_TOKEN={TOKEN}\nTELEGRAM_CHAT_ID={CHAT}\n", encoding="utf-8")
    assert cli.main(["morning", "--sample", "--telegram", "--data-dir", str(data)]) == 0
    assert api.calls and api.calls[0]["token"] == TOKEN


def test_cli_send_file_latest_and_errors(tmp_path, monkeypatch, capsys):
    data = _sample_morning(tmp_path)
    assert cli.main(["telegram", "send", "--data-dir", str(data)]) == 2  # no credentials
    api = FakeAPI()
    _configure(monkeypatch, api)
    assert cli.main(["telegram", "send", "--sample", "--data-dir", str(data)]) == 2  # nothing to send yet
    assert cli.main(["morning", "--sample", "--data-dir", str(data)]) == 0
    assert cli.main(["telegram", "send", "--sample", "--data-dir", str(data)]) == 0
    assert api.methods() == ["sendMessage", "sendDocument"]
    api.calls.clear()
    f = tmp_path / "x.mp3"
    f.write_bytes(b"1")
    assert cli.main(["telegram", "send", str(f), "--caption", "hello", "--data-dir", str(data)]) == 0
    assert api.methods() == ["sendAudio"] and api.calls[0]["fields"]["caption"] == "hello"
    bad = FakeAPI({"sendAudio": {"ok": False, "error_code": 500, "description": "boom"}})
    monkeypatch.setattr(telegram, "_post", bad)
    assert cli.main(["telegram", "send", str(f)]) == telegram.EXIT_TELEGRAM


def test_cli_setup_check_and_chat_id(tmp_path, monkeypatch, capsys):
    api = FakeAPI({"getUpdates": {"ok": True, "result": [{"update_id": 1, "message": {"chat": {"id": 9, "first_name": "M"}}}]}})
    _configure(monkeypatch, api)
    assert cli.main(["telegram", "setup-check", "--send-test", "--data-dir", str(tmp_path)]) == 0
    assert cli.main(["telegram", "chat-id", "--data-dir", str(tmp_path)]) == 0
    assert "TELEGRAM_CHAT_ID=9" in capsys.readouterr().out


# ------------------------------------------------------------------ hygiene
def test_env_example_has_names_only_and_is_not_ignored():
    from notebooklm_lab.config import repo_root

    root = repo_root()
    text = (root / ".env.example").read_text(encoding="utf-8")
    for name in settings.KNOWN:
        assert f"{name}=\n" in text, name
    assert all(line.split("=", 1)[1].strip() == "" for line in text.splitlines() if line and not line.startswith("#"))
    if (root / ".git").exists():
        r = subprocess.run(["git", "-C", str(root), "check-ignore", "-q", ".env.example"])
        assert r.returncode == 1  # not ignored
        for n in ("notebooklm-lab.env", ".env"):
            assert subprocess.run(["git", "-C", str(root), "check-ignore", "-q", n]).returncode == 0
