"""UX friction detection: objective (browser-verified) checks plus Gemini persona evaluation."""
from __future__ import annotations

import re
from collections import Counter
from typing import Literal

from pydantic import BaseModel, Field, field_validator

import config
from agents.gemini_client import GeminiClient
from agents.journey_planner import persona_profile_text

CATEGORIES = [
    "Confusing navigation", "Unclear button labels", "Misleading links", "Excessive form fields",
    "Unnecessary steps", "Poor error messages", "Missing instructions", "Dead ends", "Slow loading",
    "Repeated actions", "Unexpected navigation", "Journey abandonment", "Poor mobile usability",
    "Trust concerns", "Accessibility barrier", "Readability", "Failed interaction", "Technical errors",
]
Category = Literal[
    "Confusing navigation", "Unclear button labels", "Misleading links", "Excessive form fields",
    "Unnecessary steps", "Poor error messages", "Missing instructions", "Dead ends", "Slow loading",
    "Repeated actions", "Unexpected navigation", "Journey abandonment", "Poor mobile usability",
    "Trust concerns", "Accessibility barrier", "Readability", "Failed interaction", "Technical errors",
]
Severity = Literal["Critical", "High", "Medium", "Low"]
SEVERITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}


class AIFinding(BaseModel):
    title: str
    category: Category
    severity: Severity
    step_number: int = Field(description="Step whose evidence supports this finding.")
    description: str
    evidence: str = Field(description="Exact labels/text/behaviour observed in that step that prove the issue.")
    user_impact: str
    suggested_fix: str
    confidence: float

    @field_validator("confidence")
    @classmethod
    def _clamp(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))


class FinalEvaluation(BaseModel):
    outcome: Literal["success", "failure", "abandoned"]
    goal_progress: int = Field(description="0-100 estimate of how much of the goal was completed, from evidence.")
    summary: str = Field(description="3-5 sentence narrative of the persona's experience.")
    understood_site: bool
    action_easy_to_find: bool
    interaction_confusing: bool
    instructions_clear: bool
    unnecessary_steps: bool
    abandonment_reason: str = Field(description="Empty unless the persona abandoned.")
    findings: list[AIFinding]
    recommendations: list[str]


EVAL_SYSTEM = """You are a senior UX researcher evaluating a recorded usability session of one persona on a real website.
Use ONLY the recorded step evidence. Never fabricate observations. Every finding must cite a step_number whose recorded
observation, page title/URL, error, or friction note directly supports it, and quote that evidence.
Do not repeat issues already listed as verified issues; add persona-perceived issues (clarity, labels, instructions, trust, language).
Return 0-6 findings, prioritised by severity, and 3-6 concrete recommendations. Respond with JSON only."""


def evaluate_journey(
    client: GeminiClient,
    persona: dict,
    goal: str,
    steps: list[dict],
    end_reason: str,
    verified_titles: list[str],
    a11y_summary: str,
) -> FinalEvaluation:
    lines = []
    for s in steps:
        lines.append(
            f"Step {s['step_number']}: {s['action']} '{s.get('target') or ''}' value='{(s.get('value') or '')[:40]}' "
            f"-> {'OK' if s['success'] else 'FAILED: ' + (s.get('error') or '')} | url={s.get('url_after')} "
            f"| title={s.get('page_title')}\n  persona observation: {s.get('observation') or ''}\n"
            f"  friction: {s.get('friction_note') or 'none'} | reason: {s.get('reason') or ''}"
        )
    prompt = (
        f"PERSONA\n{persona_profile_text(persona)}\n\nGOAL\n{goal}\n\n"
        f"SESSION END REASON: {end_reason}\n\nRECORDED STEPS\n" + "\n".join(lines) + "\n\n"
        f"VERIFIED ISSUES ALREADY RECORDED (do not duplicate):\n" + ("\n".join(verified_titles) or "none") + "\n\n"
        f"ACCESSIBILITY SCAN SUMMARY: {a11y_summary}\n\nEvaluate the session."
    )
    return client.generate_structured(schema=FinalEvaluation, system=EVAL_SYSTEM, contents=[prompt], temperature=0.2)


def validate_ai_findings(findings: list[AIFinding], steps: list[dict]) -> list[dict]:
    """Keep only AI findings anchored to a real recorded step with a screenshot."""
    by_number = {s["step_number"]: s for s in steps}
    kept = []
    for f in findings:
        step = by_number.get(f.step_number)
        if step is None or not step.get("screenshot_path") or not f.evidence.strip():
            continue
        kept.append(
            {
                "title": f.title[:300],
                "category": f.category,
                "severity": f.severity,
                "url": step.get("url_after") or step.get("url_before"),
                "description": f.description,
                "evidence": f.evidence,
                "screenshot_path": step["screenshot_path"],
                "step_number": f.step_number,
                "user_impact": f.user_impact,
                "suggested_fix": f.suggested_fix,
                "confidence": f.confidence,
                "source": "ai_inferred",
            }
        )
    return kept


