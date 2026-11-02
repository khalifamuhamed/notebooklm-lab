"""The morning-digest inbox and its memory of what was already processed.

* `inbox.txt`  - a plain text file; the user pastes one link per line.
  Lines starting with # are comments, blank lines are ignored, a trailing
  ` # comment` after a link is ignored, duplicates are skipped.
* `morning_state.json` - which links were already processed (so they are never
  repeated) plus facts about the last run for `morning status`.

Nothing here contacts the network or reads any login file."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

INBOX_NAME = "inbox.txt"
STATE_NAME = "morning_state.json"
SAMPLE_STATE_NAME = "morning_state.sample.json"
STATE_VERSION = 1

INBOX_TEMPLATE = """\
# صندوق الروابط الصباحي — ألصق كل رابط (يوتيوب أو مقال) في سطر مستقل.
# الأسطر التي تبدأ بعلامة # هي ملاحظات وتُتجاهل، والأسطر الفارغة تُتجاهل أيضًا.
# الرابط المكرر يُؤخذ مرة واحدة، والرابط الذي عولج سابقًا لا يُعاد.
# Morning inbox: paste one link per line. Lines starting with # are comments.
#
# مثال / example (احذف علامة # لتفعيله):
# https://www.youtube.com/watch?v=VIDEO_ID
# https://example.com/some-article
"""


class StateError(RuntimeError):
    """The state file exists but cannot be read."""


@dataclass(frozen=True)
class InboxEntry:
    link: str  # as the user wrote it
    key: str  # normalised identity used for dedup
    line: int


def normalize_key(link: str) -> str:
    """Identity of a link: youtu.be/ID, youtube.com/watch?v=ID and m.youtube.com/... are the same
    video; for other URLs the scheme/host case, `#fragment` and a trailing `/` do not matter."""
    link = link.strip()
    parsed = urlparse(link)
    if parsed.scheme in ("http", "https") and parsed.netloc:
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        host = netloc.split(":")[0]
        vid = None
        if host == "youtu.be":
            vid = parsed.path.strip("/").split("/")[0] or None
        elif host in ("youtube.com", "m.youtube.com", "music.youtube.com"):
            if parsed.path == "/watch":
                vid = (parse_qs(parsed.query).get("v") or [None])[0]
            else:
                m = re.match(r"^/(?:shorts|embed|live)/([^/?#]+)", parsed.path)
                vid = m.group(1) if m else None
        if vid:
            return f"youtube:{vid}"
        path = parsed.path.rstrip("/")
        query = f"?{parsed.query}" if parsed.query else ""
        return f"{parsed.scheme}://{netloc}{path}{query}"
    return link  # local file path: compared as written


def parse_inbox_text(text: str) -> Tuple[List[InboxEntry], int]:
    """Return (unique entries in file order, number of duplicate lines skipped)."""
    seen = set()
    entries: List[InboxEntry] = []
    dups = 0
    for n, raw in enumerate(text.lstrip("\ufeff").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = re.split(r"\s+#", line, maxsplit=1)[0].strip().strip('"').strip("'")
        if not line:
            continue
        key = normalize_key(line)
        if key in seen:
            dups += 1
            continue
        seen.add(key)
        entries.append(InboxEntry(line, key, n))
    return entries, dups


def read_inbox(path: Path) -> Tuple[List[InboxEntry], int]:
    return parse_inbox_text(path.read_text(encoding="utf-8-sig"))


def ensure_inbox(path: Path) -> bool:
    """Create the inbox with instructions if missing. True if it was created."""
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(INBOX_TEMPLATE, encoding="utf-8")
    return True


# ------------------------------------------------------------------ state
def empty_state() -> Dict[str, Any]:
    return {"version": STATE_VERSION, "processed": {}, "failed_attempts": {}, "last_run": None, "last_success": None}


def load_state(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return empty_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("processed"), dict):
            raise ValueError("unexpected structure")
    except (OSError, ValueError) as exc:
        raise StateError(
            f"ملف الحالة تالف أو غير قابل للقراءة / state file unreadable: {path} ({exc}). "
            "احذفه (سيُعاد تجهيز الروابط) أو أصلحه. / Delete it (links would be processed again) or fix it."
        ) from exc
    base = empty_state()
    base.update(data)
    return base


def save_state(path: Path, state: Dict[str, Any]) -> None:
    """Atomic write: a crash can never leave a half-written state file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def new_entries(entries: List[InboxEntry], state: Dict[str, Any]) -> List[InboxEntry]:
    done = state.get("processed", {})
    return [e for e in entries if e.key not in done]


def mark_processed(state: Dict[str, Any], entry: InboxEntry, status: str, date: str, run: str, error: Optional[str] = None) -> None:
    state["processed"][entry.key] = {
        "link": entry.link, "status": status, "date": date, "run": run, **({"error": error} if error else {}),
    }
    state["failed_attempts"].pop(entry.key, None)


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
