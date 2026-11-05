"""Follow YouTube channels: new videos are appended to your `inbox.txt`, so the morning digest picks them up.

No YouTube account, no API key: it reads YouTube's public RSS feed of each channel
(https://www.youtube.com/feeds/videos.xml?channel_id=...). A `@handle` is turned into the channel id by reading the
public channel page. State lives in `<data dir>/channels.json` (followed channels + the video ids already seen).

Safety rules: a channel that is added only reports videos published AFTER it was added (unless `--backfill N`);
links already in the inbox or already processed by `morning` are never added again; one failing channel never
stops the others; nothing here touches your NotebookLM login."""
from __future__ import annotations

import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import inbox as ib
from . import settings
from .config import data_dir

STATE_NAME = "channels.json"
FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={}"
WATCH_URL = "https://www.youtube.com/watch?v={}"
CHANNEL_ID_RE = re.compile(r"^UC[0-9A-Za-z_-]{22}$")
MAX_SEEN = 300  # video ids remembered per channel (the RSS feed only shows the latest 15)
DEFAULT_MAX_PER_CHANNEL = 5
MAX_BYTES = 3_000_000
UA = "Mozilla/5.0 (compatible; notebooklm-lab channel follower; +https://github.com/khalifamuhamed/notebooklm-lab)"
EXIT_OK, EXIT_USAGE, EXIT_FAILED = 0, 2, 4


class ChannelError(RuntimeError):
    pass


class NetworkError(ChannelError):
    """YouTube could not be reached / answered an error (as opposed to bad input from the user)."""

    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


Fetcher = Callable[[str], str]


def http_get(url: str, timeout: float = 20.0) -> str:
    """Plain GET of a public page/feed (the only network code in this module)."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en", "Cookie": "CONSENT=YES+1; SOCS=CAI"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise NetworkError(f"HTTP {exc.code} من {urllib.parse.urlsplit(url).netloc}", exc.code) from None
    except (urllib.error.URLError, OSError, TimeoutError, ValueError) as exc:
        raise NetworkError(f"تعذّر الاتصال: {type(exc).__name__}") from None
    if len(raw) > MAX_BYTES:
        raise NetworkError("الاستجابة أكبر من المتوقع")
    return raw.decode("utf-8", "replace")


# ------------------------------------------------------------------ resolving what the user typed
@dataclass
class Ref:
    channel_id: Optional[str] = None
    page_url: Optional[str] = None  # a channel page to read when only a handle/name is known
    handle: Optional[str] = None


def _q(part: str) -> str:
    """URL-encode a handle/name (Arabic handles work) but keep the leading @ readable."""
    return urllib.parse.quote(urllib.parse.unquote(part), safe="@")


def parse_ref(text: str) -> Ref:
    """`UC...` id, channel URL, `@handle`, youtube.com/@handle, /c/name, /user/name -> something we can resolve."""
    t = text.strip().strip('"').strip("'")
    if not t:
        raise ChannelError("اكتب رابط القناة أو @handle")
    if CHANNEL_ID_RE.match(t):
        return Ref(channel_id=t)
    if t.startswith("@") and len(t) > 1 and "/" not in t:
        return Ref(page_url=f"https://www.youtube.com/{_q(t)}", handle=t)
    if not re.match(r"^https?://", t) and re.match(r"^(www\.|m\.)?youtube\.com/", t):
        t = "https://" + t
    u = urllib.parse.urlsplit(t)
    host = u.netloc.lower().split(":")[0]
    if u.scheme in ("http", "https") and host in ("youtube.com", "www.youtube.com", "m.youtube.com"):
        path = urllib.parse.unquote(u.path)
        m = re.match(r"^/channel/(UC[0-9A-Za-z_-]{22})(?:/|$)", path)
        if m:
            return Ref(channel_id=m.group(1))
        m = re.match(r"^/(@[^/\s]+)", path)
        if m:
            return Ref(page_url=f"https://www.youtube.com/{_q(m.group(1))}", handle=m.group(1))
        m = re.match(r"^/(c|user)/([^/\s]+)", path)
        if m:
            return Ref(page_url=f"https://www.youtube.com/{m.group(1)}/{_q(m.group(2))}")
        if path.startswith(("/watch", "/shorts", "/live", "/playlist")):
            raise ChannelError("هذا رابط فيديو/قائمة، وأحتاج رابط القناة نفسها (مثل https://www.youtube.com/@name) أو @handle")
    raise ChannelError(f"لم أفهم «{text}». استعمل @handle أو رابط قناة يوتيوب أو المعرّف الذي يبدأ بـ UC")


_ID_PATTERNS = (
    r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[0-9A-Za-z_-]{22})"',
    r'<meta itemprop="(?:identifier|channelId)" content="(UC[0-9A-Za-z_-]{22})"',
    r'"externalId":"(UC[0-9A-Za-z_-]{22})"',
    r'"channelId":"(UC[0-9A-Za-z_-]{22})"',
    r'"browseId":"(UC[0-9A-Za-z_-]{22})"',
)


def extract_channel_id(page: str) -> Optional[str]:
    for pat in _ID_PATTERNS:  # most reliable first: the page's own canonical/identifier
        m = re.search(pat, page)
        if m:
            return m.group(1)
    return None


def resolve(ref: Ref, fetch: Optional[Fetcher] = None) -> str:
    fetch = fetch or http_get
    if ref.channel_id:
        return ref.channel_id
    try:
        page = fetch(ref.page_url or "")
    except NetworkError as exc:
        if exc.status == 404:
            raise ChannelError(f"لم أجد قناة بهذا الاسم ({ref.handle or ref.page_url}). تأكد من كتابة @handle كما يظهر في صفحة القناة.") from None
        raise
    cid = extract_channel_id(page)
    if not cid:
        raise ChannelError("لم أجد معرّف القناة في الصفحة (هل الاسم صحيح؟ أو جرّب رابط القناة الذي يحتوي /channel/UC…)")
    return cid


# ------------------------------------------------------------------ the RSS feed
@dataclass
class Video:
    id: str
    title: str
    published: str  # ISO timestamp from the feed

    @property
    def url(self) -> str:
        return WATCH_URL.format(self.id)


_NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}


def parse_feed(xml_text: str) -> Tuple[str, List[Video]]:
    """(channel title, videos newest first as in the feed)."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ChannelError(f"ملف RSS غير صالح ({exc})") from None
    title = (root.findtext("a:title", default="", namespaces=_NS) or "").strip()
    vids: List[Video] = []
    for e in root.findall("a:entry", _NS):
        vid = (e.findtext("yt:videoId", default="", namespaces=_NS) or "").strip()
        if not re.match(r"^[0-9A-Za-z_-]{6,20}$", vid):
            continue
        vids.append(Video(vid, " ".join((e.findtext("a:title", default="", namespaces=_NS) or "").split()),
                          (e.findtext("a:published", default="", namespaces=_NS) or "").strip()))
    return title, vids


