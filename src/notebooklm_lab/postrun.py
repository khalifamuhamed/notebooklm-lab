"""Optional deliveries after a successful `morning` run (Telegram now; more later).

Rules: each delivery is opt-in, runs only after a run that produced new files, and can NEVER change the
morning exit code or lose the run - any problem is reported in plain Arabic and remembered in the state file."""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from . import deliver, inbox as ib, settings
from .morning import EXIT_OK, MorningOutcome, Paths


def telegram_enabled(flag: Optional[bool], paths: Paths) -> bool:
    return settings.flag("NOTEBOOKLM_LAB_TELEGRAM_AUTO", paths.base) if flag is None else flag


def run_post_actions(outcome: MorningOutcome, paths: Paths, *, telegram: Optional[bool] = None,
                     say: Callable[[str], None] = print) -> Dict[str, Any]:
    """Returns {delivery name: {status, ...}}; empty when nothing was enabled or nothing new was produced."""
    results: Dict[str, Any] = {}
    do_telegram = telegram_enabled(telegram, paths)
    if not do_telegram:
        return results
    if outcome.code != EXIT_OK or not outcome.run_dir or outcome.processed <= 0:
        return results  # no new files this time -> nothing to send
    d = deliver.from_run_dir(outcome.run_dir)
    if do_telegram:
        try:
            from . import telegram

            results["telegram"] = telegram.deliver_safely(d, paths.base, say)
        except Exception as exc:  # absolutely nothing may break the morning run
            say(f"⚠ تيليجرام: خطأ غير متوقع ({type(exc).__name__}) — تجاهلتُه، والملخص سليم.")
            results["telegram"] = {"status": "failed", "error": type(exc).__name__}
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
