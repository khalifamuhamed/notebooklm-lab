"""`python -m notebooklm_lab selfcheck` - quick health checks a non-programmer can run."""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import sys
import tempfile
from importlib import metadata
from pathlib import Path
from typing import Callable, List, Tuple

from . import PINNED_NOTEBOOKLM_PY, secrets_scan
from .config import repo_root

Check = Tuple[str, bool, str]

REQUIRED_IGNORED = [
    ".env", ".env.local", "server.pem", "private.key", "cookies.txt", "my_cookies.json",
    "storage_state.json", "auth.json", "master_token.json", "outputs/run/report.html",
    "downloads/a.m4a", "__pycache__/x.pyc", ".venv/bin/python", ".pytest_cache/x", "audio.mp3",
]
EXPECTED_MCP_TOOLS = {"notebook_create", "source_add", "chat_ask", "studio_generate", "studio_status", "studio_download"}


def check_python() -> Check:
    ok = sys.version_info >= (3, 10)
    return ("Python >= 3.10", ok, sys.version.split()[0])


def check_dependency_pin() -> Check:
    try:
        v = metadata.version("notebooklm-py")
    except metadata.PackageNotFoundError:
        return ("notebooklm-py installed", False, "not installed - run: pip install -r requirements.txt")
    return (f"notebooklm-py == {PINNED_NOTEBOOKLM_PY} (pinned)", v == PINNED_NOTEBOOKLM_PY, f"installed {v}")


def check_pins_declared(root: Path) -> Check:
    problems = []
    for name in ("pyproject.toml", "requirements.txt"):
        p = root / name
        if not p.exists():
            problems.append(f"{name} missing")
        elif not re.search(rf"notebooklm-py(\[[^\]]*\])?=={re.escape(PINNED_NOTEBOOKLM_PY)}", p.read_text(encoding="utf-8")):
            problems.append(f"{name} does not pin notebooklm-py=={PINNED_NOTEBOOKLM_PY}")
    return ("dependency pinned in pyproject + requirements", not problems, "; ".join(problems) or "ok")


def check_gitignore(root: Path) -> Check:
    if not (root / ".git").exists() or not shutil.which("git"):
        return (".gitignore covers secrets/outputs", True, "skipped (no git repo/git binary)")
    missing = []
    for name in REQUIRED_IGNORED:
        r = subprocess.run(["git", "-C", str(root), "check-ignore", "-q", "--no-index", name])
        if r.returncode != 0:
            missing.append(name)
    return (".gitignore covers secrets/outputs", not missing, "not ignored: " + ", ".join(missing) if missing else "ok")


def check_secrets(root: Path) -> Check:
    findings = secrets_scan.scan(root)
    return ("secrets scan", not findings, "clean" if not findings else f"{len(findings)} finding(s): run `python -m notebooklm_lab secrets-scan`")


def check_sample_mode() -> Check:
    from .sample_backend import DEMO_SPECS, SampleBackend
    from .pipeline import make_run_dir, run_digest

    with tempfile.TemporaryDirectory() as td:
        run_dir = make_run_dir(Path(td), "selfcheck")
        res = asyncio.run(run_digest(SampleBackend(), DEMO_SPECS, run_dir, "selfcheck", outputs=("briefing", "mind_map", "audio")))
        ok = (run_dir / "report.html").is_file() and all(o.ok for o in res.outputs) and 'dir=\'rtl\'' in (run_dir / "report.html").read_text(encoding="utf-8")
    return ("offline sample mode end-to-end", ok, "report + outputs created" if ok else "failed")


async def _list_mcp_tools() -> List[str]:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    with tempfile.TemporaryDirectory() as td:
        env = {**os.environ, "NOTEBOOKLM_HOME": td}  # empty home: never touches the real login
        params = StdioServerParameters(command=sys.executable, args=["-m", "notebooklm.mcp"], env=env)
        async with stdio_client(params, errlog=open(os.devnull, "w")) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                return sorted(t.name for t in (await s.list_tools()).tools)


def check_mcp() -> Check:
    try:
        import mcp  # noqa: F401
    except ImportError:
        return ("upstream MCP server starts + lists tools", False, "official `mcp` SDK missing - pip install -r requirements-dev.txt")
    try:
        tools = asyncio.run(asyncio.wait_for(_list_mcp_tools(), 90))
    except Exception as exc:
        return ("upstream MCP server starts + lists tools", False, f"{type(exc).__name__}: {exc}")
    missing = EXPECTED_MCP_TOOLS - set(tools)
    return ("upstream MCP server starts + lists tools", not missing, f"{len(tools)} tools" + (f"; missing {sorted(missing)}" if missing else ""))


def run(with_mcp: bool = False, say: Callable[[str], None] = print) -> int:
    root = repo_root()
    in_repo = (root / "pyproject.toml").exists() and (root / "src" / "notebooklm_lab").exists()
    checks: List[Check] = [check_python(), check_dependency_pin(), check_sample_mode()]
    if in_repo:
        checks[1:1] = [check_pins_declared(root)]
        checks += [check_gitignore(root), check_secrets(root)]
    if with_mcp:
        checks.append(check_mcp())
    failed = 0
    for name, ok, detail in checks:
        say(f"{'✔' if ok else '✘'} {name}: {detail}")
        failed += 0 if ok else 1
    say("\nكل الفحوصات نجحت / all checks passed" if not failed else f"\n{failed} فحص فشل / check(s) failed")
    return 1 if failed else 0
