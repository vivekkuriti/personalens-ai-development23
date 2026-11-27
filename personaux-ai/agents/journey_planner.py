"""Persona-conditioned planning: asks Gemini for the next browser action and validates it."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

import config
from agents.gemini_client import GeminiClient
from automation.dom_inspector import DomSnapshot
from automation.playwright_executor import ALLOWED_KEYS
from security import is_navigation_allowed

ActionName = Literal["navigate", "click", "fill", "select", "scroll", "press", "wait", "back", "done", "abandon"]
ELEMENT_ACTIONS = {"click", "fill", "select"}


class PlannedAction(BaseModel):
    observation: str = Field(description="What this persona perceives on the current page, in first person, max 2 sentences.")
    previous_step_assessment: str = Field(description="How the previous action went from the persona's view. Empty on first step.")
    understood_page: bool = Field(description="Does the persona understand what this page is for?")
    action_easy_to_find: bool = Field(description="Was the control needed for the next step easy to find?")
    confusing: bool = Field(description="Is anything on this page confusing to this persona?")
    instructions_clear: bool = Field(description="Are the on-page instructions clear to this persona?")
    friction_note: str = Field(description="Concrete friction the persona experiences, citing visible labels/text. Empty if none.")
    action: ActionName
    element_id: int | None = Field(default=None, description="ID from the element list for click/fill/select.")
    target: str = Field(description="Human-readable target, e.g. the button label.")
    value: str = Field(default="", description="Text to type, option label, key name, URL, or scroll direction.")
    reason: str = Field(description="Why the persona takes this action.")
    confidence: float = Field(description="0.0-1.0 confidence this action advances the goal.")

    @field_validator("confidence")
    @classmethod
    def _clamp(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))


def persona_profile_text(p: dict) -> str:
    mode = {
        "keyboard": "You CANNOT use a mouse. Every click/fill is executed by pressing Tab until the element is focused, then Enter/Space/typing.",
        "mixed": "You prefer the keyboard: you submit forms with Enter and expect shortcuts; you use the mouse only when necessary.",
        "mouse": "You use a mouse/touch.",
    }[p.get("interaction_mode", "mouse")]
    language = {
        "basic": "Your English is basic. Complex sentences, idioms, jargon or abbreviations confuse you and you may misread them.",
        "intermediate": "Your English is intermediate; jargon slows you down.",
        "native": "English is your native language.",
    }.get(p.get("language_level", "native"), "")
    zoom = p.get("text_zoom", 1.0) or 1.0
    vision = f"You browse at {int(zoom * 100)}% zoom." if zoom > 1 else ""
    if p.get("prefers_high_contrast"):
        vision += " You use a high-contrast/forced-colors mode; low-contrast or image-only controls are hard for you to see."
    return (
        f"Name: {p['name']} ({p['title']})\n"
        f"About: {p['description']}\n"
        f"Behaviors: {p.get('behaviors', '')}\n"
        f"Tech confidence: {p.get('tech_confidence', 3)}/5. Patience: {p.get('patience', 5)}/10 "
        f"(low patience = abandon sooner after friction).\n"
        f"{mode} {language} {vision}".strip()
    )


SYSTEM_PROMPT = """You are a UX research simulator role-playing a specific user persona who is using a real website through a real browser.
Stay strictly in character: decide what THIS persona would realistically do next, given their abilities, patience and understanding.
Rules:
- Base every statement ONLY on the page evidence provided (element list, headings, text, screenshot). Never invent elements, text or outcomes.
- For click/fill/select you MUST use an element_id from the provided element list.
- Use these test values only: email {email}, password (any; it will be replaced with a test password), full name "{name}", phone {phone}. Never enter payment card or government ID data.
- Never purchase, pay, donate, delete or cancel anything. If the goal would require that, choose "done" once you reach that point and explain.
- Fill all required fields of a form before submitting it. Do not repeat an action that already failed; try an alternative.
- Use "done" only when the page evidence shows the goal is achieved (e.g. a success/confirmation message) or the remaining step would be irreversible.
- Use "abandon" when this persona would realistically give up (confused, blocked, out of patience). Explain why in reason.
- Actions: navigate (value=URL on the same site), click, fill (value=text), select (value=option label), scroll (value=down|up), press (value=key such as Enter, Tab, Escape), wait, back, done, abandon.
Respond with JSON only."""


class JourneyPlanner:
    def __init__(self, client: GeminiClient) -> None:
        self.client = client

    def plan(
        self,
        persona: dict,
        goal: str,
        dom: DomSnapshot,
        history: list[str],
        step_number: int,
        max_steps: int,
        screenshot: bytes | None,
        recent_errors: list[str],
        blocked: list[str],
    ) -> PlannedAction:
        headings = "; ".join(f"h{h['level']}: {h['text']}" for h in dom.headings[:10]) or "(none)"
        prompt = (
            f"PERSONA\n{persona_profile_text(persona)}\n\n"
            f"GOAL\n{goal}\n\n"
            f"PROGRESS: step {step_number} of max {max_steps}.\n"
            f"HISTORY (most recent last):\n" + ("\n".join(history[-10:]) or "(this is the first page)") + "\n\n"
            f"CURRENT PAGE\nURL: {dom.url}\nTitle: {dom.title}\nHeadings: {headings}\n"
            f"Visible alerts/errors: {'; '.join(dom.alerts) or 'none'}\n"
            f"Forms: {dom.forms}, visible inputs: {dom.visible_inputs} (required: {dom.required_inputs})\n"
            f"Scroll: {dom.scroll_y}px of {dom.scroll_height}px page height (viewport {dom.viewport_height}px)\n"
            f"Technical errors since last step: {'; '.join(recent_errors[:4]) or 'none'}\n"
            f"Blocked off-site navigations: {'; '.join(blocked[-3:]) or 'none'}\n\n"
            f"INTERACTIVE ELEMENTS\n{dom.describe_elements()}\n\n"
            f"VISIBLE TEXT (excerpt)\n{dom.text_excerpt[:1400]}\n\n"
            "Decide the persona's next single action."
        )
        contents: list = [prompt]
        if screenshot and config.GEMINI_SEND_SCREENSHOTS:
            contents.append(GeminiClient.image_part(screenshot))
        system = SYSTEM_PROMPT.format(
            email=config.TEST_ACCOUNT_EMAIL, name=config.TEST_ACCOUNT_NAME, phone=config.TEST_ACCOUNT_PHONE
        )
        return self.client.generate_structured(schema=PlannedAction, system=system, contents=contents, temperature=0.4)


def validate_action(plan: PlannedAction, dom: DomSnapshot, allowed_domains: set[str]) -> str | None:
    """Return an error string if the planned action cannot be safely executed, else None."""
    if plan.action in ELEMENT_ACTIONS:
        element = dom.element(plan.element_id)
        if element is None and not plan.target.strip():
            return f"Planned {plan.action} references unknown element id {plan.element_id}"
        if element and element.get("disabled"):
            return f"Element [{plan.element_id}] '{element.get('name')}' is disabled"
        if plan.action == "fill" and element and element["role"] not in ("textbox", "combobox", "searchbox", "spinbutton") \
                and element["tag"] not in ("input", "textarea") and element["role"] != "textbox":
            return f"Element [{plan.element_id}] is a {element['role']}, not a text field"
        if plan.action == "select" and not plan.value:
            return "Select action requires an option value"
    if plan.action == "press":
        key = (plan.value or plan.target).strip()
        if {"Return": "Enter", "Esc": "Escape"}.get(key, key) not in ALLOWED_KEYS:
            return f"Key '{key}' is not permitted"
    if plan.action == "navigate":
        url = plan.value or plan.target
        if not url.startswith("/") and not is_navigation_allowed(url, allowed_domains):
            return f"Navigation to '{url}' is outside the approved domain"
    return None
