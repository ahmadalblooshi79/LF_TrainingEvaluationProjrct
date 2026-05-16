import enum
from datetime import datetime

from sqlalchemy import (
    String,
    Text,
    DateTime,
    ForeignKey,
    Integer,
    Float,
    Boolean,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ExerciseStatus(str, enum.Enum):
    DRAFT = "draft"
    PLANNED = "planned"
    ACTIVE = "active"
    CLOSED = "closed"


class ExercisePhase(str, enum.Enum):
    """مرحلة التمرين لمع ضبط المعاضل وقوائم التقييم."""

    PREPARATION = "preparation"  # مرحلة التحضير
    OPENING = "opening"  # مرحلة الإنفتاح
    MAIN = "main"  # مرحلة المعركة التعرضية
    REORG = "reorg"  # مرحلة إعادة التنظيم


class RoleDef(Base):
    """تعريف ثابت لكل دور: واجبات نصية للواجهة"""

    __tablename__ = "role_defs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    role_key: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    title_ar: Mapped[str] = mapped_column(String(200))
    duties_ar: Mapped[str] = mapped_column(Text())  # واجبات مفصلة


class EventFlowType(str, enum.Enum):
    BRIEFING = "briefing"  # إعالم
    STAGE = "stage"  # مرحلة
    REVIEW = "review"  # مراجعة
    DEBRIEF = "debrief"  # تغذية راجعة
    OTHER = "other"


class EventFlow(Base):
    __tablename__ = "event_flows"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercises.id", ondelete="CASCADE"), index=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text(), default="")
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    event_type: Mapped[str] = mapped_column(
        String(32),
        default=EventFlowType.STAGE.value,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    exercise = relationship("Exercise", back_populates="events")


class ProblemStatus(str, enum.Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    ESCALATED = "escalated"
    RESOLVED = "resolved"


class Problem(Base):
    __tablename__ = "problems"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercises.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text(), default="")
    severity: Mapped[int] = mapped_column(Integer, default=1)  # 1-5
    status: Mapped[str] = mapped_column(String(32), default=ProblemStatus.OPEN.value)
    reported_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    exercise = relationship("Exercise", back_populates="problems")
    reporter = relationship("User", foreign_keys=[reported_by_id])


class RefType(str, enum.Enum):
    STANDARD = "standard"  # معيار
    REGULATION = "regulation"  # لائحة
    TEMPLATE = "template"  # نموذج
    OTHER = "other"


class Reference(Base):
    __tablename__ = "references_table"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(500))
    ref_type: Mapped[str] = mapped_column(String(32), default=RefType.STANDARD.value)
    standard_code: Mapped[str] = mapped_column(String(200), default="")
    url: Mapped[str] = mapped_column(String(2000), default="")
    body: Mapped[str] = mapped_column(Text(), default="")
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    creator = relationship("User", foreign_keys=[created_by_id])


class ExerciseRefLink(Base):
    __tablename__ = "exercise_ref_links"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercises.id", ondelete="CASCADE"), index=True)
    reference_id: Mapped[int] = mapped_column(ForeignKey("references_table.id", ondelete="CASCADE"), index=True)


class Exercise(Base):
    __tablename__ = "exercises"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text(), default="")
    exercise_type: Mapped[str] = mapped_column(String(200), default="")
    exercise_level: Mapped[str] = mapped_column(String(200), default="")
    mission_label: Mapped[str] = mapped_column(String(400), default="")
    trained_unit: Mapped[str] = mapped_column(String(400), default="")
    location_label: Mapped[str] = mapped_column(String(400), default="")
    status: Mapped[str] = mapped_column(String(32), default=ExerciseStatus.DRAFT.value)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    planned_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    planned_end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    control_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner = relationship("User", back_populates="exercises_owned", foreign_keys=[owner_id])
    events = relationship(
        "EventFlow",
        back_populates="exercise",
        order_by="EventFlow.order_index",
        cascade="all, delete-orphan",
    )
    problems = relationship(
        "Problem",
        back_populates="exercise",
        cascade="all, delete-orphan",
    )
    checklists = relationship("Checklist", back_populates="exercise", cascade="all, delete-orphan")
    eval_notes = relationship("EvaluationNote", back_populates="exercise", cascade="all, delete-orphan")
    objectives = relationship(
        "ExerciseObjective",
        back_populates="exercise",
        order_by="ExerciseObjective.sort_order",
        cascade="all, delete-orphan",
    )
    timeline_items = relationship(
        "ExerciseTimelineItem",
        back_populates="exercise",
        order_by="ExerciseTimelineItem.sort_order",
        cascade="all, delete-orphan",
    )
    battle_unit_personnel = relationship(
        "ExerciseBattleUnitPersonnel",
        back_populates="exercise",
        cascade="all, delete-orphan",
    )
    roster_rows = relationship(
        "ExerciseRosterRow",
        back_populates="exercise",
        order_by="ExerciseRosterRow.sort_order",
        cascade="all, delete-orphan",
    )
    planner_flow_bundles = relationship(
        "ExercisePlannerFlowBundle",
        back_populates="exercise",
        cascade="all, delete-orphan",
    )


