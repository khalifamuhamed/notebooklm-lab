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

## Using NotebookLM from an agent
Prefer upstream's MCP server (`python -m notebooklm.mcp`, tools such as `notebook_create`, `source_add`,
`chat_ask`, `studio_generate`/`studio_status`/`studio_download`) — see `docs/AGENTS_SETUP.md`.
For the content-creator flow ("links → Arabic summary + audio overview + report") run the `digest` command.
