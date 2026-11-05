"""What a finished morning run produced (summary text, podcast file, sources), read back from its
`run.json`. Shared by the Telegram and Obsidian deliveries so they never talk to NotebookLM themselves."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .storage import list_runs


@dataclass
class Deliverable:
    title: str
    day: str  # YYYY-MM-DD
    mode: str  # "real" | "sample"
    summary_md: str  # the written Arabic summary (Markdown), may be empty
    audio_path: Optional[Path]
    sources: List[str] = field(default_factory=list)
    notebook_id: str = ""
    run_dir: Optional[Path] = None

    @property
    def is_sample(self) -> bool:
        return self.mode == "sample"


def _read_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def from_run_dir(run_dir: Path) -> Optional[Deliverable]:
    """None when the folder has no readable run.json (not a run)."""
    try:
        data = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    summary = ""
    audio: Optional[Path] = None
    for o in data.get("outputs") or []:
        if not o.get("ok") or not o.get("path"):
            continue
        f = run_dir / o["path"]
        if not f.is_file():
            continue
        if o.get("kind") == "briefing" and not summary:
            summary = _read_text(f)
        elif o.get("kind") == "audio" and audio is None:
            audio = f
    if not summary:
        qa = data.get("qa") or []
        if qa and isinstance(qa[0], dict):
            summary = str(qa[0].get("answer") or "").strip()
    m = re.match(r"\d{4}-\d{2}-\d{2}", run_dir.name)
    day = m.group(0) if m else str(data.get("created_at") or "")[:10]
    sources = [s.get("value", "") for s in data.get("sources") or [] if s.get("status") == "ready" and s.get("value")]
    return Deliverable(
        title=str(data.get("title") or run_dir.name), day=day, mode=str(data.get("mode") or "real"), summary_md=summary,
        audio_path=audio, sources=sources, notebook_id=str(data.get("notebook_id") or ""), run_dir=run_dir,
    )


def latest(outputs_root: Path) -> Optional[Deliverable]:
    for d in reversed(list_runs(outputs_root)):
        got = from_run_dir(d)
        if got:
            return got
    return None


def markdown_to_plain(md: str) -> str:
    """Telegram text is sent as plain text (no Markdown parser to choke on Arabic): drop the markup, keep the words."""
    out: List[str] = []
    for line in md.splitlines():
        s = line.rstrip()
        s = re.sub(r"^\s{0,3}#{1,6}\s*", "", s)
        s = re.sub(r"^\s*[-*+]\s+", "• ", s)
        s = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2), s)
        s = re.sub(r"(?<!\w)[*_](\S.*?\S|\S)[*_](?!\w)", r"\1", s)
        s = re.sub(r"`([^`]*)`", r"\1", s)
        s = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1 (\2)", s)
        out.append(s)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
