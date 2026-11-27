from __future__ import annotations

from html import escape

import streamlit as st

from database import get_test_run, list_test_runs
from reports.report_generator import ensure_persona_pdf, persona_report_data
from ui.common import hero, outcome_pill, render_finding, render_violations, run_selector, show_image


def render() -> None:
    hero("Persona reports", "A detailed, evidence-backed account of one persona's journey.")
    runs = list_test_runs(50)
    if not runs:
        st.info("No test runs yet.")
        return
    cols = st.columns(2)
    with cols[0]:
        run_id = run_selector(runs, "pr_run", st.session_state.get("selected_run_id"))
    st.session_state["selected_run_id"] = run_id
    run = get_test_run(run_id)
    if not run or not run.executions:
        st.info("This run has no persona executions.")
        return
    ids = [e.id for e in run.executions]
    names = {e.id: f"{e.persona_snapshot['name']} — {e.persona_snapshot['title']}" for e in run.executions}
    pre = st.session_state.get("selected_execution_id")
    with cols[1]:
        execution_id = st.selectbox("Persona", ids, index=ids.index(pre) if pre in ids else 0, format_func=names.get)
    st.session_state["selected_execution_id"] = execution_id
    data = persona_report_data(execution_id)
    p = data["persona"]

    with st.container(border=True):
        head = st.columns([3, 1, 1, 1])
        head[0].markdown(f"## {p['name']} <span class='pux-muted'>· {p['title']}</span>", unsafe_allow_html=True)
        head[0].markdown(outcome_pill(data["outcome"]), unsafe_allow_html=True)
        head[1].metric("Experience score", f"{data['score']:.0f}/100" if data["score"] is not None else "-")
        head[2].metric("Goal progress", f"{data['goal_progress']}%")
        head[3].metric("Duration", f"{data['duration_seconds'] or 0:.0f}s")
        st.markdown(f"{escape(p['description'])}  \n<span class='pux-muted'>{escape(p.get('behaviors', ''))}</span>",
                    unsafe_allow_html=True)
        st.caption(f"Interaction: {p['interaction_mode']} · zoom {int((p.get('text_zoom') or 1) * 100)}% · "
                   f"language {p['language_level']} · patience {p['patience']}/10 · tech confidence {p['tech_confidence']}/5")
        st.markdown(f"**Objective:** {escape(data['journey_goal'])}  \n**Website:** {data['website_url']}")
        if data["status"] in ("completed", "error"):
            try:
                pdf = ensure_persona_pdf(execution_id)
                if pdf:
                    st.download_button("Download PDF report", pdf.read_bytes(), file_name=pdf.name,
                                       mime="application/pdf", icon=":material/download:", type="primary")
            except Exception as exc:  # PDF generation must not break the page
                st.warning(f"PDF could not be generated: {exc}")

    tabs = st.tabs(["Summary", f"UX findings ({len(data['findings'])})",
                    f"Accessibility ({len(data['violations'])})", f"Timeline ({len(data['steps'])})"])
    with tabs[0]:
        if data["summary"]:
            st.markdown(data["summary"])
        if data["abandonment_reason"]:
            st.warning(f"End / abandonment reason: {data['abandonment_reason']}")
        a = data["assessment"]
        if a:
            q = st.columns(5)
            for col, (label, key, good) in zip(q, [
                ("Understood site", "understood_site", True), ("Action easy to find", "action_easy_to_find", True),
                ("Confusing", "interaction_confusing", False), ("Instructions clear", "instructions_clear", True),
                ("Unnecessary steps", "unnecessary_steps", False)]):
                col.metric(label, "Yes" if a.get(key) else "No")
        m = st.columns(3)
        m[0].metric("Total steps", data["total_steps"])
        m[1].metric("Successful", data["successful_steps"])
        m[2].metric("Failed", data["failed_steps"])
        if data["failed_interactions"]:
            st.markdown("**Failed interactions**")
            for s in data["failed_interactions"]:
                st.markdown(f"- Step {s['step_number']}: `{s['action']}` {escape(str(s['target'] or ''))} — {escape(s['error'] or '')}")
        if data["recommendations"]:
            st.markdown("**Recommended improvements**")
            for i, r in enumerate(data["recommendations"], 1):
                st.markdown(f"{i}. {r}")
    with tabs[1]:
        if not data["findings"]:
            st.success("No UX friction findings recorded.")
        st.caption("Verified = measured directly in the browser. AI-inferred = persona perception from Gemini, "
                   "anchored to a recorded step and screenshot.")
        for f in data["findings"]:
            render_finding(f)
    with tabs[2]:
        render_violations(data["violations"])
    with tabs[3]:
        for s in data["steps"]:
            icon = "OK" if s["success"] else "FAILED"
            with st.expander(f"Step {s['step_number']} · {s['action']} {str(s['target'] or '')[:70]} · {icon}"):
                c = st.columns([2, 3])
                with c[0]:
                    st.markdown(f"**Reason:** {s['reason'] or '-'}")
                    if s["observation"]:
                        st.markdown(f"**{p['name']} thinks:** \u201c{s['observation']}\u201d")
                    if s["friction_note"]:
                        st.markdown(f"**Friction:** {s['friction_note']}")
                    if s["error"]:
                        st.error(s["error"])
                    elif s["detail"]:
                        st.caption(s["detail"])
                    st.caption(f"URL: {s['url_after']}")
                    meta = []
                    if s["confidence"] is not None:
                        meta.append(f"confidence {s['confidence']:.0%}")
                    if s["load_time_ms"]:
                        meta.append(f"load {s['load_time_ms']} ms")
                    if s["timestamp"]:
                        meta.append(s["timestamp"].strftime("%H:%M:%S"))
                    st.caption(" · ".join(meta))
                    if s["console_errors"]:
                        st.code("\n".join(s["console_errors"][:5]))
                with c[1]:
                    show_image(s["screenshot_path"])
