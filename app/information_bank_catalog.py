"""مراحل التمرين ومستويات الوحدات الثابتة لبنك المعلومات.

بنك المعلومات مرجع عام في النظام ولا يُربَط بمعرّف تمرين؛ هذه القوائم تُستخدم
كفهرس تصنيف للمرفقات والملاحظات فقط.
"""

TRAINING_PHASES: list[dict[str, str]] = [
    {"key": "preparation", "label": "مرحلة التحضير"},
    {"key": "opening", "label": "مرحلة الإنفتاح"},
    {"key": "battle_exposure", "label": "مرحلة المعركة التعرضية"},
    {"key": "reorganization", "label": "مرحلة مسارات التقييم"},
]

INFO_BANK_UNIT_LEVELS: list[dict[str, str]] = [
    {"key": "ul_brigade_grp_cmd", "label": "قيادة مجموعة اللواء"},
    {"key": "ul_brigade_grp_staff", "label": "هيئة ركن مجموعة اللواء"},
    {"key": "ul_mech2_bn_cmd", "label": "قيادة كتيبة المشاة الآلية/2"},
    {"key": "ul_mech2_bn_c1", "label": "كتيبة المشاة الآلية/2- السرية/1"},
    {"key": "ul_mech2_bn_c2", "label": "كتيبة المشاة الآلية/2 - السرية/2"},
    {"key": "ul_mech2_bn_c3", "label": "كتيبة المشاة الآلية/2- السرية/3"},
    {"key": "ul_mech3_bn_cmd", "label": "قيادة كتيبة المشاة الآلية/13"},
    {"key": "ul_mech3_bn_c1", "label": "كتيبة المشاة الآلية/3 - السرية/1"},
    {"key": "ul_mech3_bn_c2", "label": "كتيبة المشاة الآلية/3 - السرية/2"},
    {"key": "ul_mech3_bn_c3", "label": "كتيبة المشاة الآلية/3 - السرية/3"},
    {"key": "ul_tank4_bn_cmd", "label": "قيادة كتيبة الدبابات/14"},
    {"key": "ul_tank4_bn_c1", "label": "كتيبة الدبابات/4 - السرية/1"},
    {"key": "ul_tank4_bn_c2", "label": "كتيبة الدبابات/4 - السرية/2"},
    {"key": "ul_tank4_bn_c3", "label": "كتيبة الدبابات/4 - السرية/3"},
    {"key": "ul_recon", "label": "سرية الاستطلاع"},
    {"key": "ul_at", "label": "سرية الـ م/د"},
    {"key": "ul_arty_bn_cmd", "label": "قيادة كتيبة المدفعية"},
    {"key": "ul_arty_bn_cmd_c1", "label": "قيادة كتيبة المدفعية - السرية/1"},
    {"key": "ul_arty_bn_cmd_c2", "label": "قيادة كتيبة المدفعية - السرية/2"},
    {"key": "ul_arty_bn_cmd_c3", "label": "قيادة كتيبة المدفعية - السرية/3"},
    {"key": "ul_mortar", "label": "سرية الهاون"},
    {"key": "ul_eng", "label": "سرية الهندسة"},
    {"key": "ul_sig", "label": "سرية الإشارة"},
    {"key": "ul_c2", "label": "القيادة والسيطرة"},
    {"key": "ul_ada", "label": "سرية الدفاع الجوي"},
    {"key": "ul_cbrn", "label": "سرية الدفاع الكيميائي"},
    {"key": "ul_admin_bn", "label": "كتيبة الإسناد الإداري"},
    {"key": "ul_medical", "label": "السرية الطبية"},
    {"key": "ul_maint", "label": "سرية الصيانة"},
    {"key": "ul_supply", "label": "سرية التزويد والنقل"},
    {"key": "ul_mp", "label": "فصيل الشرطة العسكرية"},
    {"key": "ul_ew", "label": "سرية الحرب الإلكترونية"},
    {"key": "ul_nco", "label": "ضباط الصف"},
]


def training_phase_label(key: str | None) -> str:
    k = (key or "").strip()
    for row in TRAINING_PHASES:
        if row["key"] == k:
            return row["label"]
    return ""


def info_bank_unit_label(key: str | None) -> str:
    k = (key or "").strip()
    for row in INFO_BANK_UNIT_LEVELS:
        if row["key"] == k:
            return row["label"]
    return ""


def is_valid_training_phase_key(key: str | None) -> bool:
    return any((key or "").strip() == p["key"] for p in TRAINING_PHASES)


def is_valid_info_bank_unit_key(key: str | None) -> bool:
    return any((key or "").strip() == u["key"] for u in INFO_BANK_UNIT_LEVELS)
