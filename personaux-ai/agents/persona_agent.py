"""OBSERVE -> PLAN -> ACT -> CAPTURE -> EVALUATE loop for a single persona, plus the multi-persona orchestrator."""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable

from playwright.sync_api import Error as PlaywrightError

import config
from accessibility.axe_scanner import AxeScanner, keyboard_audit
from agents.gemini_client import GeminiClient, GeminiError
from agents.journey_planner import JourneyPlanner, validate_action
from agents.ux_analyzer import (
    SEVERITY_ORDER,
    evaluate_journey,
    experience_score,
    objective_findings,
    validate_ai_findings,
)
from automation.browser_manager import BrowserManager
from automation.dom_inspector import DomSnapshot, inspect_page
from automation.playwright_executor import PlaywrightExecutor
from database import session_scope
from models import AccessibilityViolation, ExecutionStep, Finding, PersonaExecution, Screenshot, TestRun, utcnow
from security import allowed_domains_for

log = logging.getLogger(__name__)
Emit = Callable[..., None]


def _noop(*_a, **_k) -> None:
    pass


class PersonaAgent:
    def __init__(self, execution_id: int, run: dict, browser: BrowserManager, client: GeminiClient, emit: Emit = _noop):
        self.execution_id = execution_id
        self.run = run
        self.browser = browser
        self.client = client
        self.planner = JourneyPlanner(client)
        self.axe = AxeScanner()
        self.emit = emit
        self.steps: list[dict] = []
        self.violations: list[dict] = []
        self.scanned_paths: set[str] = set()
        self.shot_dir = Path(config.SCREENSHOTS_DIR) / f"run_{run['id']}" / f"exec_{execution_id}"
        self.shot_dir.mkdir(parents=True, exist_ok=True)

    # ---------- persistence helpers ----------

    def _update_execution(self, **fields) -> None:
        with session_scope() as s:
            ex = s.get(PersonaExecution, self.execution_id)
            for k, v in fields.items():
                setattr(ex, k, v)

    def _capture(self, page, step_number: int) -> tuple[str, bytes]:
        path = self.shot_dir / f"step_{step_number:02d}.jpg"
        data = page.screenshot(type="jpeg", quality=70, full_page=False, timeout=15000)
        path.write_bytes(data)
        return str(path), data

    def _record_step(self, step: dict) -> None:
        self.steps.append(step)
        persisted = {k: step.get(k) for k in (
            "step_number", "action", "target", "element_id", "value", "reason", "confidence", "success", "error",
            "detail", "url_before", "url_after", "page_title", "observation", "friction_note", "ai_flags",
            "dom_summary", "load_time_ms", "console_errors", "screenshot_path",
        )}
        if persisted.get("action") == "fill" and persisted.get("value") and "password" in (step.get("value_hint") or ""):
            persisted["value"] = "********"
        with session_scope() as s:
            s.add(ExecutionStep(execution_id=self.execution_id, **persisted))
            if step.get("screenshot_path"):
                s.add(Screenshot(execution_id=self.execution_id, step_number=step["step_number"],
                                 path=step["screenshot_path"], url=step.get("url_after") or ""))
            ex = s.get(PersonaExecution, self.execution_id)
            ex.total_steps = len(self.steps)
            ex.successful_steps = sum(1 for x in self.steps if x["success"])
            ex.failed_steps = sum(1 for x in self.steps if not x["success"])
            ex.current_url = step.get("url_after")
        self.emit("step", f"Step {step['step_number']}: {step['action']} {step.get('target') or ''} -> "
                          f"{'ok' if step['success'] else 'failed: ' + (step.get('error') or '')}",
                  screenshot=step.get("screenshot_path"), url=step.get("url_after"), step=step)
        if step.get("friction_note"):
            self.emit("friction", step["friction_note"], step_number=step["step_number"])

    def _scan_accessibility(self, page, persona_name: str) -> None:
        path = page.url.split("#")[0].split("?")[0]
        if path in self.scanned_paths or len(self.scanned_paths) >= config.MAX_AXE_SCANS_PER_PERSONA:
            return
        self.scanned_paths.add(path)
        self.emit("status", f"Running axe-core accessibility scan on {path}")
        found = self.axe.scan(page)
        self._save_violations(found, persona_name)
        if found:
            rules = sorted({v["rule_id"] for v in found})
            self.emit("a11y", f"{len(found)} axe-core violations ({len(rules)} rules) on {path}: {', '.join(rules[:6])}")

    def _save_violations(self, found: list[dict], persona_name: str) -> None:
        if not found:
            return
        self.violations.extend(found)
        with session_scope() as s:
            for v in found:
                s.add(AccessibilityViolation(test_run_id=self.run["id"], execution_id=self.execution_id,
                                             persona_name=persona_name, **v))

    # ---------- main loop ----------

    def run_journey(self) -> None:
        persona = self.run["personas"][self.execution_id]
        name = persona["name"]
        goal, max_steps = self.run["journey_goal"], self.run["max_steps"]
        allowed = allowed_domains_for(self.run["website_url"])
        started = time.monotonic()
        self._update_execution(status="running", started_at=utcnow(), current_action="Launching browser context")
        self.emit("persona", f"{name} ({persona['title']}) is starting the journey", persona=name)

        context = None
        outcome, end_reason, final = "failure", "Maximum step limit reached", None
        try:
            context, page, monitor = self.browser.new_persona_context(persona, self.run["viewport"], allowed)
            executor = PlaywrightExecutor(page, persona, allowed)

            # Step 1: arrive at the website.
            self._update_execution(current_action=f"Navigating to {self.run['website_url']}")
            result = executor.execute("navigate", None, self.run["website_url"], self.run["website_url"],
                                      DomSnapshot(**_empty_dom()))
            dom = inspect_page(page) if result.success or result.navigated else None
            shot_path, shot = self._capture(page, 1)
            self._record_step({
                "step_number": 1, "action": "navigate", "target": self.run["website_url"], "value": self.run["website_url"],
                "reason": "Persona opens the website", "confidence": 1.0, "success": result.success,
                "error": result.error, "detail": result.detail, "url_before": "about:blank", "url_after": page.url,
                "page_title": page.title(), "dom_summary": dom.summary() if dom else None,
                "load_time_ms": result.load_time_ms, "console_errors": monitor.drain(), "screenshot_path": shot_path,
                "text_excerpt": dom.text_excerpt if dom else "",
            })
            if not result.success:
                outcome, end_reason = "failure", f"Website could not be loaded: {result.error}"
                raise _JourneyStop()

            self._scan_accessibility(page, name)
            if persona.get("interaction_mode") in ("keyboard", "mixed"):
                self.emit("status", "Running keyboard navigation audit (Tab order, focus visibility, traps)")
                audit = keyboard_audit(page)
                self._save_violations(audit["issues"], name)
                self.emit("a11y", f"Keyboard audit: {len(audit['reached'])} elements reached by Tab, "
                                  f"{len(audit['issues'])} issues")

            history = [f"Step 1: opened {self.run['website_url']} -> {'loaded' if result.success else result.error}"]
            consecutive_failures = 0
            patience_limit = max(2, min(5, round(persona.get("patience", 5) / 2)))
            last_signature, repeat = None, 0

            for step_number in range(2, max_steps + 1):
                # OBSERVE
                self._update_execution(current_action=f"Observing page (step {step_number})")
                try:
                    dom = inspect_page(page)
                except PlaywrightError as exc:
                    page.wait_for_timeout(1000)
                    dom = inspect_page(page) if not page.is_closed() else None
                    if dom is None:
                        raise RuntimeError(f"Page became unavailable: {exc}") from exc
                errors_now = monitor.drain()

                # PLAN
                self._update_execution(current_action=f"Gemini is planning {name}'s next action")
                self.emit("status", f"Asking Gemini what {name} would do next (step {step_number}/{max_steps})")
                try:
                    plan = self.planner.plan(persona, goal, dom, history, step_number, max_steps, shot,
                                             errors_now, monitor.blocked_navigations)
                except GeminiError as exc:
                    outcome, end_reason = "error", f"Gemini planning failed: {exc}"
                    self.emit("error", end_reason)
                    break

                ai_flags = {
                    "understood_page": plan.understood_page, "action_easy_to_find": plan.action_easy_to_find,
                    "confusing": plan.confusing, "instructions_clear": plan.instructions_clear,
                    "previous_step_assessment": plan.previous_step_assessment,
                }
                element = dom.element(plan.element_id)
                target_label = (element or {}).get("name") or plan.target
                base_step = {
                    "step_number": step_number, "action": plan.action, "target": target_label,
                    "element_id": plan.element_id, "value": plan.value, "reason": plan.reason,
                    "confidence": plan.confidence, "observation": plan.observation, "friction_note": plan.friction_note,
                    "ai_flags": ai_flags, "url_before": page.url, "dom_summary": dom.summary(),
                    "text_excerpt": dom.text_excerpt, "value_hint": (element or {}).get("type", ""),
                }

                if plan.action in ("done", "abandon"):
                    shot_path, shot = self._capture(page, step_number)
                    self._record_step({**base_step, "success": True, "url_after": page.url, "page_title": page.title(),
                                       "detail": "Persona ended the journey", "console_errors": errors_now,
                                       "screenshot_path": shot_path})
                    outcome = "success" if plan.action == "done" else "abandoned"
                    end_reason = plan.reason
                    break

                # VALIDATE + ACT
                problem = validate_action(plan, dom, allowed)
                if problem:
                    shot_path, shot = self._capture(page, step_number)
                    self._record_step({**base_step, "success": False, "error": f"Invalid action rejected: {problem}",
                                       "validation_error": True, "url_after": page.url, "page_title": page.title(),
                                       "console_errors": errors_now, "screenshot_path": shot_path})
                    history.append(f"Step {step_number}: {plan.action} [{plan.element_id}] '{target_label}' -> REJECTED: {problem}")
                    consecutive_failures += 1
                else:
                    self._update_execution(current_action=f"{plan.action} '{target_label}'")
                    self.emit("action", f"{name}: {plan.action} '{target_label}' — {plan.reason}")
                    res = executor.execute(plan.action, plan.element_id, plan.target, plan.value, dom)
                    # CAPTURE
                    try:
                        page.wait_for_timeout(300)
                        shot_path, shot = self._capture(page, step_number)
                        title = page.title()
                    except PlaywrightError:
                        shot_path, title = None, ""
                    self._record_step({
                        **base_step, "success": res.success, "error": res.error, "detail": res.detail,
                        "url_after": page.url, "page_title": title, "load_time_ms": res.load_time_ms,
                        "console_errors": errors_now + monitor.drain(), "screenshot_path": shot_path,
                        "keyboard_unreachable": res.keyboard_unreachable, "blocked": res.blocked,
                    })
                    history.append(
                        f"Step {step_number}: {plan.action} [{plan.element_id}] '{target_label}'"
                        f"{' value=' + repr(plan.value[:30]) if plan.value and plan.action != 'fill' else ''} -> "
                        f"{'OK' if res.success else 'FAILED: ' + (res.error or '')}; now at {page.url}"
                    )
                    consecutive_failures = 0 if res.success else consecutive_failures + 1
                    if res.navigated:
                        self._scan_accessibility(page, name)

                # Loop detection and patience
                signature = (plan.action, plan.element_id, plan.value, page.url)
                repeat = repeat + 1 if signature == last_signature else 0
                last_signature = signature
                if repeat >= 2:
                    outcome, end_reason = "abandoned", f"Stuck repeating '{plan.action} {target_label}' with no progress"
                    break
                if consecutive_failures >= patience_limit:
                    outcome, end_reason = "abandoned", (
                        f"{name} gave up after {consecutive_failures} consecutive failed interactions "
                        f"(patience {persona.get('patience')}/10)")
                    break
        except _JourneyStop:
            pass
        except Exception as exc:
            log.exception("Persona %s crashed", name)
            outcome, end_reason = "error", f"Execution error: {str(exc)[:300]}"
            self.emit("error", end_reason)
        finally:
            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass

        # EVALUATE
        self._update_execution(current_action="Gemini is evaluating the journey")
        self.emit("status", f"Evaluating {name}'s journey with Gemini")
        verified = objective_findings(persona, self.steps, self.run["viewport"], end_reason, outcome,
                                      [])
        ai_findings: list[dict] = []
        goal_progress = 100 if outcome == "success" else 0
        summary, recommendations, assessment = None, [], None
        if self.steps:
            try:
                a11y_summary = f"{len(self.violations)} violations across rules: " + ", ".join(
                    sorted({v['rule_id'] for v in self.violations})[:15]) if self.violations else "no violations detected"
                final = evaluate_journey(self.client, persona, goal, self.steps, end_reason,
                                         [f["title"] for f in verified], a11y_summary)
                ai_findings = validate_ai_findings(final.findings, self.steps)
                goal_progress = max(0, min(100, final.goal_progress))
                summary, recommendations = final.summary, final.recommendations
                assessment = final.model_dump(exclude={"findings", "recommendations"})
                if outcome == "success" and final.outcome != "success":
                    outcome = "failure"
                    end_reason = f"Persona believed the goal was complete, but evaluation found: {final.summary[:200]}"
                elif outcome == "failure" and final.outcome == "success":
                    outcome = "success"
                if outcome == "success":
                    goal_progress = max(goal_progress, 90)
            except GeminiError as exc:
                self.emit("error", f"Final evaluation unavailable: {exc}")
                summary = f"Automated evaluation unavailable ({exc}). Outcome based on recorded steps."
        if outcome == "abandoned" and not any(f["category"] == "Journey abandonment" for f in verified):
            verified += objective_findings(persona, self.steps[-1:], self.run["viewport"], end_reason, outcome, [])[-1:]

        findings = sorted(verified + ai_findings, key=lambda f: SEVERITY_ORDER.get(f["severity"], 9))
        score = experience_score(outcome, goal_progress, findings, self.violations)
        with session_scope() as s:
            for f in findings:
                s.add(Finding(test_run_id=self.run["id"], execution_id=self.execution_id, persona_name=name, **f))
            ex = s.get(PersonaExecution, self.execution_id)
            ex.status = "completed" if outcome != "error" else "error"
            ex.outcome = outcome
            ex.goal_progress = goal_progress
            ex.abandonment_reason = end_reason if outcome in ("abandoned", "failure", "error") else None
            ex.error_message = end_reason if outcome == "error" else None
            ex.ai_summary = summary
            ex.ai_assessment = assessment
            ex.recommendations = recommendations
            ex.experience_score = score
            ex.finished_at = utcnow()
            ex.duration_seconds = round(time.monotonic() - started, 1)
            ex.current_action = "Finished"
        for f in findings[:8]:
            self.emit("finding", f"[{f['severity']}] {f['title']} ({'verified' if f['source'] == 'verified' else 'AI-inferred'})")
        self.emit("persona_done", f"{name} finished: {outcome} (score {score})", persona=name, outcome=outcome)


