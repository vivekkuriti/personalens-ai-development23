"""SQLAlchemy ORM models for PersonaUX AI."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    website_url: Mapped[str] = mapped_column(String(2048), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    test_runs: Mapped[list["TestRun"]] = relationship(back_populates="project")


class Persona(Base):
    __tablename__ = "personas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(150))
    description: Mapped[str] = mapped_column(Text)
    behaviors: Mapped[str] = mapped_column(Text, default="")
    tech_confidence: Mapped[int] = mapped_column(Integer, default=3)  # 1-5
    patience: Mapped[int] = mapped_column(Integer, default=5)  # 1-10
    interaction_mode: Mapped[str] = mapped_column(String(20), default="mouse")  # mouse | keyboard | mixed
    text_zoom: Mapped[float] = mapped_column(Float, default=1.0)  # 1.0 - 2.0 browser zoom
    prefers_high_contrast: Mapped[bool] = mapped_column(Boolean, default=False)
    language_level: Mapped[str] = mapped_column(String(20), default="native")  # native | intermediate | basic
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    def to_profile(self) -> dict:
        return {
            "id": self.id,
            "key": self.key,
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "behaviors": self.behaviors,
            "tech_confidence": self.tech_confidence,
            "patience": self.patience,
            "interaction_mode": self.interaction_mode,
            "text_zoom": self.text_zoom,
            "prefers_high_contrast": self.prefers_high_contrast,
            "language_level": self.language_level,
            "is_custom": self.is_custom,
        }


class TestRun(Base):
    __tablename__ = "test_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    website_url: Mapped[str] = mapped_column(String(2048))
    journey_goal: Mapped[str] = mapped_column(Text)
    selected_persona_ids: Mapped[list] = mapped_column(JSON, default=list)
    max_steps: Mapped[int] = mapped_column(Integer, default=15)
    viewport: Mapped[str] = mapped_column(String(20), default="Desktop")
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|running|completed|failed|interrupted
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    combined_report_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    project: Mapped[Project] = relationship(back_populates="test_runs")
    executions: Mapped[list["PersonaExecution"]] = relationship(
        back_populates="test_run", cascade="all, delete-orphan", order_by="PersonaExecution.id"
    )


class PersonaExecution(Base):
    __tablename__ = "persona_executions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    test_run_id: Mapped[int] = mapped_column(ForeignKey("test_runs.id"), index=True)
    persona_id: Mapped[int | None] = mapped_column(ForeignKey("personas.id"), nullable=True)
    persona_snapshot: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|running|completed|error
    outcome: Mapped[str | None] = mapped_column(String(20), nullable=True)  # success|failure|abandoned|error
    goal_progress: Mapped[int] = mapped_column(Integer, default=0)
    abandonment_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_assessment: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    recommendations: Mapped[list | None] = mapped_column(JSON, nullable=True)
    experience_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_steps: Mapped[int] = mapped_column(Integer, default=0)
    successful_steps: Mapped[int] = mapped_column(Integer, default=0)
    failed_steps: Mapped[int] = mapped_column(Integer, default=0)
    current_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    test_run: Mapped[TestRun] = relationship(back_populates="executions")
    steps: Mapped[list["ExecutionStep"]] = relationship(
        back_populates="execution", cascade="all, delete-orphan", order_by="ExecutionStep.step_number"
    )
    findings: Mapped[list["Finding"]] = relationship(back_populates="execution", cascade="all, delete-orphan")
    violations: Mapped[list["AccessibilityViolation"]] = relationship(
        back_populates="execution", cascade="all, delete-orphan"
    )


class Screenshot(Base):
    __tablename__ = "screenshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    execution_id: Mapped[int] = mapped_column(ForeignKey("persona_executions.id"), index=True)
    step_number: Mapped[int] = mapped_column(Integer)
    path: Mapped[str] = mapped_column(String(1024))
    url: Mapped[str] = mapped_column(String(2048))
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ExecutionStep(Base):
    __tablename__ = "execution_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    execution_id: Mapped[int] = mapped_column(ForeignKey("persona_executions.id"), index=True)
    step_number: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(30))
    target: Mapped[str | None] = mapped_column(Text, nullable=True)
    element_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    url_before: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    url_after: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    page_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    observation: Mapped[str | None] = mapped_column(Text, nullable=True)
    friction_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_flags: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    dom_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    load_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    console_errors: Mapped[list | None] = mapped_column(JSON, nullable=True)
    screenshot_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    execution: Mapped[PersonaExecution] = relationship(back_populates="steps")


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    test_run_id: Mapped[int] = mapped_column(ForeignKey("test_runs.id"), index=True)
    execution_id: Mapped[int] = mapped_column(ForeignKey("persona_executions.id"), index=True)
    persona_name: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(300))
    category: Mapped[str] = mapped_column(String(60))
    severity: Mapped[str] = mapped_column(String(10))  # Critical|High|Medium|Low
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    description: Mapped[str] = mapped_column(Text)
    evidence: Mapped[str] = mapped_column(Text)
    screenshot_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    step_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user_impact: Mapped[str] = mapped_column(Text, default="")
    suggested_fix: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    source: Mapped[str] = mapped_column(String(20))  # verified | ai_inferred
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    execution: Mapped[PersonaExecution] = relationship(back_populates="findings")


class AccessibilityViolation(Base):
    __tablename__ = "accessibility_violations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    test_run_id: Mapped[int] = mapped_column(ForeignKey("test_runs.id"), index=True)
    execution_id: Mapped[int] = mapped_column(ForeignKey("persona_executions.id"), index=True)
    persona_name: Mapped[str] = mapped_column(String(100))
    rule_id: Mapped[str] = mapped_column(String(120))
    impact: Mapped[str] = mapped_column(String(20))  # critical|serious|moderate|minor
    severity: Mapped[str] = mapped_column(String(10))  # Critical|High|Medium|Low
    description: Mapped[str] = mapped_column(Text)
    help_text: Mapped[str] = mapped_column(Text, default="")
    help_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    html: Mapped[str] = mapped_column(Text, default="")
    target: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(String(2048))
    suggested_fix: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(30), default="axe-core")  # axe-core | keyboard-check
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    execution: Mapped[PersonaExecution] = relationship(back_populates="violations")