def flesch_reading_ease(text: str) -> float | None:
    words = re.findall(r"[A-Za-z]+", text)
    if len(words) < 80:
        return None
    sentences = max(1, len(re.findall(r"[.!?]+", text)))

    def syllables(w: str) -> int:
        w = w.lower()
        groups = re.findall(r"[aeiouy]+", w)
        n = len(groups) - (1 if w.endswith("e") and len(groups) > 1 else 0)
        return max(1, n)

    syl = sum(syllables(w) for w in words)
    return round(206.835 - 1.015 * (len(words) / sentences) - 84.6 * (syl / len(words)), 1)


def _finding(step: dict, **kw) -> dict:
    base = {
        "url": step.get("url_after") or step.get("url_before"),
        "screenshot_path": step.get("screenshot_path"),
        "step_number": step["step_number"],
        "confidence": 1.0,
        "source": "verified",
    }
    base.update(kw)
    return base


def objective_findings(persona: dict, steps: list[dict], viewport: str, end_reason: str, outcome: str,
                       blocked: list[str]) -> list[dict]:
    """Findings derived purely from measured browser behaviour — no AI involved."""
    out: list[dict] = []
    patience = persona.get("patience", 5)
    slow_threshold = config.SLOW_PAGE_THRESHOLD_MS * (0.5 if patience <= 3 else 1.0)
    seen_pages: set[str] = set()

    for s in steps:
        dom = s.get("dom_summary") or {}
        url = s.get("url_after") or ""
        if not s["success"] and s["action"] not in ("done", "abandon"):
            if s.get("keyboard_unreachable"):
                out.append(_finding(s, title=f"'{s.get('target')}' cannot be reached by keyboard", category="Accessibility barrier",
                                    severity="High", description="The persona tried to reach this control by pressing Tab, but focus never arrived on it.",
                                    evidence=s.get("error") or "", user_impact="Keyboard-only users cannot complete this step.",
                                    suggested_fix="Use a native <button>/<a>/<input> or add tabindex=0 plus Enter/Space handlers; check tab order."))
            elif s.get("blocked"):
                out.append(_finding(s, title="Action blocked by safety policy or domain restriction", category="Unexpected navigation",
                                    severity="Low", description="The planned action would leave the approved domain or perform an irreversible operation, so it was not executed.",
                                    evidence=s.get("error") or "", user_impact="Journey could not proceed along this path in a test environment.",
                                    suggested_fix="Keep core journeys on the primary domain, or provide test-safe flows (sandbox payments)."))
            elif "HTTP" in (s.get("error") or ""):
                out.append(_finding(s, title=f"Page returned an error ({s.get('error')})", category="Dead ends", severity="High",
                                    description="A page in the journey responded with an HTTP error status.", evidence=s.get("error") or "",
                                    user_impact="Users reach an error page and cannot continue.", suggested_fix="Fix the broken route or link and add a helpful error page with navigation."))
            elif not s.get("validation_error"):
                out.append(_finding(s, title=f"Interaction with '{s.get('target') or s['action']}' failed", category="Failed interaction",
                                    severity="Medium", description=f"The browser could not perform '{s['action']}' on the intended element.",
                                    evidence=s.get("error") or "", user_impact="The persona's intended action had no effect, causing confusion.",
                                    suggested_fix="Ensure the control is visible, enabled, not covered by overlays, and responds to standard input."))

        if s.get("load_time_ms") and s["load_time_ms"] > slow_threshold:
            sev = "High" if s["load_time_ms"] > 2 * slow_threshold else "Medium"
            out.append(_finding(s, title=f"Slow page load ({s['load_time_ms'] / 1000:.1f}s)", category="Slow loading", severity=sev,
                                description=f"Measured navigation load time exceeded {slow_threshold / 1000:.1f}s for this persona.",
                                evidence=f"Navigation Timing load = {s['load_time_ms']} ms at {url}",
                                user_impact="Impatient users abandon slow pages; perceived reliability drops.",
                                suggested_fix="Reduce blocking scripts, optimise images, enable caching/CDN, and defer non-critical resources."))

        if url and url not in seen_pages and dom:
            seen_pages.add(url)
            if dom.get("total_interactive", 1) == 0:
                out.append(_finding(s, title="Dead end: page has no interactive elements", category="Dead ends", severity="High",
                                    description="No links, buttons or inputs were visible on this page.", evidence=f"0 interactive elements detected at {url}",
                                    user_impact="Users have no way forward except the browser back button.", suggested_fix="Add clear navigation or a next-step call to action."))
            if dom.get("visible_inputs", 0) > 8:
                out.append(_finding(s, title=f"Long form with {dom['visible_inputs']} fields", category="Excessive form fields",
                                    severity="Medium" if patience <= 3 else "Low",
                                    description="The form asks for many inputs at once.", evidence=f"{dom['visible_inputs']} visible inputs ({dom.get('required_inputs', 0)} required)",
                                    user_impact="Long forms increase abandonment, especially for impatient or less confident users.",
                                    suggested_fix="Ask only for essential fields, split into steps, or use progressive disclosure."))
            if (persona.get("text_zoom", 1) > 1 or viewport == "Mobile") and dom.get("small_targets", 0) > 0:
                out.append(_finding(s, title=f"{dom['small_targets']} touch/click targets smaller than 24px", category="Poor mobile usability" if viewport == "Mobile" else "Accessibility barrier",
                                    severity="Medium", description="Interactive targets measured below the WCAG 2.2 minimum target size.",
                                    evidence="Examples: " + "; ".join(dom.get("small_target_samples", [])),
                                    user_impact="Users with tremors, low vision or touch screens mis-tap or miss controls.",
                                    suggested_fix="Make targets at least 24x24 CSS px (44x44 recommended) with spacing between them."))
            if persona.get("text_zoom", 1) > 1 and dom.get("small_text", 0) > 3:
                out.append(_finding(s, title=f"{dom['small_text']} text elements below 12px", category="Readability", severity="Medium",
                                    description="Measured computed font sizes are very small even before zoom.",
                                    evidence="Examples: " + "; ".join(dom.get("small_text_samples", [])),
                                    user_impact="Elderly and low-vision users struggle to read small text.",
                                    suggested_fix="Use a base font size of at least 16px and avoid text below 12px."))
            if persona.get("language_level") in ("basic", "intermediate"):
                score = flesch_reading_ease(s.get("text_excerpt") or "")
                if score is not None and score < 50:
                    out.append(_finding(s, title=f"Difficult language (Flesch reading ease {score})", category="Readability",
                                        severity="Medium" if score >= 30 else "High",
                                        description="Page copy scores as difficult to read by the Flesch reading-ease formula.",
                                        evidence=f"Reading ease {score} on visible text at {url} (60+ is plain English)",
                                        user_impact="Non-native speakers may misunderstand instructions.",
                                        suggested_fix="Use shorter sentences, common words, and avoid jargon and idioms."))
            if dom.get("unnamed_controls", 0) > 0 and persona.get("interaction_mode") == "keyboard":
                out.append(_finding(s, title=f"{dom['unnamed_controls']} controls without an accessible name", category="Unclear button labels",
                                    severity="Medium", description="Some interactive controls have no text, aria-label or title.",
                                    evidence=f"{dom['unnamed_controls']} unnamed interactive elements at {url}",
                                    user_impact="Assistive-technology users cannot tell what these controls do.",
                                    suggested_fix="Provide visible text or aria-label for icon buttons and links."))
        if s.get("console_errors"):
            errs = [e for e in s["console_errors"] if "js error" in e or "HTTP 5" in e]
            if errs:
                out.append(_finding(s, title="JavaScript or server errors during the journey", category="Technical errors", severity="Low",
                                    description="Errors were reported by the browser while the persona interacted.", evidence="; ".join(errs[:3]),
                                    user_impact="Features may silently break; erodes trust.", suggested_fix="Investigate and fix the reported errors."))

    signatures = Counter((s["action"], (s.get("target") or "").lower(), s.get("url_before")) for s in steps
                         if s["action"] in ("click", "fill", "select", "press"))
    for (action, target, url), count in signatures.items():
        if count >= 3:
            step = next(s for s in steps if s["action"] == action and (s.get("target") or "").lower() == target)
            out.append(_finding(step, title=f"Repeated action: {action} '{target}' x{count}", category="Repeated actions", severity="Medium",
                                description="The persona repeated the same action on the same page, indicating it did not produce the expected result.",
                                evidence=f"{action} on '{target}' at {url} executed {count} times", user_impact="Users feel stuck and lose confidence.",
                                suggested_fix="Give immediate, visible feedback after the action and clarify what happens next."))

    if outcome == "abandoned" and steps:
        out.append(_finding(steps[-1], title="Persona abandoned the journey", category="Journey abandonment", severity="High",
                            description="The persona gave up before reaching the goal.", evidence=end_reason,
                            user_impact="Lost conversion for users with this profile.", suggested_fix="Address the friction findings that preceded abandonment."))

    deduped, seen = [], set()
    for f in out:
        key = (f["title"], f.get("url"))
        if key not in seen:
            seen.add(key)
            deduped.append(f)
    return deduped


def experience_score(outcome: str, goal_progress: int, findings: list[dict], violations: list[dict]) -> float:
    base = {"success": 100, "failure": 55, "abandoned": 40, "error": 20}.get(outcome, 50)
    base = base * 0.6 + goal_progress * 0.4
    penalty = sum({"Critical": 12, "High": 7, "Medium": 3, "Low": 1}.get(f["severity"], 1) for f in findings)
    rules = {(v["rule_id"], v["severity"]) for v in violations}
    penalty += min(20, sum({"Critical": 4, "High": 3, "Medium": 2, "Low": 1}.get(sev, 1) for _, sev in rules))
    return round(max(0.0, min(100.0, base - penalty)), 1)