def fetch_feed(channel_id: str, fetch: Optional[Fetcher] = None, sleep: Callable[[float], None] = time.sleep) -> Tuple[str, List[Video]]:
    """YouTube's feed endpoint is known to answer a temporary 404/500 for perfectly good channels, so try 3 times."""
    fetch = fetch or http_get
    last: Optional[ChannelError] = None
    for attempt in (1, 2, 3):
        try:
            return parse_feed(fetch(FEED_URL.format(channel_id)))
        except ChannelError as exc:
            last = exc
            if attempt < 3:
                sleep(2.0 * attempt)
    raise last or ChannelError("unknown")


# ------------------------------------------------------------------ state
def state_path(base: Optional[Path] = None) -> Path:
    return (Path(base).expanduser().resolve() if base else data_dir()) / STATE_NAME


def load(base: Optional[Path] = None) -> Dict[str, Any]:
    p = state_path(base)
    if not p.exists():
        return {"version": 1, "channels": {}}
    import json

    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("channels"), dict):
            raise ValueError("unexpected structure")
        return data
    except (OSError, ValueError) as exc:
        raise ChannelError(f"ملف القنوات تالف أو غير قابل للقراءة: {p} ({exc}). أصلحه أو احذفه (ستفقد قائمة القنوات).") from None


def save(state: Dict[str, Any], base: Optional[Path] = None) -> None:
    ib.save_state(state_path(base), state)  # same atomic write as the morning state


