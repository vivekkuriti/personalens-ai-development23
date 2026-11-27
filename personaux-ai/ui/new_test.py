from __future__ import annotations

import streamlit as st

import config
from agents.test_runner import start_run
from database import create_test_run, list_personas
from security import URLValidationError, validate_target_url
from ui.common import go, hero

GOAL_EXAMPLES = [
    "Find the pricing page and identify the cheapest plan.",
    "Create a new account using a test email address.",
    "Find the contact page and submit a support inquiry.",
    "Search for a product and add it to the cart.",
    "Find information about the company's return policy.",
]


def render() -> None:
    hero("New UX test", "Point personas at a live website and describe what they should try to accomplish.")
    if not config.GEMINI_API_KEY:
        st.error("GEMINI_API_KEY is not configured. Add it to your .env file before running tests.")

    personas = list_personas()
    with st.form("new_test_form", border=True):
        url = st.text_input("Website URL", placeholder="https://example.com",
                            help="Only public http(s) websites. Private networks and metadata endpoints are blocked.")
        goal = st.text_area("User journey goal", height=90, placeholder=GOAL_EXAMPLES[0],
                            help="Examples: " + " · ".join(GOAL_EXAMPLES[1:]))
        st.markdown("**Personas**")
        cols = st.columns(3)
        selected: list[int] = []
        for i, p in enumerate(personas):
            with cols[i % 3]:
                default = p.key in ("sarah", "alex", "david")
                if st.checkbox(f"{p.name} — {p.title}" + (" (custom)" if p.is_custom else ""), value=default,
                               key=f"persona_{p.id}", help=p.description):
                    selected.append(p.id)
        c1, c2 = st.columns(2)
        max_steps = c1.slider("Maximum steps per persona", 3, config.HARD_MAX_STEPS, config.DEFAULT_MAX_STEPS)
        viewport = c2.radio("Viewport", list(config.VIEWPORTS), horizontal=True)
        st.caption("Personas never make purchases, payments or deletions, use a dedicated test email "
                   f"({config.TEST_ACCOUNT_EMAIL}), and are restricted to the target domain.")
        consent = st.checkbox("I own this website or am authorised to run automated tests against it.")
        submitted = st.form_submit_button("Start test", type="primary", icon=":material/play_arrow:")

    if not submitted:
        return
    errors = []
    try:
        clean_url = validate_target_url(url)
    except URLValidationError as exc:
        clean_url = None
        errors.append(str(exc))
    if len(goal.strip()) < 8:
        errors.append("Describe the journey goal in a sentence (at least 8 characters).")
    if len(goal) > 600:
        errors.append("Keep the journey goal under 600 characters.")
    if not selected:
        errors.append("Select at least one persona.")
    if not consent:
        errors.append("Confirm you are authorised to test this website.")
    if not config.GEMINI_API_KEY:
        errors.append("GEMINI_API_KEY is missing.")
    if errors:
        for e in errors:
            st.error(e)
        return
    run_id = create_test_run(clean_url, goal.strip(), selected, max_steps, viewport)
    start_run(run_id)
    go("execution", live_run_id=run_id)
