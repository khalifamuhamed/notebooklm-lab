"""Turn the user's list of links/files into SourceSpec objects."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, List
from urllib.parse import urlparse

from .models import SourceSpec

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "music.youtube.com"}


class SourceError(ValueError):
    pass


def classify(value: str) -> SourceSpec:
    value = value.strip().strip('"').strip("'")
    if not value:
        raise SourceError("empty source")
    parsed = urlparse(value)
    if parsed.scheme in ("http", "https") and parsed.netloc:
        host = parsed.netloc.lower().split(":")[0]
        return SourceSpec("youtube" if host in YOUTUBE_HOSTS else "url", value)
    if parsed.scheme and len(parsed.scheme) > 1:  # ftp://, file://, javascript: ... (but not C:\ drive letters)
        raise SourceError(f"unsupported link type: {value!r} (only http/https links or local files)")
    path = Path(value).expanduser()
    if path.is_file():
        return SourceSpec("file", str(path))
    raise SourceError(f"not a link and not an existing file: {value!r}")


def read_links_file(path: Path) -> List[str]:
    """One link or file path per line; blank lines and lines starting with # are ignored."""
    out: List[str] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def build_specs(items: Iterable[str]) -> List[SourceSpec]:
    return [classify(i) for i in items]
