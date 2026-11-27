"""Database engine, sessions, persona seeding and query helpers."""
from __future__ import annotations

import re
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, selectinload, sessionmaker

import config
from models import (
    AccessibilityViolation,
    Base,
    ExecutionStep,
    Finding,
    Persona,
    PersonaExecution,
    Project,
    TestRun,
    utcnow,
)

config.ensure_dirs()

engine = create_engine(
    config.DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30} if config.DATABASE_URL.startswith("sqlite") else {},
    future=True,
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - driver hook
    if config.DATABASE_URL.startswith("sqlite"):
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


PREDEFINED_PERSONAS = [
    {
        "key": "sarah",
        "name": "Sarah",
        "title": "First-Time User",
        "description": "Visiting this website for the first time with low digital confidence.",
        "behaviors": "Needs simple navigation. Easily confused by unclear labels or icons without text. "
        "Reads instructions carefully and looks for trust signals (security badges, contact info, privacy notes) "
        "before entering personal data. Hesitates when a step is not explained.",
        "tech_confidence": 1,
        "patience": 5,
        "interaction_mode": "mouse",
        "text_zoom": 1.0,
        "prefers_high_contrast": False,
        "language_level": "native",
    },
    {
        "key": "robert",
        "name": "Robert",
        "title": "Elderly User",
        "description": "A 72-year-old who uses the web occasionally and browses with enlarged text.",
        "behaviors": "Prefers larger text and browses at 150% zoom. Struggles with small buttons and tightly packed links. "
        "Needs readable content and is sensitive to low contrast and complex, multi-level navigation. "
        "Moves slowly and double-checks before clicking.",
        "tech_confidence": 2,
        "patience": 6,
        "interaction_mode": "mouse",
        "text_zoom": 1.5,
        "prefers_high_contrast": False,
        "language_level": "native",
    },
    {
        "key": "alex",
        "name": "Alex",
        "title": "Impatient Power User",
        "description": "An experienced professional who wants to finish tasks as fast as possible.",
        "behaviors": "Expects fast interactions and skips reading long text. Dislikes unnecessary steps, modals and "
        "repetitive forms. Prefers keyboard navigation (Tab, Enter) and shortcuts. Gets frustrated quickly by slow pages "
        "and abandons after repeated friction.",
        "tech_confidence": 5,
        "patience": 2,
        "interaction_mode": "mixed",
        "text_zoom": 1.0,
        "prefers_high_contrast": False,
        "language_level": "native",
    },
    {
        "key": "maria",
        "name": "Maria",
        "title": "Non-Native English Speaker",
        "description": "Uses English as a second language with limited proficiency.",
        "behaviors": "Prefers simple, short sentences. Struggles with idioms, technical terms, jargon and ambiguous "
        "instructions. May misinterpret clever marketing copy or abbreviations. Relies on clear labels and icons with text.",
        "tech_confidence": 3,
        "patience": 6,
        "interaction_mode": "mouse",
        "text_zoom": 1.0,
        "prefers_high_contrast": False,
        "language_level": "basic",
    },
    {
        "key": "david",
        "name": "David",
        "title": "Keyboard-Only User",
        "description": "Cannot use a mouse because of a motor impairment and navigates entirely by keyboard.",
        "behaviors": "Uses Tab, Shift+Tab, Enter, Space and arrow keys only. Requires a logical tab order and clearly "
        "visible focus indicators. Cannot operate elements that are not keyboard accessible (e.g. click-only divs).",
        "tech_confidence": 4,
        "patience": 6,
        "interaction_mode": "keyboard",
        "text_zoom": 1.0,
        "prefers_high_contrast": False,
        "language_level": "native",
    },
    {
        "key": "emily",
        "name": "Emily",
        "title": "Low Vision User",
        "description": "Has low vision and browses at 200% zoom with a high-contrast preference.",
        "behaviors": "Needs larger text and strong contrast. Struggles with small icons, thin fonts and light grey text. "
        "Benefits from clear text labels and accessible controls. Loses context when layouts reflow unpredictably.",
        "tech_confidence": 3,
        "patience": 6,
        "interaction_mode": "mouse",
        "text_zoom": 2.0,
        "prefers_high_contrast": True,
        "language_level": "native",
    },
]


def init_db() -> None:
    config.ensure_dirs()
    Base.metadata.create_all(engine)
    with session_scope() as s:
        existing = {p.key for p in s.scalars(select(Persona)).all()}
        for data in PREDEFINED_PERSONAS:
            if data["key"] not in existing:
                s.add(Persona(is_custom=False, **data))


def mark_stale_runs_interrupted(active_run_ids: set[int]) -> None:
    """Runs left in 'running' state by a previous process can never finish; flag them."""
    with session_scope() as s:
        for run in s.scalars(select(TestRun).where(TestRun.status.in_(["running", "pending"]))).all():
            if run.id in active_run_ids:
                continue
            run.status = "interrupted"
            run.error_message = run.error_message or "Application stopped before the run finished."
            run.finished_at = run.finished_at or utcnow()
            for ex in run.executions:
                if ex.status in ("running", "pending"):
                    ex.status = "error"
                    ex.outcome = ex.outcome or "error"
                    ex.error_message = ex.error_message or "Interrupted"


# ---------- personas ----------

def list_personas() -> list[Persona]:
    with session_scope() as s:
        return list(s.scalars(select(Persona).order_by(Persona.is_custom, Persona.id)).all())


def get_persona(persona_id: int) -> Persona | None:
    with session_scope() as s:
        return s.get(Persona, persona_id)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "persona"


