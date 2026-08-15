# -*- coding: utf-8 -*-
"""إيجابيات/سلبيات المحكم — إدخال بشري معزول بالمستخدم والوحدة."""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models import JudgePolarityNote, User
from app.models.domain import (
    EvaluationListPdfItem,
    ExercisePlannerFlowBundleActionEval,
)


def _serialize_note(row: JudgePolarityNote) -> dict:
    return {
        "id": int(row.id),
        "client_uuid": (row.client_uuid or "").strip(),
        "exercise_id": int(row.exercise_id),
        "judge_user_id": int(row.judge_user_id),
        "unit_level_key": (row.unit_level_key or "").strip(),
        "judge_label": (row.judge_label or "").strip(),
        "polarity": (row.polarity or "positive").strip(),
        "body": (row.body or "").strip(),
        "source_kind": (row.source_kind or "general").strip(),
        "evaluation_list_item_id": row.evaluation_list_item_id,
        "bundle_action_eval_id": row.bundle_action_eval_id,
        "row_index": row.row_index,
        "criterion_label": (row.criterion_label or "").strip(),
        "created_at": row.created_at.isoformat() + "Z" if row.created_at else "",
        "updated_at": row.updated_at.isoformat() + "Z" if row.updated_at else "",
    }


def list_notes_for_judge(db: Session, user: User, exercise_id: int) -> list[dict]:
    rows = (
        db.query(JudgePolarityNote)
        .filter(
            JudgePolarityNote.exercise_id == int(exercise_id),
            JudgePolarityNote.judge_user_id == int(user.id),
        )
        .order_by(JudgePolarityNote.updated_at.desc(), JudgePolarityNote.id.desc())
        .all()
    )
    return [_serialize_note(r) for r in rows]


def list_general_notes_for_scope(
    db: Session,
    user: User | None,
    *,
    exercise_id: int,
    unit_level_key: str,
    polarity: str,
) -> list[dict]:
    """قائمة عامة مشتركة على مستوى التمرين+الوحدة (نفس العرض لإدارة النظام والمحكم)."""
    uk = (unit_level_key or "").strip()
    pol = (polarity or "positive").strip().lower()
    if pol not in ("positive", "negative"):
        pol = "positive"
    rows = (
        db.query(JudgePolarityNote)
        .filter(
            JudgePolarityNote.exercise_id == int(exercise_id),
            JudgePolarityNote.unit_level_key == uk,
            JudgePolarityNote.polarity == pol,
            JudgePolarityNote.source_kind == "general",
        )
        .order_by(JudgePolarityNote.id.asc())
        .all()
    )
    return [_serialize_note(r) for r in rows]


def list_general_notes_grouped_by_unit(
    db: Session,
    *,
    exercise_id: int,
    unit_order: dict[str, int] | None = None,
) -> list[dict]:
    """تجميع الإيجابيات/السلبيات العامة لكل مستوى وحدة — للعرض في السيطرة والمحللين."""
    rows = (
        db.query(JudgePolarityNote)
        .filter(
            JudgePolarityNote.exercise_id == int(exercise_id),
            JudgePolarityNote.source_kind == "general",
        )
        .order_by(JudgePolarityNote.unit_level_key.asc(), JudgePolarityNote.id.asc())
        .all()
    )
    by_unit: dict[str, dict] = {}
    for row in rows:
        uk = (row.unit_level_key or "").strip()
        if uk not in by_unit:
            by_unit[uk] = {
                "unit_key": uk,
                "positives": [],
                "negatives": [],
            }
        entry = {
            "id": int(row.id),
            "body": (row.body or "").strip(),
            "judge_label": (row.judge_label or "").strip(),
            "updated_at": row.updated_at.isoformat() + "Z" if row.updated_at else "",
        }
        if not entry["body"]:
            continue
        if (row.polarity or "").strip().lower() == "negative":
            by_unit[uk]["negatives"].append(entry)
        else:
            by_unit[uk]["positives"].append(entry)

    order = unit_order or {}
    units = list(by_unit.values())
    units.sort(
        key=lambda u: (
            order.get((u.get("unit_key") or "").strip(), len(order) + 1),
            u.get("unit_key") or "",
        )
    )
    return units


def replace_general_notes_for_scope(
    db: Session,
    user: User,
    *,
    exercise_id: int,
    unit_level_key: str,
    polarity: str,
    bodies: list[str],
    judge_label: str,
) -> tuple[dict, int]:
    """استبدال القائمة العامة للتمرين+الوحدة+النوع — مشتركة بين كل المستخدمين."""
    pol = (polarity or "positive").strip().lower()
    if pol in ("positive", "pos", "إيجابي", "ايجابي"):
        pol = "positive"
    elif pol in ("negative", "neg", "سلبي"):
        pol = "negative"
    else:
        return {"ok": False, "error": "polarity"}, 400

    uk = (unit_level_key or "").strip()[:64]
    if not uk:
        return {"ok": False, "error": "unit_required"}, 400

    cleaned: list[str] = []
    for raw in bodies:
        t = (raw or "").strip()
        if t:
            cleaned.append(t[:4000])

    existing = (
        db.query(JudgePolarityNote)
        .filter(
            JudgePolarityNote.exercise_id == int(exercise_id),
            JudgePolarityNote.unit_level_key == uk,
            JudgePolarityNote.polarity == pol,
            JudgePolarityNote.source_kind == "general",
        )
        .all()
    )
    for row in existing:
        db.delete(row)
    db.flush()

    label = (judge_label or "")[:200]
    notes_out: list[dict] = []
    for i, body in enumerate(cleaned):
        row = JudgePolarityNote(
            client_uuid=f"web-{uuid4().hex}"[:120],
            exercise_id=int(exercise_id),
            judge_user_id=int(user.id),
            unit_level_key=uk,
            judge_label=label,
            polarity=pol,
            body=body,
            source_kind="general",
            row_index=i,
            criterion_label="",
        )
        db.add(row)
        db.flush()
        notes_out.append(_serialize_note(row))

    return {"ok": True, "notes": notes_out, "count": len(notes_out)}, 200


