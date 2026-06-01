"""مستويات الوحدة الموحدة — المعاضل، التقييم، قوائم الوحدة (متدربين/محكمين).

بنك المعلومات يستخدم ``INFO_BANK_UNIT_LEVELS`` في ``information_bank_catalog.py``.
``UNIT_LEVELS`` هنا يُملأ تلقائياً من صفوف «مدرج في التمرين» عبر ``planning_catalog_sync``.
"""

from app.information_bank_catalog import PLANNING_CATALOG_ALL_KEY

UNIT_LEVELS: list[dict[str, str]] = []


def default_unit_level_key() -> str:
    """أول مستوى وحدة فعلي (بعد خيار «الكل» إن وُجد)."""
    for row in UNIT_LEVELS:
        if row["key"] != PLANNING_CATALOG_ALL_KEY:
            return row["key"]
    return PLANNING_CATALOG_ALL_KEY if UNIT_LEVELS else ""


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
        return PLANNING_CATALOG_ALL_KEY
    if not v:
        return ""
    for row in UNIT_LEVELS:
        if v == row["key"]:
            return row["key"]
    for row in UNIT_LEVELS:
        if v == row["label"]:
            return row["key"]
    return ""


def label_for_unit_level_key(key: str | None) -> str:
    """تسمية العرض لمفتاح مستوى الوحدة."""
    k = (key or "").strip()
    for row in UNIT_LEVELS:
        if row["key"] == k:
            return row["label"]
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