# ------------------------------------------------------------------ commands
def add(text: str, base: Optional[Path] = None, backfill: int = 0, fetch: Optional[Fetcher] = None,
        say: Callable[[str], None] = print, sleep: Callable[[float], None] = time.sleep) -> int:
    try:
        ref = parse_ref(text)
        cid = resolve(ref, fetch)
        state = load(base)
    except ChannelError as exc:
        say(f"✘ {exc}")
        return EXIT_FAILED if isinstance(exc, NetworkError) else EXIT_USAGE
    if cid in state["channels"]:
        say(f"ℹ القناة مضافة مسبقًا: {state['channels'][cid]['title']} ({cid})")
        return EXIT_OK
    try:
        title, vids = fetch_feed(cid, fetch, sleep)
    except NetworkError as exc:
        # the channel id is known, only the feed hiccuped: follow it anyway; the first successful check will
        # mark everything that exists by then as "already seen" (so old videos are not flooded into the inbox)
        state["channels"][cid] = {"id": cid, "title": ref.handle or cid, "handle": ref.handle or "", "added": ib.now_iso(),
                                  "last_checked": None, "seen": [], "last_new": 0, "last_error": str(exc)[:200], "pending_init": True}
        save(state, base)
        say(f"⚠ أضفتُ القناة ({ref.handle or cid}) لكن يوتيوب لم يرجع قائمة فيديوهاتها الآن ({exc}) — هذا يحدث أحيانًا مؤقتًا.")
        say("  عند أول `channels check` ناجح سأعتبر الفيديوهات الموجودة حينها قديمة، وأضيف ما يُنشر بعدها فقط.")
        return EXIT_OK
    except ChannelError as exc:
        say(f"✘ {exc}")
        return EXIT_USAGE
    new_first = vids[: max(0, backfill)]
    seen = [v.id for v in vids if v not in new_first]  # everything currently published is "already seen"
    state["channels"][cid] = {
        "id": cid, "title": title or cid, "handle": ref.handle or "", "added": ib.now_iso(), "last_checked": None,
        "seen": seen[:MAX_SEEN], "last_new": 0, "last_error": None,
    }
    save(state, base)
    say(f"✔ أُضيفت القناة: {title or cid}  ({cid})")
    say(f"  الفيديوهات الحالية ({len(seen)}) اعتُبرت قديمة؛ سأضيف فقط ما يُنشر بعد الآن."
        + (f" وأتيح {len(new_first)} فيديو للإضافة في أول `channels check`." if new_first else ""))
    return EXIT_OK


def remove(text: str, base: Optional[Path] = None, say: Callable[[str], None] = print) -> int:
    """Matches the saved id, @handle, URL or part of the title - no network needed."""
    state = load(base)
    q = text.strip().strip('"').lower()
    ref: Optional[Ref] = None
    try:
        ref = parse_ref(text)
    except ChannelError:
        pass
    hits = []
    for cid, c in state["channels"].items():
        handle = (c.get("handle") or "").lower()
        if (ref and ref.channel_id == cid) or cid.lower() == q or (handle and (q.lstrip("@") == handle.lstrip("@") or (ref and ref.handle and ref.handle.lower() == handle))) \
                or (len(q) >= 3 and q in c["title"].lower()):
            hits.append(cid)
    if not hits:
        say(f"✘ لا توجد قناة مطابقة لـ «{text}». القنوات الحالية: python -m notebooklm_lab channels list")
        return EXIT_USAGE
    if len(hits) > 1:
        say("✘ أكثر من قناة تطابق؛ حدّد أدق (المعرّف UC… أو @handle):")
        for cid in hits:
            say(f"   {state['channels'][cid]['title']}  ({cid})")
        return EXIT_USAGE
    gone = state["channels"].pop(hits[0])
    save(state, base)
    say(f"✔ أُزيلت القناة: {gone['title']}  — روابطها التي أُضيفت سابقًا إلى inbox.txt لم تُحذف.")
    return EXIT_OK


def list_text(base: Optional[Path] = None) -> str:
    state = load(base)
    chans = state["channels"]
    if not chans:
        return "لا توجد قنوات متابَعة. أضف واحدة:  python -m notebooklm_lab channels add @handle"
    lines = [f"القنوات المتابَعة ({len(chans)}):", ""]
    for c in chans.values():
        lines.append(f"• {c['title']}  {c.get('handle') or ''}  ({c['id']})")
        last = c.get("last_checked") or "لم تُفحص بعد"
        err = f"  ⚠ آخر خطأ: {c['last_error']}" if c.get("last_error") else ""
        lines.append(f"    أُضيفت: {c.get('added')}   آخر فحص: {last}   آخر فحص أضاف: {c.get('last_new', 0)} فيديو{err}")
    return "\n".join(lines)


@dataclass
class CheckReport:
    channels: int = 0
    failed: int = 0
    added: List[Tuple[str, Video]] = field(default_factory=list)  # (channel title, video)
    skipped_old: int = 0
    already_known: int = 0


def append_to_inbox(inbox: Path, lines: List[str]) -> None:
    ib.ensure_inbox(inbox)
    text = inbox.read_text(encoding="utf-8-sig")
    prefix = "" if (not text or text.endswith("\n")) else "\n"
    with inbox.open("a", encoding="utf-8", newline="\n") as f:
        f.write(prefix + "\n".join(lines) + "\n")


