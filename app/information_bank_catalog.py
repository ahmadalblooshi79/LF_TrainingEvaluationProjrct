"""مراحل التمرين لبنك المعلومات، والتنظيم يُعرَّف من المستخدم في قاعدة البيانات المحلية.

بنك المعلومات مرجع عام في النظام ولا يُربَط بمعرّف تمرين.
"""

# مراحل التمرين يضيفها المستخدم في بنك المعلومات — لا قائمة افتراضية في الشيفرة.
TRAINING_PHASES: list[dict[str, str]] = []
TRAINING_PHASE_ORDER: tuple[str, ...] = ()


def ordered_training_phase_keys(keys: list[str] | set[str] | tuple[str, ...]) -> list[str]:
    """يحافظ على ترتيب المفاتيح المعطى مع حذف التكرار."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in keys:
        k = (raw or "").strip()
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(k)
    return out

# مجموعات الألوية في بنك المعلومات (تبويب مستويات الوحدات — التنظيم)
INFO_BANK_BRIGADE_GROUPS: list[dict[str, str]] = [
    {"key": "1", "tab": "units-bg-1", "label": "التنظيم"},
]

INFO_BANK_BRIGADE_GROUPS_REMOVED_KEYS: frozenset[str] = frozenset({"3", "4", "5"})
INFO_BANK_BRIGADE_REMOVED_TABS: frozenset[str] = frozenset(
    {"units-bg-3", "units-bg-4", "units-bg-5"}
)


def info_bank_brigade_groups_for_ui() -> list[dict[str, str]]:
    """مجموعات الألوية الظاهرة في تبويبات بنك المعلومات."""
    return list(INFO_BANK_BRIGADE_GROUPS)

# التنظيم يُنشئه المستخدم في بنك المعلومات فقط — لا قائمة افتراضية في الشيفرة.
INFO_BANK_UNIT_LEVEL_TEMPLATES: list[dict[str, str]] = []
INFO_BANK_UNIT_OBSOLETE_LABELS: dict[str, frozenset[str]] = {}
_BUILTIN_SEEDED_UNIT_KEY_PREFIX = "ul_"


def is_builtin_seeded_unit_catalog_key(key: str | None) -> bool:
    """مفاتيح التنظيم القديم المزروع برمجياً (``ul_*``) — ليست تنظيماً يعرّفه المستخدم."""
    return (key or "").strip().startswith(_BUILTIN_SEEDED_UNIT_KEY_PREFIX)


def template_label_for_unit_template_key(template_key: str) -> str:
    tk = (template_key or "").strip()
    for row in INFO_BANK_UNIT_LEVEL_TEMPLATES:
        if row["key"] == tk:
            return row["label"]
    return ""


def apply_information_bank_unit_label_migrations(db) -> bool:
    """ترحيل تسميات قديمة — معطّل بعد إلغاء التنظيم الافتراضي."""
    from app.ibank_ui import ibank_brigade_groups_for_page
    from app.models import InformationBankTreeNode, InformationBankUnitLevel

    changed = False

    for template_key, obsolete_labels in INFO_BANK_UNIT_OBSOLETE_LABELS.items():
        new_label = template_label_for_unit_template_key(template_key)
        if not new_label:
            continue
        for bg in ibank_brigade_groups_for_page():
            catalog_key = unit_catalog_key_for_brigade(bg["key"], template_key)
            if not catalog_key:
                continue
            row = db.query(InformationBankUnitLevel).filter_by(key=catalog_key).first()
            if row is None:
                continue
            current = (row.label or "").strip()
            if current not in obsolete_labels:
                continue
            row.label = new_label
            for node in (
                db.query(InformationBankTreeNode)
                .filter(
                    InformationBankTreeNode.catalog_unit_key == catalog_key,
                    InformationBankTreeNode.is_folder.is_(True),
                )
                .all()
            ):
                node.name = new_label[:500]
            changed = True
    if changed:
        from app.planning_catalog_sync import invalidate_planning_catalog_cache

        invalidate_planning_catalog_cache()
    return changed

# توافق خلفي مع الاستيرادات القديمة
INFO_BANK_UNIT_LEVELS: list[dict[str, str]] = INFO_BANK_UNIT_LEVEL_TEMPLATES

PLANNING_CATALOG_ALL_KEY = "__all__"
PLANNING_CATALOG_ALL_LABEL = "الكل"


def unit_catalog_key_for_brigade(brigade_key: str, template_key: str) -> str:
    """مفتاح التخزين: المجموعة /1 تحتفظ بالمفاتيح القديمة ``ul_*``."""
    bg = (brigade_key or "").strip()
    tk = (template_key or "").strip()
    if not tk:
        return ""
    if bg in ("", "1"):
        return tk
    return f"bg{bg}_{tk}"


def brigade_group_for_tab(tab: str | None) -> str:
    t = (tab or "").strip()
    if t in INFO_BANK_BRIGADE_REMOVED_TABS:
        return "1"
    for bg in info_bank_brigade_groups_for_ui():
        if bg["tab"] == t:
            return bg["key"]
    return "1"


def brigade_tab_for_group(brigade_key: str | None) -> str:
    k = (brigade_key or "").strip()
    for bg in INFO_BANK_BRIGADE_GROUPS:
        if bg["key"] == k:
            return bg["tab"]
    return INFO_BANK_BRIGADE_GROUPS[0]["tab"]


_TRAINING_PHASE_LEGACY_KEYS: dict[str, str] = {
    "main": "battle_exposure",
    "reorg": "reorganization",
}


def training_phase_label(key: str | None) -> str:
    k = (key or "").strip()
    if not k:
        return ""
    for row in TRAINING_PHASES:
        if row["key"] == k:
            return row["label"]
    catalog_key = _TRAINING_PHASE_LEGACY_KEYS.get(k)
    if catalog_key:
        for row in TRAINING_PHASES:
            if row["key"] == catalog_key:
                return row["label"]
    return ""


_LEGACY_BRIGADE_UNIT_PREFIXES = ("bg3_", "bg4_", "bg5_")


def _legacy_brigade_unit_template_key(key: str) -> str | None:
    """مفاتيح قديمة لمجموعات ألوية محذوفة (مثل ``bg3_ul_brigade_grp_cmd`` → ``ul_brigade_grp_cmd``)."""
    for prefix in _LEGACY_BRIGADE_UNIT_PREFIXES:
        if key.startswith(prefix):
            base = key[len(prefix) :]
            if base:
                return base
    return None


def info_bank_unit_label(key: str | None) -> str:
    k = (key or "").strip()
    if k == PLANNING_CATALOG_ALL_KEY:
        return ""
    for row in INFO_BANK_UNIT_LEVEL_TEMPLATES:
        if row["key"] == k:
            return row["label"]
        for bg in INFO_BANK_BRIGADE_GROUPS:
            if unit_catalog_key_for_brigade(bg["key"], row["key"]) == k:
                return row["label"]
    legacy_base = _legacy_brigade_unit_template_key(k)
    if legacy_base:
        for row in INFO_BANK_UNIT_LEVEL_TEMPLATES:
            if row["key"] == legacy_base:
                return row["label"]
    return ""


def is_valid_training_phase_key(key: str | None) -> bool:
    return any((key or "").strip() == p["key"] for p in TRAINING_PHASES)


def is_valid_info_bank_unit_key(key: str | None) -> bool:
    return any((key or "").strip() == u["key"] for u in INFO_BANK_UNIT_LEVELS)
