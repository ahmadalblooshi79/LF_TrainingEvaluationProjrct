"""واجهة بنك المعلومات — تبويبات مجموعات الألوية (منفصل عن views لتجنّب كاش debugpy)."""

from __future__ import annotations

# أقسام بنك المعلومات (قائمة منسدلة بجانب العنوان)
IBANK_SECTION_MISSION = "mission-readiness"
IBANK_SECTION_WARGAMES = "wargames"
IBANK_SECTIONS: tuple[dict[str, str], ...] = (
    {"key": IBANK_SECTION_MISSION, "label": "جاهزية المهمة"},
    {"key": IBANK_SECTION_WARGAMES, "label": "لعبات الحرب"},
)


def normalize_ibank_section(raw: str | None) -> str:
    k = (raw or "").strip()
    if k == IBANK_SECTION_WARGAMES:
        return IBANK_SECTION_WARGAMES
    return IBANK_SECTION_MISSION


def ibank_section_from_exercise_type(exercise_type: str | None) -> str:
    """تمرين جاهزية المهمة → جاهزية المهمة، تمرين لعبات الحرب → لعبات الحرب."""
    from app.exercise_options import EXERCISE_TYPE_WARGAMES

    t = (exercise_type or "").strip()
    if t == EXERCISE_TYPE_WARGAMES:
        return IBANK_SECTION_WARGAMES
    return IBANK_SECTION_MISSION


# التبويب الوحيد لمستويات الوحدات (أُلغيت زايد/3 والظفرة/4 وراشد/5)
IBANK_UNIT_BRIGADE_TAB: dict[str, str] = {
    "key": "1",
    "tab": "units-bg-1",
    "label": "التنظيم",
}

IBANK_REMOVED_BRIGADE_KEYS: frozenset[str] = frozenset({"3", "4", "5"})
IBANK_REMOVED_BRIGADE_TABS: frozenset[str] = frozenset(
    {"units-bg-3", "units-bg-4", "units-bg-5"}
)


def ibank_brigade_groups_for_page() -> list[dict[str, str]]:
    return [dict(IBANK_UNIT_BRIGADE_TAB)]


def is_removed_brigade_tab(tab: str | None) -> bool:
    return (tab or "").strip() in IBANK_REMOVED_BRIGADE_TABS


def is_removed_brigade_key(key: str | None) -> bool:
    return str(key or "").strip() in IBANK_REMOVED_BRIGADE_KEYS


def is_removed_brigade_unit_catalog_key(key: str | None) -> bool:
    """مفاتيح مستويات الوحدات التابعة لمجموعات الألوية 3/4/5 (مثل ``bg3_ul_*``)."""
    k = (key or "").strip()
    if not k:
        return False
    return k.startswith("bg3_") or k.startswith("bg4_") or k.startswith("bg5_")


def unit_level_row_is_removed_brigade(
    *,
    key: str | None = None,
    brigade_group: str | None = None,
) -> bool:
    if is_removed_brigade_key(brigade_group):
        return True
    return is_removed_brigade_unit_catalog_key(key)
