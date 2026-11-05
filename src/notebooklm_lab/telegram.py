"""Send the morning podcast + Arabic summary to a Telegram chat through YOUR OWN Telegram bot.

* Credentials come only from the environment / the local settings file: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID.
  The token is never printed, logged or stored anywhere else (error texts are scrubbed).
* Uses only the Python standard library (plain HTTPS to api.telegram.org).
* Telegram bots can upload files up to 50 MB: bigger audio is re-encoded smaller with ffmpeg when it is installed,
  otherwise the summary is sent with a short note. Every public function returns a result instead of raising,
  so a Telegram problem can never break a morning run."""
from __future__ import annotations

import json
import mimetypes
import re
import shutil
import subprocess
import tempfile
import time
import uuid
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import settings
from .deliver import Deliverable, markdown_to_plain

API = "https://api.telegram.org"
UPLOAD_LIMIT = 49 * 1024 * 1024  # Telegram says 50 MB for bots; keep a small margin
TEXT_LIMIT = 4000  # sendMessage allows 4096 characters
CAPTION_LIMIT = 1000  # captions allow 1024
MAX_MESSAGES = 6  # a very long summary is cut after this many messages (+ a note)
EXIT_TELEGRAM = 5
BITRATES_KBPS = (64, 48, 32, 24)
AUDIO_EXTS = {".mp3", ".m4a"}  # sendAudio accepts these; anything else goes as a document


class TelegramError(RuntimeError):
    """A Telegram call failed. The message is already scrubbed of the bot token."""


# ------------------------------------------------------------------ credentials
@dataclass
class Credentials:
    token: str
    chat_id: str


def credentials(base: Optional[Path] = None) -> Tuple[str, str]:
    return settings.get("TELEGRAM_BOT_TOKEN", base), settings.get("TELEGRAM_CHAT_ID", base)


def scrub(text: str, token: str) -> str:
    text = str(text)
    if token:
        text = text.replace(token, "<TOKEN>")
    return re.sub(r"bot\d{5,}:[A-Za-z0-9_\-]{20,}", "bot<TOKEN>", text)


# ------------------------------------------------------------------ HTTP layer (the only place that touches the network)
def _multipart(fields: Dict[str, str], file_field: str, file_path: Path) -> Tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    crlf = b"\r\n"
    parts: List[bytes] = []
    for k, v in fields.items():
        parts += [f"--{boundary}".encode(), f'Content-Disposition: form-data; name="{k}"'.encode(), b"", str(v).encode("utf-8")]
    ctype = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    safe_name = file_path.name.replace('"', "")
    parts += [
        f"--{boundary}".encode(),
        f'Content-Disposition: form-data; name="{file_field}"; filename="{safe_name}"'.encode("utf-8"),
        f"Content-Type: {ctype}".encode(),
        b"",
        file_path.read_bytes(),
        f"--{boundary}--".encode(),
        b"",
    ]
    return crlf.join(parts), f"multipart/form-data; boundary={boundary}"


