"""مزامنة كتالوج التخطيط (مستويات الوحدة ومراحل التمرين) من بنك المعلومات."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app import exercise_phase_catalog as phase_cat
from app import unit_levels_catalog as unit_cat
from app.information_bank_catalog import PLANNING_CATALOG_ALL_KEY, PLANNING_CATALOG_ALL_LABEL
from app.models import InformationBankTrainingPhase, InformationBankUnitLevel


def sync_planning_unit_levels_from_db(db: Session) -> list[dict[str, str]]:
    """تحديث ``UNIT_LEVELS`` من صفوف بنك المعلومات المدرجة في التمرين."""
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
    out = [{"key": r.key, "label": r.label} for r in rows if (r.key or "").strip()]
    unit_cat.UNIT_LEVELS.clear()
    unit_cat.UNIT_LEVELS.append(
        {"key": PLANNING_CATALOG_ALL_KEY, "label": PLANNING_CATALOG_ALL_LABEL}
    )
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
    out = [(PLANNING_CATALOG_ALL_KEY, PLANNING_CATALOG_ALL_LABEL)] + included
    phase_cat.EXERCISE_PHASE_OPTIONS.clear()
    phase_cat.EXERCISE_PHASE_OPTIONS.extend(out)
    if included:
        phase_cat.DEFAULT_EXERCISE_PHASE = included[0][0]
    else:
        phase_cat.DEFAULT_EXERCISE_PHASE = PLANNING_CATALOG_ALL_KEY
    phase_cat._PHASE_LABELS.clear()
    phase_cat._PHASE_LABELS.update(dict(out))
    phase_cat.register_planning_phase_label_aliases()
    return out


def sync_planning_catalogs_from_db(db: Session) -> None:
    sync_planning_unit_levels_from_db(db)
    sync_planning_exercise_phases_from_db(db)
