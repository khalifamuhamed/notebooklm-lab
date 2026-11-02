See [AGENTS.md](AGENTS.md) — the same rules apply to Claude Code.
Key points: never read or commit NotebookLM login files; run `python -m notebooklm_lab secrets-scan` before commits;
sample-mode data must stay labelled as sample; `notebooklm-py` is an unofficial dependency pinned in `pyproject.toml`.
