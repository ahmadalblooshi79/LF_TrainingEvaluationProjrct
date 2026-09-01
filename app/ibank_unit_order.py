"""ترتيب مستويات الوحدات في صفحة التنظيم."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models import InformationBankUnitLevel


def ordered_unit_levels_for_group(
    db: Session, brigade_group: str | None
) -> list[InformationBankUnitLevel]:
    bg = (brigade_group or "1").strip() or "1"
    return (
        db.query(InformationBankUnitLevel)
        .filter(InformationBankUnitLevel.brigade_group == bg)
        .order_by(
            InformationBankUnitLevel.sort_order,
            InformationBankUnitLevel.created_at,
            InformationBankUnitLevel.key,
        )
        .all()
    )


def apply_information_bank_unit_order(
    db: Session,
    *,
    ordered_keys: list[str],
) -> list[str]:
    """حفظ ترتيب مستويات الوحدة داخل المجموعة حسب قائمة المفاتيح."""
    incoming = [(k or "").strip() for k in ordered_keys if (k or "").strip()]
    if not incoming:
        raise ValueError("ترتيب غير صالح.")
    first = db.query(InformationBankUnitLevel).filter_by(key=incoming[0]).first()
    if first is None:
        raise ValueError("مستوى الوحدة غير موجود.")
    rows = ordered_unit_levels_for_group(db, getattr(first, "brigade_group", None))
    by_key = {(r.key or "").strip(): r for r in rows if (r.key or "").strip()}
    known = [k for k in incoming if k in by_key]
    for k in by_key:
        if k not in known:
            known.append(k)
    if not known:
        raise ValueError("مستوى الوحدة غير موجود.")
    now = datetime.utcnow()
    for n, key in enumerate(known):
        row = by_key[key]
        row.sort_order = n
        row.updated_at = now
    db.flush()
    return known
