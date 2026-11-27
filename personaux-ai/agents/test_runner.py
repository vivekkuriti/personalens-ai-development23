"""Runs test runs on background threads so they survive Streamlit reruns and page navigation."""
from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

from agents.persona_agent import run_test


@dataclass
class LiveState:
    run_id: int
    events: deque = field(default_factory=lambda: deque(maxlen=400))
    current_persona: str | None = None
    latest_screenshot: str | None = None
    latest_url: str | None = None
    finished: bool = False
    thread: threading.Thread | None = None

    def add(self, kind: str, message: str, **data) -> None:
        if kind == "persona":
            self.current_persona = data.get("persona")
        if data.get("screenshot"):
            self.latest_screenshot = data["screenshot"]
        if data.get("url"):
            self.latest_url = data["url"]
        self.events.append({"time": datetime.now().strftime("%H:%M:%S"), "kind": kind, "message": message,
                            "persona": self.current_persona})


_lock = threading.Lock()
_states: dict[int, LiveState] = {}


def start_run(run_id: int) -> LiveState:
    with _lock:
        state = _states.get(run_id)
        if state and state.thread and state.thread.is_alive():
            return state
        state = LiveState(run_id=run_id)
        _states[run_id] = state

    def target() -> None:
        try:
            run_test(run_id, emit=state.add)
        finally:
            state.finished = True

    state.thread = threading.Thread(target=target, name=f"personaux-run-{run_id}", daemon=True)
    state.thread.start()
    return state


def get_state(run_id: int) -> LiveState | None:
    return _states.get(run_id)


def active_run_ids() -> set[int]:
    return {rid for rid, st in _states.items() if st.thread and st.thread.is_alive()}
