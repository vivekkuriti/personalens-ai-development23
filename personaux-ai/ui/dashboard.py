from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

import config
from database import dashboard_stats, list_test_runs
from ui.common import OUTCOME_COLORS, SEVERITY_ORDER, fmt_dt, go, hero


def render() -> None:
    hero(config.APP_NAME, config.APP_TAGLINE + " AI personas explore your site in a real browser and report verified friction.")
    stats = dashboard_stats()

    c = st.columns(4)
    c[0].metric("Test runs", stats["total_runs"])
    c[1].metric("Personas tested", stats["total_executions"], help=f"{stats['distinct_personas']} distinct personas")
    c[2].metric("Journey success rate", f"{stats['success_rate']}%")
    c[3].metric("Critical findings", stats["critical_findings"])
    c = st.columns(4)
    c[0].metric("UX findings", stats["total_findings"])
    c[1].metric("Accessibility violations", stats["a11y_violations"])
    with c[3]:
        if st.button("Start a new UX test", type="primary", use_container_width=True, icon=":material/play_arrow:"):
            go("new_test")

    if stats["total_runs"] == 0:
        st.info("No tests yet. Start a new UX test to see personas navigate your website.")
        return

    left, right = st.columns(2)
    with left:
        with st.container(border=True):
            st.subheader("Issue severity distribution")
            sev = stats["severity_distribution"]
            a11y = stats["a11y_distribution"]
            rows = [{"Severity": s, "Type": "UX finding", "Count": sev.get(s, 0)} for s in SEVERITY_ORDER] + \
                   [{"Severity": s, "Type": "Accessibility", "Count": a11y.get(s, 0)} for s in SEVERITY_ORDER]
            df = pd.DataFrame(rows)
            if df["Count"].sum():
                fig = px.bar(df, x="Severity", y="Count", color="Type", barmode="group",
                             color_discrete_sequence=["#0F766E", "#7C3AED"], category_orders={"Severity": SEVERITY_ORDER})
                fig.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10), legend_title=None)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.caption("No issues recorded yet.")
    with right:
        with st.container(border=True):
            st.subheader("Persona comparison")
            pc = pd.DataFrame(stats["persona_comparison"])
            if not pc.empty:
                fig = px.bar(pc.sort_values("avg_score"), x="avg_score", y="persona", orientation="h",
                             text="avg_score", labels={"avg_score": "Avg. experience score", "persona": ""},
                             color_discrete_sequence=["#0F766E"], range_x=[0, 100])
                fig.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10))
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.caption("Results appear here after the first completed persona.")

    st.subheader("Recent test runs")
    for run in list_test_runs(10):
        with st.container(border=True):
            cols = st.columns([4, 2, 2, 2])
            cols[0].markdown(f"**#{run.id} · {run.website_url}**  \n<span class='pux-muted'>{run.journey_goal[:110]}</span>",
                             unsafe_allow_html=True)
            outcomes = [e.outcome for e in run.executions]
            cols[1].markdown(f"<span class='pux-muted'>Personas</span><br>{len(run.executions)} · "
                             f"{outcomes.count('success')} succeeded", unsafe_allow_html=True)
            cols[2].markdown(f"<span class='pux-muted'>{fmt_dt(run.created_at)}</span><br>"
                             f"<b style='color:{OUTCOME_COLORS.get(run.status, '#64748B')}'>{run.status.capitalize()}</b>",
                             unsafe_allow_html=True)
            if run.status in ("running", "pending"):
                if cols[3].button("Watch live", key=f"dash_live_{run.id}", use_container_width=True):
                    go("execution", live_run_id=run.id)
            elif cols[3].button("View results", key=f"dash_res_{run.id}", use_container_width=True):
                go("results", selected_run_id=run.id)
