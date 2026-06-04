"""مستويات الوحدة الموحدة — المعاضل، التقييم، قوائم الوحدة (متدربين/محكمين).

بنك المعلومات يستخدم ``INFO_BANK_UNIT_LEVELS`` في ``information_bank_catalog.py``.
``UNIT_LEVELS`` هنا يُملأ تلقائياً من صفوف «مدرج في التمرين» عبر ``planning_catalog_sync``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.ibank_ui import unit_level_row_is_removed_brigade
from app.information_bank_catalog import PLANNING_CATALOG_ALL_KEY, info_bank_unit_label

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

UNIT_LEVELS: list[dict[str, str]] = []


def planning_included_unit_keys() -> set[str]:
    """مفاتيح مستويات الوحدة المفعّلة في التمرين (مدرجة في بنك المعلومات)."""
    return {(row.get("key") or "").strip() for row in UNIT_LEVELS if (row.get("key") or "").strip()}


def default_unit_level_key() -> str:
    """أول مستوى وحدة في كتالوج التخطيط."""
    if UNIT_LEVELS:
        return UNIT_LEVELS[0]["key"]
    return ""


def unit_level_row(unit_key: str | None) -> dict[str, str] | None:
    """صف الكتالوج لمفتاح معيّن، أو ``None`` إن كان المفتاح فارغاً."""
    k = (unit_key or "").strip()
    if not k:
        return None
    return next((x for x in UNIT_LEVELS if x["key"] == k), None)


def normalize_unit_level_key(raw: str | None) -> str:
    """يحوّل مفتاحاً معروفاً أو تسمية عربية لمستوى الوحدة إلى ``key``؛ وإلا سلسلة فارغة."""
    v = (raw or "").strip()
    if v == PLANNING_CATALOG_ALL_KEY:
        return default_unit_level_key()
    if not v:
        return ""
    for row in UNIT_LEVELS:
        if v == row["key"]:
            return row["key"]
    for row in UNIT_LEVELS:
        if v == row["label"]:
            return row["key"]
    if unit_level_row_is_removed_brigade(key=v):
        return ""
    return ""


def label_for_unit_level_key(key: str | None, db: Session | None = None) -> str:
    """تسمية العرض لمفتاح مستوى الوحدة (كتالوج التخطيط ثم بنك المعلومات ثم قاعدة البيانات)."""
    k = (key or "").strip()
    if not k:
        return ""
    for row in UNIT_LEVELS:
        if row["key"] == k:
            return row["label"]
    if unit_level_row_is_removed_brigade(key=k):
        return ""
    label = info_bank_unit_label(k)
    if label:
        return label
    if db is not None:
        from app.models import InformationBankUnitLevel

        row = db.get(InformationBankUnitLevel, k)
        if row is not None:
            lbl = (row.label or "").strip()
            if lbl:
                return lbl
    return ""


def coerce_roster_import_position_cell(cell: str) -> tuple[str, str]:
    """
    عمود المستوى من ملف الاستيراد: إن وافق مفتاحاً أو تسمية مستوى وحدّة يُخزَّن في ``unit_level_key``.
    تعيد ``(unit_level_key, position_ar)`` حيث ``position_ar`` التسمية عند وجود مفتاح، أو النص الخام للتوافق الخلفي.
    """
    key = normalize_unit_level_key(cell)
    if key:
        return key, label_for_unit_level_key(key)
    return "", (cell or "").strip()[:512]
