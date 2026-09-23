"""ترتيب مراحل التمرين في بنك المعلومات."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models import InformationBankTrainingPhase, InformationBankTreeNode


def ordered_training_phases(db: Session) -> list[InformationBankTrainingPhase]:
    return (
        db.query(InformationBankTrainingPhase)
        .order_by(
            InformationBankTrainingPhase.sort_order,
            InformationBankTrainingPhase.created_at,
            InformationBankTrainingPhase.key,
        )
        .all()
    )


def apply_information_bank_phase_order(
    db: Session,
    *,
    ordered_keys: list[str],
) -> list[str]:
    """حفظ ترتيب مراحل التمرين حسب قائمة المفاتيح."""
    incoming = [(k or "").strip() for k in ordered_keys if (k or "").strip()]
    if not incoming:
        raise ValueError("ترتيب غير صالح.")
    rows = ordered_training_phases(db)
    by_key = {(r.key or "").strip(): r for r in rows if (r.key or "").strip()}
    if incoming[0] not in by_key:
        raise ValueError("مرحلة التمرين غير موجودة.")
    known = [k for k in incoming if k in by_key]
    for k in by_key:
        if k not in known:
            known.append(k)
    if not known:
        raise ValueError("مرحلة التمرين غير موجودة.")
    now = datetime.utcnow()
    for n, key in enumerate(known):
        row = by_key[key]
        row.sort_order = n
        row.updated_at = now
        for node in (
            db.query(InformationBankTreeNode)
            .filter(
                InformationBankTreeNode.catalog_phase_key == key,
                InformationBankTreeNode.parent_id.is_(None),
                InformationBankTreeNode.is_folder.is_(True),
            )
            .all()
        ):
            node.sort_order = n
    db.flush()
    return known
