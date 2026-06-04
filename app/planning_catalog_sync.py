"""مزامنة كتالوج التخطيط (مستويات الوحدة ومراحل التمرين) من بنك المعلومات."""
from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app import exercise_phase_catalog as phase_cat
from app import unit_levels_catalog as unit_cat
from app.ibank_ui import (
    IBANK_REMOVED_BRIGADE_KEYS,
    is_removed_brigade_unit_catalog_key,
    unit_level_row_is_removed_brigade,
)
from app.models import (
    InformationBankTrainingPhase,
    InformationBankUnitLevel,
    InformationBankUnitNote,
    InformationBankTreeNode,
)


def purge_removed_brigade_unit_levels(db: Session) -> int:
    """إزالة مستويات الوحدات التابعة لمجموعات الألوية 3/4/5 من بنك المعلومات والتخطيط."""
    removed_bg = list(IBANK_REMOVED_BRIGADE_KEYS)
    rows = (
        db.query(InformationBankUnitLevel)
        .filter(
            or_(
                InformationBankUnitLevel.brigade_group.in_(removed_bg),
                InformationBankUnitLevel.key.like("bg3_%"),
                InformationBankUnitLevel.key.like("bg4_%"),
                InformationBankUnitLevel.key.like("bg5_%"),
            )
        )
        .all()
    )
    if not rows:
        return 0
    keys = [(r.key or "").strip() for r in rows if (r.key or "").strip()]
    for k in keys:
        db.query(InformationBankUnitNote).filter(
            InformationBankUnitNote.unit_level_key == k
        ).delete(synchronize_session=False)
        db.query(InformationBankTreeNode).filter(
            InformationBankTreeNode.catalog_unit_key == k
        ).delete(synchronize_session=False)
    for r in rows:
        db.delete(r)
    db.commit()
    return len(rows)


def sync_planning_unit_levels_from_db(db: Session) -> list[dict[str, str]]:
    """تحديث ``UNIT_LEVELS`` من صفوف بنك المعلومات المدرجة في التمرين (الإمارات /1 فقط)."""
    rows = (
        db.query(InformationBankUnitLevel)
        .filter(InformationBankUnitLevel.included_in_exercise.is_(True))
        .order_by(
            InformationBankUnitLevel.sort_order,
            InformationBankUnitLevel.created_at,
            InformationBankUnitLevel.key,
        )
        .all()
    )
    out: list[dict[str, str]] = []
    for r in rows:
        key = (r.key or "").strip()
        if not key:
            continue
        if unit_level_row_is_removed_brigade(
            key=key, brigade_group=getattr(r, "brigade_group", None)
        ):
            continue
        if is_removed_brigade_unit_catalog_key(key):
            continue
        out.append({"key": key, "label": r.label})
    unit_cat.UNIT_LEVELS.clear()
    unit_cat.UNIT_LEVELS.extend(out)
    return unit_cat.UNIT_LEVELS


def sync_planning_exercise_phases_from_db(db: Session) -> list[tuple[str, str]]:
    """تحديث ``EXERCISE_PHASE_OPTIONS`` من مراحل بنك المعلومات المدرجة في التمرين."""
    rows = (
        db.query(InformationBankTrainingPhase)
        .filter(InformationBankTrainingPhase.included_in_exercise.is_(True))
        .order_by(
            InformationBankTrainingPhase.sort_order,
            InformationBankTrainingPhase.created_at,
            InformationBankTrainingPhase.key,
        )
        .all()
    )
    included = [(r.key, r.label) for r in rows if (r.key or "").strip()]
    phase_cat.EXERCISE_PHASE_OPTIONS.clear()
    phase_cat.EXERCISE_PHASE_OPTIONS.extend(included)
    phase_cat.DEFAULT_EXERCISE_PHASE = included[0][0] if included else ""
    phase_cat._PHASE_LABELS.clear()
    phase_cat._PHASE_LABELS.update(dict(included))
    phase_cat.register_planning_phase_label_aliases()
    return included


def sync_planning_catalogs_from_db(db: Session) -> None:
    purge_removed_brigade_unit_levels(db)
    sync_planning_unit_levels_from_db(db)
    sync_planning_exercise_phases_from_db(db)
