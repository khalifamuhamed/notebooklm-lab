"""Simple, dependency-free ranked keyword search over the Markdown notes of an Obsidian vault.

No index, no database, no embeddings, no background process: every search reads the `.md` files once (one file at a
time, so memory stays small even for big vaults) and ranks them with a small BM25-style score. Arabic is handled
sensibly (diacritics and tatweel removed, alef/yaa/taa-marbuta variants unified, the definite article «ال» and common
one-letter prefixes ignored), titles / headings / tags count more than body text.

Never writes to the vault. Files are only read."""
from __future__ import annotations

import math
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

MAX_FILE_BYTES = 1_500_000
MAX_FILES = 30_000
SKIP_DIRS = {".obsidian", ".trash", ".git", ".stfolder", "node_modules"}
K1, B = 1.4, 0.75
SNIPPET_CHARS = 280

_DIACRITICS = re.compile("[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]")  # tashkeel + tatweel
# letters/digits only: Arabic punctuation such as «؟ ، ؛» must never become part of a word
_WORD = re.compile(r"[0-9A-Za-z\u00C0-\u024F\u0621-\u063F\u0641-\u064A\u0660-\u0669\u066E-\u06D3]+")
_STOP = {
    # Arabic
    "في", "من", "على", "الى", "عن", "ما", "ماذا", "هل", "هذا", "هذه", "ذلك", "تلك", "هو", "هي", "هم", "كان", "كانت", "ان", "انه", "انها",
    "او", "ثم", "كل", "مع", "قد", "لا", "لم", "لن", "التي", "الذي", "الذين", "اي", "كيف", "متى", "اين", "لماذا", "بين", "عند", "حول",
    # English
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is", "are", "was", "were", "what", "how", "why", "when", "where",
    "which", "who", "about", "with", "from", "by", "at", "as", "it", "this", "that", "do", "does", "did", "be", "me", "my", "i", "you",
}
_PREFIXES = ("وال", "فال", "بال", "كال", "لل", "ال")


def normalize_word(w: str) -> str:
    """Also used on whole texts (every step is character-level): diacritics/tatweel removed FIRST so they never split a word."""
    w = _DIACRITICS.sub("", w.lower())
    w = re.sub("[\u0623\u0625\u0622\u0671]", "\u0627", w)  # أ إ آ ٱ -> ا
    w = w.replace("\u0649", "\u064A").replace("\u0629", "\u0647")  # ى -> ي ، ة -> ه
    return w


def stem(w: str) -> str:
    for p in _PREFIXES:
        if w.startswith(p) and len(w) - len(p) >= 3:
            return w[len(p):]
    return w


def tokens(text: str, drop_stop: bool = False) -> List[str]:
    out = []
    for raw in _WORD.findall(normalize_word(text)):
        w = stem(raw)
        if len(w) < 2 or (drop_stop and (w in _STOP or raw in _STOP)):
            continue
        out.append(w)
    return out


def words_match(query_term: str, doc_word: str) -> bool:
    """Equal, or one is a prefix of the other (both 4+ letters, length differing by at most 3): فيديو ~ فيديوهات, هوك ~ هوكات."""
    if query_term == doc_word:
        return True
    a, b = (query_term, doc_word) if len(query_term) <= len(doc_word) else (doc_word, query_term)
    return len(a) >= 4 and len(b) - len(a) <= 3 and b.startswith(a)


def query_terms(question: str) -> List[str]:
    """Distinct meaningful words of the question (stop-words dropped; if nothing is left, keep everything)."""
    terms = list(dict.fromkeys(tokens(question, drop_stop=True)))
    return terms or list(dict.fromkeys(tokens(question)))


@dataclass
class Hit:
    path: str  # relative to the vault, forward slashes
    abs_path: str
    title: str
    score: float
    snippet: str
    matched: List[str] = field(default_factory=list)
    modified: str = ""
    tags: List[str] = field(default_factory=list)


@dataclass
class SearchResult:
    query: str
    terms: List[str]
    hits: List[Hit]
    files_scanned: int = 0
    truncated: bool = False  # more than MAX_FILES notes: the rest were not read


def _iter_notes(root: Path, vault_root: Optional[Path] = None) -> Iterable[Path]:
    """Markdown files below `root`. Symlinks that lead outside the vault are never followed or read."""
    vault_root = vault_root or root
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for fn in sorted(filenames):
            if fn.lower().endswith(".md") and not fn.startswith("."):
                f = Path(dirpath) / fn
                try:
                    inside = f.resolve().is_relative_to(vault_root)
                except (OSError, RuntimeError):
                    inside = False
                if inside:
                    yield f


