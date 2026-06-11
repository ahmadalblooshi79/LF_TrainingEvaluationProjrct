"""تصدير التمرين كاملًا إلى JSON في مجلد خارجي وقراءة الملف للعودة إلى صفحة التمرين."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session, joinedload

from app import exercise_options as ex_opts
from app.config import (
    CHAT_UPLOAD_DIR,
    DILEMMA_PDF_DIR,
    EVAL_CRITERION_MEDIA_DIR,
    EVALUATION_LIST_XLSX_DIR,
    EXERCISE_EXPORT_DIR,
    PLANNER_FLOW_BUNDLE_DIR,
    VISUAL_DOC_DIR,
)
from app.exercise_phase_catalog import normalize_exercise_phase
from app.unit_levels_catalog import label_for_unit_level_key, normalize_unit_level_key
from app.models import (
    AnalystEvaluationCriteriaPhaseItem,
    AnalystEvaluationCriteriaResult,
    AnalystEvaluationCriteriaUnit,
    AnalystFinalEvaluationAllocatedMax,
    AnalystFinalEvaluationPhaseAllocatedMax,
    ChatMessage,
    ChatRoom,
    ChatRoomMember,
    Checklist,
    ChecklistItem,
    DilemmaItem,
    EvaluationCriterionMedia,
    EvaluationListPdfItem,
    EvaluationListSavedResult,
    EvaluationNote,
    EventFlow,
    EventFlowType,
    Exercise,
    ExerciseBattleUnitPersonnel,
    ExerciseNotification,
    ExerciseObjective,
    ExercisePlannerFlowBundle,
    ExercisePlannerFlowBundleActionEval,
    ExercisePlannerFlowBundleEventFlow,
    ExerciseRefLink,
    ExerciseRosterRow,
    ExerciseStatus,
    ExerciseTimelineItem,
    JudgeIncompleteTaskStatus,
    JudgeTraineeAssignment,
    PlannerFlowBundleEvalSavedResult,
    Problem,
    ProblemStatus,
    Reference,
    User,
    VisualDocument,
)

EXPORT_SCHEMA_VERSION = 3

# أسماء مجلدات داخل حزمة الملفات `{اسم_التمرين}_files/` — تطابق مجلدات instance
FILE_BUCKET_ROOTS: dict[str, Path] = {
    "dilemma_pdfs": DILEMMA_PDF_DIR,
    "evaluation_list_xlsx": EVALUATION_LIST_XLSX_DIR,
    "planner_flow_bundles": PLANNER_FLOW_BUNDLE_DIR,
    "chat_uploads": CHAT_UPLOAD_DIR,
    "visual_docs": VISUAL_DOC_DIR,
    "eval_criterion_media": EVAL_CRITERION_MEDIA_DIR,
}


def export_directory() -> Path:
    p = Path(EXERCISE_EXPORT_DIR)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat()


def _eval_saved_export_row(s: EvaluationListSavedResult | PlannerFlowBundleEvalSavedResult) -> dict[str, Any]:
    return {
        "id": s.id,
        "evaluation_item_id": getattr(s, "evaluation_item_id", None),
        "bundle_action_eval_id": getattr(s, "bundle_action_eval_id", None),
        "exercise_id": s.exercise_id,
        "exercise_phase": normalize_exercise_phase(getattr(s, "exercise_phase", None)),
        "unit_level_key": s.unit_level_key or "",
        "payload_json": s.payload_json or "",
        "total_pct": s.total_pct,
        "grade_label": s.grade_label or "",
        "saved_by_id": s.saved_by_id,
        "is_approved": bool(s.is_approved),
        "approved_by_id": s.approved_by_id,
        "approved_at": _iso(s.approved_at),
        "reopened_for_judge": bool(getattr(s, "reopened_for_judge", False)),
        "is_chief_approved": bool(getattr(s, "is_chief_approved", False)),
        "chief_approved_by_id": getattr(s, "chief_approved_by_id", None),
        "chief_approved_at": _iso(getattr(s, "chief_approved_at", None)),
        "is_control_approved": bool(getattr(s, "is_control_approved", False)),
        "control_approved_by_id": getattr(s, "control_approved_by_id", None),
        "control_approved_at": _iso(getattr(s, "control_approved_at", None)),
        "created_at": _iso(s.created_at),
        "updated_at": _iso(getattr(s, "updated_at", None)),
    }


def _sanitize_filename_stem(name: str, fallback: str) -> str:
    s = (name or "").strip() or fallback
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s)
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > 180:
        s = s[:180].rstrip()
    return s or fallback


def _export_path_for_exercise(directory: Path, title: str, code: str, exercise_id: int) -> Path:
    stem = _sanitize_filename_stem(title, code or "exercise")
    primary = directory / f"{stem}.json"
    if not primary.exists():
        return primary
    try:
        data = json.loads(primary.read_text(encoding="utf-8"))
        ex = data.get("exercise") if isinstance(data, dict) else None
        if isinstance(ex, dict) and ex.get("id") == exercise_id:
            return primary
    except Exception:
        pass
    alt = _sanitize_filename_stem(f"{stem}_{code}", code or str(exercise_id))
    return directory / f"{alt}.json"


def load_exercise_for_export(db: Session, exercise_id: int) -> Exercise | None:
    return (
        db.query(Exercise)
        .options(
            joinedload(Exercise.objectives),
            joinedload(Exercise.roster_rows),
            joinedload(Exercise.events),
            joinedload(Exercise.problems),
            joinedload(Exercise.checklists).joinedload(Checklist.items),
            joinedload(Exercise.eval_notes),
        )
        .filter(Exercise.id == exercise_id)
        .first()
    )


def exercise_to_export_dict(ex: Exercise, db: Session) -> dict[str, Any]:
    ref_rows = (
        db.query(ExerciseRefLink)
        .filter(ExerciseRefLink.exercise_id == ex.id)
        .all()
    )
    objectives = sorted(ex.objectives or [], key=lambda o: o.sort_order)
    roster_all = sorted(ex.roster_rows or [], key=lambda r: (r.roster_kind, r.sort_order, r.id))
    roster_trainee = [r for r in roster_all if (r.roster_kind or "") == "trainee"]
    roster_judge = [r for r in roster_all if (r.roster_kind or "") == "judge"]
    events = sorted(ex.events or [], key=lambda e: e.order_index)
    problems = list(ex.problems or [])
    checklists = list(ex.checklists or [])
    notes = list(ex.eval_notes or [])
    dilemma_rows = (
        db.query(DilemmaItem)
        .filter(DilemmaItem.exercise_id == ex.id)
        .order_by(DilemmaItem.unit_level_key, DilemmaItem.sort_order, DilemmaItem.id)
        .all()
    )
    evaluation_list_rows = (
        db.query(EvaluationListPdfItem)
        .filter(EvaluationListPdfItem.exercise_id == ex.id)
        .order_by(EvaluationListPdfItem.unit_level_key, EvaluationListPdfItem.sort_order, EvaluationListPdfItem.id)
        .all()
    )
    timeline_rows = (
        db.query(ExerciseTimelineItem)
        .filter(ExerciseTimelineItem.exercise_id == ex.id)
        .order_by(ExerciseTimelineItem.sort_order, ExerciseTimelineItem.id)
        .all()
    )
    battle_personnel = (
        db.query(ExerciseBattleUnitPersonnel)
        .filter(ExerciseBattleUnitPersonnel.exercise_id == ex.id)
        .order_by(ExerciseBattleUnitPersonnel.unit_id)
        .all()
    )
    planner_bundles = (
        db.query(ExercisePlannerFlowBundle)
        .options(
            joinedload(ExercisePlannerFlowBundle.event_flow_items),
            joinedload(ExercisePlannerFlowBundle.action_eval_slots).joinedload(
                ExercisePlannerFlowBundleActionEval.eval_saved
            ),
        )
        .filter(ExercisePlannerFlowBundle.exercise_id == ex.id)
        .order_by(
            ExercisePlannerFlowBundle.exercise_phase,
            ExercisePlannerFlowBundle.unit_level_key,
        )
        .all()
    )
    eval_saved_rows = (
        db.query(EvaluationListSavedResult)
        .filter(EvaluationListSavedResult.exercise_id == ex.id)
        .all()
    )
    judge_assignments = (
        db.query(JudgeTraineeAssignment)
        .filter(JudgeTraineeAssignment.exercise_id == ex.id)
        .all()
    )
    analyst_units = (
        db.query(AnalystEvaluationCriteriaUnit)
        .filter(AnalystEvaluationCriteriaUnit.exercise_id == ex.id)
        .order_by(AnalystEvaluationCriteriaUnit.sort_order, AnalystEvaluationCriteriaUnit.id)
        .all()
    )
    analyst_phase_items = (
        db.query(AnalystEvaluationCriteriaPhaseItem)
        .filter(AnalystEvaluationCriteriaPhaseItem.exercise_id == ex.id)
        .order_by(AnalystEvaluationCriteriaPhaseItem.criteria_unit_id, AnalystEvaluationCriteriaPhaseItem.sort_order)
        .all()
    )
    analyst_results = (
        db.query(AnalystEvaluationCriteriaResult)
        .filter(AnalystEvaluationCriteriaResult.exercise_id == ex.id)
        .all()
    )
    judge_tasks = (
        db.query(JudgeIncompleteTaskStatus)
        .filter(JudgeIncompleteTaskStatus.exercise_id == ex.id)
        .all()
    )
    crit_media = (
        db.query(EvaluationCriterionMedia)
        .filter(EvaluationCriterionMedia.exercise_id == ex.id)
        .all()
    )
    visual_docs = (
        db.query(VisualDocument)
        .filter(VisualDocument.exercise_id == ex.id)
        .order_by(VisualDocument.created_at)
        .all()
    )
    chat_rooms = (
        db.query(ChatRoom)
        .options(joinedload(ChatRoom.members), joinedload(ChatRoom.messages))
        .filter(ChatRoom.exercise_id == ex.id)
        .order_by(ChatRoom.id)
        .all()
    )
    notifications = (
        db.query(ExerciseNotification)
        .filter(ExerciseNotification.exercise_id == ex.id)
        .order_by(ExerciseNotification.created_at)
        .all()
    )

    return {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "exported_at": _iso(datetime.utcnow()),
        "exercise": {
            "id": ex.id,
            "code": ex.code,
            "title": ex.title,
            "description": ex.description or "",
            "exercise_type": ex.exercise_type or "",
            "exercise_level": ex.exercise_level or "",
            "mission_label": ex.mission_label or "",
            "trained_unit": ex.trained_unit or "",
            "location_label": ex.location_label or "",
            "status": ex.status or "",
            "owner_id": ex.owner_id,
            "planned_start": _iso(ex.planned_start),
            "planned_end": _iso(ex.planned_end),
            "control_approved": bool(ex.control_approved),
            "created_at": _iso(ex.created_at),
            "updated_at": _iso(ex.updated_at),
        },
        "objectives": [
            {
                "id": o.id,
                "sort_order": o.sort_order,
                "text": o.text,
                "created_at": _iso(o.created_at),
            }
            for o in objectives
        ],
        "trainee_unit_roster": [
            {
                "sort_order": r.sort_order,
                "military_number": r.military_number or "",
                "rank_ar": r.rank_ar or "",
                "full_name": r.full_name or "",
                "unit_level_key": getattr(r, "unit_level_key", None) or "",
                "position_ar": r.position_ar or "",
                "created_at": _iso(r.created_at),
            }
            for r in roster_trainee
        ],
        "judge_unit_roster": [
            {
                "sort_order": r.sort_order,
                "military_number": r.military_number or "",
                "rank_ar": r.rank_ar or "",
                "full_name": r.full_name or "",
                "unit_level_key": getattr(r, "unit_level_key", None) or "",
                "position_ar": r.position_ar or "",
                "created_at": _iso(r.created_at),
            }
            for r in roster_judge
        ],
        "event_flows": [
            {
                "id": ev.id,
                "order_index": ev.order_index,
                "title": ev.title,
                "description": ev.description or "",
                "scheduled_at": _iso(ev.scheduled_at),
                "event_type": ev.event_type or "",
                "created_at": _iso(ev.created_at),
            }
            for ev in events
        ],
        "problems": [
            {
                "id": p.id,
                "title": p.title,
                "description": p.description or "",
                "severity": p.severity,
                "status": p.status or "",
                "reported_by_id": p.reported_by_id,
                "created_at": _iso(p.created_at),
                "updated_at": _iso(p.updated_at),
            }
            for p in problems
        ],
        "checklists": [
            {
                "id": cl.id,
                "title": cl.title,
                "created_by_id": cl.created_by_id,
                "created_at": _iso(cl.created_at),
                "items": [
                    {
                        "id": it.id,
                        "sort_order": it.sort_order,
                        "text": it.text,
                        "weight": float(it.weight),
                        "is_done": bool(it.is_done),
                        "judge_note": it.judge_note or "",
                    }
                    for it in sorted(cl.items or [], key=lambda x: x.sort_order)
                ],
            }
            for cl in checklists
        ],
        "evaluation_notes": [
            {
                "id": n.id,
                "user_id": n.user_id,
                "body": n.body or "",
                "created_at": _iso(n.created_at),
            }
            for n in notes
        ],
        "exercise_ref_links": [
            {"id": r.id, "reference_id": r.reference_id} for r in ref_rows
        ],
        "dilemma_items": [
            {
                "id": d.id,
                "unit_level_key": d.unit_level_key,
                "unit_level_label": d.unit_level_label or "",
                "exercise_phase": normalize_exercise_phase(getattr(d, "exercise_phase", None)),
                "sort_order": d.sort_order,
                "text": d.text,
                "pdf_relpath": d.pdf_relpath or "",
                "created_at": _iso(d.created_at),
            }
            for d in dilemma_rows
        ],
        "evaluation_list_items": [
            {
                "id": e.id,
                "unit_level_key": e.unit_level_key,
                "unit_level_label": e.unit_level_label or "",
                "exercise_phase": normalize_exercise_phase(getattr(e, "exercise_phase", None)),
                "sort_order": e.sort_order,
                "text": e.text,
                "pdf_relpath": e.pdf_relpath or "",
                "created_at": _iso(e.created_at),
            }
            for e in evaluation_list_rows
        ],
        "timeline_items": [
            {
                "id": t.id,
                "parent_id": t.parent_id,
                "sort_order": t.sort_order,
                "row_kind": t.row_kind or "",
                "sequence_no": t.sequence_no,
                "child_sequence_no": t.child_sequence_no,
                "title": t.title or "",
                "time_from": t.time_from or "",
                "time_to": t.time_to or "",
                "reporting_systems": t.reporting_systems or "",
                "description": t.description or "",
                "expected_reaction": t.expected_reaction or "",
                "training_objective": t.training_objective or "",
                "notes": t.notes or "",
                "created_at": _iso(t.created_at),
                "updated_at": _iso(t.updated_at),
            }
            for t in timeline_rows
        ],
        "battle_unit_personnel": [
            {
                "unit_id": p.unit_id,
                "trainee_name": p.trainee_name or "",
                "trainee_military_number": p.trainee_military_number or "",
                "rank_ar": p.rank_ar or "",
                "position_ar": p.position_ar or "",
                "judge_trainee_name": p.judge_trainee_name or "",
                "judge_military_number": p.judge_military_number or "",
                "judge_rank_ar": p.judge_rank_ar or "",
                "judge_position_ar": p.judge_position_ar or "",
                "updated_at": _iso(p.updated_at),
            }
            for p in battle_personnel
        ],
        "planner_flow_bundles": [
            {
                "id": b.id,
                "exercise_phase": normalize_exercise_phase(b.exercise_phase),
                "unit_level_key": b.unit_level_key,
                "unit_level_label": b.unit_level_label or "",
                "event_flow_title": b.event_flow_title or "",
                "event_flow_file_relpath": b.event_flow_file_relpath or "",
                "dilemma_count": b.dilemma_count,
                "linked_at": _iso(b.linked_at),
                "flow_table_json": b.flow_table_json or "",
                "created_at": _iso(b.created_at),
                "updated_at": _iso(b.updated_at),
                "event_flow_items": [
                    {
                        "id": ef.id,
                        "slot_index": ef.slot_index,
                        "title": ef.title or "",
                        "file_relpath": ef.file_relpath or "",
                        "created_at": _iso(ef.created_at),
                    }
                    for ef in sorted(b.event_flow_items or [], key=lambda x: x.slot_index)
                ],
                "action_eval_slots": [
                    {
                        "id": ae.id,
                        "slot_index": ae.slot_index,
                        "event_flow_item_id": ae.event_flow_item_id,
                        "title": ae.title or "",
                        "file_relpath": ae.file_relpath or "",
                        "created_at": _iso(ae.created_at),
                        "eval_saved": (
                            _eval_saved_export_row(ae.eval_saved)
                            if ae.eval_saved is not None
                            else None
                        ),
                    }
                    for ae in sorted(b.action_eval_slots or [], key=lambda x: x.slot_index)
                ],
            }
            for b in planner_bundles
        ],
        "evaluation_list_saved_results": [
            _eval_saved_export_row(s) for s in eval_saved_rows
        ],
        "judge_trainee_assignments": [
            {
                "id": a.id,
                "judge_user_id": a.judge_user_id,
                "unit_level_key": a.unit_level_key or "",
                "trainee_name": a.trainee_name or "",
                "trainee_military_number": a.trainee_military_number or "",
                "planner_flow_bundle_id": a.planner_flow_bundle_id,
                "created_at": _iso(a.created_at),
            }
            for a in judge_assignments
        ],
        "analyst_evaluation_criteria_units": [
            {
                "id": u.id,
                "sort_order": u.sort_order,
                "label": u.label or "",
                "created_at": _iso(u.created_at),
                "updated_at": _iso(u.updated_at),
            }
            for u in analyst_units
        ],
        "analyst_evaluation_criteria_phase_items": [
            {
                "id": pi.id,
                "criteria_unit_id": pi.criteria_unit_id,
                "phase_key": pi.phase_key or "",
                "sort_order": pi.sort_order,
                "criteria_text": pi.criteria_text or "",
                "allocated_mark": pi.allocated_mark,
                "created_at": _iso(pi.created_at),
                "updated_at": _iso(pi.updated_at),
            }
            for pi in analyst_phase_items
        ],
        "analyst_evaluation_criteria_results": [
            {
                "id": r.id,
                "unit_level_key": r.unit_level_key or "",
                "preparation_pct": r.preparation_pct,
                "operations_pct": r.operations_pct,
                "updated_by_id": r.updated_by_id,
                "updated_at": _iso(r.updated_at),
            }
            for r in analyst_results
        ],
        "judge_incomplete_task_status": [
            {
                "id": t.id,
                "judge_id": t.judge_id,
                "unit_level_key": t.unit_level_key or "",
                "exercise_phase": normalize_exercise_phase(t.exercise_phase),
                "pair_index": t.pair_index,
                "dilemma_id": t.dilemma_id,
                "evaluation_item_id": t.evaluation_item_id,
                "status_key": t.status_key or "",
                "updated_at": _iso(t.updated_at),
            }
            for t in judge_tasks
        ],
        "evaluation_criterion_media": [
            {
                "id": m.id,
                "unit_level_key": m.unit_level_key or "",
                "evaluation_list_item_id": m.evaluation_list_item_id,
                "bundle_action_eval_id": m.bundle_action_eval_id,
                "row_index": m.row_index,
                "media_kind": m.media_kind or "",
                "mime_type": m.mime_type or "",
                "file_relpath": m.file_relpath or "",
                "uploaded_by_id": m.uploaded_by_id,
                "created_at": _iso(m.created_at),
            }
            for m in crit_media
        ],
        "visual_documents": [
            {
                "id": v.id,
                "event_id": v.event_id,
                "dilemma_id": v.dilemma_id,
                "unit_level_key": v.unit_level_key or "",
                "uploaded_by_id": v.uploaded_by_id,
                "file_type": v.file_type or "",
                "file_relpath": v.file_relpath or "",
                "description": v.description or "",
                "location_label": v.location_label or "",
                "created_at": _iso(v.created_at),
            }
            for v in visual_docs
        ],
        "chat_rooms": [
            {
                "id": room.id,
                "title": room.title or "",
                "description": room.description or "",
                "room_kind": room.room_kind or "",
                "unit_level_key": room.unit_level_key or "",
                "created_by_id": room.created_by_id,
                "created_at": _iso(room.created_at),
                "last_activity_at": _iso(room.last_activity_at),
                "is_archived": bool(room.is_archived),
                "members": [
                    {
                        "user_id": mem.user_id,
                        "role_in_room": mem.role_in_room or "",
                        "joined_at": _iso(mem.joined_at),
                    }
                    for mem in sorted(room.members or [], key=lambda x: x.joined_at or datetime.min)
                ],
                "messages": [
                    {
                        "id": msg.id,
                        "sender_id": msg.sender_id,
                        "message_type": msg.message_type or "",
                        "body_text": msg.body_text or "",
                        "file_relpath": msg.file_relpath or "",
                        "original_filename": msg.original_filename or "",
                        "mime_type": msg.mime_type or "",
                        "file_size": msg.file_size,
                        "created_at": _iso(msg.created_at),
                    }
                    for msg in sorted(room.messages or [], key=lambda x: x.created_at or datetime.min)
                ],
            }
            for room in chat_rooms
        ],
        "exercise_notifications": [
            {
                "id": n.id,
                "user_id": n.user_id,
                "type": n.type or "",
                "title": n.title or "",
                "body": n.body or "",
                "priority": n.priority or "",
                "is_read": bool(n.is_read),
                "related_file": n.related_file or "",
                "related_room_id": n.related_room_id,
                "action_url": n.action_url or "",
                "created_at": _iso(n.created_at),
            }
            for n in notifications
        ],
    }


def _normalize_storage_relpath(relpath: str) -> str:
    return (relpath or "").replace("\\", "/").lstrip("/")


def archive_bundle_dir_for_json(json_path: Path) -> Path:
    return json_path.parent / f"{json_path.stem}_files"


def _resolve_exercise_file_source(relpath: str) -> tuple[str, Path] | None:
    """يُرجع (اسم_المجلد، المسار_الكامل) إن وُجد الملف في أحد مجلدات التخزين."""
    rel = _normalize_storage_relpath(relpath)
    if not rel or ".." in rel.split("/"):
        return None
    for bucket, root in FILE_BUCKET_ROOTS.items():
        src = (root / rel).resolve()
        try:
            src.relative_to(root.resolve())
        except ValueError:
            continue
        if src.is_file():
            return bucket, src
    return None


def sync_exercise_files_to_archive_bundle(
    db: Session, exercise_id: int, bundle_dir: Path
) -> list[dict[str, str]]:
    """نسخ كل ملفات التمرين إلى مجلد الأرشيف بجانب JSON."""
    entries: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for relpath in _collect_exercise_file_relpaths(db, exercise_id):
        resolved = _resolve_exercise_file_source(relpath)
        if not resolved:
            continue
        bucket, src = resolved
        rel = _normalize_storage_relpath(relpath)
        key = (bucket, rel)
        if key in seen:
            continue
        seen.add(key)
        dest = bundle_dir / bucket / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(src, dest)
        except OSError:
            continue
        entries.append({"bucket": bucket, "relpath": rel})
    return entries


def _archive_entries_from_bundle_scan(bundle_dir: Path) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    if not bundle_dir.is_dir():
        return entries
    for bucket in FILE_BUCKET_ROOTS:
        bucket_path = bundle_dir / bucket
        if not bucket_path.is_dir():
            continue
        for f in bucket_path.rglob("*"):
            if not f.is_file():
                continue
            rel = f.relative_to(bucket_path).as_posix()
            entries.append({"bucket": bucket, "relpath": rel})
    return entries


def restore_exercise_files_from_archive(
    bundle_dir: Path, data: dict[str, Any] | None = None
) -> int:
    """استعادة ملفات التمرين من حزمة الأرشيف إلى مجلدات instance."""
    if not bundle_dir.is_dir():
        return 0
    entries: list[dict[str, Any]] = []
    if isinstance(data, dict):
        af = data.get("archive_files")
        if isinstance(af, dict) and isinstance(af.get("entries"), list):
            entries = [e for e in af["entries"] if isinstance(e, dict)]
    if not entries:
        entries = _archive_entries_from_bundle_scan(bundle_dir)
    restored = 0
    for row in entries:
        bucket = str(row.get("bucket") or "").strip()
        rel = _normalize_storage_relpath(str(row.get("relpath") or ""))
        if not bucket or not rel or bucket not in FILE_BUCKET_ROOTS:
            continue
        src = bundle_dir / bucket / rel
        if not src.is_file():
            continue
        root = FILE_BUCKET_ROOTS[bucket]
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(src, dest)
            restored += 1
        except OSError:
            continue
    return restored


def resolve_archive_bundle_dir_for_import(data: dict[str, Any]) -> Path | None:
    """تحديد مجلد `_files` المرافق لملف JSON في مجلد التصدير."""
    directory = export_directory()
    if isinstance(data.get("archive_files"), dict):
        bundle_name = str(data["archive_files"].get("bundle_dir") or "").strip()
        if bundle_name:
            candidate = (directory / bundle_name).resolve()
            try:
                candidate.relative_to(directory.resolve())
            except ValueError:
                candidate = None  # type: ignore[assignment]
            if candidate is not None and candidate.is_dir():
                return candidate
    exj = data.get("exercise")
    if isinstance(exj, dict):
        try:
            eid = int(exj.get("id")) if exj.get("id") is not None else 0
        except (TypeError, ValueError):
            eid = 0
        json_path = _export_path_for_exercise(
            directory,
            str(exj.get("title") or ""),
            str(exj.get("code") or ""),
            eid,
        )
        bundle = archive_bundle_dir_for_json(json_path)
        if bundle.is_dir():
            return bundle
        for p in sorted(directory.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                j = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(j, dict):
                continue
            jex = j.get("exercise")
            if not isinstance(jex, dict):
                continue
            if eid and jex.get("id") == eid:
                b = archive_bundle_dir_for_json(p)
                if b.is_dir():
                    return b
            if (
                not eid
                and str(jex.get("title") or "").strip() == str(exj.get("title") or "").strip()
                and str(jex.get("code") or "").strip() == str(exj.get("code") or "").strip()
            ):
                b = archive_bundle_dir_for_json(p)
                if b.is_dir():
                    return b
    return None


def write_exercise_json_file(
    db: Session,
    exercise_id: int,
    *,
    mark_closed: bool = False,
    archive_meta: dict[str, Any] | None = None,
    sync_file_bundle: bool = True,
) -> Path | None:
    ex = load_exercise_for_export(db, exercise_id)
    if not ex:
        return None
    directory = export_directory()
    path = _export_path_for_exercise(directory, ex.title, ex.code, ex.id)
    file_entries: list[dict[str, str]] = []
    if sync_file_bundle:
        bundle_dir = archive_bundle_dir_for_json(path)
        bundle_dir.mkdir(parents=True, exist_ok=True)
        file_entries = sync_exercise_files_to_archive_bundle(db, exercise_id, bundle_dir)
    payload = exercise_to_export_dict(ex, db)
    if mark_closed:
        payload.setdefault("exercise", {})["status"] = ExerciseStatus.CLOSED.value
    if archive_meta:
        payload["archive"] = archive_meta
    if sync_file_bundle:
        payload["archive_files"] = {
            "bundle_dir": f"{path.stem}_files",
            "entries": file_entries,
            "file_count": len(file_entries),
        }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def _safe_unlink_under(root: Path, relpath: str) -> None:
    if not relpath or not isinstance(relpath, str):
        return
    rel = relpath.replace("\\", "/").lstrip("/")
    if ".." in rel.split("/"):
        return
    target = (root / rel).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return
    if target.is_file():
        try:
            target.unlink()
        except OSError:
            pass


def _collect_exercise_file_relpaths(db: Session, exercise_id: int) -> set[str]:
    rels: set[str] = set()
    for row in db.query(DilemmaItem.pdf_relpath).filter(DilemmaItem.exercise_id == exercise_id):
        if row[0]:
            rels.add(row[0])
    for row in db.query(EvaluationListPdfItem.pdf_relpath).filter(
        EvaluationListPdfItem.exercise_id == exercise_id
    ):
        if row[0]:
            rels.add(row[0])
    bundles = (
        db.query(ExercisePlannerFlowBundle)
        .options(
            joinedload(ExercisePlannerFlowBundle.event_flow_items),
            joinedload(ExercisePlannerFlowBundle.action_eval_slots),
        )
        .filter(ExercisePlannerFlowBundle.exercise_id == exercise_id)
        .all()
    )
    for b in bundles:
        if b.event_flow_file_relpath:
            rels.add(b.event_flow_file_relpath)
        for ef in b.event_flow_items or []:
            if ef.file_relpath:
                rels.add(ef.file_relpath)
        for ae in b.action_eval_slots or []:
            if ae.file_relpath:
                rels.add(ae.file_relpath)
    for row in db.query(ChatMessage.file_relpath).join(ChatRoom).filter(
        ChatRoom.exercise_id == exercise_id, ChatMessage.file_relpath != ""
    ):
        if row[0]:
            rels.add(row[0])
    for row in db.query(VisualDocument.file_relpath).filter(
        VisualDocument.exercise_id == exercise_id
    ):
        if row[0]:
            rels.add(row[0])
    for row in db.query(EvaluationCriterionMedia.file_relpath).filter(
        EvaluationCriterionMedia.exercise_id == exercise_id
    ):
        if row[0]:
            rels.add(row[0])
    for row in db.query(ExerciseNotification.related_file).filter(
        ExerciseNotification.exercise_id == exercise_id
    ):
        if row[0]:
            rels.add(row[0])
    return rels


def _remove_exercise_upload_files(db: Session, exercise_id: int) -> None:
    rels = _collect_exercise_file_relpaths(db, exercise_id)
    for rel in rels:
        _safe_unlink_under(DILEMMA_PDF_DIR, rel)
        _safe_unlink_under(EVALUATION_LIST_XLSX_DIR, rel)
        _safe_unlink_under(PLANNER_FLOW_BUNDLE_DIR, rel)
        _safe_unlink_under(CHAT_UPLOAD_DIR, rel)
        _safe_unlink_under(VISUAL_DOC_DIR, rel)
        _safe_unlink_under(EVAL_CRITERION_MEDIA_DIR, rel)


def _ensure_sqlite_foreign_keys(db: Session) -> None:
    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "sqlite":
        db.execute(text("PRAGMA foreign_keys=ON"))


def _purge_exercise_database_rows(db: Session, exercise_id: int) -> None:
    """حذف كل صفوف بيانات التمرين من القاعدة (دون بنك المعلومات ولا المستخدمين)."""
    _ensure_sqlite_foreign_keys(db)
    eid = int(exercise_id)
    bundle_ids = list(
        db.scalars(
            select(ExercisePlannerFlowBundle.id).where(
                ExercisePlannerFlowBundle.exercise_id == eid
            )
        )
    )
    db.execute(
        delete(PlannerFlowBundleEvalSavedResult).where(
            PlannerFlowBundleEvalSavedResult.exercise_id == eid
        )
    )
    db.execute(
        delete(EvaluationListSavedResult).where(
            EvaluationListSavedResult.exercise_id == eid
        )
    )
    db.execute(
        delete(EvaluationCriterionMedia).where(
            EvaluationCriterionMedia.exercise_id == eid
        )
    )
    db.execute(
        delete(AnalystFinalEvaluationAllocatedMax).where(
            AnalystFinalEvaluationAllocatedMax.exercise_id == eid
        )
    )
    db.execute(
        delete(AnalystFinalEvaluationPhaseAllocatedMax).where(
            AnalystFinalEvaluationPhaseAllocatedMax.exercise_id == eid
        )
    )
    db.execute(
        delete(AnalystEvaluationCriteriaPhaseItem).where(
            AnalystEvaluationCriteriaPhaseItem.exercise_id == eid
        )
    )
    db.execute(
        delete(AnalystEvaluationCriteriaResult).where(
            AnalystEvaluationCriteriaResult.exercise_id == eid
        )
    )
    db.execute(
        delete(AnalystEvaluationCriteriaUnit).where(
            AnalystEvaluationCriteriaUnit.exercise_id == eid
        )
    )
    db.execute(
        delete(JudgeIncompleteTaskStatus).where(
            JudgeIncompleteTaskStatus.exercise_id == eid
        )
    )
    db.execute(
        delete(JudgeTraineeAssignment).where(
            JudgeTraineeAssignment.exercise_id == eid
        )
    )
    if bundle_ids:
        db.execute(
            delete(ExercisePlannerFlowBundleActionEval).where(
                ExercisePlannerFlowBundleActionEval.bundle_id.in_(bundle_ids)
            )
        )
        db.execute(
            delete(ExercisePlannerFlowBundleEventFlow).where(
                ExercisePlannerFlowBundleEventFlow.bundle_id.in_(bundle_ids)
            )
        )
    db.execute(
        delete(ExercisePlannerFlowBundle).where(
            ExercisePlannerFlowBundle.exercise_id == eid
        )
    )
    db.execute(delete(VisualDocument).where(VisualDocument.exercise_id == eid))
    db.execute(delete(DilemmaItem).where(DilemmaItem.exercise_id == eid))
    db.execute(
        delete(EvaluationListPdfItem).where(EvaluationListPdfItem.exercise_id == eid)
    )
    db.execute(delete(ChatRoom).where(ChatRoom.exercise_id == eid))
    db.execute(
        delete(ExerciseNotification).where(ExerciseNotification.exercise_id == eid)
    )
    db.execute(delete(ExerciseRosterRow).where(ExerciseRosterRow.exercise_id == eid))
    db.execute(
        delete(ExerciseBattleUnitPersonnel).where(
            ExerciseBattleUnitPersonnel.exercise_id == eid
        )
    )
    db.execute(delete(ExerciseObjective).where(ExerciseObjective.exercise_id == eid))
    db.execute(
        delete(ExerciseTimelineItem).where(ExerciseTimelineItem.exercise_id == eid)
    )
    db.execute(delete(ExerciseRefLink).where(ExerciseRefLink.exercise_id == eid))
    db.execute(delete(EventFlow).where(EventFlow.exercise_id == eid))
    db.execute(delete(Problem).where(Problem.exercise_id == eid))
    db.execute(delete(Checklist).where(Checklist.exercise_id == eid))
    db.execute(delete(EvaluationNote).where(EvaluationNote.exercise_id == eid))
    db.execute(delete(Exercise).where(Exercise.id == eid))
    db.flush()


def _remove_exercise_export_artifacts(ex: Exercise) -> None:
    """حذف ملف JSON للتمرين ومجلد الملفات المرفقة بجانبه في exercise_store."""
    directory = export_directory()
    candidates: set[Path] = set()
    candidates.add(_export_path_for_exercise(directory, ex.title, ex.code, ex.id))
    for p in directory.glob("*.json"):
        if p.is_file():
            candidates.add(p)
    for path in candidates:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        ex_blob = data.get("exercise") if isinstance(data, dict) else None
        if not isinstance(ex_blob, dict) or ex_blob.get("id") != ex.id:
            continue
        bundle = archive_bundle_dir_for_json(path)
        try:
            path.unlink()
        except OSError:
            pass
        if bundle.is_dir():
            try:
                shutil.rmtree(bundle)
            except OSError:
                pass


def wipe_exercise_from_system(db: Session, exercise_id: int) -> bool:
    """حذف التمرين وكل بياناته من النظام (دون بنك المعلومات ولا أرشفة)."""
    ex = db.get(Exercise, exercise_id)
    if not ex:
        return False
    _remove_exercise_upload_files(db, exercise_id)
    _remove_exercise_export_artifacts(ex)
    _purge_exercise_database_rows(db, exercise_id)
    return True


def archive_and_clear_current_exercise(
    db: Session, exercise_id: int, *, finished_by_id: int
) -> Path | None:
    """حفظ نسخة أرشيف كاملة (JSON + ملفات) ثم حذف التمرين وكل بياناته (دون بنك المعلومات)."""
    ex = db.get(Exercise, exercise_id)
    if not ex:
        return None
    path = write_exercise_json_file(
        db,
        exercise_id,
        mark_closed=True,
        archive_meta={
            "finished_at": datetime.utcnow().isoformat(),
            "finished_by_id": finished_by_id,
            "reason": "end_exercise",
        },
        sync_file_bundle=True,
    )
    wipe_exercise_from_system(db, exercise_id)
    return path


def list_export_json_files() -> list[tuple[str, float]]:
    """أسماء الملفات (.json) ووقت التعديل."""
    d = export_directory()
    out: list[tuple[str, float]] = []
    for p in sorted(d.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        if p.is_file():
            out.append((p.name, p.stat().st_mtime))
    return out


def read_exercise_id_from_json_path(path: Path) -> int | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    ex = data.get("exercise")
    if isinstance(ex, dict) and ex.get("id") is not None:
        try:
            return int(ex["id"])
        except (TypeError, ValueError):
            return None
    return None


def _iso_to_datetime_local_value(s: Any) -> str | None:
    """تحويل قيمة ISO من JSON إلى صيغة input datetime-local."""
    if s is None or s == "":
        return None
    if not isinstance(s, str):
        return None
    t = s.strip().replace(" ", "T")
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    if not t:
        return None
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M")


def extract_create_form_prefill_from_export_json(
    data: dict[str, Any],
) -> tuple[dict[str, str | None], list[str]]:
    """
    يقرأ نفس مخطط تصدير التمرين ويُرجع قيماً تطابق قوائم نموذج الإنشاء (أو None).
    المفتاح الثاني: تحذيرات عربية للقيم غير المعتمدة في القوائم الثابتة.
    """
    warnings: list[str] = []

    def _pick(val: Any, allowed: list[str], label_ar: str) -> str | None:
        if val is None:
            return None
        s = str(val).strip()
        if not s:
            return None
        if s in allowed:
            return s
        snippet = s if len(s) <= 100 else s[:97] + "…"
        warnings.append(f"قيمة غير معتمدة في القائمة ({label_ar})، وتُركت: {snippet}")
        return None

    def _text(val: Any, max_len: int) -> str | None:
        if val is None:
            return None
        s = str(val).strip()
        if not s:
            return None
        return s[:max_len]

    if not isinstance(data, dict):
        return {}, ["ملف JSON غير صالح (الجذر ليس كائناً)."]
    ex = data.get("exercise")
    if not isinstance(ex, dict):
        return {}, ["الملف لا يحتوي على كائن «exercise» كما في ملفات التصدير."]

    fields: dict[str, str | None] = {
        "exercise_name": _text(ex.get("title"), 500),
        "exercise_type": _pick(ex.get("exercise_type"), ex_opts.EXERCISE_TYPES, "نوع التمرين"),
        "exercise_level": _pick(ex.get("exercise_level"), ex_opts.EXERCISE_LEVELS, "مستوى التمرين"),
        "mission": _pick(ex.get("mission_label"), ex_opts.MISSIONS, "المهمة"),
        "trained_unit": _text(ex.get("trained_unit"), 400),
        "location_label": _text(ex.get("location_label"), 400),
        "planned_start": _iso_to_datetime_local_value(ex.get("planned_start")),
        "planned_end": _iso_to_datetime_local_value(ex.get("planned_end")),
    }
    return fields, warnings


def read_exercise_id_from_json_bytes(raw: bytes) -> int | None:
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    ex = data.get("exercise")
    if isinstance(ex, dict) and ex.get("id") is not None:
        try:
            return int(ex["id"])
        except (TypeError, ValueError):
            return None
    return None


def open_export_directory_in_os() -> tuple[bool, str]:
    """يفتح مجلد التصدير في مدير الملفات على الجهاز الذي يشغّل تطبيق Flask (محلياً = جهازك)."""
    d = export_directory()
    d.mkdir(parents=True, exist_ok=True)
    path = str(d.resolve())
    try:
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path], close_fds=True)
        else:
            subprocess.Popen(["xdg-open", path], close_fds=True)
        return True, ""
    except OSError as e:
        return False, str(e)


def _reset_upload_directory(root: Path) -> None:
    """إفراغ مجلد رفع ملفات التمرين وإعادة إنشائه."""
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)


def purge_exercise_export_archives() -> None:
    """حذف ملفات JSON وأرشيفات _files في مجلد تصدير التمارين (نموذج إنشاء/فتح تمرين)."""
    d = export_directory()
    d.mkdir(parents=True, exist_ok=True)
    for p in list(d.iterdir()):
        if p.is_file() and p.suffix.lower() == ".json":
            try:
                p.unlink()
            except OSError:
                pass
        elif p.is_dir() and p.name.endswith("_files"):
            shutil.rmtree(p, ignore_errors=True)


def purge_all_exercises_and_dilemmas(db: Session) -> None:
    """حذف جميع التمارين وملفاتها وملفات التصدير (دون commit). يبقى بنك المعلومات والمستخدمون."""
    exercise_ids = [int(row[0]) for row in db.query(Exercise.id).all()]
    for eid in exercise_ids:
        wipe_exercise_from_system(db, eid)
    for root in FILE_BUCKET_ROOTS.values():
        _reset_upload_directory(root)
    purge_exercise_export_archives()


def clear_app_unit_level_data(db: Session) -> dict[str, int]:
    """تفريغ مستوى الوحدة في التطبيق (قوائم منسدلة ومخزون) دون المساس ببنك المعلومات."""
    stats: dict[str, int] = {}

    stats["analyst_criteria_phase_items"] = (
        db.query(AnalystEvaluationCriteriaPhaseItem).delete(synchronize_session=False)
    )
    stats["analyst_criteria_units"] = (
        db.query(AnalystEvaluationCriteriaUnit).delete(synchronize_session=False)
    )
    stats["analyst_criteria_results"] = (
        db.query(AnalystEvaluationCriteriaResult).delete(synchronize_session=False)
    )
    stats["analyst_final_phase_max"] = (
        db.query(AnalystFinalEvaluationPhaseAllocatedMax).delete(synchronize_session=False)
    )
    stats["analyst_final_alloc_max"] = (
        db.query(AnalystFinalEvaluationAllocatedMax).delete(synchronize_session=False)
    )

    stats["planner_bundle_eval_saved"] = (
        db.query(PlannerFlowBundleEvalSavedResult).delete(synchronize_session=False)
    )
    stats["planner_bundle_action_evals"] = (
        db.query(ExercisePlannerFlowBundleActionEval).delete(synchronize_session=False)
    )
    stats["planner_bundle_event_flows"] = (
        db.query(ExercisePlannerFlowBundleEventFlow).delete(synchronize_session=False)
    )
    stats["planner_flow_bundles"] = (
        db.query(ExercisePlannerFlowBundle).delete(synchronize_session=False)
    )

    stats["judge_incomplete_tasks"] = (
        db.query(JudgeIncompleteTaskStatus).delete(synchronize_session=False)
    )
    stats["judge_trainee_assignments"] = db.query(JudgeTraineeAssignment).update(
        {JudgeTraineeAssignment.unit_level_key: ""},
        synchronize_session=False,
    )
    stats["evaluation_saved_results"] = db.query(EvaluationListSavedResult).update(
        {EvaluationListSavedResult.unit_level_key: ""},
        synchronize_session=False,
    )
    stats["evaluation_criterion_media"] = db.query(EvaluationCriterionMedia).update(
        {EvaluationCriterionMedia.unit_level_key: ""},
        synchronize_session=False,
    )
    stats["visual_documents"] = db.query(VisualDocument).update(
        {VisualDocument.unit_level_key: ""},
        synchronize_session=False,
    )
    stats["chat_rooms"] = db.query(ChatRoom).update(
        {ChatRoom.unit_level_key: ""},
        synchronize_session=False,
    )
    stats["exercise_roster_rows"] = db.query(ExerciseRosterRow).update(
        {
            ExerciseRosterRow.unit_level_key: "",
            ExerciseRosterRow.position_ar: "",
        },
        synchronize_session=False,
    )
    stats["dilemma_items"] = db.query(DilemmaItem).update(
        {
            DilemmaItem.unit_level_key: "",
            DilemmaItem.unit_level_label: "",
        },
        synchronize_session=False,
    )
    stats["evaluation_list_items"] = db.query(EvaluationListPdfItem).update(
        {
            EvaluationListPdfItem.unit_level_key: "",
            EvaluationListPdfItem.unit_level_label: "",
        },
        synchronize_session=False,
    )

    db.commit()
    return stats


def clear_app_exercise_phase_data(db: Session) -> dict[str, int]:
    """تفريغ مراحل التمرين في التطبيق (قوائم منسدلة ومخزون) دون المساس ببنك المعلومات."""
    stats: dict[str, int] = {}

    stats["analyst_criteria_phase_items"] = (
        db.query(AnalystEvaluationCriteriaPhaseItem).delete(synchronize_session=False)
    )
    stats["analyst_final_phase_max"] = (
        db.query(AnalystFinalEvaluationPhaseAllocatedMax).delete(synchronize_session=False)
    )
    stats["planner_bundle_eval_saved"] = (
        db.query(PlannerFlowBundleEvalSavedResult).delete(synchronize_session=False)
    )
    stats["planner_bundle_action_evals"] = (
        db.query(ExercisePlannerFlowBundleActionEval).delete(synchronize_session=False)
    )
    stats["planner_bundle_event_flows"] = (
        db.query(ExercisePlannerFlowBundleEventFlow).delete(synchronize_session=False)
    )
    stats["planner_flow_bundles"] = (
        db.query(ExercisePlannerFlowBundle).delete(synchronize_session=False)
    )
    stats["judge_incomplete_tasks"] = (
        db.query(JudgeIncompleteTaskStatus).delete(synchronize_session=False)
    )
    stats["evaluation_saved_results"] = db.query(EvaluationListSavedResult).update(
        {EvaluationListSavedResult.exercise_phase: ""},
        synchronize_session=False,
    )
    stats["dilemma_items"] = db.query(DilemmaItem).update(
        {DilemmaItem.exercise_phase: ""},
        synchronize_session=False,
    )
    stats["evaluation_list_items"] = db.query(EvaluationListPdfItem).update(
        {EvaluationListPdfItem.exercise_phase: ""},
        synchronize_session=False,
    )

    db.commit()
    return stats


def _parse_dt(val: Any) -> datetime | None:
    if val is None or val == "":
        return None
    if isinstance(val, datetime):
        return val
    if not isinstance(val, str):
        return None
    s = val.strip().replace(" ", "T")
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _uid_or(db: Session, uid: Any, fallback: int) -> int:
    try:
        i = int(uid)
    except (TypeError, ValueError):
        return fallback
    return i if db.get(User, i) is not None else fallback


def _import_saved_eval_row(
    db: Session,
    ex: Exercise,
    row: dict[str, Any],
    *,
    evaluation_item_id: int | None,
    bundle_action_eval_id: int | None,
) -> None:
    if evaluation_item_id is None and bundle_action_eval_id is None:
        return
    try:
        total_pct = float(row["total_pct"]) if row.get("total_pct") is not None else None
    except (TypeError, ValueError):
        total_pct = None
    phase = normalize_exercise_phase(str(row.get("exercise_phase") or ""))
    common = dict(
        exercise_id=ex.id,
        exercise_phase=phase,
        unit_level_key=str(row.get("unit_level_key") or "")[:64],
        payload_json=str(row.get("payload_json") or ""),
        total_pct=total_pct,
        grade_label=str(row.get("grade_label") or "")[:64],
        saved_by_id=_uid_or(db, row.get("saved_by_id"), ex.owner_id),
        is_approved=bool(row.get("is_approved")),
        approved_by_id=_uid_or(db, row.get("approved_by_id"), ex.owner_id)
        if row.get("approved_by_id")
        else None,
        approved_at=_parse_dt(row.get("approved_at")),
        reopened_for_judge=bool(row.get("reopened_for_judge")),
        is_chief_approved=bool(row.get("is_chief_approved")),
        chief_approved_by_id=_uid_or(db, row.get("chief_approved_by_id"), ex.owner_id)
        if row.get("chief_approved_by_id")
        else None,
        chief_approved_at=_parse_dt(row.get("chief_approved_at")),
        is_control_approved=bool(row.get("is_control_approved")),
        control_approved_by_id=_uid_or(db, row.get("control_approved_by_id"), ex.owner_id)
        if row.get("control_approved_by_id")
        else None,
        control_approved_at=_parse_dt(row.get("control_approved_at")),
        created_at=_parse_dt(row.get("created_at")) or datetime.utcnow(),
        updated_at=_parse_dt(row.get("updated_at")) or datetime.utcnow(),
    )
    if bundle_action_eval_id is not None:
        db.add(
            PlannerFlowBundleEvalSavedResult(
                bundle_action_eval_id=bundle_action_eval_id,
                **common,
            )
        )
    elif evaluation_item_id is not None:
        db.add(
            EvaluationListSavedResult(
                evaluation_item_id=evaluation_item_id,
                **common,
            )
        )


def _import_v3_exercise_bundle(
    db: Session,
    ex: Exercise,
    data: dict[str, Any],
    owner_id: int,
    *,
    eval_item_old_to_new: dict[int, int],
    dilemma_old_to_new: dict[int, int],
    timeline_old_to_new: dict[int, int],
) -> None:
    """استيراد أقسام مخطط التصدير 3 (نتائج، حزم مجرى، محادثات، …)."""
    personnel = data.get("battle_unit_personnel") or []
    if isinstance(personnel, list):
        for row in personnel:
            if not isinstance(row, dict):
                continue
            uid = str(row.get("unit_id") or "").strip()[:64]
            if not uid:
                continue
            db.add(
                ExerciseBattleUnitPersonnel(
                    exercise_id=ex.id,
                    unit_id=uid,
                    trainee_name=str(row.get("trainee_name") or "")[:256],
                    trainee_military_number=str(row.get("trainee_military_number") or "")[:128],
                    rank_ar=str(row.get("rank_ar") or "")[:256],
                    position_ar=str(row.get("position_ar") or "")[:512],
                    judge_trainee_name=str(row.get("judge_trainee_name") or "")[:256],
                    judge_military_number=str(row.get("judge_military_number") or "")[:128],
                    judge_rank_ar=str(row.get("judge_rank_ar") or "")[:256],
                    judge_position_ar=str(row.get("judge_position_ar") or "")[:512],
                    updated_at=_parse_dt(row.get("updated_at")) or datetime.utcnow(),
                )
            )

    bundle_old_to_new: dict[int, int] = {}
    event_flow_old_to_new: dict[int, int] = {}
    action_old_to_new: dict[int, int] = {}
    bundles = data.get("planner_flow_bundles") or []
    if isinstance(bundles, list):
        for row in bundles:
            if not isinstance(row, dict):
                continue
            try:
                old_bid = int(row.get("id")) if row.get("id") is not None else 0
            except (TypeError, ValueError):
                old_bid = 0
            b = ExercisePlannerFlowBundle(
                exercise_id=ex.id,
                exercise_phase=normalize_exercise_phase(str(row.get("exercise_phase") or "")),
                unit_level_key=str(row.get("unit_level_key") or "")[:64],
                unit_level_label=str(row.get("unit_level_label") or "")[:200],
                event_flow_title=str(row.get("event_flow_title") or "")[:500],
                event_flow_file_relpath=str(row.get("event_flow_file_relpath") or "")[:500],
                dilemma_count=int(row.get("dilemma_count") or 0),
                linked_at=_parse_dt(row.get("linked_at")),
                flow_table_json=str(row.get("flow_table_json") or ""),
                created_at=_parse_dt(row.get("created_at")) or datetime.utcnow(),
                updated_at=_parse_dt(row.get("updated_at")) or datetime.utcnow(),
            )
            db.add(b)
            db.flush()
            if old_bid:
                bundle_old_to_new[old_bid] = b.id
            for ef in row.get("event_flow_items") or []:
                if not isinstance(ef, dict):
                    continue
                try:
                    old_ef = int(ef.get("id")) if ef.get("id") is not None else 0
                except (TypeError, ValueError):
                    old_ef = 0
                try:
                    slot_i = int(ef.get("slot_index") or 0)
                except (TypeError, ValueError):
                    slot_i = 0
                ef_row = ExercisePlannerFlowBundleEventFlow(
                    bundle_id=b.id,
                    slot_index=slot_i,
                    title=str(ef.get("title") or "")[:500],
                    file_relpath=str(ef.get("file_relpath") or "")[:500],
                    created_at=_parse_dt(ef.get("created_at")) or datetime.utcnow(),
                )
                db.add(ef_row)
                db.flush()
                if old_ef:
                    event_flow_old_to_new[old_ef] = ef_row.id
            for ae in row.get("action_eval_slots") or []:
                if not isinstance(ae, dict):
                    continue
                try:
                    old_ae = int(ae.get("id")) if ae.get("id") is not None else 0
                except (TypeError, ValueError):
                    old_ae = 0
                try:
                    slot_i = int(ae.get("slot_index") or 0)
                except (TypeError, ValueError):
                    slot_i = 0
                try:
                    old_ef_ref = int(ae.get("event_flow_item_id")) if ae.get("event_flow_item_id") else 0
                except (TypeError, ValueError):
                    old_ef_ref = 0
                new_ef_ref = event_flow_old_to_new.get(old_ef_ref) if old_ef_ref else None
                ae_row = ExercisePlannerFlowBundleActionEval(
                    bundle_id=b.id,
                    slot_index=slot_i,
                    event_flow_item_id=new_ef_ref,
                    title=str(ae.get("title") or "")[:500],
                    file_relpath=str(ae.get("file_relpath") or "")[:500],
                    created_at=_parse_dt(ae.get("created_at")) or datetime.utcnow(),
                )
                db.add(ae_row)
                db.flush()
                if old_ae:
                    action_old_to_new[old_ae] = ae_row.id
                es = ae.get("eval_saved")
                if isinstance(es, dict):
                    _import_saved_eval_row(
                        db,
                        ex,
                        es,
                        evaluation_item_id=None,
                        bundle_action_eval_id=ae_row.id,
                    )

    saved_list = data.get("evaluation_list_saved_results") or []
    if isinstance(saved_list, list):
        for row in saved_list:
            if not isinstance(row, dict):
                continue
            try:
                old_eid = int(row.get("evaluation_item_id")) if row.get("evaluation_item_id") else 0
            except (TypeError, ValueError):
                old_eid = 0
            new_eid = eval_item_old_to_new.get(old_eid)
            if not new_eid:
                continue
            _import_saved_eval_row(
                db,
                ex,
                row,
                evaluation_item_id=new_eid,
                bundle_action_eval_id=None,
            )

    assignments = data.get("judge_trainee_assignments") or []
    if isinstance(assignments, list):
        for row in assignments:
            if not isinstance(row, dict):
                continue
            try:
                old_pb = int(row.get("planner_flow_bundle_id")) if row.get("planner_flow_bundle_id") else 0
            except (TypeError, ValueError):
                old_pb = 0
            db.add(
                JudgeTraineeAssignment(
                    exercise_id=ex.id,
                    judge_user_id=_uid_or(db, row.get("judge_user_id"), owner_id),
                    unit_level_key=str(row.get("unit_level_key") or "")[:64],
                    trainee_name=str(row.get("trainee_name") or "")[:256],
                    trainee_military_number=str(row.get("trainee_military_number") or "")[:128],
                    planner_flow_bundle_id=bundle_old_to_new.get(old_pb) if old_pb else None,
                    created_at=_parse_dt(row.get("created_at")) or datetime.utcnow(),
                )
            )

    unit_old_to_new: dict[int, int] = {}
    analyst_units = data.get("analyst_evaluation_criteria_units") or []
    if isinstance(analyst_units, list):
        for row in analyst_units:
            if not isinstance(row, dict):
                continue
            try:
                old_uid = int(row.get("id")) if row.get("id") is not None else 0
            except (TypeError, ValueError):
                old_uid = 0
            try:
                so = int(row.get("sort_order") or 0)
            except (TypeError, ValueError):
                so = 0
            u = AnalystEvaluationCriteriaUnit(
                exercise_id=ex.id,
                sort_order=so,
                label=str(row.get("label") or "")[:300],
                created_at=_parse_dt(row.get("created_at")) or datetime.utcnow(),
                updated_at=_parse_dt(row.get("updated_at")) or datetime.utcnow(),
            )
            db.add(u)
            db.flush()
            if old_uid:
                unit_old_to_new[old_uid] = u.id

    phase_items = data.get("analyst_evaluation_criteria_phase_items") or []
    if isinstance(phase_items, list):
        for row in phase_items:
            if not isinstance(row, dict):
                continue
            try:
                old_cuid = int(row.get("criteria_unit_id")) if row.get("criteria_unit_id") else 0
            except (TypeError, ValueError):
                old_cuid = 0
            new_cuid = unit_old_to_new.get(old_cuid)
            if not new_cuid:
                continue
            try:
                so = int(row.get("sort_order") or 0)
            except (TypeError, ValueError):
                so = 0
            try:
                mark = float(row["allocated_mark"]) if row.get("allocated_mark") is not None else None
            except (TypeError, ValueError):
                mark = None
            db.add(
                AnalystEvaluationCriteriaPhaseItem(
                    exercise_id=ex.id,
                    criteria_unit_id=new_cuid,
                    phase_key=str(row.get("phase_key") or "")[:32],
                    sort_order=so,
                    criteria_text=str(row.get("criteria_text") or "")[:1000],
                    allocated_mark=mark,
                    created_at=_parse_dt(row.get("created_at")) or datetime.utcnow(),
                    updated_at=_parse_dt(row.get("updated_at")) or datetime.utcnow(),
                )
            )

    analyst_results = data.get("analyst_evaluation_criteria_results") or []
    if isinstance(analyst_results, list):
        for row in analyst_results:
            if not isinstance(row, dict):
                continue
            try:
                prep = float(row["preparation_pct"]) if row.get("preparation_pct") is not None else None
            except (TypeError, ValueError):
                prep = None
            try:
                ops = float(row["operations_pct"]) if row.get("operations_pct") is not None else None
            except (TypeError, ValueError):
                ops = None
            db.add(
                AnalystEvaluationCriteriaResult(
                    exercise_id=ex.id,
                    unit_level_key=str(row.get("unit_level_key") or "")[:64],
                    preparation_pct=prep,
                    operations_pct=ops,
                    updated_by_id=_uid_or(db, row.get("updated_by_id"), owner_id)
                    if row.get("updated_by_id")
                    else None,
                    updated_at=_parse_dt(row.get("updated_at")) or datetime.utcnow(),
                )
            )

    tasks = data.get("judge_incomplete_task_status") or []
    if isinstance(tasks, list):
        for row in tasks:
            if not isinstance(row, dict):
                continue
            try:
                pair_i = int(row.get("pair_index") or 0)
            except (TypeError, ValueError):
                pair_i = 0
            try:
                old_did = int(row.get("dilemma_id")) if row.get("dilemma_id") else 0
            except (TypeError, ValueError):
                old_did = 0
            try:
                old_eid = int(row.get("evaluation_item_id")) if row.get("evaluation_item_id") else 0
            except (TypeError, ValueError):
                old_eid = 0
            db.add(
                JudgeIncompleteTaskStatus(
                    exercise_id=ex.id,
                    judge_id=_uid_or(db, row.get("judge_id"), owner_id),
                    unit_level_key=str(row.get("unit_level_key") or "")[:64],
                    exercise_phase=normalize_exercise_phase(str(row.get("exercise_phase") or "")),
                    pair_index=pair_i,
                    dilemma_id=dilemma_old_to_new.get(old_did) if old_did else None,
                    evaluation_item_id=eval_item_old_to_new.get(old_eid) if old_eid else None,
                    status_key=str(row.get("status_key") or "ontime")[:16],
                    updated_at=_parse_dt(row.get("updated_at")) or datetime.utcnow(),
                )
            )

    for row in data.get("evaluation_criterion_media") or []:
        if not isinstance(row, dict):
            continue
        try:
            old_eid = int(row.get("evaluation_list_item_id")) if row.get("evaluation_list_item_id") else 0
        except (TypeError, ValueError):
            old_eid = 0
        try:
            old_ae = int(row.get("bundle_action_eval_id")) if row.get("bundle_action_eval_id") else 0
        except (TypeError, ValueError):
            old_ae = 0
        try:
            ri = int(row.get("row_index") or 0)
        except (TypeError, ValueError):
            ri = 0
        db.add(
            EvaluationCriterionMedia(
                exercise_id=ex.id,
                unit_level_key=str(row.get("unit_level_key") or "")[:64],
                evaluation_list_item_id=eval_item_old_to_new.get(old_eid) if old_eid else None,
                bundle_action_eval_id=action_old_to_new.get(old_ae) if old_ae else None,
                row_index=ri,
                media_kind=str(row.get("media_kind") or "photo")[:16],
                mime_type=str(row.get("mime_type") or "")[:120],
                file_relpath=str(row.get("file_relpath") or "")[:700],
                uploaded_by_id=_uid_or(db, row.get("uploaded_by_id"), owner_id)
                if row.get("uploaded_by_id")
                else None,
                created_at=_parse_dt(row.get("created_at")) or datetime.utcnow(),
            )
        )

    for row in data.get("visual_documents") or []:
        if not isinstance(row, dict):
            continue
        try:
            old_ev = int(row.get("event_id")) if row.get("event_id") else 0
        except (TypeError, ValueError):
            old_ev = 0
        try:
            old_did = int(row.get("dilemma_id")) if row.get("dilemma_id") else 0
        except (TypeError, ValueError):
            old_did = 0
        db.add(
            VisualDocument(
                exercise_id=ex.id,
                event_id=timeline_old_to_new.get(old_ev) if old_ev else None,
                dilemma_id=dilemma_old_to_new.get(old_did) if old_did else None,
                unit_level_key=str(row.get("unit_level_key") or "")[:64],
                uploaded_by_id=_uid_or(db, row.get("uploaded_by_id"), owner_id),
                file_type=str(row.get("file_type") or "image")[:16],
                file_relpath=str(row.get("file_relpath") or "")[:700],
                description=str(row.get("description") or ""),
                location_label=str(row.get("location_label") or "")[:400],
                created_at=_parse_dt(row.get("created_at")) or datetime.utcnow(),
            )
        )

    room_old_to_new: dict[int, int] = {}
    for row in data.get("chat_rooms") or []:
        if not isinstance(row, dict):
            continue
        try:
            old_rid = int(row.get("id")) if row.get("id") is not None else 0
        except (TypeError, ValueError):
            old_rid = 0
        room = ChatRoom(
            exercise_id=ex.id,
            title=str(row.get("title") or "")[:500],
            description=str(row.get("description") or ""),
            room_kind=str(row.get("room_kind") or "custom")[:64],
            unit_level_key=str(row.get("unit_level_key") or "")[:64],
            created_by_id=_uid_or(db, row.get("created_by_id"), owner_id)
            if row.get("created_by_id")
            else None,
            created_at=_parse_dt(row.get("created_at")) or datetime.utcnow(),
            last_activity_at=_parse_dt(row.get("last_activity_at")),
            is_archived=bool(row.get("is_archived")),
        )
        db.add(room)
        db.flush()
        if old_rid:
            room_old_to_new[old_rid] = room.id
        for mem in row.get("members") or []:
            if not isinstance(mem, dict):
                continue
            db.add(
                ChatRoomMember(
                    room_id=room.id,
                    user_id=_uid_or(db, mem.get("user_id"), owner_id),
                    role_in_room=str(mem.get("role_in_room") or "member")[:32],
                    joined_at=_parse_dt(mem.get("joined_at")) or datetime.utcnow(),
                )
            )
        for msg in row.get("messages") or []:
            if not isinstance(msg, dict):
                continue
            try:
                fsize = int(msg.get("file_size") or 0)
            except (TypeError, ValueError):
                fsize = 0
            db.add(
                ChatMessage(
                    room_id=room.id,
                    sender_id=_uid_or(db, msg.get("sender_id"), owner_id),
                    message_type=str(msg.get("message_type") or "text")[:32],
                    body_text=str(msg.get("body_text") or ""),
                    file_relpath=str(msg.get("file_relpath") or "")[:600],
                    original_filename=str(msg.get("original_filename") or "")[:500],
                    mime_type=str(msg.get("mime_type") or "")[:200],
                    file_size=fsize,
                    created_at=_parse_dt(msg.get("created_at")) or datetime.utcnow(),
                )
            )

    for row in data.get("exercise_notifications") or []:
        if not isinstance(row, dict):
            continue
        try:
            old_rr = int(row.get("related_room_id")) if row.get("related_room_id") else 0
        except (TypeError, ValueError):
            old_rr = 0
        db.add(
            ExerciseNotification(
                exercise_id=ex.id,
                user_id=_uid_or(db, row.get("user_id"), owner_id),
                type=str(row.get("type") or "system")[:32],
                title=str(row.get("title") or "")[:500],
                body=str(row.get("body") or ""),
                priority=str(row.get("priority") or "normal")[:32],
                is_read=bool(row.get("is_read")),
                related_file=str(row.get("related_file") or "")[:600],
                related_room_id=room_old_to_new.get(old_rr) if old_rr else None,
                action_url=str(row.get("action_url") or "")[:500],
                created_at=_parse_dt(row.get("created_at")) or datetime.utcnow(),
            )
        )


def import_exercise_bundle_from_dict(db: Session, data: dict[str, Any], owner_id: int) -> int | None:
    """
    يستورد تمريناً كاملاً من قاموس JSON بنفس مخطط التصدير (نسخة 1 أو 2).
    يُفترض أن قاعدة البيانات خالية من التمارين مسبقاً.
    """
    if not isinstance(data, dict):
        return None
    exj = data.get("exercise")
    if not isinstance(exj, dict):
        return None

    code = str(exj.get("code") or "").strip() or f"EX-{uuid.uuid4().hex[:8].upper()}"
    if db.query(Exercise).filter(Exercise.code == code).first():
        code = f"EX-{uuid.uuid4().hex[:8].upper()}"

    title = str(exj.get("title") or "").strip() or "تمرين"
    status = str(exj.get("status") or ExerciseStatus.DRAFT.value)[:32]
    ex = Exercise(
        code=code,
        title=title,
        description=str(exj.get("description") or ""),
        exercise_type=str(exj.get("exercise_type") or "")[:200],
        exercise_level=str(exj.get("exercise_level") or "")[:200],
        mission_label=str(exj.get("mission_label") or "")[:400],
        trained_unit=str(exj.get("trained_unit") or "")[:400],
        location_label=str(exj.get("location_label") or "")[:400],
        status=status,
        owner_id=owner_id,
        planned_start=_parse_dt(exj.get("planned_start")),
        planned_end=_parse_dt(exj.get("planned_end")),
        control_approved=bool(exj.get("control_approved")),
        created_at=_parse_dt(exj.get("created_at")) or datetime.utcnow(),
        updated_at=_parse_dt(exj.get("updated_at")) or datetime.utcnow(),
    )
    db.add(ex)
    db.flush()

    objectives = data.get("objectives") or []
    if isinstance(objectives, list):
        for i, row in enumerate(objectives):
            if not isinstance(row, dict):
                continue
            txt = str(row.get("text") or "").strip()[:2000]
            if not txt:
                continue
            so = row.get("sort_order")
            try:
                sort_order = int(so) if so is not None else i
            except (TypeError, ValueError):
                sort_order = i
            db.add(
                ExerciseObjective(
                    exercise_id=ex.id,
                    sort_order=sort_order,
                    text=txt,
                    created_at=_parse_dt(row.get("created_at")) or datetime.utcnow(),
                )
            )

    def _import_roster_block(key: str, kind: str) -> None:
        block = data.get(key) or []
        if not isinstance(block, list):
            return
        for i, row in enumerate(block):
            if not isinstance(row, dict):
                continue
            mil = str(row.get("military_number") or "").strip()[:128]
            rk = str(row.get("rank_ar") or "").strip()[:256]
            nm = str(row.get("full_name") or "").strip()[:256]
            pos = str(row.get("position_ar") or "").strip()[:512]
            uk = normalize_unit_level_key(str(row.get("unit_level_key") or "").strip())
            if not uk:
                uk = normalize_unit_level_key(pos)
            if uk and not pos:
                pos = label_for_unit_level_key(uk)
            if not (mil or rk or nm or uk or pos):
                continue
            so = row.get("sort_order")
            try:
                sort_order = int(so) if so is not None else i
            except (TypeError, ValueError):
                sort_order = i
            db.add(
                ExerciseRosterRow(
                    exercise_id=ex.id,
                    roster_kind=kind,
                    sort_order=sort_order,
                    military_number=mil,
                    rank_ar=rk,
                    full_name=nm,
                    unit_level_key=(uk or "")[:64],
                    position_ar=pos,
                    created_at=_parse_dt(row.get("created_at")) or datetime.utcnow(),
                )
            )

    _import_roster_block("trainee_unit_roster", "trainee")
    _import_roster_block("judge_unit_roster", "judge")

    events = data.get("event_flows") or []
    if isinstance(events, list):
        for i, row in enumerate(events):
            if not isinstance(row, dict):
                continue
            et = str(row.get("event_type") or EventFlowType.STAGE.value)[:32]
            db.add(
                EventFlow(
                    exercise_id=ex.id,
                    order_index=int(row.get("order_index") or i),
                    title=str(row.get("title") or "")[:500],
                    description=str(row.get("description") or ""),
                    scheduled_at=_parse_dt(row.get("scheduled_at")),
                    event_type=et,
                    created_at=_parse_dt(row.get("created_at")) or datetime.utcnow(),
                )
            )


    timeline_old_to_new: dict[int, int] = {}
    timeline = data.get("timeline_items") or []
    if isinstance(timeline, list):
        pending_parent: list[tuple[ExerciseTimelineItem, int]] = []
        for i, row in enumerate(timeline):
            if not isinstance(row, dict):
                continue
            try:
                so = int(row.get("sort_order") or i)
            except (TypeError, ValueError):
                so = i
            try:
                old_id = int(row.get("id")) if row.get("id") is not None else 0
            except (TypeError, ValueError):
                old_id = 0
            try:
                old_parent = int(row.get("parent_id")) if row.get("parent_id") is not None else 0
            except (TypeError, ValueError):
                old_parent = 0
            try:
                seq = int(row.get("sequence_no") or 0)
            except (TypeError, ValueError):
                seq = 0
            try:
                child_seq = int(row.get("child_sequence_no") or 0)
            except (TypeError, ValueError):
                child_seq = 0
            kind = str(row.get("row_kind") or "detail")[:32]
            if kind not in ("event", "dilemma", "detail"):
                kind = "detail"
            item = ExerciseTimelineItem(
                exercise_id=ex.id,
                sort_order=so,
                row_kind=kind,
                sequence_no=seq,
                child_sequence_no=child_seq,
                title=str(row.get("title") or "")[:500],
                time_from=str(row.get("time_from") or "")[:64],
                time_to=str(row.get("time_to") or "")[:64],
                reporting_systems=str(row.get("reporting_systems") or "")[:1000],
                description=str(row.get("description") or ""),
                expected_reaction=str(row.get("expected_reaction") or ""),
                training_objective=str(row.get("training_objective") or ""),
                notes=str(row.get("notes") or ""),
                created_at=_parse_dt(row.get("created_at")) or datetime.utcnow(),
                updated_at=_parse_dt(row.get("updated_at")) or datetime.utcnow(),
            )
            db.add(item)
            db.flush()
            if old_id:
                timeline_old_to_new[old_id] = item.id
            if old_parent:
                pending_parent.append((item, old_parent))
        for item, old_parent in pending_parent:
            new_parent = timeline_old_to_new.get(old_parent)
            if new_parent:
                item.parent_id = new_parent

    problems = data.get("problems") or []
    if isinstance(problems, list):
        for row in problems:
            if not isinstance(row, dict):
                continue
            rid = _uid_or(db, row.get("reported_by_id"), owner_id)
            try:
                sev = int(row.get("severity") or 1)
            except (TypeError, ValueError):
                sev = 1
            sev = max(1, min(5, sev))
            st = str(row.get("status") or ProblemStatus.OPEN.value)[:32]
            db.add(
                Problem(
                    exercise_id=ex.id,
                    title=str(row.get("title") or "")[:500],
                    description=str(row.get("description") or ""),
                    severity=sev,
                    status=st,
                    reported_by_id=rid,
                    created_at=_parse_dt(row.get("created_at")) or datetime.utcnow(),
                    updated_at=_parse_dt(row.get("updated_at")) or datetime.utcnow(),
                )
            )

    checklists = data.get("checklists") or []
    if isinstance(checklists, list):
        for cl in checklists:
            if not isinstance(cl, dict):
                continue
            cid = _uid_or(db, cl.get("created_by_id"), owner_id)
            c = Checklist(
                exercise_id=ex.id,
                title=str(cl.get("title") or "")[:500],
                created_by_id=cid,
                created_at=_parse_dt(cl.get("created_at")) or datetime.utcnow(),
            )
            db.add(c)
            db.flush()
            items = cl.get("items") or []
            if isinstance(items, list):
                for j, it in enumerate(items):
                    if not isinstance(it, dict):
                        continue
                    try:
                        w = float(it.get("weight") or 1.0)
                    except (TypeError, ValueError):
                        w = 1.0
                    try:
                        so = int(it.get("sort_order") or j)
                    except (TypeError, ValueError):
                        so = j
                    db.add(
                        ChecklistItem(
                            checklist_id=c.id,
                            sort_order=so,
                            text=str(it.get("text") or "")[:2000],
                            weight=w,
                            is_done=bool(it.get("is_done")),
                            judge_note=str(it.get("judge_note") or "")[:2000],
                        )
                    )

    notes = data.get("evaluation_notes") or []
    if isinstance(notes, list):
        for row in notes:
            if not isinstance(row, dict):
                continue
            uid = _uid_or(db, row.get("user_id"), owner_id)
            db.add(
                EvaluationNote(
                    exercise_id=ex.id,
                    user_id=uid,
                    body=str(row.get("body") or ""),
                    created_at=_parse_dt(row.get("created_at")) or datetime.utcnow(),
                )
            )

    links = data.get("exercise_ref_links") or []
    if isinstance(links, list):
        for row in links:
            if not isinstance(row, dict):
                continue
            try:
                ref_id = int(row.get("reference_id"))
            except (TypeError, ValueError):
                continue
            if db.get(Reference, ref_id) is None:
                continue
            db.add(ExerciseRefLink(exercise_id=ex.id, reference_id=ref_id))

    dilemma_old_to_new: dict[int, int] = {}
    dilemmas = data.get("dilemma_items")
    if isinstance(dilemmas, list) and dilemmas:
        db.execute(delete(DilemmaItem))
        for row in dilemmas:
            if not isinstance(row, dict):
                continue
            uk = str(row.get("unit_level_key") or "").strip()[:64]
            if not uk:
                continue
            try:
                so = int(row.get("sort_order") or 0)
            except (TypeError, ValueError):
                so = 0
            try:
                old_did = int(row.get("id")) if row.get("id") is not None else 0
            except (TypeError, ValueError):
                old_did = 0
            exercise_phase = normalize_exercise_phase(
                str(row.get("exercise_phase") or "").strip()[:32]
            )
            d_row = DilemmaItem(
                exercise_id=ex.id,
                exercise_phase=exercise_phase,
                unit_level_key=uk,
                unit_level_label=str(row.get("unit_level_label") or "")[:200],
                sort_order=so,
                text=str(row.get("text") or "")[:2000],
                pdf_relpath=str(row.get("pdf_relpath") or "")[:500],
                created_at=_parse_dt(row.get("created_at")) or datetime.utcnow(),
            )
            db.add(d_row)
            db.flush()
            if old_did:
                dilemma_old_to_new[old_did] = d_row.id

    eval_item_old_to_new: dict[int, int] = {}
    evaluation_lists = data.get("evaluation_list_items") or data.get("evaluation_lists")
    if isinstance(evaluation_lists, list) and evaluation_lists:
        db.execute(delete(EvaluationListPdfItem).where(EvaluationListPdfItem.exercise_id == ex.id))
        for row in evaluation_lists:
            if not isinstance(row, dict):
                continue
            uk = str(row.get("unit_level_key") or "").strip()[:64]
            if not uk:
                continue
            try:
                so = int(row.get("sort_order") or 0)
            except (TypeError, ValueError):
                so = 0
            try:
                old_eid = int(row.get("id")) if row.get("id") is not None else 0
            except (TypeError, ValueError):
                old_eid = 0
            exercise_phase = normalize_exercise_phase(
                str(row.get("exercise_phase") or "").strip()[:32]
            )
            e_row = EvaluationListPdfItem(
                exercise_id=ex.id,
                exercise_phase=exercise_phase,
                unit_level_key=uk,
                unit_level_label=str(row.get("unit_level_label") or "")[:200],
                sort_order=so,
                text=str(row.get("text") or "")[:2000],
                pdf_relpath=str(row.get("pdf_relpath") or "")[:500],
                created_at=_parse_dt(row.get("created_at")) or datetime.utcnow(),
            )
            db.add(e_row)
            db.flush()
            if old_eid:
                eval_item_old_to_new[old_eid] = e_row.id

    _import_v3_exercise_bundle(
        db,
        ex,
        data,
        owner_id,
        eval_item_old_to_new=eval_item_old_to_new,
        dilemma_old_to_new=dilemma_old_to_new,
        timeline_old_to_new=timeline_old_to_new,
    )

    bundle_dir = resolve_archive_bundle_dir_for_import(data)
    if bundle_dir is not None:
        restore_exercise_files_from_archive(bundle_dir, data)

    db.flush()
    db.refresh(ex)
    write_exercise_json_file(db, ex.id)
    return ex.id
