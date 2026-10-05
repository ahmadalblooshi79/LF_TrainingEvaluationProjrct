"""نسبة حفظ/اعتماد قوائم التقييم إلى المحكم المعين للوحدة بدل إدارة النظام."""
from __future__ import annotations

from app.exercise_phase_catalog import normalize_exercise_phase
from app.models import (
    EvaluationListSavedResult,
    ExerciseRosterKind,
    ExerciseRosterRow,
    JudgeTraineeAssignment,
    PlannerFlowBundleEvalSavedResult,
    RoleKey,
    User,
)

_ADMIN_DISPLAY_NAMES = frozenset({"إدارة النظام", "المحكم إدارة النظام"})


def user_is_admin_attribution_source(user: User | None) -> bool:
    """حساب يُعرض اسمه كإدارة النظام ولا يُنسب إليه حفظ القائمة."""
    if user is None:
        return False
    if (getattr(user, "role_key", None) or "") == RoleKey.SYSTEM_ADMIN.value:
        return True
    name = (getattr(user, "full_name", None) or "").strip()
    return name in _ADMIN_DISPLAY_NAMES


def assigned_judge_user_for_unit(
    db,
    *,
    exercise_id: int,
    unit_key: str,
    phase_key: str | None = None,
) -> User | None:
    """المحكم المعين للوحدة (والمرحلة إن وُجدت) من الإسناد ثم قائمة المحكمين."""
    eid = int(exercise_id)
    uk = (unit_key or "").strip()
    if not uk:
        return None
    pk_raw = (phase_key or "").strip()
    pk = normalize_exercise_phase(pk_raw) or pk_raw

    assignments = (
        db.query(JudgeTraineeAssignment)
        .filter(
            JudgeTraineeAssignment.exercise_id == eid,
            JudgeTraineeAssignment.unit_level_key == uk,
        )
        .order_by(JudgeTraineeAssignment.id)
        .all()
    )

    def _user_from_assignment(row: JudgeTraineeAssignment) -> User | None:
        u = db.get(User, int(row.judge_user_id))
        if u is None or user_is_admin_attribution_source(u):
            return None
        return u

    if pk:
        for row in assignments:
            raw = (row.exercise_phase or "").strip()
            if (normalize_exercise_phase(raw) or raw) == pk:
                found = _user_from_assignment(row)
                if found is not None:
                    return found
    for row in assignments:
        found = _user_from_assignment(row)
        if found is not None:
            return found

    roster = (
        db.query(ExerciseRosterRow)
        .filter(
            ExerciseRosterRow.exercise_id == eid,
            ExerciseRosterRow.roster_kind == ExerciseRosterKind.JUDGE.value,
            ExerciseRosterRow.unit_level_key == uk,
        )
        .order_by(ExerciseRosterRow.sort_order, ExerciseRosterRow.id)
        .all()
    )

    def _user_from_roster(jr: ExerciseRosterRow) -> User | None:
        mil = (jr.military_number or "").strip()
        if not mil:
            return None
        u = db.query(User).filter(User.username == mil).first()
        if u is None or user_is_admin_attribution_source(u):
            return None
        return u

    if pk:
        for jr in roster:
            raw = (jr.exercise_phase or "").strip()
            if (normalize_exercise_phase(raw) or raw) == pk:
                found = _user_from_roster(jr)
                if found is not None:
                    return found
    for jr in roster:
        found = _user_from_roster(jr)
        if found is not None:
            return found
    return None


def attribution_user_id_for_eval_actor(
    db,
    actor: User | None,
    *,
    exercise_id: int,
    unit_key: str,
    phase_key: str | None = None,
) -> int | None:
    """معرّف المستخدم المسجَّل على الحفظ/اعتماد المحكم: المحكم المعين إن كان الفاعل إدارة النظام."""
    if actor is None:
        return None
    aid = getattr(actor, "id", None)
    if not user_is_admin_attribution_source(actor):
        return aid
    assigned = assigned_judge_user_for_unit(
        db,
        exercise_id=int(exercise_id),
        unit_key=unit_key,
        phase_key=phase_key,
    )
    if assigned is not None:
        return int(assigned.id)
    return aid


def _admin_user_ids(db) -> set[int]:
    ids: set[int] = set()
    for u in db.query(User).all():
        if user_is_admin_attribution_source(u) and getattr(u, "id", None) is not None:
            ids.add(int(u.id))
    return ids


def _reattribute_saved_row(db, saved, admin_ids: set[int]) -> bool:
    uk = (getattr(saved, "unit_level_key", None) or "").strip()
    pk = getattr(saved, "exercise_phase", None)
    eid = int(getattr(saved, "exercise_id", 0) or 0)
    if not eid or not uk:
        return False
    needs = False
    for field in ("saved_by_id", "approved_by_id"):
        uid = getattr(saved, field, None)
        if uid is not None and int(uid) in admin_ids:
            needs = True
            break
    if not needs:
        return False
    assigned = assigned_judge_user_for_unit(
        db, exercise_id=eid, unit_key=uk, phase_key=pk
    )
    if assigned is None:
        return False
    jid = int(assigned.id)
    changed = False
    for field in ("saved_by_id", "approved_by_id"):
        uid = getattr(saved, field, None)
        if uid is not None and int(uid) in admin_ids:
            setattr(saved, field, jid)
            changed = True
    return changed


def reattribute_admin_saved_eval_rows(db, exercise_id: int | None = None) -> int:
    """نقل saved_by/approved_by من حسابات إدارة النظام إلى المحكم المعين للوحدة."""
    admin_ids = _admin_user_ids(db)
    if not admin_ids:
        return 0
    n = 0
    eval_q = db.query(EvaluationListSavedResult)
    action_q = db.query(PlannerFlowBundleEvalSavedResult)
    if exercise_id is not None:
        eval_q = eval_q.filter(EvaluationListSavedResult.exercise_id == int(exercise_id))
        action_q = action_q.filter(
            PlannerFlowBundleEvalSavedResult.exercise_id == int(exercise_id)
        )
    for saved in eval_q.all():
        if _reattribute_saved_row(db, saved, admin_ids):
            n += 1
    for saved in action_q.all():
        if _reattribute_saved_row(db, saved, admin_ids):
            n += 1
    return n
