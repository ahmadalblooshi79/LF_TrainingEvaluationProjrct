"""مستويات الوحدة الموحدة — المعاضل، التقييم، قوائم الوحدة (متدربين/محكمين)."""

UNIT_LEVELS: list[dict[str, str]] = [
    {"key": "brigade_group", "label": "مجموعة لواء"},
    {"key": "mech_infantry_bn", "label": "كتيبة مشاة آلية"},
    {"key": "tank_bn", "label": "كتيبة دبابات"},
    {"key": "artillery_bn", "label": "كتيبة المدفعية"},
    {"key": "recon_co", "label": "سرية الاستطلاع"},
    {"key": "anti_tank_co", "label": "سرية م/د"},
    {"key": "mortar_co", "label": "سرية الهاون"},
    {"key": "chemical_def_co", "label": "سرية الدفاع الكيميائي"},
    {"key": "field_eng_co", "label": "سرية هندسة الميدان"},
    {"key": "medical_co", "label": "سرية الطبية"},
    {"key": "maintenance_co", "label": "سرية الصيانة"},
    {"key": "supply_transport_co", "label": "سرية التزويد والنقل"},
]


def normalize_unit_level_key(raw: str | None) -> str:
    """يحوّل مفتاحاً معروفاً أو تسمية عربية لمستوى الوحدة إلى ``key``؛ وإلا سلسلة فارغة."""
    v = (raw or "").strip()
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