def split_frontmatter(text: str) -> Tuple[Dict[str, str], str]:
    """Tiny front-matter reader (only `title:` and `tags:` matter here). Returns (fields, body)."""
    text = text.lstrip("\ufeff")
    if not text.startswith("---"):
        return {}, text
    m = re.match(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", text, re.S)
    if not m:
        return {}, text
    fields: Dict[str, str] = {}
    block = m.group(1)
    t = re.search(r"^title:\s*(.+)$", block, re.M)
    if t:
        fields["title"] = t.group(1).strip().strip("\"'")
    tg = re.search(r"^tags:\s*(.*(?:\n[ \t]+-.*)*)", block, re.M)
    if tg:
        fields["tags"] = " ".join(re.findall(r"[^\s\[\],\-#]+", tg.group(1)))
    return fields, text[m.end():]


def _read(p: Path) -> Optional[str]:
    try:
        if p.stat().st_size > MAX_FILE_BYTES:
            return None
        return p.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None


def _title_of(p: Path, fields: Dict[str, str], body: str) -> str:
    if fields.get("title"):
        return fields["title"]
    m = re.search(r"^#\s+(.+)$", body, re.M)
    return (m.group(1).strip() if m else p.stem)[:150]


def _weighted_tf(p: Path, text: str) -> Tuple[Counter, int, str]:
    """term -> weighted frequency (title x4, headings x2.5, tags x3, body x1), doc length, title."""
    fields, body = split_frontmatter(text)
    title = _title_of(p, fields, body)
    tf: Counter = Counter()
    for w in tokens(body):
        tf[w] += 1.0
    length = sum(tf.values()) or 1
    for w in tokens(p.stem + " " + title):
        tf[w] += 4.0
    for line in body.splitlines():
        if line.lstrip().startswith("#"):
            for w in tokens(line):
                tf[w] += 2.5
    for w in tokens(fields.get("tags", "")):
        tf[w] += 3.0
    return tf, length, title


def _snippet(text: str, terms: List[str]) -> str:
    """The ~280 characters around the densest cluster of query words (cut at word boundaries)."""
    _f, body = split_frontmatter(text)
    body = re.sub(r"```.*?```", " ", body, flags=re.S)
    body = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", body)  # heading marks
    body = re.sub(r"(?m)^\s*>\s?", "", body)
    body = re.sub(r"\*\*|__|`|\[\[|\]\]", "", body)
    flat = " ".join(body.split())
    if not flat:
        return ""
    best, best_pos = -1, 0
    for m in _WORD.finditer(flat):
        w = stem(normalize_word(m.group(0)))
        if any(words_match(t, w) for t in terms):
            window = flat[m.start(): m.start() + SNIPPET_CHARS]
            score = sum(1 for x in _WORD.findall(window) if any(words_match(t, stem(normalize_word(x))) for t in terms))
            if score > best:
                best, best_pos = score, m.start()
    start = max(0, best_pos - 60) if best >= 0 else 0
    if start:
        sp = flat.find(" ", start)
        start = sp + 1 if 0 <= sp < best_pos else start
    chunk = flat[start: start + SNIPPET_CHARS]
    if start + SNIPPET_CHARS < len(flat):
        chunk = chunk[: chunk.rfind(" ")] + "…" if " " in chunk else chunk + "…"
    return ("…" if start else "") + chunk


def search(vault: Path, question: str, limit: int = 5, folder: Optional[str] = None) -> SearchResult:
    """Rank the notes of `vault` (or of `vault/folder`) for the question. Read-only."""
    root = vault.resolve()
    scan_root = root
    if folder:
        scan_root = (root / folder).resolve()
        if scan_root != root and root not in scan_root.parents:
            raise ValueError("folder must be inside the vault")
        if not scan_root.is_dir():
            raise ValueError(f"folder not found in the vault: {folder}")
    terms = query_terms(question)
    res = SearchResult(query=question, terms=terms, hits=[])
    if not terms:
        return res
    docs: List[Tuple[Path, Counter, int, str]] = []
    df: Counter = Counter()
    total_len = 0
    for p in _iter_notes(scan_root, root):
        if res.files_scanned >= MAX_FILES:
            res.truncated = True
            break
        text = _read(p)
        if text is None:
            continue
        res.files_scanned += 1
        norm = normalize_word(text)
        if not any(t[:3] in norm for t in terms):  # cheap pre-filter: skip notes that cannot match at all
            continue
        tf, length, title = _weighted_tf(p, text)
        match: Counter = Counter()
        for t in terms:
            if t in tf:
                match[t] += tf[t]
            elif len(t) >= 4:  # inflected forms count a bit less than the exact word
                pre = sum(c for w, c in tf.items() if words_match(t, w))
                if pre:
                    match[t] += 0.6 * pre
        if match:
            docs.append((p, match, length, title))
            total_len += length
            for t in match:
                df[t] += 1
    if not docs:
        return res
    n_docs_total = max(res.files_scanned, 1)
    avg_len = (total_len / len(docs)) or 1
    scored: List[Tuple[float, Path, List[str], str]] = []
    for p, match, length, title in docs:
        score = 0.0
        for t, f in match.items():
            idf = math.log(1 + (n_docs_total - df[t] + 0.5) / (df[t] + 0.5))
            score += idf * (f * (K1 + 1)) / (f + K1 * (1 - B + B * length / avg_len))
        coverage = len(match) / len(terms)  # notes that contain MORE of the question's words rank higher
        scored.append((score * (0.5 + coverage), p, list(match), title))
    scored.sort(key=lambda x: (-x[0], str(x[1])))
    for score, p, matched, title in scored[: max(1, limit)]:
        text = _read(p) or ""
        fields, _ = split_frontmatter(text)
        try:
            mtime = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d")
        except OSError:
            mtime = ""
        res.hits.append(Hit(
            path=p.relative_to(root).as_posix(), abs_path=str(p), title=title, score=round(score, 3),
            snippet=_snippet(text, terms), matched=matched, modified=mtime, tags=fields.get("tags", "").split(),
        ))
    return res
