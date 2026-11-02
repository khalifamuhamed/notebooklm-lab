"""A small, dependency-free scanner that fails when something that looks like a
secret, a Google login file, or a developer-machine path is about to be
committed. It scans the files git would commit (tracked + untracked-not-ignored)
or, outside git, every file under the folder (skipping caches/venvs/outputs)."""
from __future__ import annotations

import fnmatch
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Pattern, Tuple

# Pattern text is assembled from pieces so this file does not trip its own rules.
_PK = "-----BEGIN " + r"(?:[A-Z]+ )?" + "PRIVATE KEY"
_BOX = "|".join(["/home/" + "box", "/work" + "space/", "/cur" + "sor/stores"])

CONTENT_RULES: List[Tuple[str, Pattern[str]]] = [
    ("private-key-block", re.compile(_PK)),
    ("github-token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,})")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("openai/xai-style-key", re.compile(r"\b(?:sk|xai)-[A-Za-z0-9_\-]{24,}")),
    (
        "google-auth-cookie",
        re.compile(r"""(?:__Secure-[13]PSID(?:TS|CC)?|\bSAPISID|\bAPISID|\bHSID|\bSSID)["']?\s*[:=,]\s*["']?[A-Za-z0-9_\-\.%/]{20,}"""),
    ),
    ("playwright-storage-state", re.compile(r'"cookies"\s*:\s*\[\s*\{[^}]*"domain"\s*:\s*"\.?(?:google|youtube)\.')),
    (
        "hardcoded-secret",
        re.compile(r"""(?i)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token)\b\s*[:=]\s*["'](?![^"']*(?:your|example|placeholder|changeme|xxx|<|\$\{|\*\*\*))[^"'\s]{12,}["']"""),
    ),
    ("developer-machine-path", re.compile(_BOX)),
]

FORBIDDEN_NAME_GLOBS = [
    ".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa*", "id_ed25519*",
    "storage_state*.json", "*storage_state*", "master_token*.json", "*cookies*", "auth*.json",
]
ALLOWED_NAMES = {".env.example"}
SKIP_DIRS = {".git", ".venv", "venv", "env", "__pycache__", "node_modules", "outputs", "downloads", ".pytest_cache", "build", "dist", ".mypy_cache", ".ruff_cache"}
MAX_BYTES = 2_000_000


@dataclass
class Finding:
    path: str
    line: int
    rule: str
    snippet: str

    def __str__(self) -> str:
        where = f"{self.path}:{self.line}" if self.line else self.path
        return f"{where}  [{self.rule}]  {self.snippet}"


def _redact(s: str) -> str:
    s = s.strip()
    return (s[:6] + "…[redacted]") if len(s) > 6 else "[redacted]"


def _candidate_files(root: Path) -> List[Path]:
    if (root / ".git").exists():
        try:
            out = subprocess.run(
                ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                capture_output=True, check=True,
            ).stdout.decode("utf-8", "replace")
            files = [root / p for p in out.split("\0") if p]
            return [f for f in files if f.is_file()]
        except (OSError, subprocess.CalledProcessError):
            pass
    found: List[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.endswith(".egg-info")]
        for fn in filenames:
            found.append(Path(dirpath) / fn)
    return found


def scan(root: Path, files: Iterable[Path] = ()) -> List[Finding]:
    root = root.resolve()
    findings: List[Finding] = []
    for f in list(files) or _candidate_files(root):
        rel = f.resolve().relative_to(root).as_posix()
        name = f.name
        if name not in ALLOWED_NAMES and any(fnmatch.fnmatch(name.lower(), g.lower()) for g in FORBIDDEN_NAME_GLOBS):
            findings.append(Finding(rel, 0, "forbidden-file-name", "this file name is reserved for secrets/login data"))
            continue
        try:
            if f.stat().st_size > MAX_BYTES:
                continue
            data = f.read_bytes()
        except OSError:
            continue
        if b"\0" in data[:4096]:
            continue
        text = data.decode("utf-8", "replace")
        for rule, rx in CONTENT_RULES:
            for m in rx.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                findings.append(Finding(rel, line, rule, _redact(m.group(0))))
    return findings


def run(root: Path) -> int:
    findings = scan(root)
    if findings:
        print(f"✘ secrets-scan: {len(findings)} problem(s) found (values are redacted):")
        for f in findings:
            print("   ", f)
        return 1
    print("✔ secrets-scan: no secrets, login files or machine paths found in files that would be committed.")
    return 0
