"""Config snippets for Claude Code, Codex and Hermes. They all launch the MCP
server that notebooklm-py itself ships (`python -m notebooklm.mcp`, the same
server as the `notebooklm-mcp` command). The path of YOUR Python is filled in
at run time, so nothing machine-specific is stored in this repo."""
from __future__ import annotations

import sys
from typing import Dict

AGENTS = ("claude", "codex", "hermes")


def _q(p: str) -> str:
    return f'"{p}"' if " " in p else p


def snippets(python: str = "") -> Dict[str, str]:
    py = python or sys.executable
    return {
        "claude": (
            "# Claude Code - register the MCP server (run once, in a terminal):\n"
            f"claude mcp add notebooklm -- {_q(py)} -m notebooklm.mcp\n"
            "claude mcp list\n\n"
            "# Upstream also ships a Claude Code/agent *skill*:\n"
            "notebooklm skill install        # installs the skill from notebooklm-py\n"
        ),
        "codex": (
            "# Codex CLI - either run:\n"
            f"codex mcp add notebooklm -- {_q(py)} -m notebooklm.mcp\n"
            "codex mcp list\n\n"
            "# ...or add this to ~/.codex/config.toml (TOML literal string: backslashes are fine):\n"
            "[mcp_servers.notebooklm]\n"
            f"command = '{py}'\n"
            "args = [\"-m\", \"notebooklm.mcp\"]\n\n"
            "# Upstream's skill installer also writes the vendor-neutral Agent Skills folder\n"
            "# (~/.agents/skills/notebooklm); whether your Codex version reads it is not verified:\n"
            "notebooklm skill install\n"
        ),
        "hermes": (
            "# Hermes Agent - add to ~/.hermes/config.yaml (single quotes keep Windows backslashes literal):\n"
            "mcp_servers:\n"
            "  notebooklm:\n"
            f"    command: '{py}'\n"
            "    args: [\"-m\", \"notebooklm.mcp\"]\n"
            "    timeout: 1300      # audio generation can take many minutes\n"
            "    connect_timeout: 60\n"
            "# then restart Hermes. Tools appear with the prefix mcp_notebooklm_*\n"
        ),
    }


def render(which: str, python: str = "") -> str:
    s = snippets(python)
    if which == "all":
        return "\n\n".join(f"===== {k} =====\n{v}" for k, v in s.items())
    if which not in s:
        raise SystemExit(f"unknown agent {which!r}; choose from {', '.join(AGENTS)} or all")
    return s[which]