class _JourneyStop(Exception):
    pass


def _empty_dom() -> dict:
    return dict(url="", title="", lang="", elements=[], total_interactive=0, headings=[], alerts=[], forms=0,
                visible_inputs=0, required_inputs=0, small_targets=0, small_target_samples=[], small_text=0,
                small_text_samples=[], unnamed_controls=0, images_missing_alt=0, text_excerpt="", word_count=0,
                scroll_height=0, viewport_height=0, scroll_y=0)


def run_test(run_id: int, emit: Emit = _noop) -> None:
    """Run every selected persona independently; one failure never stops the others."""
    from reports.report_generator import finalize_run_reports

    with session_scope() as s:
        run = s.get(TestRun, run_id)
        run.status, run.started_at = "running", utcnow()
        run_info = {
            "id": run.id, "website_url": run.website_url, "journey_goal": run.journey_goal,
            "max_steps": max(2, min(run.max_steps, config.HARD_MAX_STEPS)), "viewport": run.viewport,
            "personas": {ex.id: ex.persona_snapshot for ex in run.executions},
        }
    emit("status", f"Test run #{run_id} started for {run_info['website_url']}")
    try:
        client = GeminiClient()
    except GeminiError as exc:
        with session_scope() as s:
            run = s.get(TestRun, run_id)
            run.status, run.error_message, run.finished_at = "failed", str(exc), utcnow()
        emit("error", str(exc))
        return

    try:
        with BrowserManager() as browser:
            emit("status", "Chromium launched")
            for execution_id in run_info["personas"]:
                try:
                    PersonaAgent(execution_id, run_info, browser, client, emit).run_journey()
                except Exception as exc:  # isolate persona failures
                    log.exception("Persona execution %s failed", execution_id)
                    with session_scope() as s:
                        ex = s.get(PersonaExecution, execution_id)
                        ex.status, ex.outcome, ex.error_message = "error", "error", str(exc)[:500]
                        ex.finished_at = utcnow()
                    emit("error", f"Persona execution failed: {exc}")
        emit("status", "Generating overall comparison and PDF reports")
        finalize_run_reports(run_id, client)
        with session_scope() as s:
            run = s.get(TestRun, run_id)
            run.status, run.finished_at = "completed", utcnow()
        emit("done", f"Test run #{run_id} completed")
    except Exception as exc:
        log.exception("Run %s failed", run_id)
        with session_scope() as s:
            run = s.get(TestRun, run_id)
            run.status, run.error_message, run.finished_at = "failed", str(exc)[:500], utcnow()
        emit("error", f"Test run failed: {exc}")
