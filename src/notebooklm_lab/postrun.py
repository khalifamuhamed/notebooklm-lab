"""Optional deliveries after a successful `morning` run (Telegram, Obsidian).

Rules: each delivery is opt-in, runs only after a run that produced new files, and can NEVER change the
morning exit code or lose the run - any problem is reported in plain Arabic and remembered in the state file."""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from . import deliver, inbox as ib, settings
from .morning import EXIT_OK, MorningOutcome, Paths

AUTO_ENV = {"telegram": "NOTEBOOKLM_LAB_TELEGRAM_AUTO", "obsidian": "NOTEBOOKLM_LAB_OBSIDIAN_AUTO"}


def enabled(name: str, flag: Optional[bool], paths: Paths) -> bool:
    """An explicit --flag / --no-flag wins; otherwise the NOTEBOOKLM_LAB_<NAME>_AUTO setting decides (default: off)."""
    return settings.flag(AUTO_ENV[name], paths.base) if flag is None else flag


def _telegram(d, paths, say):
    from . import telegram

    return telegram.deliver_safely(d, paths.base, say)


def _obsidian(d, paths, say):
    from . import obsidian

    return obsidian.deliver_safely(d, paths.base, say)


DELIVERIES = {"telegram": ("تيليجرام", _telegram), "obsidian": ("Obsidian", _obsidian)}


def run_post_actions(outcome: MorningOutcome, paths: Paths, *, telegram: Optional[bool] = None, obsidian: Optional[bool] = None,
                     say: Callable[[str], None] = print) -> Dict[str, Any]:
    """Returns {delivery name: {status, ...}}; empty when nothing was enabled or nothing new was produced."""
    flags = {"telegram": telegram, "obsidian": obsidian}
    wanted = [n for n in DELIVERIES if enabled(n, flags[n], paths)]
    if not wanted or outcome.code != EXIT_OK or not outcome.run_dir or outcome.processed <= 0:
        return {}  # nothing enabled, or no new files this time -> nothing to deliver
    d = deliver.from_run_dir(outcome.run_dir)
    results: Dict[str, Any] = {}
    for name in wanted:
        label, fn = DELIVERIES[name]
        try:
            results[name] = fn(d, paths, say)
        except Exception as exc:  # absolutely nothing may break the morning run
            say(f"⚠ {label}: خطأ غير متوقع ({type(exc).__name__}) — تجاهلتُه، والملخص سليم.")
            results[name] = {"status": "failed", "error": type(exc).__name__}
    _remember(paths, results)
    return results


def _remember(paths: Paths, results: Dict[str, Any]) -> None:
    try:
        state = ib.load_state(paths.state)
        for key in ("last_run", "last_success"):
            if isinstance(state.get(key), dict):
                state[key]["delivery"] = results
        ib.save_state(paths.state, state)
    except Exception:
        pass
