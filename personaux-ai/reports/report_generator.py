"""Aggregates persisted results into persona and overall report structures (and triggers PDF output)."""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from pathlib import Path

from pydantic import BaseModel, Field

import config
from agents.gemini_client import GeminiClient, GeminiError
from agents.ux_analyzer import SEVERITY_ORDER
from database import get_execution, get_test_run, session_scope
from models import PersonaExecution, TestRun

log = logging.getLogger(__name__)


class PrioritizedRecommendation(BaseModel):
    priority: int = Field(description="1 = most urgent")
    recommendation: str
    rationale: str = Field(description="Which findings and personas this addresses.")
    personas_affected: list[str]


class OverallSynthesis(BaseModel):
    executive_summary: str
    recommendations: list[PrioritizedRecommendation]


def _finding_dict(f) -> dict:
    return {c: getattr(f, c) for c in (
        "id", "persona_name", "title", "category", "severity", "url", "description", "evidence", "screenshot_path",
        "step_number", "user_impact", "suggested_fix", "confidence", "source")}


def _violation_dict(v) -> dict:
    return {c: getattr(v, c) for c in (
        "id", "persona_name", "rule_id", "impact", "severity", "description", "help_text", "help_url", "html",
        "target", "url", "suggested_fix", "source")}


def _step_dict(s) -> dict:
    return {c: getattr(s, c) for c in (
        "step_number", "action", "target", "value", "reason", "confidence", "success", "error", "detail",
        "url_before", "url_after", "page_title", "observation", "friction_note", "ai_flags", "load_time_ms",
        "console_errors", "screenshot_path", "timestamp")}


def persona_report_data(execution_id: int) -> dict | None:
    ex = get_execution(execution_id)
    if ex is None:
        return None
    run = ex.test_run
    findings = sorted((_finding_dict(f) for f in ex.findings), key=lambda f: SEVERITY_ORDER.get(f["severity"], 9))
    violations = sorted((_violation_dict(v) for v in ex.violations), key=lambda v: SEVERITY_ORDER.get(v["severity"], 9))
    steps = [_step_dict(s) for s in ex.steps]
    recs = list(ex.recommendations or [])
    for f in findings:
        if f["suggested_fix"] and f["suggested_fix"] not in recs and len(recs) < 10:
            recs.append(f["suggested_fix"])
    return {
        "execution_id": ex.id,
        "run_id": run.id,
        "website_url": run.website_url,
        "journey_goal": run.journey_goal,
        "viewport": run.viewport,
        "test_date": run.created_at,
        "persona": ex.persona_snapshot,
        "status": ex.status,
        "outcome": ex.outcome or ex.status,
        "goal_progress": ex.goal_progress,
        "abandonment_reason": ex.abandonment_reason,
        "summary": ex.ai_summary,
        "assessment": ex.ai_assessment or {},
        "score": ex.experience_score,
        "total_steps": ex.total_steps,
        "successful_steps": ex.successful_steps,
        "failed_steps": ex.failed_steps,
        "duration_seconds": ex.duration_seconds,
        "steps": steps,
        "failed_interactions": [s for s in steps if not s["success"]],
        "findings": findings,
        "violations": violations,
        "recommendations": recs,
        "report_path": ex.report_path,
    }


def overall_report_data(run_id: int) -> dict | None:
    run = get_test_run(run_id)
    if run is None:
        return None
    personas = [persona_report_data(ex.id) for ex in run.executions]
    personas = [p for p in personas if p]
    all_findings = [f for p in personas for f in p["findings"]]
    all_violations = [v for p in personas for v in p["violations"]]

    page_counts: Counter = Counter()
    for f in all_findings:
        if f["url"]:
            page_counts[f["url"].split("#")[0]] += 1
    for v in all_violations:
        page_counts[v["url"].split("#")[0]] += 1

    category_personas: dict[str, set] = defaultdict(set)
    for f in all_findings:
        category_personas[f["category"]].add(f["persona_name"])
    rule_personas: dict[str, set] = defaultdict(set)
    for v in all_violations:
        rule_personas[f"{v['rule_id']}: {v['help_text'] or v['description']}"].add(v["persona_name"])
    common = sorted(
        [{"issue": k, "type": "UX", "personas": sorted(v)} for k, v in category_personas.items() if len(v) >= 2]
        + [{"issue": k, "type": "Accessibility", "personas": sorted(v)} for k, v in rule_personas.items() if len(v) >= 2],
        key=lambda x: -len(x["personas"]),
    )
    outcomes = Counter(p["outcome"] for p in personas)
    unique_rules = {(v["rule_id"], v["url"]) for v in all_violations}
    return {
        "run_id": run.id,
        "project": run.project.name if run.project else run.website_url,
        "website_url": run.website_url,
        "journey_goal": run.journey_goal,
        "viewport": run.viewport,
        "max_steps": run.max_steps,
        "status": run.status,
        "test_date": run.created_at,
        "finished_at": run.finished_at,
        "personas": personas,
        "total_personas": len(personas),
        "successful": outcomes.get("success", 0),
        "failed": outcomes.get("failure", 0) + outcomes.get("error", 0),
        "abandoned": outcomes.get("abandoned", 0),
        "total_findings": len(all_findings),
        "verified_findings": sum(1 for f in all_findings if f["source"] == "verified"),
        "total_a11y": len(all_violations),
        "unique_a11y_rules": len({v["rule_id"] for v in all_violations}),
        "unique_a11y_issues": len(unique_rules),
        "critical": sum(1 for f in all_findings if f["severity"] == "Critical")
        + sum(1 for v in all_violations if v["severity"] == "Critical"),
        "severity_counts": dict(Counter(f["severity"] for f in all_findings)),
        "a11y_severity_counts": dict(Counter(v["severity"] for v in all_violations)),
        "problem_pages": page_counts.most_common(8),
        "common_issues": common[:12],
        "findings": sorted(all_findings, key=lambda f: SEVERITY_ORDER.get(f["severity"], 9)),
        "synthesis": run.summary or {},
        "combined_report_path": run.combined_report_path,
    }


