from __future__ import annotations

from html import escape

import streamlit as st

from database import list_test_runs
from reports.report_generator import overall_report_data
from ui.common import go, hero, outcome_pill, run_selector, show_image


def render() -> None:
    hero("Test results", "Outcome, score and key evidence for every persona in a run.")
    runs = list_test_runs(50)
    if not runs:
        st.info("No test runs yet.")
        return
    run_id = run_selector(runs, "results_run", st.session_state.get("selected_run_id"))
    st.session_state["selected_run_id"] = run_id
    data = overall_report_data(run_id)
    if data is None:
        st.error("Run not found.")
        return

    st.markdown(f"**Goal:** {escape(data['journey_goal'])}  \n<span class='pux-muted'>{data['viewport']} · "
                f"max {data['max_steps']} steps · status {data['status']}</span>", unsafe_allow_html=True)
    c = st.columns(5)
    c[0].metric("Personas", data["total_personas"])
    c[1].metric("Successful", data["successful"])
    c[2].metric("Abandoned", data["abandoned"])
    c[3].metric("UX findings", data["total_findings"], help=f"{data['verified_findings']} verified in browser")
    c[4].metric("A11y violations", data["total_a11y"], help=f"{data['unique_a11y_rules']} distinct rules")
    b = st.columns([1, 1, 3])
    if b[0].button("Overall report", type="primary", icon=":material/summarize:", use_container_width=True):
        go("overall", selected_run_id=run_id)
    if data["status"] in ("running", "pending") and b[1].button("Watch live", use_container_width=True):
        go("execution", live_run_id=run_id)

    for p in data["personas"]:
        persona = p["persona"]
        with st.container(border=True):
            top = st.columns([3, 1, 1, 1])
            top[0].markdown(f"### {persona['name']} <span class='pux-muted'>· {persona['title']}</span>",
                            unsafe_allow_html=True)
            top[0].markdown(outcome_pill(p["outcome"]), unsafe_allow_html=True)
            top[1].metric("Score", f"{p['score']:.0f}" if p["score"] is not None else "-")
            top[2].metric("Goal progress", f"{p['goal_progress']}%")
            top[3].metric("Steps", f"{p['successful_steps']}/{p['total_steps']}", help="successful / total")
            body = st.columns([3, 2])
            with body[0]:
                if p["summary"]:
                    st.markdown(p["summary"])
                if p["abandonment_reason"]:
                    st.warning(f"End reason: {p['abandonment_reason']}")
                crit = [f for f in p["findings"] if f["severity"] in ("Critical", "High")][:4]
                if crit:
                    st.markdown("**Top findings**")
                    for f in crit:
                        tag = "verified" if f["source"] == "verified" else "AI-inferred"
                        st.markdown(f"- **[{f['severity']}]** {f['title']} <span class='pux-muted'>({tag})</span>",
                                    unsafe_allow_html=True)
                st.caption(f"{len(p['findings'])} UX findings · {len(p['violations'])} accessibility violations · "
                           f"{p['duration_seconds'] or 0:.0f}s")
                if st.button("Open persona report", key=f"open_{p['execution_id']}", icon=":material/person_search:"):
                    go("persona_reports", selected_run_id=run_id, selected_execution_id=p["execution_id"])
            with body[1]:
                shots = [s for s in p["steps"] if s["screenshot_path"]]
                if shots:
                    show_image(shots[-1]["screenshot_path"], caption=f"Final state · step {shots[-1]['step_number']}")
