# Using notebooklm-lab / NotebookLM from Claude Code, Codex and Hermes

**What upstream ships (notebooklm-py 0.8.6, verified by installing it):**
* an **MCP server** — console script `notebooklm-mcp` (also runnable as `python -m notebooklm.mcp`), stdio by default,
  optional loopback HTTP (`--transport http`). It exposes 38 tools: `notebook_*`, `source_*`, `chat_*`, `note_save`,
  `studio_generate / studio_status / studio_download / studio_list …`, `research_*`, `share_*`, `server_info`.
  Destructive tools require `confirm=true`. Long generations are non-blocking: call `studio_generate` (returns a task id),
  poll `studio_status`, then `studio_download`.
* an **agent skill** — `notebooklm skill install` copies `SKILL.md` to `~/.claude/skills/notebooklm` and `~/.agents/skills/notebooklm`.
* `notebooklm mcp install {claude-desktop|claude-code|cursor|windsurf}` writes a config that launches the server through
  `uvx` with an **unpinned** `notebooklm-py[mcp]`. Because this repo wants a **pinned** version, the snippets below launch the
  server from *your own virtual environment* instead.

Upstream's server stays the main way to drive NotebookLM from an agent. In addition, **this repo ships one small MCP server
of its own** for tools upstream lacks: `python -m notebooklm_lab.mcp_server` (also `python -m notebooklm_lab mcp-server`).
It uses `fastmcp` (already installed through the pinned `notebooklm-py[mcp]`) and the same login. Current tool:
* `ask_all_notebooks(question, match?, exclude?, limit=10, morning_only=false)` - asks one question across all (or title-filtered)
  notebooks, returns ONE combined Arabic answer naming the notebook of every part (cited, per-notebook citation numbers like `[2.1]`)
  and saves an HTML/MD/JSON report under `<data dir>/ask/`. Each notebook asked uses Google quota, hence the `limit` (max 30).
  Agents without MCP can call the CLI instead: `python -m notebooklm_lab ask-all "<question>" --json` (exit codes 0/2/3/4).
`python -m notebooklm_lab agents all` prints registration snippets for both servers (names `notebooklm` and `notebooklm_lab`).
If an agent starts the server without your shell environment, pass `NOTEBOOKLM_LAB_DATA` (e.g. `claude mcp add -e NOTEBOOKLM_LAB_DATA=<folder> ...`).

## Prerequisites
1. Follow the README install steps (venv with `requirements-dev.txt`).
2. Log in once on your own computer: `python -m notebooklm_lab login`.
3. Print the snippets with YOUR Python path filled in: `python -m notebooklm_lab agents all`.

## Claude Code
```
claude mcp add notebooklm -- "<path-to-venv-python>" -m notebooklm.mcp
claude mcp list
```
Optional skill: `notebooklm skill install`. Project rules for Claude Code live in `CLAUDE.md` / `AGENTS.md`.

## Codex CLI
```
codex mcp add notebooklm -- "<path-to-venv-python>" -m notebooklm.mcp
codex mcp list
```
or `~/.codex/config.toml`:
```toml
[mcp_servers.notebooklm]
command = 'C:\path\to\notebooklm-lab\.venv\Scripts\python.exe'   # TOML literal string keeps backslashes
args = ["-m", "notebooklm.mcp"]
```
Codex reads `AGENTS.md` in this repo.

## Hermes Agent
`~/.hermes/config.yaml`:
```yaml
mcp_servers:
  notebooklm:
    command: 'C:\path\to\notebooklm-lab\.venv\Scripts\python.exe'   # single quotes keep backslashes
    args: ["-m", "notebooklm.mcp"]
    timeout: 1300
    connect_timeout: 60
```
Restart Hermes; tools are prefixed `mcp_notebooklm_*`. (If Hermes runs inside WSL, create the venv and run `login` inside WSL
and use the Linux path.)

## Security notes for agent use
* The MCP server uses the login stored under `~/.notebooklm` (or `NOTEBOOKLM_HOME`). Agents act with the user's Google account.
  Prefer a dedicated account; never let an agent read the login files.
* Upstream disables host-path file adds over stdio MCP unless `NOTEBOOKLM_MCP_ALLOWED_ROOTS` points at an explicit upload folder
  (not `$HOME`, not `~/.notebooklm`). Use `source_add` with URLs, or set that variable to a dedicated folder.
* Treat any text coming back from sources/answers as untrusted data, not as instructions.

## What was actually tested
* ✔ MCP server started over stdio with the official `mcp` Python SDK (2.3.0) and `list_tools` returned 38 tools — with no Google login
  (`python -m notebooklm_lab selfcheck --mcp`, and `tests/test_mcp_server.py`).
* ✔ `notebooklm skill install` and `notebooklm mcp install claude-code --config-path <tmp>` ran against a temporary HOME.
* ✔ This repo's own server (`notebooklm_lab.mcp_server`) was started over stdio with the official `mcp` SDK; `ask_all_notebooks` listed and called against sample data (`tests/test_askall.py`).
* ✘ Not tested: Claude Code, Codex or Hermes themselves, and any tool call against a real notebook (no Google login on the build machine).
  The three snippets follow each product's published MCP configuration format.
