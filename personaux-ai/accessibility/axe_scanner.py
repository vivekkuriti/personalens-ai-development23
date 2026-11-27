"""axe-core scans and basic keyboard-navigation checks via Playwright.

Automated checks cover only a subset of WCAG; results never imply full compliance.
"""
from __future__ import annotations

import logging

from axe_playwright_python.sync_playwright import Axe
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page

log = logging.getLogger(__name__)

IMPACT_TO_SEVERITY = {"critical": "Critical", "serious": "High", "moderate": "Medium", "minor": "Low"}
AXE_OPTIONS = {
    "resultTypes": ["violations"],
    "runOnly": {"type": "tag", "values": ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"]},
}
MAX_NODES_PER_RULE = 5

FOCUS_PROBE_JS = r"""
() => {
  const el = document.activeElement;
  if (!el || el === document.body || el === document.documentElement) return { none: true };
  const snap = () => { const s = getComputedStyle(el); return [s.outlineStyle, s.outlineWidth, s.outlineColor, s.boxShadow,
    s.backgroundColor, s.borderColor, s.color, s.textDecorationLine].join('|'); };
  const focused = snap();
  const s = getComputedStyle(el);
  const hasOutline = s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) > 0;
  const hasShadow = s.boxShadow && s.boxShadow !== 'none';
  el.blur();
  const unfocused = snap();
  el.focus();
  const r = el.getBoundingClientRect();
  const name = (el.getAttribute('aria-label') || el.innerText || el.value || el.getAttribute('title') || '').trim().slice(0, 60);
  return {
    none: false,
    tag: el.tagName.toLowerCase(),
    name,
    html: el.outerHTML.slice(0, 220),
    visible_indicator: hasOutline || hasShadow || focused !== unfocused,
    offscreen: r.bottom < 0 || r.right < 0 || r.width < 1 || r.height < 1,
    key: el.tagName + '|' + name + '|' + Math.round(r.top) + '|' + Math.round(r.left),
  };
}
"""


class AxeScanner:
    def __init__(self) -> None:
        self._axe = Axe()

    def scan(self, page: Page) -> list[dict]:
        try:
            results = self._axe.run(page, options=AXE_OPTIONS)
        except PlaywrightError as exc:
            log.warning("axe scan failed: %s", exc)
            return []
        violations = []
        for v in results.response.get("violations", []):
            impact = v.get("impact") or "minor"
            for node in v.get("nodes", [])[:MAX_NODES_PER_RULE]:
                summary = (node.get("failureSummary") or "").replace("\n", " ").strip()
                violations.append(
                    {
                        "rule_id": v.get("id", "unknown"),
                        "impact": impact,
                        "severity": IMPACT_TO_SEVERITY.get(impact, "Low"),
                        "description": v.get("description", ""),
                        "help_text": v.get("help", ""),
                        "help_url": v.get("helpUrl"),
                        "html": (node.get("html") or "")[:500],
                        "target": ", ".join(str(t) for t in node.get("target", []))[:300],
                        "url": page.url,
                        "suggested_fix": f"{v.get('help', '')}. {summary}".strip()[:800],
                        "source": "axe-core",
                    }
                )
        return violations


def keyboard_audit(page: Page, max_tabs: int = 30) -> dict:
    """Tab through the page to check reachability, focus visibility and traps."""
    issues: list[dict] = []
    reached: list[str] = []
    try:
        page.evaluate("() => { if (document.activeElement) document.activeElement.blur(); window.scrollTo(0, 0); }")
        repeat_count = 0
        last_key = None
        for _ in range(max_tabs):
            page.keyboard.press("Tab")
            info = page.evaluate(FOCUS_PROBE_JS)
            if info.get("none"):
                continue
            if info["key"] == last_key:
                repeat_count += 1
                if repeat_count >= 3:
                    issues.append(
                        {
                            "rule_id": "keyboard-focus-trap",
                            "impact": "critical",
                            "severity": "Critical",
                            "description": "Keyboard focus stayed on the same element after repeated Tab presses (possible focus trap).",
                            "help_text": "Users must be able to move focus away from any component using the keyboard.",
                            "help_url": "https://www.w3.org/WAI/WCAG22/Understanding/no-keyboard-trap",
                            "html": info["html"],
                            "target": info["name"] or info["tag"],
                            "url": page.url,
                            "suggested_fix": "Ensure Tab/Shift+Tab move focus out of the component; avoid trapping focus outside modals.",
                            "source": "keyboard-check",
                        }
                    )
                    break
            else:
                repeat_count = 0
            last_key = info["key"]
            reached.append(info["name"] or info["tag"])
            if not info["visible_indicator"]:
                issues.append(
                    {
                        "rule_id": "focus-not-visible",
                        "impact": "serious",
                        "severity": "High",
                        "description": "Focused element shows no detectable visual focus indicator (heuristic computed-style check).",
                        "help_text": "Any keyboard-operable interface must have a visible focus indicator.",
                        "help_url": "https://www.w3.org/WAI/WCAG22/Understanding/focus-visible",
                        "html": info["html"],
                        "target": info["name"] or info["tag"],
                        "url": page.url,
                        "suggested_fix": "Add a clear :focus-visible style (e.g. 2px outline with 3:1 contrast). Do not remove outlines without a replacement.",
                        "source": "keyboard-check",
                    }
                )
            if info["offscreen"]:
                issues.append(
                    {
                        "rule_id": "focus-offscreen",
                        "impact": "moderate",
                        "severity": "Medium",
                        "description": "Keyboard focus moved to an element that is not visible on screen.",
                        "help_text": "Focused elements should be visible so keyboard users know where they are.",
                        "help_url": "https://www.w3.org/WAI/WCAG22/Understanding/focus-not-obscured-minimum",
                        "html": info["html"],
                        "target": info["name"] or info["tag"],
                        "url": page.url,
                        "suggested_fix": "Remove hidden elements from the tab order (tabindex=-1, inert, or display:none).",
                        "source": "keyboard-check",
                    }
                )
        page.evaluate("() => { if (document.activeElement) document.activeElement.blur(); window.scrollTo(0, 0); }")
    except PlaywrightError as exc:
        log.warning("keyboard audit failed: %s", exc)
    if not reached:
        issues.append(
            {
                "rule_id": "keyboard-no-focusable",
                "impact": "critical",
                "severity": "Critical",
                "description": "No element received keyboard focus after pressing Tab repeatedly.",
                "help_text": "All functionality must be operable through a keyboard interface.",
                "help_url": "https://www.w3.org/WAI/WCAG22/Understanding/keyboard",
                "html": "",
                "target": "document",
                "url": page.url,
                "suggested_fix": "Use native interactive elements (a, button, input) or add tabindex=0 with key handlers.",
                "source": "keyboard-check",
            }
        )
    # Collapse duplicate focus-visibility issues to keep reports actionable.
    deduped, seen = [], set()
    for i in issues:
        k = (i["rule_id"], i["target"])
        if k not in seen:
            seen.add(k)
            deduped.append(i)
    return {"reached": reached, "issues": deduped[:12]}
