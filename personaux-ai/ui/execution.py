from __future__ import annotations

from html import escape

import streamlit as st

from agents.test_runner import get_state
from database import get_test_run, latest_step, list_test_runs
from ui.common import fmt_dt, go, hero, outcome_pill, run_selector, show_image


def _log_html(events) -> str:
    lines = []
    for e in list(events)[-120:]:
        lines.append(f"<div><span class='t'>{e['time']}</span> <span class='k-{e['kind']}'>"
                     f"{escape(e['message'])}</span></div>")
    return "<div class='pux-log'>" + ("".join(reversed(lines)) or "Waiting for events...") + "</div>"


@st.fragment(run_every=2)
def _live_panel(run_id: int) -> None:
    run = get_test_run(run_id)
    if run is None:
        st.error("Run not found.")
        return
    state = get_state(run_id)
    executions = run.executions
    done = sum(1 for e in executions if e.status in ("completed", "error"))
    total = max(1, len(executions))
    running = next((e for e in executions if e.status == "running"), None)

    head = st.columns([3, 1])
    head[0].markdown(f"**#{run.id} · {run.website_url}**  \n<span class='pux-muted'>Goal: {escape(run.journey_goal)}</span>",
                     unsafe_allow_html=True)
    head[1].markdown(outcome_pill(run.status), unsafe_allow_html=True)
    progress = done / total
    if running:
        progress += (running.total_steps / max(1, run.max_steps)) / total
    st.progress(min(progress, 1.0), text=f"{done}/{len(executions)} personas finished")

    left, right = st.columns([3, 2])
    with left:
        if running:
            p = running.persona_snapshot
            with st.container(border=True):
                st.markdown(f"**Current persona:** {p['name']} — {p['title']}")
                st.markdown(f"**Current action:** {running.current_action or '-'}")
                st.markdown(f"**Current URL:** {running.current_url or '-'}")
                st.markdown(f"**Steps:** {running.total_steps}/{run.max_steps} · "
                            f"{running.successful_steps} ok · {running.failed_steps} failed")
            step = latest_step(running.id)
            if step:
                show_image(step.screenshot_path, caption=f"Step {step.step_number}: {step.action} {step.target or ''}")
                if step.observation:
                    st.info(f"{p['name']}: \u201c{step.observation}\u201d")
        elif run.status in ("completed", "failed", "interrupted"):
            st.success("All personas finished.") if run.status == "completed" else st.warning(
                f"Run {run.status}: {run.error_message or ''}")
            if st.button("View results", type="primary", icon=":material/insights:"):
                go("results", selected_run_id=run.id)
        else:
            st.info("Preparing browser...")
        st.markdown("**Persona status**")
        for e in executions:
            st.markdown(f"{outcome_pill(e.outcome or e.status)} &nbsp; {e.persona_snapshot['name']} "
                        f"<span class='pux-muted'>· {e.total_steps} steps"
                        f"{' · score ' + str(e.experience_score) if e.experience_score is not None else ''}</span>",
                        unsafe_allow_html=True)
    with right:
        st.markdown("**Live log**")
        if state:
            st.markdown(_log_html(state.events), unsafe_allow_html=True)
        else:
            st.caption("Live log is only available in the server session that started this run. Step history:")
            for e in executions:
                for s in e.steps[-15:]:
                    st.caption(f"{e.persona_snapshot['name']} · step {s.step_number}: {s.action} {s.target or ''} "
                               f"-> {'ok' if s.success else s.error}")
    finished = run.status in ("completed", "failed", "interrupted")
    if not finished:
        st.session_state["_live_was_running"] = True
    elif st.session_state.pop("_live_was_running", False):
        st.rerun(scope="app")


def render() -> None:
    hero("Live execution", "Watch personas navigate in a real Chromium browser, step by step.")
    runs = list_test_runs(30)
    if not runs:
        st.info("No test runs yet.")
        if st.button("Start a new UX test", type="primary"):
            go("new_test")
        return
    default = st.session_state.get("live_run_id") or next((r.id for r in runs if r.status == "running"), runs[0].id)
    run_id = run_selector(runs, "live_run_select", default)
    st.session_state["live_run_id"] = run_id
    st.caption("Runs continue in the background if you leave this page. Started " +
               fmt_dt(next(r.created_at for r in runs if r.id == run_id)))
    _live_panel(run_id)
