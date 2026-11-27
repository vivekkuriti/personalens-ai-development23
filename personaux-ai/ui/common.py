"""Shared UI helpers: page registry, styling, badges and reusable renderers."""
from __future__ import annotations

from html import escape
from pathlib import Path

import streamlit as st

PAGES: dict = {}

SEVERITY_COLORS = {"Critical": "#B91C1C", "High": "#C2410C", "Medium": "#A16207", "Low": "#1D4ED8"}
OUTCOME_COLORS = {"success": "#15803D", "failure": "#B91C1C", "abandoned": "#C2410C", "error": "#6B7280",
                  "running": "#0F766E", "pending": "#64748B", "completed": "#15803D", "failed": "#B91C1C",
                  "interrupted": "#6B7280"}
SEVERITY_ORDER = ["Critical", "High", "Medium", "Low"]

CSS = """
<style>
  .block-container { padding-top: 2rem; max-width: 1200px; }
  .pux-hero h1 { font-size: 1.9rem; margin-bottom: .1rem; color: #0F172A; }
  .pux-hero p { color: #475569; margin-top: 0; }
  .pux-pill { display:inline-block; padding: 2px 10px; border-radius: 999px; font-size: .78rem; font-weight: 600;
              color: #fff; letter-spacing: .01em; }
  .pux-muted { color: #64748B; font-size: .85rem; }
  .pux-log { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .8rem; line-height: 1.45;
             background: #0F172A; color: #E2E8F0; border-radius: 8px; padding: .75rem 1rem; max-height: 420px; overflow-y: auto; }
  .pux-log .t { color: #94A3B8; } .pux-log .k-error { color: #FCA5A5; } .pux-log .k-finding { color: #FCD34D; }
  .pux-log .k-a11y { color: #C4B5FD; } .pux-log .k-action { color: #5EEAD4; } .pux-log .k-persona { color: #FFFFFF; font-weight: 700; }
  .pux-log .k-friction { color: #FDBA74; } .pux-log .k-done { color: #86EFAC; font-weight: 700; }
  div[data-testid="stMetricValue"] { font-size: 1.6rem; }
</style>
"""


def apply_style() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def hero(title: str, subtitle: str) -> None:
    st.markdown(f'<div class="pux-hero"><h1>{escape(title)}</h1><p>{escape(subtitle)}</p></div>', unsafe_allow_html=True)


def pill(label: str, color: str) -> str:
    return f'<span class="pux-pill" style="background:{color}">{escape(label)}</span>'


def severity_pill(sev: str) -> str:
    return pill(sev, SEVERITY_COLORS.get(sev, "#64748B"))


def outcome_pill(outcome: str | None) -> str:
    o = outcome or "pending"
    return pill(o.capitalize(), OUTCOME_COLORS.get(o, "#64748B"))


def go(page_key: str, **state) -> None:
    for k, v in state.items():
        st.session_state[k] = v
    st.switch_page(PAGES[page_key])


def fmt_dt(d) -> str:
    return d.strftime("%Y-%m-%d %H:%M") if d else "-"


def show_image(path: str | None, caption: str | None = None) -> None:
    if path and Path(path).exists():
        st.image(path, caption=caption, use_container_width=True)
    else:
        st.caption("Screenshot unavailable")


def render_finding(f: dict, show_persona: bool = False, expanded: bool = False) -> None:
    source = "Verified in browser" if f["source"] == "verified" else f"AI-inferred · {f['confidence']:.0%} confidence"
    label = f"[{f['severity']}] {f['title']}" + (f" — {f['persona_name']}" if show_persona else "")
    with st.expander(label, expanded=expanded):
        st.markdown(f"{severity_pill(f['severity'])} &nbsp; **{escape(f['category'])}** &nbsp; "
                    f"<span class='pux-muted'>{escape(source)}</span>", unsafe_allow_html=True)
        cols = st.columns([3, 2]) if f.get("screenshot_path") else [st.container()]
        with cols[0]:
            st.markdown(f"**Description:** {f['description']}")
            st.markdown(f"**Evidence:** {f['evidence']}")
            st.markdown(f"**User impact:** {f['user_impact']}")
            st.markdown(f"**Suggested fix:** {f['suggested_fix']}")
            if f.get("url"):
                st.caption(f"URL: {f['url']}" + (f" · step {f['step_number']}" if f.get("step_number") else ""))
        if f.get("screenshot_path"):
            with cols[1]:
                show_image(f["screenshot_path"], caption=f"Step {f.get('step_number')}")


def render_violations(violations: list[dict]) -> None:
    if not violations:
        st.success("No automated accessibility violations detected on the scanned pages.")
        st.caption("Automated checks cover only part of WCAG; they do not establish full compliance.")
        return
    grouped: dict[str, dict] = {}
    for v in violations:
        g = grouped.setdefault(v["rule_id"], {**v, "nodes": [], "pages": set()})
        g["nodes"].append(v)
        g["pages"].add(v["url"])
    for g in sorted(grouped.values(), key=lambda x: SEVERITY_ORDER.index(x["severity"])):
        with st.expander(f"[{g['severity']}] {g['rule_id']} — {g['help_text'] or g['description']} ({len(g['nodes'])})"):
            st.markdown(f"{severity_pill(g['severity'])} &nbsp; impact **{g['impact']}** &nbsp; "
                        f"<span class='pux-muted'>source: {escape(g['source'])}</span>", unsafe_allow_html=True)
            st.markdown(g["description"])
            st.markdown(f"**Suggested fix:** {g['suggested_fix']}")
            if g.get("help_url"):
                st.markdown(f"[Rule documentation]({g['help_url']})")
            for n in g["nodes"][:5]:
                if n["html"]:
                    st.code(n["html"], language="html")
            st.caption("Pages: " + ", ".join(sorted(g["pages"])))
    st.caption("Automated checks (axe-core and keyboard heuristics) cover only part of WCAG; they do not establish full compliance.")


def run_selector(runs, key: str, default_id: int | None = None):
    if not runs:
        return None
    labels = {r.id: f"#{r.id} · {r.website_url} · {fmt_dt(r.created_at)} · {r.status}" for r in runs}
    ids = list(labels)
    index = ids.index(default_id) if default_id in ids else 0
    return st.selectbox("Test run", ids, index=index, format_func=labels.get, key=key)