def _post(token: str, method: str, fields: Dict[str, Any], file: Optional[Tuple[str, Path]] = None, timeout: float = 60.0) -> Dict[str, Any]:
    """POST one Bot API method; returns the decoded JSON (even for an `ok: false` answer). Raises TelegramError on network problems."""
    url = f"{API}/bot{token}/{method}"
    try:
        if file:
            body, ctype = _multipart({k: str(v) for k, v in fields.items()}, file[0], file[1])
            req = urllib.request.Request(url, data=body, headers={"Content-Type": ctype})
            timeout = max(timeout, 600.0)
        else:
            req = urllib.request.Request(url, data=json.dumps(fields).encode("utf-8"), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # Telegram answers 4xx with a JSON body that explains why
        try:
            return json.loads(exc.read().decode("utf-8"))
        except Exception:
            raise TelegramError(scrub(f"HTTP {exc.code}", token)) from None
    except (urllib.error.URLError, OSError, TimeoutError, ValueError) as exc:
        raise TelegramError(scrub(f"{type(exc).__name__}: {exc}", token)) from None


Poster = Callable[..., Dict[str, Any]]


def call(token: str, method: str, fields: Dict[str, Any], file: Optional[Tuple[str, Path]] = None,
         post: Optional[Poster] = None, sleep: Callable[[float], None] = time.sleep) -> Any:
    """One API call with a single polite retry when Telegram says 'too many requests'. Returns `result`."""
    post = post or _post
    for attempt in (1, 2):
        data = post(token, method, fields, file) if file else post(token, method, fields)
        if data.get("ok"):
            return data.get("result")
        wait = (data.get("parameters") or {}).get("retry_after")
        if data.get("error_code") == 429 and attempt == 1 and isinstance(wait, int) and wait <= 60:
            sleep(wait + 1)
            continue
        raise TelegramError(explain(data, token))
    raise TelegramError("unreachable")  # pragma: no cover


def explain(data: Dict[str, Any], token: str = "") -> str:
    code, desc = data.get("error_code"), str(data.get("description") or "")
    hint = ""
    low = desc.lower()
    if code == 401 or "unauthorized" in low:
        hint = " — التوكن غير صحيح (انسخه من @BotFather مرة أخرى)"
    elif "chat not found" in low:
        hint = " — رقم المحادثة خطأ، أو لم ترسل رسالة للبوت أولًا (أرسل /start للبوت ثم شغّل: telegram chat-id)"
    elif "bot was blocked" in low or code == 403:
        hint = " — البوت محظور أو لا يملك صلاحية الكتابة في هذه المحادثة"
    elif code == 413 or "too large" in low:
        hint = " — الملف أكبر من حد تيليجرام"
    return scrub(f"Telegram {code}: {desc}{hint}", token)


# ------------------------------------------------------------------ text helpers
def split_text(text: str, limit: int = TEXT_LIMIT) -> List[str]:
    """Cut at paragraph/line/space boundaries so no message exceeds the limit."""
    text = text.strip()
    chunks: List[str] = []
    while len(text) > limit:
        cut = max(text.rfind("\n\n", 0, limit), text.rfind("\n", 0, limit), text.rfind(" ", 0, limit))
        if cut < limit // 3:
            cut = limit
        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text:
        chunks.append(text)
    return chunks


def make_caption(d: Deliverable) -> str:
    cap = f"{'⚠ تجريبي (بيانات مثال) — ' if d.is_sample else ''}🎧 {d.title}"
    return cap[:CAPTION_LIMIT]


# ------------------------------------------------------------------ audio size handling
def shrink_audio(src: Path, limit: int = UPLOAD_LIMIT, which: Callable[[str], Optional[str]] = shutil.which,
                 runner: Callable[..., Any] = subprocess.run) -> Tuple[Optional[Path], str]:
    """Re-encode `src` as mono AAC (.m4a) at falling bitrates until it fits. Returns (new file, note) or (None, why not).
    Speech stays clear at 32 kbps. The original file is never touched; the new one is a temp file."""
    ff = which("ffmpeg")
    if not ff:
        return None, "ffmpeg غير مثبّت"
    tmpdir = Path(tempfile.mkdtemp(prefix="nblab-tg-"))
    for kbps in BITRATES_KBPS:
        out = tmpdir / f"{src.stem}-{kbps}k.m4a"
        try:
            r = runner([ff, "-y", "-loglevel", "error", "-i", str(src), "-vn", "-ac", "1", "-c:a", "aac", "-b:a", f"{kbps}k", str(out)],
                       capture_output=True, timeout=900)
        except (OSError, subprocess.SubprocessError) as exc:
            shutil.rmtree(tmpdir, ignore_errors=True)
            return None, f"فشل ffmpeg: {type(exc).__name__}"
        if getattr(r, "returncode", 1) != 0 or not out.is_file():
            shutil.rmtree(tmpdir, ignore_errors=True)
            return None, "فشل ffmpeg في ضغط الملف"
        if out.stat().st_size <= limit:
            return out, f"ضُغط الصوت إلى {kbps}kbps ليناسب حد تيليجرام"
    size = out.stat().st_size if out.is_file() else 0
    shutil.rmtree(tmpdir, ignore_errors=True)
    return None, f"حتى بعد الضغط ({size // (1024 * 1024)}MB) الملف أكبر من الحد"


# ------------------------------------------------------------------ sending
@dataclass
class SendReport:
    ok: bool  # everything that was asked got delivered
    sent_text: int = 0
    sent_audio: bool = False
    notes: List[str] = field(default_factory=list)
    error: Optional[str] = None

    def summary(self) -> str:
        bits = []
        if self.sent_text:
            bits.append(f"{self.sent_text} رسالة نصية")
        if self.sent_audio:
            bits.append("ملف صوتي")
        got = " + ".join(bits) or "لا شيء"
        extra = ("؛ " + "؛ ".join(self.notes)) if self.notes else ""
        return f"{'✔' if self.ok else '✘'} تيليجرام: أُرسل {got}{extra}" + (f" — {self.error}" if self.error else "")


def send_file(token: str, chat_id: str, path: Path, caption: str = "", post: Optional[Poster] = None,
              limit: int = UPLOAD_LIMIT, which: Callable[[str], Optional[str]] = shutil.which,
              runner: Callable[..., Any] = subprocess.run, sleep: Callable[[float], None] = time.sleep) -> SendReport:
    """Send one audio/document file. Too big -> try ffmpeg -> else a note instead. Never raises."""
    rep = SendReport(ok=False)
    tmp_to_remove: Optional[Path] = None
    try:
        if not path.is_file():
            rep.error = f"الملف غير موجود: {path}"
            return rep
        target = path
        if path.stat().st_size > limit:
            small, note = shrink_audio(path, limit, which, runner)
            if small is None:
                rep.notes.append(f"الملف {path.name} أكبر من 50MB ({note}) فلم يُرسل")
                try:
                    call(token, "sendMessage", {"chat_id": chat_id, "text": f"ملاحظة: الملف الصوتي ({path.name}) أكبر من حد تيليجرام (50MB) ولم يُرسل. هو محفوظ على جهازك."},
                         post=post, sleep=sleep)
                    rep.sent_text += 1
                except TelegramError as exc:
                    rep.error = str(exc)
                return rep
            target, tmp_to_remove = small, small.parent
            rep.notes.append(note)
        audio = target.suffix.lower() in AUDIO_EXTS
        fields = {"chat_id": chat_id, **({"caption": caption[:CAPTION_LIMIT]} if caption else {})}
        call(token, "sendAudio" if audio else "sendDocument", fields, file=("audio" if audio else "document", target), post=post, sleep=sleep)
        rep.sent_audio, rep.ok = True, True
    except TelegramError as exc:
        rep.error = str(exc)
    except Exception as exc:  # defensive: sending must never crash the caller
        rep.error = scrub(f"{type(exc).__name__}: {exc}", token)
    finally:
        if tmp_to_remove:
            shutil.rmtree(tmp_to_remove, ignore_errors=True)
    return rep


def send_deliverable(token: str, chat_id: str, d: Deliverable, post: Optional[Poster] = None, **kw: Any) -> SendReport:
    """Summary text first (split into several messages when long), then the audio with a short caption. Never raises."""
    sleep = kw.get("sleep", time.sleep)
    rep = SendReport(ok=True)
    try:
        sample_note = "⚠ تجريبي (بيانات مثال وليست من NotebookLM)\n" if d.is_sample else ""
        header = sample_note + d.title
        body = markdown_to_plain(d.summary_md) if d.summary_md else "(لا يوجد ملخص مكتوب في هذا التشغيل)"
        chunks = split_text(f"{header}\n\n{body}")
        if len(chunks) > MAX_MESSAGES:
            chunks = chunks[:MAX_MESSAGES] + ["… (الملخص طويل؛ النص الكامل محفوظ في مجلد التشغيل على جهازك)"]
            rep.notes.append("قُصّ الملخص لطوله")
        for c in chunks:
            call(token, "sendMessage", {"chat_id": chat_id, "text": c, "disable_web_page_preview": True}, post=post, sleep=sleep)
            rep.sent_text += 1
    except TelegramError as exc:
        rep.ok, rep.error = False, str(exc)
        return rep  # if text already fails (bad token/chat) there is no point uploading
    except Exception as exc:
        rep.ok, rep.error = False, scrub(f"{type(exc).__name__}: {exc}", token)
        return rep
    if d.audio_path is None:
        rep.notes.append("لا يوجد ملف صوتي في هذا التشغيل")
        return rep
    a = send_file(token, chat_id, d.audio_path, make_caption(d), post=post, **kw)
    rep.sent_audio, rep.notes = a.sent_audio, rep.notes + a.notes
    rep.sent_text += a.sent_text
    if not a.ok:
        rep.ok, rep.error = False, a.error or "الملف الصوتي لم يُرسل"
    return rep


def deliver_safely(d: Optional[Deliverable], base: Optional[Path], say: Callable[[str], None], post: Optional[Poster] = None, **kw: Any) -> Dict[str, Any]:
    """Used by `morning`: never raises, never changes the morning exit code. Returns a small dict for the state file."""
    token, chat = credentials(base)
    if d is None:
        say("تيليجرام: لا توجد نتيجة لإرسالها. / Telegram: nothing to send.")
        return {"status": "skipped"}
    if not token or not chat:
        say("⚠ تيليجرام مفعّل لكن TELEGRAM_BOT_TOKEN أو TELEGRAM_CHAT_ID غير مضبوط؛ تخطّيتُ الإرسال (الملخص لم يتأثر). جرّب: python -m notebooklm_lab telegram setup-check")
        return {"status": "not_configured"}
    rep = send_deliverable(token, chat, d, post=post, **kw)
    say(rep.summary() + ("\n   الملخص والملفات سليمة على جهازك؛ جرّب لاحقًا: python -m notebooklm_lab telegram send" if not rep.ok else ""))
    return {"status": "sent" if rep.ok else "failed", **({"error": rep.error} if rep.error else {})}


# ------------------------------------------------------------------ setup helpers
def setup_check(base: Optional[Path] = None, send_test: bool = False, post: Optional[Poster] = None,
                say: Callable[[str], None] = print) -> int:
    token, chat = credentials(base)
    if not token:
        say("✘ TELEGRAM_BOT_TOKEN غير مضبوط. أنشئ بوتًا من @BotFather (انظر README) ثم ضع التوكن في متغير البيئة أو في الملف:")
        say(f"   {settings.candidate_files(base)[0]}   (أنشئه بـ: python -m notebooklm_lab config init)")
        return 2
    say("التوكن موجود (لن يُعرض). أتحقق منه … / token is set (not shown), checking …")
    try:
        me = call(token, "getMe", {}, post=post)
    except TelegramError as exc:
        say(f"✘ التوكن مرفوض: {exc}")
        return EXIT_TELEGRAM
    say(f"✔ البوت يعمل: @{me.get('username')}")
    if not chat:
        say("✘ TELEGRAM_CHAT_ID غير مضبوط. أرسل أي رسالة (مثل /start) لبوتك من تيليجرام، ثم شغّل:  python -m notebooklm_lab telegram chat-id")
        return 2
    try:
        info = call(token, "getChat", {"chat_id": chat}, post=post)
    except TelegramError as exc:
        say(f"✘ لا أستطيع الوصول إلى المحادثة {chat}: {exc}")
        return EXIT_TELEGRAM
    name = info.get("title") or " ".join(x for x in (info.get("first_name"), info.get("last_name")) if x) or info.get("username") or ""
    say(f"✔ المحادثة موجودة: {name} ({info.get('type')})")
    if send_test:
        try:
            call(token, "sendMessage", {"chat_id": chat, "text": "✔ notebooklm-lab: رسالة اختبار — الاتصال يعمل."}, post=post)
            say("✔ أُرسلت رسالة اختبار؛ تحقق من تيليجرام.")
        except TelegramError as exc:
            say(f"✘ فشل إرسال رسالة الاختبار: {exc}")
            return EXIT_TELEGRAM
    else:
        say("لإرسال رسالة اختبار فعلية أضف:  --send-test")
    say(f"ffmpeg (لضغط الملفات الكبيرة): {'موجود ✔' if shutil.which('ffmpeg') else 'غير موجود — الملفات الأكبر من 50MB لن تُرسل (يُرسل الملخص فقط)'}")
    return 0


def find_chat_ids(base: Optional[Path] = None, post: Optional[Poster] = None, say: Callable[[str], None] = print) -> int:
    """List chats that recently wrote to the bot (names/ids only, never message text) so the user can copy the chat id."""
    token, _ = credentials(base)
    if not token:
        say("✘ TELEGRAM_BOT_TOKEN غير مضبوط.")
        return 2
    try:
        updates = call(token, "getUpdates", {"limit": 100, "timeout": 0}, post=post)
    except TelegramError as exc:
        say(f"✘ {exc}")
        return EXIT_TELEGRAM
    seen: Dict[int, str] = {}
    for u in updates or []:
        msg = u.get("message") or u.get("channel_post") or u.get("edited_message") or u.get("my_chat_member") or {}
        chat = msg.get("chat") or {}
        if "id" in chat:
            seen[chat["id"]] = chat.get("title") or " ".join(x for x in (chat.get("first_name"), chat.get("last_name")) if x) or chat.get("username") or "?"
    if not seen:
        say("لم أجد أي محادثة. افتح بوتك في تيليجرام، اضغط Start وأرسل أي رسالة، ثم أعد الأمر. / No chats yet: open your bot, press Start, send a message, run again.")
        return 1
    say("المحادثات التي راسلت البوت (انسخ الرقم إلى TELEGRAM_CHAT_ID):")
    for cid, name in seen.items():
        say(f"   TELEGRAM_CHAT_ID={cid}    ({name})")
    return 0