class ExerciseRosterKind(str, enum.Enum):
    TRAINEE = "trainee"
    JUDGE = "judge"


class ExerciseBattleUnitPersonnel(Base):
    """بيانات متدرب ومحكم الوحدة لكل رمز ضمن تنظيم المعركة — مرتبطة بالتمرين."""

    __tablename__ = "exercise_battle_unit_personnel"
    __table_args__ = (
        UniqueConstraint("exercise_id", "unit_id", name="uq_exercise_battle_unit_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    exercise_id: Mapped[int] = mapped_column(
        ForeignKey("exercises.id", ondelete="CASCADE"), index=True
    )
    unit_id: Mapped[str] = mapped_column(String(64), index=True)
    trainee_name: Mapped[str] = mapped_column(String(256), default="")
    trainee_military_number: Mapped[str] = mapped_column(String(128), default="")
    rank_ar: Mapped[str] = mapped_column(String(256), default="")
    position_ar: Mapped[str] = mapped_column(String(512), default="")
    judge_trainee_name: Mapped[str] = mapped_column(String(256), default="")
    judge_military_number: Mapped[str] = mapped_column(String(128), default="")
    judge_rank_ar: Mapped[str] = mapped_column(String(256), default="")
    judge_position_ar: Mapped[str] = mapped_column(String(512), default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    exercise = relationship("Exercise", back_populates="battle_unit_personnel")


class ExerciseObjective(Base):
    __tablename__ = "exercise_objectives"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    exercise_id: Mapped[int] = mapped_column(
        ForeignKey("exercises.id", ondelete="CASCADE"), index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    exercise = relationship("Exercise", back_populates="objectives")


class ExerciseRosterRow(Base):
    """صف في قائمة وحدة (متدربين أو محكمين) مرتبط بالتمرين."""

    __tablename__ = "exercise_roster_rows"
    __table_args__ = (Index("ix_exercise_roster_ex_kind", "exercise_id", "roster_kind"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    exercise_id: Mapped[int] = mapped_column(
        ForeignKey("exercises.id", ondelete="CASCADE"), index=True
    )
    roster_kind: Mapped[str] = mapped_column(
        String(16), default=ExerciseRosterKind.TRAINEE.value, index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    military_number: Mapped[str] = mapped_column(String(128), default="")
    rank_ar: Mapped[str] = mapped_column(String(256), default="")
    full_name: Mapped[str] = mapped_column(String(256), default="")
    # نفس مفتاح مستوى الوحدة في المعاضل وقوائم التقييم (قائمة واحدة موحّدة)
    unit_level_key: Mapped[str] = mapped_column(String(64), default="", index=True)
    position_ar: Mapped[str] = mapped_column(String(512), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    exercise = relationship("Exercise", back_populates="roster_rows")


class ExercisePlannerFlowBundle(Base):
    """حزمة تخطيط: قائمة واحدة لمجرى الأحداث والمعاضل + عدة قوائم تقييم إجراءات لكل مرحلة ومستوى وحدة ضمن تمرين."""

    __tablename__ = "exercise_planner_flow_bundles"
    __table_args__ = (
        UniqueConstraint(
            "exercise_id",
            "exercise_phase",
            "unit_level_key",
            name="uq_planner_bundle_ex_phase_unit",
        ),
        Index("ix_planner_bundle_exercise", "exercise_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    exercise_id: Mapped[int] = mapped_column(
        ForeignKey("exercises.id", ondelete="CASCADE"), index=True
    )
    exercise_phase: Mapped[str] = mapped_column(String(32), index=True)
    unit_level_key: Mapped[str] = mapped_column(String(64), index=True)
    unit_level_label: Mapped[str] = mapped_column(String(200), default="")
    event_flow_title: Mapped[str] = mapped_column(String(500), default="")
    event_flow_file_relpath: Mapped[str] = mapped_column(String(500), default="")
    dilemma_count: Mapped[int] = mapped_column(Integer, default=0)
    linked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    exercise = relationship("Exercise", back_populates="planner_flow_bundles")
    event_flow_items = relationship(
        "ExercisePlannerFlowBundleEventFlow",
        back_populates="bundle",
        order_by="ExercisePlannerFlowBundleEventFlow.slot_index",
        cascade="all, delete-orphan",
    )
    action_eval_slots = relationship(
        "ExercisePlannerFlowBundleActionEval",
        back_populates="bundle",
        order_by="ExercisePlannerFlowBundleActionEval.slot_index",
        cascade="all, delete-orphan",
    )
    judge_assignments = relationship(
        "JudgeTraineeAssignment",
        back_populates="planner_flow_bundle",
    )


class ExercisePlannerFlowBundleEventFlow(Base):
    """ملف مجرى أحداث ومعاضل ضمن حزمة التخطيط (عدة ملفات لكل حزمة)."""

    __tablename__ = "exercise_planner_flow_bundle_event_flows"
    __table_args__ = (
        UniqueConstraint("bundle_id", "slot_index", name="uq_bundle_event_flow_slot"),
        Index("ix_bundle_event_flow_bundle", "bundle_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    bundle_id: Mapped[int] = mapped_column(
        ForeignKey("exercise_planner_flow_bundles.id", ondelete="CASCADE"), index=True
    )
    slot_index: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(500), default="")
    file_relpath: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    bundle = relationship("ExercisePlannerFlowBundle", back_populates="event_flow_items")
    action_eval_slots = relationship(
        "ExercisePlannerFlowBundleActionEval",
        back_populates="event_flow_item",
    )


class ExercisePlannerFlowBundleActionEval(Base):
    """عنصر قائمة تقييم إجراءات (Excel) مرتبط بفهرس ضمن الحزمة (1..عدد المعاضل)."""

    __tablename__ = "exercise_planner_flow_bundle_action_evals"
    __table_args__ = (
        UniqueConstraint("bundle_id", "slot_index", name="uq_bundle_action_slot"),
        Index("ix_bundle_action_bundle", "bundle_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    bundle_id: Mapped[int] = mapped_column(
        ForeignKey("exercise_planner_flow_bundles.id", ondelete="CASCADE"), index=True
    )
    slot_index: Mapped[int] = mapped_column(Integer)
    event_flow_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("exercise_planner_flow_bundle_event_flows.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(500), default="")
    file_relpath: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    bundle = relationship("ExercisePlannerFlowBundle", back_populates="action_eval_slots")
    event_flow_item = relationship(
        "ExercisePlannerFlowBundleEventFlow",
        back_populates="action_eval_slots",
    )
    eval_saved = relationship(
        "PlannerFlowBundleEvalSavedResult",
        back_populates="action_slot",
        uselist=False,
        cascade="all, delete-orphan",
    )


class PlannerFlowBundleEvalSavedResult(Base):
    """نتيجة تقييم محفوظة لقائمة إجراءات داخل حزمة المجرى (واجهة المحكم الفعلية)."""

    __tablename__ = "planner_flow_bundle_eval_saved_results"
    __table_args__ = (
        UniqueConstraint(
            "bundle_action_eval_id", name="uq_pf_bundle_eval_saved_action"
        ),
        Index("ix_pf_bundle_eval_exercise", "exercise_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    bundle_action_eval_id: Mapped[int] = mapped_column(
        ForeignKey("exercise_planner_flow_bundle_action_evals.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    exercise_id: Mapped[int | None] = mapped_column(
        ForeignKey("exercises.id", ondelete="CASCADE"), nullable=True, index=True
    )
    exercise_phase: Mapped[str] = mapped_column(
        String(32), default=ExercisePhase.PREPARATION.value, index=True
    )
    unit_level_key: Mapped[str] = mapped_column(String(64), default="", index=True)
    payload_json: Mapped[str] = mapped_column(Text(), default="")
    total_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    grade_label: Mapped[str] = mapped_column(String(64), default="")
    saved_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    approved_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reopened_for_judge: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_chief_approved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    chief_approved_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    chief_approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_control_approved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    control_approved_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    control_approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    action_slot = relationship(
        "ExercisePlannerFlowBundleActionEval", back_populates="eval_saved"
    )


class JudgeTraineeAssignment(Base):
    """تخصيص محكّم لمتدرب محدد ضمن تمرين محدد.

    الربط يعتمد على `unit_level_key` لأنه المفتاح المستخدم لربط (المعاضل + قوائم التقييم).
    """

    __tablename__ = "judge_trainee_assignments"
    __table_args__ = (
        UniqueConstraint("exercise_id", "judge_user_id", name="uq_jta_exercise_judge"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    exercise_id: Mapped[int] = mapped_column(
        ForeignKey("exercises.id", ondelete="CASCADE"), index=True
    )
    judge_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    unit_level_key: Mapped[str] = mapped_column(String(64), default="", index=True)
    trainee_name: Mapped[str] = mapped_column(String(256), default="")
    trainee_military_number: Mapped[str] = mapped_column(String(128), default="", index=True)
    planner_flow_bundle_id: Mapped[int | None] = mapped_column(
        ForeignKey("exercise_planner_flow_bundles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    judge_user = relationship("User", foreign_keys=[judge_user_id])
    planner_flow_bundle = relationship(
        "ExercisePlannerFlowBundle",
        back_populates="judge_assignments",
        foreign_keys=[planner_flow_bundle_id],
    )


class DilemmaItem(Base):
    """عنصر معضلة بصيغة PDF لكل مستوى وحدة، مرتبط بالتمرين الحالي دون ربط بقوائم التقييم."""

    __tablename__ = "dilemma_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    exercise_id: Mapped[int | None] = mapped_column(ForeignKey("exercises.id", ondelete="CASCADE"), nullable=True, index=True)
    exercise_phase: Mapped[str] = mapped_column(
        String(32), default=ExercisePhase.PREPARATION.value, index=True
    )
    unit_level_key: Mapped[str] = mapped_column(String(64), index=True)
    unit_level_label: Mapped[str] = mapped_column(String(200), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(String(2000))
    pdf_relpath: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class EvaluationListPdfItem(Base):
    """عناصر قوائم التقييم (ملفات Excel) لكل مستوى وحدة ومرحلة، مستقلة عن المعاضل."""

    __tablename__ = "evaluation_list_pdf_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    exercise_id: Mapped[int | None] = mapped_column(ForeignKey("exercises.id", ondelete="CASCADE"), nullable=True, index=True)
    exercise_phase: Mapped[str] = mapped_column(
        String(32), default=ExercisePhase.PREPARATION.value, index=True
    )
    unit_level_key: Mapped[str] = mapped_column(String(64), index=True)
    unit_level_label: Mapped[str] = mapped_column(String(200), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(String(2000))
    pdf_relpath: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class EvaluationListSavedResult(Base):
    """نتائج تقييم محفوظة لملف Excel واحد."""

    __tablename__ = "evaluation_list_saved_results"
    __table_args__ = (
        Index("ix_eval_saved_eval_item", "evaluation_item_id"),
        Index("ix_eval_saved_exercise_unit", "exercise_id", "unit_level_key"),
        Index("ix_eval_saved_exercise_judge", "exercise_id", "saved_by_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    evaluation_item_id: Mapped[int] = mapped_column(
        ForeignKey("evaluation_list_pdf_items.id", ondelete="CASCADE"), index=True
    )
    exercise_id: Mapped[int | None] = mapped_column(
        ForeignKey("exercises.id", ondelete="CASCADE"), nullable=True, index=True
    )
    exercise_phase: Mapped[str] = mapped_column(String(32), default=ExercisePhase.PREPARATION.value, index=True)
    unit_level_key: Mapped[str] = mapped_column(String(64), default="", index=True)
    payload_json: Mapped[str] = mapped_column(Text(), default="")  # rows + notes + totals
    total_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    grade_label: Mapped[str] = mapped_column(String(64), default="")
    saved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reopened_for_judge: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_chief_approved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    chief_approved_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    chief_approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_control_approved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    control_approved_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    control_approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EvaluationCriterionMedia(Base):
    """صورة أو فيديو يوثّق بنداً في قائمة التقييم (صف جدول المعايير)."""

    __tablename__ = "evaluation_criterion_media"
    __table_args__ = (
        Index("ix_eval_crit_media_ex_list_row", "exercise_id", "evaluation_list_item_id", "row_index"),
        Index("ix_eval_crit_media_ex_bundle_row", "exercise_id", "bundle_action_eval_id", "row_index"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    exercise_id: Mapped[int] = mapped_column(
        ForeignKey("exercises.id", ondelete="CASCADE"), index=True
    )
    unit_level_key: Mapped[str] = mapped_column(String(64), default="", index=True)
    evaluation_list_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("evaluation_list_pdf_items.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    bundle_action_eval_id: Mapped[int | None] = mapped_column(
        ForeignKey("exercise_planner_flow_bundle_action_evals.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    row_index: Mapped[int] = mapped_column(Integer, default=0, index=True)
    media_kind: Mapped[str] = mapped_column(String(16), default="photo", index=True)
    mime_type: Mapped[str] = mapped_column(String(120), default="")
    file_relpath: Mapped[str] = mapped_column(String(700), default="")
    uploaded_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class AnalystEvaluationCriteriaResult(Base):
    """نتائج مراحل التقييم اليدوية للمحللين، مستقلة عن قوائم التقييم."""

    __tablename__ = "analyst_evaluation_criteria_results"
    __table_args__ = (
        UniqueConstraint("exercise_id", "unit_level_key", name="uq_analyst_eval_criteria_ex_unit"),
        Index("ix_analyst_eval_criteria_exercise", "exercise_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercises.id", ondelete="CASCADE"), index=True)
    unit_level_key: Mapped[str] = mapped_column(String(64), default="", index=True)
    preparation_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    operations_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AnalystEvaluationCriteriaUnit(Base):
    """قائمة وحدات معايير التقييم الخاصة بالمحللين، قابلة للتعديل والحذف."""

    __tablename__ = "analyst_evaluation_criteria_units"
    __table_args__ = (
        Index("ix_analyst_eval_criteria_units_exercise", "exercise_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercises.id", ondelete="CASCADE"), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    label: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AnalystEvaluationCriteriaPhaseItem(Base):
    """معايير وعلامات مرحلة محددة لوحدة ضمن جدول معايير التقييم."""

    __tablename__ = "analyst_evaluation_criteria_phase_items"
    __table_args__ = (
        Index("ix_analyst_eval_criteria_phase_unit", "criteria_unit_id", "phase_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercises.id", ondelete="CASCADE"), index=True)
    criteria_unit_id: Mapped[int] = mapped_column(
        ForeignKey("analyst_evaluation_criteria_units.id", ondelete="CASCADE"),
        index=True,
    )
    phase_key: Mapped[str] = mapped_column(String(32), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    criteria_text: Mapped[str] = mapped_column(String(1000), default="")
    allocated_mark: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class JudgeTaskStatusKey(str, enum.Enum):
    LATE = "late"
    ONTIME = "ontime"
    DONE = "done"


class JudgeIncompleteTaskStatus(Base):
    """حالة مهمة تقييم لكل محكم داخل تمرين."""

    __tablename__ = "judge_incomplete_task_status"
    __table_args__ = (
        Index("ix_jtask_exercise_judge", "exercise_id", "judge_id"),
        Index("ix_jtask_exercise_pair", "exercise_id", "unit_level_key", "pair_index"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercises.id", ondelete="CASCADE"), index=True)
    judge_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    unit_level_key: Mapped[str] = mapped_column(String(64), default="", index=True)
    exercise_phase: Mapped[str] = mapped_column(String(32), default=ExercisePhase.PREPARATION.value, index=True)
    pair_index: Mapped[int] = mapped_column(Integer, default=0)  # index داخل تقرير الربط (1..n)
    dilemma_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evaluation_item_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status_key: Mapped[str] = mapped_column(String(16), default=JudgeTaskStatusKey.ONTIME.value, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TimelineRowKind(str, enum.Enum):
    EVENT = "event"
    DILEMMA = "dilemma"
    DETAIL = "detail"


class ExerciseTimelineItem(Base):
    """جدول قديم غير مستخدم حالياً."""

    __tablename__ = "exercise_timeline_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercises.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("exercise_timeline_items.id", ondelete="CASCADE"), nullable=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    row_kind: Mapped[str] = mapped_column(String(32), default=TimelineRowKind.DETAIL.value, index=True)
    sequence_no: Mapped[int] = mapped_column(Integer, default=0)
    child_sequence_no: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(500), default="")
    time_from: Mapped[str] = mapped_column(String(64), default="")
    time_to: Mapped[str] = mapped_column(String(64), default="")
    reporting_systems: Mapped[str] = mapped_column(String(1000), default="")
    description: Mapped[str] = mapped_column(Text(), default="")
    expected_reaction: Mapped[str] = mapped_column(Text(), default="")
    training_objective: Mapped[str] = mapped_column(Text(), default="")
    notes: Mapped[str] = mapped_column(Text(), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    exercise = relationship("Exercise", back_populates="timeline_items")
    parent = relationship("ExerciseTimelineItem", remote_side=[id], back_populates="children")
    children = relationship(
        "ExerciseTimelineItem",
        back_populates="parent",
        order_by="ExerciseTimelineItem.sort_order",
        cascade="all, delete-orphan",
    )


class Checklist(Base):
    __tablename__ = "checklists"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercises.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(500))
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    exercise = relationship("Exercise", back_populates="checklists")
    creator = relationship("User", foreign_keys=[created_by_id])
    items = relationship("ChecklistItem", back_populates="checklist", order_by="ChecklistItem.sort_order", cascade="all, delete-orphan")


class ChecklistItem(Base):
    __tablename__ = "checklist_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    checklist_id: Mapped[int] = mapped_column(ForeignKey("checklists.id", ondelete="CASCADE"), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(String(2000))
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    # للمحكّم: إكمال
    is_done: Mapped[bool] = mapped_column(Boolean, default=False)
    judge_note: Mapped[str] = mapped_column(String(2000), default="")

    checklist = relationship("Checklist", back_populates="items")


class EvaluationNote(Base):
    __tablename__ = "evaluation_notes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercises.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    body: Mapped[str] = mapped_column(Text(), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    exercise = relationship("Exercise", back_populates="eval_notes")
    author = relationship("User", foreign_keys=[user_id])


class ChatRoomKind:
    """قيم مقترحة لعمود ``ChatRoom.room_kind`` (نص حر مع قيم مساعدة)."""

    JUDGE_BRIGADE = "judge_brigade"
    JUDGE_BN = "judge_bn"
    CONTROL = "control"
    ADMIN_SUPPORT = "admin_support"
    CUSTOM = "custom"


class ChatRoom(Base):
    """غرفة محادثة مرتبطة بتمرين واحد."""

    __tablename__ = "chat_rooms"
    __table_args__ = (Index("ix_chat_rooms_exercise", "exercise_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercises.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(500), default="")
    description: Mapped[str] = mapped_column(Text(), default="")
    room_kind: Mapped[str] = mapped_column(String(64), default=ChatRoomKind.CUSTOM, index=True)
    unit_level_key: Mapped[str] = mapped_column(String(64), default="", index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    members = relationship(
        "ChatRoomMember",
        back_populates="room",
        cascade="all, delete-orphan",
        order_by="ChatRoomMember.joined_at",
    )
    messages = relationship(
        "ChatMessage",
        back_populates="room",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at",
    )


class ChatRoomMember(Base):
    __tablename__ = "chat_room_members"
    __table_args__ = (
        UniqueConstraint("room_id", "user_id", name="uq_chat_room_member"),
        Index("ix_chat_room_members_user", "user_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("chat_rooms.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role_in_room: Mapped[str] = mapped_column(String(32), default="member")  # member | moderator
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    room = relationship("ChatRoom", back_populates="members")


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (Index("ix_chat_messages_room_created", "room_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("chat_rooms.id", ondelete="CASCADE"), index=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    message_type: Mapped[str] = mapped_column(String(32), default="text", index=True)  # text | file
    body_text: Mapped[str] = mapped_column(Text(), default="")
    file_relpath: Mapped[str] = mapped_column(String(600), default="")
    original_filename: Mapped[str] = mapped_column(String(500), default="")
    mime_type: Mapped[str] = mapped_column(String(200), default="")
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    room = relationship("ChatRoom", back_populates="messages")
    reads = relationship(
        "ChatMessageRead",
        back_populates="message",
        cascade="all, delete-orphan",
    )


class ChatMessageRead(Base):
    __tablename__ = "chat_message_reads"
    __table_args__ = (
        UniqueConstraint("message_id", "user_id", name="uq_chat_message_read"),
        Index("ix_chat_message_reads_message", "message_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("chat_messages.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    read_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    message = relationship("ChatMessage", back_populates="reads")


class ExerciseNotification(Base):
    """إشعار مرتبط بتمرين ومستخدم مستهدف (سجل الإشعارات)."""

    __tablename__ = "exercise_notifications"
    __table_args__ = (
        Index("ix_ex_notif_user_ex_read", "user_id", "exercise_id", "is_read"),
        Index("ix_ex_notif_ex_created", "exercise_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    exercise_id: Mapped[int] = mapped_column(
        ForeignKey("exercises.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(32), default="system", index=True)
    title: Mapped[str] = mapped_column(String(500), default="")
    body: Mapped[str] = mapped_column(Text(), default="")
    priority: Mapped[str] = mapped_column(String(32), default="normal", index=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    related_file: Mapped[str] = mapped_column(String(600), default="")
    related_room_id: Mapped[int | None] = mapped_column(
        ForeignKey("chat_rooms.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action_url: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )


class VisualDocument(Base):
    """مادة توثيق مرئي/فيديو/صوت مرتبطة بالتمرين."""

    __tablename__ = "visual_documents"
    __table_args__ = (
        Index("ix_visual_docs_ex_created", "exercise_id", "created_at"),
        Index("ix_visual_docs_ex_unit", "exercise_id", "unit_level_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    exercise_id: Mapped[int] = mapped_column(
        ForeignKey("exercises.id", ondelete="CASCADE"), index=True
    )
    # ربط اختياري: حدث/عنصر زمني أو معضلة
    event_id: Mapped[int | None] = mapped_column(
        ForeignKey("exercise_timeline_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    dilemma_id: Mapped[int | None] = mapped_column(
        ForeignKey("dilemma_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    unit_level_key: Mapped[str] = mapped_column(String(64), default="", index=True)
    uploaded_by_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    file_type: Mapped[str] = mapped_column(String(16), default="image", index=True)  # image|video|audio
    file_relpath: Mapped[str] = mapped_column(String(700), default="")
    description: Mapped[str] = mapped_column(Text(), default="")
    location_label: Mapped[str] = mapped_column(String(400), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    uploader = relationship("User", foreign_keys=[uploaded_by_id])


class InformationBankPhaseNote(Base):
    """ملاحظات مرحلة تمرين في بنك المعلومات — عامة للنظام دون ForeignKey إلى تمرين."""

    __tablename__ = "information_bank_phase_notes"

    phase_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    notes: Mapped[str] = mapped_column(Text(), default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class InformationBankUnitNote(Base):
    """ملاحظات مستوى وحدة في بنك المعلومات — عامة للنظام دون ارتباط بتمرين."""

    __tablename__ = "information_bank_unit_notes"

    unit_level_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    notes: Mapped[str] = mapped_column(Text(), default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class InformationBankTrainingPhase(Base):
    """كتالوج مراحل التمرين في بنك المعلومات، قابل للإضافة والحذف."""

    __tablename__ = "information_bank_training_phases"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(300), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class InformationBankUnitLevel(Base):
    """كتالوج مستويات الوحدات في بنك المعلومات، قابل للإضافة والحذف."""

    __tablename__ = "information_bank_unit_levels"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    label: Mapped[str] = mapped_column(String(300), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class InformationBankTreeNode(Base):
    """عقدة شجرة بنك المعلومات — مجلد أو ملف ضمن مرحلة/وحدة/مجلد فرعي."""

    __tablename__ = "information_bank_tree_nodes"
    __table_args__ = (
        Index("ix_ib_tree_kind_parent", "kind", "parent_id"),
        Index("ix_ib_tree_kind_phase", "kind", "catalog_phase_key"),
        Index("ix_ib_tree_kind_unit", "kind", "catalog_unit_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("information_bank_tree_nodes.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(500), default="")
    is_folder: Mapped[bool] = mapped_column(Boolean, default=False)
    file_relpath: Mapped[str] = mapped_column(String(700), default="")
    catalog_phase_key: Mapped[str] = mapped_column(String(64), default="", index=True)
    catalog_unit_key: Mapped[str] = mapped_column(String(128), default="", index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    parent = relationship(
        "InformationBankTreeNode",
        remote_side="InformationBankTreeNode.id",
        back_populates="children",
    )
    children = relationship(
        "InformationBankTreeNode",
        back_populates="parent",
        cascade="all, delete-orphan",
    )


class InfoBankEventFlowPdf(Base):
    """مجرى الأحداث والمعاضل — ملف PDF أو Word (.doc/.docx) لمرحلة ومستوى وحدة؛ تخزين عام بلا exercise_id."""

    __tablename__ = "info_bank_event_flow_pdfs"
    __table_args__ = (Index("ix_ib_flow_phase_unit", "training_phase_key", "unit_level_key"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    training_phase_key: Mapped[str] = mapped_column(String(64), index=True)
    unit_level_key: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(String(500), default="")
    file_relpath: Mapped[str] = mapped_column(String(500), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class InfoBankActionEvalXlsx(Base):
    """قوائم تقييم الإجراءات (Excel) في بنك المعلومات — عامة بلا ارتباط بتمرين."""

    __tablename__ = "info_bank_action_eval_xlsx"
    __table_args__ = (Index("ix_ib_action_phase_unit", "training_phase_key", "unit_level_key"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    training_phase_key: Mapped[str] = mapped_column(String(64), index=True)
    unit_level_key: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(String(500), default="")
    file_relpath: Mapped[str] = mapped_column(String(500), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class InfoBankDilemmaEvalXlsx(Base):
    """قوائم تقييم المعاضل (Excel) في بنك المعلومات — عامة بلا exercise_id."""

    __tablename__ = "info_bank_dilemma_eval_xlsx"
    __table_args__ = (Index("ix_ib_dilemma_phase_unit", "training_phase_key", "unit_level_key"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    training_phase_key: Mapped[str] = mapped_column(String(64), index=True)
    unit_level_key: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(String(500), default="")
    file_relpath: Mapped[str] = mapped_column(String(500), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