def check(base: Optional[Path] = None, *, dry_run: bool = False, max_per_channel: int = DEFAULT_MAX_PER_CHANNEL,
          fetch: Optional[Fetcher] = None, say: Callable[[str], None] = print,
          sleep: Callable[[float], None] = time.sleep) -> Tuple[int, CheckReport]:
    """Find new videos of every followed channel and append their links to inbox.txt. Returns (exit code, report)."""
    root = Path(base).expanduser().resolve() if base else data_dir()
    rep = CheckReport()
    try:
        state = load(root)
    except ChannelError as exc:
        say(f"✘ {exc}")
        return EXIT_USAGE, rep
    chans = state["channels"]
    rep.channels = len(chans)
    if not chans:
        say("لا توجد قنوات متابَعة (أضف واحدة بـ channels add).")
        return EXIT_OK, rep
    inbox_path = root / ib.INBOX_NAME
    known = set()  # links the inbox already has or `morning` already processed
    try:
        if inbox_path.exists():
            known |= {e.key for e in ib.read_inbox(inbox_path)[0]}
        known |= set(ib.load_state(root / ib.STATE_NAME).get("processed", {}))
    except (OSError, ib.StateError) as exc:
        say(f"⚠ تعذّرت قراءة الصندوق/الحالة ({exc}); سأكمل لكن قد تتكرر روابط.")
    new_lines: List[str] = []
    for cid, c in chans.items():
        try:
            feed_title, vids = fetch_feed(cid, fetch, sleep)
        except ChannelError as exc:
            rep.failed += 1
            c["last_error"] = str(exc)[:200]
            say(f"✘ {c['title']}: {exc}" + ("  (قد يكون خطأً مؤقتًا من يوتيوب؛ سأعيد المحاولة في الفحص القادم)" if isinstance(exc, NetworkError) else ""))
            continue
        c["last_error"] = None
        if c.pop("pending_init", False):  # first successful look at a channel added while its feed was down
            c["title"] = feed_title or c["title"]
            c["seen"] = [v.id for v in vids][:MAX_SEEN]
            c["last_checked"], c["last_new"] = ib.now_iso(), 0
            say(f"· {c['title']}: تهيئة — اعتُبرت {len(vids)} فيديو موجودة قديمة؛ سأضيف الجديد من الفحص القادم")
            continue
        seen = set(c.get("seen", []))
        fresh = [v for v in vids if v.id not in seen]
        take = fresh[: max(1, max_per_channel)]
        rep.skipped_old += len(fresh) - len(take)
        added_vids: List[Video] = []
        for v in take:
            key = ib.normalize_key(v.url)
            if key in known:
                rep.already_known += 1
                continue
            known.add(key)
            added_vids.append(v)
        added_here = len(added_vids)
        rep.added += [(c["title"], v) for v in added_vids]
        for v in reversed(added_vids):  # the feed is newest-first; the inbox gets them oldest-first
            new_lines.append(f"{v.url}  # " + " ".join(f"{c['title']}: {v.title}".split())[:140])
        c["seen"] = ([v.id for v in fresh] + c.get("seen", []))[:MAX_SEEN]
        c["last_checked"] = ib.now_iso()
        c["last_new"] = added_here
        say(f"{'✔' if added_here else '·'} {c['title']}: {added_here} فيديو جديد" + (f" (تخطيتُ {len(fresh) - len(take)} أقدم)" if len(fresh) > len(take) else ""))
    if dry_run:
        say(f"(تجربة بلا كتابة) كان سيُضاف {len(new_lines)} رابط إلى {inbox_path}:")
        for ln in new_lines:
            say(f"   {ln}")
        return (EXIT_FAILED if rep.failed == rep.channels else EXIT_OK), rep
    if new_lines:
        append_to_inbox(inbox_path, new_lines)
    save(state, root)
    say(f"انتهى: {len(new_lines)} رابط جديد أُضيف إلى {inbox_path}" + (f"؛ فشلت {rep.failed} قناة" if rep.failed else ""))
    return (EXIT_FAILED if rep.failed == rep.channels else EXIT_OK), rep


def auto_enabled(flag: Optional[bool], base: Optional[Path] = None) -> bool:
    """Default ON (following a channel IS the opt-in). Off with --no-channels or NOTEBOOKLM_LAB_CHANNELS_AUTO=0."""
    if flag is not None:
        return flag
    return settings.get("NOTEBOOKLM_LAB_CHANNELS_AUTO", base).lower() not in ("0", "false", "no", "off")


def check_safely(base: Optional[Path], say: Callable[[str], None], fetch: Optional[Fetcher] = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
    """Used by `morning` before it reads the inbox: never raises, never changes the exit code, silent if nothing is followed."""
    try:
        if not load(base)["channels"]:
            return
        say("— فحص القنوات المتابَعة قبل الملخص … / checking followed channels")
        check(base, fetch=fetch, say=say, sleep=sleep)
    except Exception as exc:
        say(f"⚠ فحص القنوات تعذّر ({type(exc).__name__}) — تجاهلتُه وأكملتُ الملخص بما في inbox.txt.")
