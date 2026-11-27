from __future__ import annotations

from html import escape

import streamlit as st

from database import delete_custom_persona, list_personas, save_custom_persona
from ui.common import hero

MODES = {"mouse": "Mouse / touch", "keyboard": "Keyboard only", "mixed": "Keyboard preferred"}
LANGS = {"native": "Native", "intermediate": "Intermediate", "basic": "Basic"}


def _form(prefix: str, persona=None) -> dict | None:
    with st.form(f"{prefix}_form", border=False):
        c = st.columns(2)
        name = c[0].text_input("Name", value=getattr(persona, "name", ""), max_chars=60)
        title = c[1].text_input("Title", value=getattr(persona, "title", ""), max_chars=80,
                                placeholder="e.g. Busy Parent on Mobile")
        description = st.text_area("Description", value=getattr(persona, "description", ""), max_chars=500, height=70)
        behaviors = st.text_area("Behaviors and needs", value=getattr(persona, "behaviors", ""), max_chars=1200,
                                 height=100, help="How they browse, what confuses them, what they expect.")
        c = st.columns(3)
        tech = c[0].slider("Tech confidence", 1, 5, getattr(persona, "tech_confidence", 3))
        patience = c[1].slider("Patience", 1, 10, getattr(persona, "patience", 5))
        zoom = c[2].select_slider("Browser zoom", [1.0, 1.25, 1.5, 1.75, 2.0], value=getattr(persona, "text_zoom", 1.0),
                                  format_func=lambda z: f"{int(z * 100)}%")
        c = st.columns(3)
        modes = list(MODES)
        mode = c[0].selectbox("Interaction", modes, index=modes.index(getattr(persona, "interaction_mode", "mouse")),
                              format_func=MODES.get)
        langs = list(LANGS)
        lang = c[1].selectbox("English level", langs, index=langs.index(getattr(persona, "language_level", "native")),
                              format_func=LANGS.get)
        contrast = c[2].checkbox("High-contrast mode", value=getattr(persona, "prefers_high_contrast", False))
        if not st.form_submit_button("Save persona", type="primary"):
            return None
    if len(name.strip()) < 2 or len(title.strip()) < 2 or len(description.strip()) < 10:
        st.error("Name, title and a description (10+ characters) are required.")
        return None
    return {"name": name.strip(), "title": title.strip(), "description": description.strip(),
            "behaviors": behaviors.strip(), "tech_confidence": tech, "patience": patience,
            "interaction_mode": mode, "text_zoom": float(zoom), "prefers_high_contrast": contrast,
            "language_level": lang}


def render() -> None:
    hero("Persona library", "Six research-based personas plus any custom personas you define.")
    with st.expander("Create a custom persona", icon=":material/person_add:"):
        data = _form("create")
        if data:
            save_custom_persona(data)
            st.success(f"Persona '{data['name']}' created.")
            st.rerun()

    personas = list_personas()
    cols = st.columns(2)
    for i, p in enumerate(personas):
        with cols[i % 2]:
            with st.container(border=True):
                tag = "Custom" if p.is_custom else "Predefined"
                st.markdown(f"#### {escape(p.name)} <span class='pux-muted'>· {escape(p.title)} · {tag}</span>",
                            unsafe_allow_html=True)
                st.markdown(escape(p.description))
                st.caption(p.behaviors)
                st.caption(f"{MODES[p.interaction_mode]} · zoom {int(p.text_zoom * 100)}% · English "
                           f"{LANGS[p.language_level].lower()} · patience {p.patience}/10 · tech {p.tech_confidence}/5"
                           + (" · high contrast" if p.prefers_high_contrast else ""))
                if p.is_custom:
                    with st.expander("Edit"):
                        data = _form(f"edit_{p.id}", p)
                        if data:
                            save_custom_persona(data, p.id)
                            st.success("Saved.")
                            st.rerun()
                        if st.button("Delete persona", key=f"del_{p.id}"):
                            delete_custom_persona(p.id)
                            st.rerun()
