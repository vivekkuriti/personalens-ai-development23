"""PersonaUX AI — Streamlit entry point.  Run with:  streamlit run app.py"""
from __future__ import annotations

import logging

import streamlit as st

import config

st.set_page_config(page_title=f"{config.APP_NAME} — Persona-based UX testing", page_icon=":material/visibility:",
                   layout="wide", initial_sidebar_state="expanded")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

from agents.test_runner import active_run_ids  # noqa: E402
from database import init_db, mark_stale_runs_interrupted  # noqa: E402
from ui import dashboard, execution, new_test, overall_report, persona_library, persona_reports, results  # noqa: E402
from ui.common import PAGES, apply_style  # noqa: E402


@st.cache_resource
def _bootstrap() -> bool:
    init_db()
    mark_stale_runs_interrupted(active_run_ids())
    return True


_bootstrap()
apply_style()

PAGES.update({
    "dashboard": st.Page(dashboard.render, title="Dashboard", icon=":material/space_dashboard:", url_path="dashboard", default=True),
    "new_test": st.Page(new_test.render, title="New UX Test", icon=":material/add_circle:", url_path="new-test"),
    "execution": st.Page(execution.render, title="Live Execution", icon=":material/play_circle:", url_path="live"),
    "results": st.Page(results.render, title="Test Results", icon=":material/fact_check:", url_path="results"),
    "persona_reports": st.Page(persona_reports.render, title="Persona Reports", icon=":material/person_search:", url_path="persona-reports"),
    "overall": st.Page(overall_report.render, title="Overall Report", icon=":material/summarize:", url_path="overall-report"),
    "personas": st.Page(persona_library.render, title="Persona Library", icon=":material/groups:", url_path="personas"),
})

with st.sidebar:
    st.markdown(f"### {config.APP_NAME}")
    st.caption(config.APP_TAGLINE)

nav = st.navigation({
    "Workspace": [PAGES["dashboard"], PAGES["new_test"], PAGES["execution"]],
    "Reports": [PAGES["results"], PAGES["persona_reports"], PAGES["overall"]],
    "Configure": [PAGES["personas"]],
})

with st.sidebar:
    st.divider()
    st.caption(f"Model: {config.GEMINI_MODEL}")
    if not config.GEMINI_API_KEY:
        st.error("GEMINI_API_KEY missing")
    running = active_run_ids()
    if running:
        st.info(f"{len(running)} test run(s) in progress")

nav.run()