def upsert_note(
    db: Session,
    user: User,
    *,
    exercise_id: int,
    unit_level_key: str,
    judge_label: str,
    data: dict,
) -> tuple[dict, int]:
    polarity = (data.get("polarity") or "positive").strip().lower()
    if polarity in ("positive", "pos", "إيجابي", "ايجابي"):
        polarity = "positive"
    elif polarity in ("negative", "neg", "سلبي"):
        polarity = "negative"
    else:
        return {"ok": False, "error": "polarity"}, 400

    body = (data.get("body") or "").strip()
    if not body:
        return {"ok": False, "error": "body_required"}, 400

    client_uuid = (data.get("client_uuid") or data.get("client_op_id") or "").strip()[:120]
    source_kind = (data.get("source_kind") or "general").strip().lower()
    if source_kind not in ("general", "criterion", "action_eval"):
        source_kind = "general"

    li_id = data.get("evaluation_list_item_id")
    ba_id = data.get("bundle_action_eval_id")
    li_id = int(li_id) if li_id not in (None, "", 0, "0") else None
    ba_id = int(ba_id) if ba_id not in (None, "", 0, "0") else None
    row_index = data.get("row_index")
    row_index = int(row_index) if row_index not in (None, "") else None
    criterion_label = (data.get("criterion_label") or "").strip()[:500]

    # تحقق ملكية النطاق إن وُجد ربط
    if li_id is not None:
        item = db.get(EvaluationListPdfItem, li_id)
        if item is None or int(item.exercise_id or 0) != int(exercise_id):
            return {"ok": False, "error": "item"}, 404
    if ba_id is not None:
        ar = db.get(ExercisePlannerFlowBundleActionEval, ba_id)
        if ar is None:
            return {"ok": False, "error": "action"}, 404

    note_id = data.get("id")
    note_id = int(note_id) if note_id not in (None, "", 0, "0") else None

    row = None
    if client_uuid:
        row = (
            db.query(JudgePolarityNote)
            .filter(
                JudgePolarityNote.judge_user_id == int(user.id),
                JudgePolarityNote.client_uuid == client_uuid,
            )
            .first()
        )
    if row is None and note_id is not None:
        row = (
            db.query(JudgePolarityNote)
            .filter(
                JudgePolarityNote.id == note_id,
                JudgePolarityNote.judge_user_id == int(user.id),
            )
            .first()
        )
        if row is None:
            return {"ok": False, "error": "not_found"}, 404

    if row is None:
        # client_uuid فارغ يسبب تعارض UNIQUE بين السجلات — ولّد معرّفاً فريداً دائماً
        new_uuid = client_uuid or f"web-{uuid4().hex}"
        row = JudgePolarityNote(
            client_uuid=new_uuid[:120],
            exercise_id=int(exercise_id),
            judge_user_id=int(user.id),
            unit_level_key=(unit_level_key or "")[:64],
            judge_label=(judge_label or "")[:200],
        )
        db.add(row)

    row.polarity = polarity
    row.body = body
    row.source_kind = source_kind
    row.evaluation_list_item_id = li_id
    row.bundle_action_eval_id = ba_id
    row.row_index = row_index
    row.criterion_label = criterion_label
    row.unit_level_key = (unit_level_key or row.unit_level_key or "")[:64]
    row.judge_label = (judge_label or row.judge_label or "")[:200]
    row.updated_at = datetime.utcnow()
    if not (row.client_uuid or "").strip():
        row.client_uuid = (client_uuid or f"web-{uuid4().hex}")[:120]
    db.flush()
    return {"ok": True, "note": _serialize_note(row)}, 200


def delete_note(db: Session, user: User, note_id: int | None, client_uuid: str) -> tuple[dict, int]:
    q = db.query(JudgePolarityNote).filter(
        JudgePolarityNote.judge_user_id == int(user.id)
    )
    row = None
    if note_id:
        row = q.filter(JudgePolarityNote.id == int(note_id)).first()
    elif client_uuid:
        row = q.filter(JudgePolarityNote.client_uuid == client_uuid.strip()).first()
    if row is None:
        return {"ok": False, "error": "not_found"}, 404
    db.delete(row)
    db.flush()
    return {"ok": True, "deleted": True}, 200
