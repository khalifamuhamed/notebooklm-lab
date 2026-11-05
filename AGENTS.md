# AGENTS.md — rules for coding/automation agents working in this repo

This is `notebooklm-lab`, a prototype built **on top of** the unofficial third-party library
[`notebooklm-py`](https://github.com/teng-lin/notebooklm-py) (MIT, by Teng Lin; pinned to `0.8.6`).
It is unofficial and **not affiliated with Google**.

## Commands
```
pip install -r requirements-dev.txt && pip install -e .
python -m notebooklm_lab demo                    # offline SAMPLE data, no login
python -m notebooklm_lab digest --file links.txt # REAL NotebookLM (needs the user's own login)
python -m notebooklm_lab digest --file links.txt --sample
python -m notebooklm_lab morning --sample        # morning digest offline (inbox.txt in ~/NotebookLM-Lab or --data-dir)
python -m notebooklm_lab morning status | schedule --time 07:30 [--install] | unschedule
python -m notebooklm_lab config init|show        # private settings file <data>/notebooklm-lab.env (git-ignored; names in .env.example)
python -m notebooklm_lab telegram setup-check [--send-test] | chat-id | send [file] [--sample]   # needs TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
python -m notebooklm_lab morning --telegram      # also send summary + podcast to Telegram (or NOTEBOOKLM_LAB_TELEGRAM_AUTO=1)
python -m notebooklm_lab obsidian setup-check | save [--sample] [--no-audio]   # needs OBSIDIAN_VAULT (existing folder), OBSIDIAN_SUBFOLDER (default NotebookLM)
python -m notebooklm_lab morning --obsidian      # also save note + audio into the vault (or NOTEBOOKLM_LAB_OBSIDIAN_AUTO=1)
python -m notebooklm_lab ask-all "question" [--match T] [--limit N] [--sample] [--json]   # one question across all notebooks -> combined Arabic answer + report in <data>/ask
python -m notebooklm_lab mcp-server [--sample]   # this repo's own MCP server (stdio), tool ask_all_notebooks
python -m notebooklm_lab channels add @handle|URL | list | remove X | check [--dry-run]   # follow YouTube channels (public RSS) -> new links appended to inbox.txt; state <data>/channels.json
python -m notebooklm_lab morning --channels|--no-channels   # channel check runs first by default when channels are followed (not in --sample unless --channels)
python -m notebooklm_lab selfcheck --mcp         # pins, sample mode, .gitignore, secrets, MCP tools
pytest -q
```

## Hard rules
1. **Never read, print, copy, upload or commit** the NotebookLM login files (`storage_state.json`,
   `master_token.json`, `browser_profile/`, anything under `~/.notebooklm`). They are account-equivalent secrets.
   Use `python -m notebooklm_lab session where` to inspect their location/size instead.
2. Never vendor/copy code from `notebooklm-py`; depend on it via `pyproject.toml` / `requirements.txt` (pinned).
3. Run `python -m notebooklm_lab secrets-scan` before any commit. No machine-specific paths in committed files.
4. Sample-mode output is **example data, not NotebookLM output**; keep it labelled as such.
5. Do not push or create GitHub repos unless the user explicitly asks.
6. Generating audio/video uses the user's Google quota and can take many minutes — confirm before bulk runs.

## Credentials and settings
All credentials come from environment variables or the local, git-ignored `<data dir>/notebooklm-lab.env`
(`src/notebooklm_lab/settings.py`; env wins over the file). Never hard-code, print or commit a token; `.env.example` lists names only.
Optional deliveries after `morning` (`postrun.py`: Telegram, Obsidian) are opt-in, never raise, and never change the morning exit codes
(0 ok, 2 usage, 3 login missing/expired, 4 all failed). `telegram` commands use exit 5 for Telegram failures.
Obsidian (`obsidian.py`) writes plain files only, never overwrites/edits an existing note, never creates a missing vault, exit 6 on write problems.
`channels.py` reads only public YouTube pages/feeds (no key, no login), retries YouTube's flaky feed 3x, and never raises into `morning`.
Tests must mock the network (`telegram._post`, `channels.http_get`) — never call api.telegram.org or youtube.com from tests.

## Using NotebookLM from an agent
For questions across ALL notebooks use this repo's tool `ask_all_notebooks` (MCP server `python -m notebooklm_lab.mcp_server`) or the CLI `ask-all ... --json`;
it costs Google quota per notebook, so narrow with `match`/`limit`. stdout of the MCP server is protocol-only: never print there.
Prefer upstream's MCP server (`python -m notebooklm.mcp`, tools such as `notebook_create`, `source_add`,
`chat_ask`, `studio_generate`/`studio_status`/`studio_download`) — see `docs/AGENTS_SETUP.md`.
For the content-creator flow ("links → Arabic summary + audio overview + report") run the `digest` command.