def _fallback_synthesis(data: dict) -> dict:
    recs, seen = [], set()
    for f in data["findings"]:
        if f["suggested_fix"] and f["suggested_fix"] not in seen:
            seen.add(f["suggested_fix"])
            recs.append({"priority": len(recs) + 1, "recommendation": f["suggested_fix"],
                         "rationale": f"{f['severity']} — {f['title']}", "personas_affected": [f["persona_name"]]})
        if len(recs) >= 8:
            break
    return {
        "executive_summary": (
            f"{data['total_personas']} personas tested: {data['successful']} succeeded, {data['failed']} failed, "
            f"{data['abandoned']} abandoned. {data['total_findings']} UX findings and {data['total_a11y']} accessibility "
            "violations were recorded."),
        "recommendations": recs,
        "generated_by": "rules",
    }


def synthesize_overall(run_id: int, client: GeminiClient | None) -> dict:
    data = overall_report_data(run_id)
    if data is None:
        return {}
    synthesis = _fallback_synthesis(data)
    if client is not None and data["personas"]:
        lines = []
        for p in data["personas"]:
            lines.append(f"- {p['persona']['name']} ({p['persona']['title']}): outcome={p['outcome']}, progress={p['goal_progress']}%, "
                         f"score={p['score']}, reason={p['abandonment_reason'] or ''}")
            for f in p["findings"][:8]:
                lines.append(f"    [{f['severity']}/{f['source']}] {f['title']} — fix: {f['suggested_fix'][:120]}")
        rules = Counter(v["rule_id"] for p in data["personas"] for v in p["violations"])
        prompt = (
            f"Website: {data['website_url']}\nGoal: {data['journey_goal']}\n\nPersona results:\n" + "\n".join(lines)
            + f"\n\nAccessibility rules violated (count): {dict(rules.most_common(12))}\n"
            + f"Common issues across personas: {[c['issue'] for c in data['common_issues']]}\n\n"
            "Write a concise executive summary (4-6 sentences) and 4-8 prioritised recommendations grounded ONLY in these results."
        )
        try:
            result = client.generate_structured(
                schema=OverallSynthesis,
                system="You are a UX research lead summarising a multi-persona usability study. Use only provided evidence. JSON only.",
                contents=[prompt], temperature=0.2)
            synthesis = result.model_dump() | {"generated_by": "gemini"}
            synthesis["recommendations"].sort(key=lambda r: r["priority"])
        except GeminiError as exc:
            log.warning("Overall synthesis failed: %s", exc)
    with session_scope() as s:
        run = s.get(TestRun, run_id)
        run.summary = synthesis
    return synthesis


def ensure_persona_pdf(execution_id: int, force: bool = False) -> Path | None:
    from reports.pdf_generator import build_persona_pdf

    data = persona_report_data(execution_id)
    if data is None:
        return None
    if data["report_path"] and Path(data["report_path"]).exists() and not force:
        return Path(data["report_path"])
    path = Path(config.REPORTS_DIR) / f"run_{data['run_id']}_persona_{execution_id}_{data['persona']['key']}.pdf"
    build_persona_pdf(data, path)
    with session_scope() as s:
        s.get(PersonaExecution, execution_id).report_path = str(path)
    return path


def ensure_combined_pdf(run_id: int, force: bool = False) -> Path | None:
    from reports.pdf_generator import build_combined_pdf

    data = overall_report_data(run_id)
    if data is None:
        return None
    if data["combined_report_path"] and Path(data["combined_report_path"]).exists() and not force:
        return Path(data["combined_report_path"])
    path = Path(config.REPORTS_DIR) / f"run_{run_id}_combined_report.pdf"
    build_combined_pdf(data, path)
    with session_scope() as s:
        s.get(TestRun, run_id).combined_report_path = str(path)
    return path


def finalize_run_reports(run_id: int, client: GeminiClient | None) -> None:
    synthesize_overall(run_id, client)
    run = get_test_run(run_id)
    for ex in run.executions:
        try:
            ensure_persona_pdf(ex.id, force=True)
        except Exception:
            log.exception("Persona PDF failed for execution %s", ex.id)
    ensure_combined_pdf(run_id, force=True)
