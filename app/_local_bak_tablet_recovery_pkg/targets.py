# -*- coding: utf-8 -*-
"""حلّ هدف القائمة القابلة للتصفح عند مفاتيح وحدة يتيمة (مثل ul_supply)."""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from app.models.domain import EvaluationListPdfItem
from app.unit_levels_catalog import label_for_unit_level_key


_PATH_UNIT_RE = re.compile(
    r"/evaluation-lists/([^/]+)/\d+",
    re.IGNORECASE,
)


def unit_hints_from_package(package: Any) -> dict[int, list[str]]:
    """استخراج مفاتيح الوحدة من مسارات العمليات ومفاتيح الـ cache لكل eval_item_id."""
    out: dict[int, list[str]] = {}

    def _add(item_id: int | None, uk: str | None) -> None:
        if item_id is None or not uk:
            return
        uk = str(uk).strip()
        if not uk or uk in ("_",):
            return
        bucket = out.setdefault(int(item_id), [])
        if uk not in bucket:
            bucket.append(uk)

    for op in getattr(package, "pending_ops", None) or []:
        path = getattr(op, "path", "") or ""
        m = _PATH_UNIT_RE.search(path.replace("\\", "/"))
        if m:
            _add(getattr(op, "eval_item_id", None), m.group(1))
        # list_id مثل evaluation_list_detail:unit_xxx:180
        lid = getattr(op, "list_id", None) or ""
        parts = str(lid).split(":")
        if len(parts) >= 3 and parts[-1].isdigit():
            _add(int(parts[-1]), parts[-2] if "unit" in parts[-2] or parts[-2].startswith("ul_") else None)
            if len(parts) >= 3:
                _add(int(parts[-1]), parts[1] if parts[0].endswith("detail") else parts[-2])

    for c in getattr(package, "cache_evals", None) or []:
        key = getattr(c, "cache_key", "") or ""
        # u174:evaluation_list_detail:unit_xxx:180
        parts = str(key).split(":")
        if len(parts) >= 2 and parts[-1].isdigit():
            _add(int(parts[-1]), getattr(c, "unit_key", None))
            if len(parts) >= 3:
                _add(int(parts[-1]), parts[-2])

    return out


def unit_is_navigable(db: Session, unit_key: str | None) -> bool:
    uk = (unit_key or "").strip()
    if not uk:
        return False
    return bool(label_for_unit_level_key(uk, db=db))


def resolve_navigable_eval_item(
    db: Session,
    item: EvaluationListPdfItem | None,
    *,
    hint_unit_keys: list[str] | None = None,
) -> EvaluationListPdfItem | None:
    """
    إذا كانت وحدة القائمة يتيمة (بدون تسمية في الكتالوج/البنك)،
    ابحث عن نسخة بنفس العنوان والتمرين تحت وحدة قابلة للتصفح.
    """
    if item is None:
        return None
    if unit_is_navigable(db, item.unit_level_key):
        return item

    title = (item.text or "").strip()
    if not title:
        return item

    candidates = (
        db.query(EvaluationListPdfItem)
        .filter(
            EvaluationListPdfItem.exercise_id == int(item.exercise_id),
            EvaluationListPdfItem.text == item.text,
            EvaluationListPdfItem.id != int(item.id),
        )
        .all()
    )
    navigable = [
        c for c in candidates if unit_is_navigable(db, c.unit_level_key)
    ]
    if not navigable:
        return item

    hints = [h for h in (hint_unit_keys or []) if h]
    for hint in hints:
        for c in navigable:
            if (c.unit_level_key or "").strip() == hint:
                return c

    phase = (getattr(item, "exercise_phase", None) or "").strip()
    same_phase = [
        c for c in navigable if (getattr(c, "exercise_phase", None) or "").strip() == phase
    ]
    pool = same_phase or navigable
    # فضّل المرحلة الفارغة ثم أصغر id (النشر الأقدم/الأساسي)
    pool.sort(
        key=lambda c: (
            0 if not (getattr(c, "exercise_phase", None) or "").strip() else 1,
            int(c.id),
        )
    )
    return pool[0]


def remap_note(source: EvaluationListPdfItem, target: EvaluationListPdfItem) -> str | None:
    if source is None or target is None:
        return None
    if int(source.id) == int(target.id):
        return None
    return (
        f"أُعيد توجيه الاستعادة من القائمة #{source.id} ({source.unit_level_key}) "
        f"إلى #{target.id} ({target.unit_level_key}) لأن مفتاح الوحدة الأصلي غير ظاهر في الواجهة."
    )
