"""مستويات الوحدة الموحدة — المعاضل، التقييم، قوائم الوحدة (متدربين/محكمين)."""

UNIT_LEVELS: list[dict[str, str]] = [
    {"key": "brigade_group", "label": "قيادة مجموعة اللواء"},
    {"key": "brigade_group_staff", "label": "هيئة ركن مجموعة اللواء"},
    {"key": "mech_infantry_bn", "label": "قيادة كتيبة المشاة الآلية/2"},
    {"key": "mech_infantry_bn_2_c1", "label": "كتيبة المشاة الآلية/2- السرية/1"},
    {"key": "mech_infantry_bn_2_c2", "label": "كتيبة المشاة الآلية/2 - السرية/2"},
    {"key": "mech_infantry_bn_2_c3", "label": "كتيبة المشاة الآلية/2- السرية/3"},
    {"key": "mech_infantry_bn_13", "label": "قيادة كتيبة المشاة الآلية/13"},
    {"key": "mech_infantry_bn_3_c1", "label": "كتيبة المشاة الآلية/3 - السرية/1"},
    {"key": "mech_infantry_bn_3_c2", "label": "كتيبة المشاة الآلية/3 - السرية/2"},
    {"key": "mech_infantry_bn_3_c3", "label": "كتيبة المشاة الآلية/3 - السرية/3"},
    {"key": "tank_bn", "label": "قيادة كتيبة الدبابات/14"},
    {"key": "tank_bn_4_c1", "label": "كتيبة الدبابات/4 - السرية/1"},
    {"key": "tank_bn_4_c2", "label": "كتيبة الدبابات/4 - السرية/2"},
    {"key": "tank_bn_4_c3", "label": "كتيبة الدبابات/4 - السرية/3"},
    {"key": "recon_co", "label": "سرية الاستطلاع"},
    {"key": "anti_tank_co", "label": "سرية الـ م/د"},
    {"key": "artillery_bn", "label": "قيادة كتيبة المدفعية"},
    {"key": "artillery_bn_c1", "label": "قيادة كتيبة المدفعية - السرية/1"},
    {"key": "artillery_bn_c2", "label": "قيادة كتيبة المدفعية - السرية/2"},
    {"key": "artillery_bn_c3", "label": "قيادة كتيبة المدفعية - السرية/3"},
    {"key": "mortar_co", "label": "سرية الهاون"},
    {"key": "field_eng_co", "label": "سرية الهندسة"},
    {"key": "signal_co", "label": "سرية الإشارة"},
    {"key": "command_control", "label": "القيادة والسيطرة"},
    {"key": "air_defense_co", "label": "سرية الدفاع الجوي"},
    {"key": "chemical_def_co", "label": "سرية الدفاع الكيميائي"},
    {"key": "admin_support_bn", "label": "كتيبة الإسناد الإداري"},
    {"key": "medical_co", "label": "السرية الطبية"},
    {"key": "maintenance_co", "label": "سرية الصيانة"},
    {"key": "supply_transport_co", "label": "سرية التزويد والنقل"},
    {"key": "military_police_platoon", "label": "فصيل الشرطة العسكرية"},
    {"key": "electronic_warfare_co", "label": "سرية الحرب الإلكترونية"},
    {"key": "nco", "label": "ضباط الصف"},
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