def save_custom_persona(data: dict, persona_id: int | None = None) -> Persona:
    with session_scope() as s:
        if persona_id:
            persona = s.get(Persona, persona_id)
            if persona is None or not persona.is_custom:
                raise ValueError("Only custom personas can be edited.")
        else:
            base = f"custom-{_slug(data['name'])}"
            key, n = base, 2
            while s.scalar(select(Persona).where(Persona.key == key)):
                key, n = f"{base}-{n}", n + 1
            persona = Persona(key=key, is_custom=True)
            s.add(persona)
        for field in (
            "name", "title", "description", "behaviors", "tech_confidence", "patience",
            "interaction_mode", "text_zoom", "prefers_high_contrast", "language_level",
        ):
            setattr(persona, field, data[field])
        s.flush()
        return persona


def delete_custom_persona(persona_id: int) -> None:
    with session_scope() as s:
        persona = s.get(Persona, persona_id)
        if persona and persona.is_custom:
            for ex in s.scalars(select(PersonaExecution).where(PersonaExecution.persona_id == persona_id)).all():
                ex.persona_id = None
            s.delete(persona)


# ---------- runs ----------

def create_test_run(website_url: str, journey_goal: str, persona_ids: list[int], max_steps: int, viewport: str) -> int:
    from urllib.parse import urlparse

    with session_scope() as s:
        host = urlparse(website_url).hostname or website_url
        project = s.scalar(select(Project).where(Project.website_url == website_url))
        if project is None:
            project = Project(name=host, website_url=website_url)
            s.add(project)
            s.flush()
        run = TestRun(
            project_id=project.id,
            website_url=website_url,
            journey_goal=journey_goal,
            selected_persona_ids=persona_ids,
            max_steps=max_steps,
            viewport=viewport,
            status="pending",
        )
        s.add(run)
        s.flush()
        for pid in persona_ids:
            persona = s.get(Persona, pid)
            if persona is None:
                continue
            s.add(PersonaExecution(test_run_id=run.id, persona_id=pid, persona_snapshot=persona.to_profile()))
        return run.id


def list_test_runs(limit: int = 50) -> list[TestRun]:
    with session_scope() as s:
        stmt = (
            select(TestRun)
            .options(selectinload(TestRun.executions))
            .order_by(TestRun.id.desc())
            .limit(limit)
        )
        return list(s.scalars(stmt).all())


def get_test_run(run_id: int) -> TestRun | None:
    with session_scope() as s:
        stmt = (
            select(TestRun)
            .where(TestRun.id == run_id)
            .options(
                selectinload(TestRun.project),
                selectinload(TestRun.executions).selectinload(PersonaExecution.steps),
                selectinload(TestRun.executions).selectinload(PersonaExecution.findings),
                selectinload(TestRun.executions).selectinload(PersonaExecution.violations),
            )
        )
        return s.scalar(stmt)


def get_execution(execution_id: int) -> PersonaExecution | None:
    with session_scope() as s:
        stmt = (
            select(PersonaExecution)
            .where(PersonaExecution.id == execution_id)
            .options(
                selectinload(PersonaExecution.steps),
                selectinload(PersonaExecution.findings),
                selectinload(PersonaExecution.violations),
                selectinload(PersonaExecution.test_run),
            )
        )
        return s.scalar(stmt)


def dashboard_stats() -> dict:
    with session_scope() as s:
        total_runs = s.scalar(select(func.count(TestRun.id))) or 0
        total_execs = s.scalar(select(func.count(PersonaExecution.id))) or 0
        distinct_personas = s.scalar(
            select(func.count(func.distinct(PersonaExecution.persona_snapshot["key"].as_string())))
        ) or 0
        total_findings = s.scalar(select(func.count(Finding.id))) or 0
        critical = s.scalar(select(func.count(Finding.id)).where(Finding.severity == "Critical")) or 0
        a11y = s.scalar(select(func.count(AccessibilityViolation.id))) or 0
        finished = s.scalars(
            select(PersonaExecution).where(PersonaExecution.status == "completed")
        ).all()
        success_rate = (
            round(100 * sum(1 for e in finished if e.outcome == "success") / len(finished), 1) if finished else 0.0
        )
        sev_rows = s.execute(select(Finding.severity, func.count(Finding.id)).group_by(Finding.severity)).all()
        a11y_rows = s.execute(
            select(AccessibilityViolation.severity, func.count(AccessibilityViolation.id)).group_by(
                AccessibilityViolation.severity
            )
        ).all()
        persona_rows: dict[str, dict] = {}
        for e in finished:
            name = e.persona_snapshot.get("name", "?")
            row = persona_rows.setdefault(name, {"persona": name, "runs": 0, "successes": 0, "score_total": 0.0})
            row["runs"] += 1
            row["successes"] += 1 if e.outcome == "success" else 0
            row["score_total"] += e.experience_score or 0
        persona_comparison = [
            {
                "persona": r["persona"],
                "runs": r["runs"],
                "success_rate": round(100 * r["successes"] / r["runs"], 1),
                "avg_score": round(r["score_total"] / r["runs"], 1),
            }
            for r in persona_rows.values()
        ]
        return {
            "total_runs": total_runs,
            "total_executions": total_execs,
            "distinct_personas": distinct_personas,
            "total_findings": total_findings,
            "critical_findings": critical,
            "a11y_violations": a11y,
            "success_rate": success_rate,
            "severity_distribution": {k: v for k, v in sev_rows},
            "a11y_distribution": {k: v for k, v in a11y_rows},
            "persona_comparison": persona_comparison,
        }


def latest_step(execution_id: int) -> ExecutionStep | None:
    with session_scope() as s:
        return s.scalar(
            select(ExecutionStep)
            .where(ExecutionStep.execution_id == execution_id)
            .order_by(ExecutionStep.step_number.desc())
            .limit(1)
        )
