"""خيارات مراحل التمرين المستخدمة في المعاضل وقوائم التقييم.

بنك المعلومات يستخدم ``TRAINING_PHASES`` في ``information_bank_catalog.py`` ولا يتأثر بهذا الكتالوج.
"""

from app.information_bank_catalog import PLANNING_CATALOG_ALL_KEY

EXERCISE_PHASE_OPTIONS: list[tuple[str, str]] = []

DEFAULT_EXERCISE_PHASE = ""

_PHASE_LABELS = dict(EXERCISE_PHASE_OPTIONS)

# مفاتيح قديمة مخزّنة في قاعدة البيانات → مفاتيح كتالوج بنك المعلومات.
_LEGACY_TO_CATALOG: dict[str, str] = {
    "main": "battle_exposure",
    "reorg": "reorganization",
}
_CATALOG_TO_LEGACY: dict[str, str] = {v: k for k, v in _LEGACY_TO_CATALOG.items()}

# مرادفات قديمة (اسم كتالوجي → مفتاح تخزين قديم) — للتوافق مع بيانات قديمة فقط.
_PHASE_ALIASES: dict[str, str] = {
    "battle_exposure": "main",
    "reorganization": "reorg",
}

# تسميات ثابتة عند غياب مزامنة الكتالوج أو لمرادفات legacy.
_STATIC_PHASE_LABELS: dict[str, str] = {
    "preparation": "مرحلة التحضير",
    "opening": "مرحلة الإنفتاح",
    "battle_exposure": "مرحلة المعركة التعرضية",
    "reorganization": "مرحلة مسارات التقييم",
    "main": "مرحلة المعركة التعرضية",
    "reorg": "مرحلة مسارات التقييم",
}


def _phase_label_lookup_keys(key: str) -> list[str]:
    """كل المفاتيح المحتملة للعثور على التسمية العربية."""
    candidates: list[str] = [key]
    if key in _PHASE_ALIASES:
        candidates.append(_PHASE_ALIASES[key])
    if key in _LEGACY_TO_CATALOG:
        candidates.append(_LEGACY_TO_CATALOG[key])
    if key in _CATALOG_TO_LEGACY:
        candidates.append(_CATALOG_TO_LEGACY[key])
    aliased = _PHASE_ALIASES.get(key)
    if aliased and aliased in _LEGACY_TO_CATALOG:
        candidates.append(_LEGACY_TO_CATALOG[aliased])
    seen: set[str] = set()
    out: list[str] = []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def exercise_phase_keys() -> list[str]:
    return [key for key, _ in EXERCISE_PHASE_OPTIONS]


def default_exercise_phase_key() -> str:
    for key, _ in EXERCISE_PHASE_OPTIONS:
        if key != PLANNING_CATALOG_ALL_KEY:
            return key
    return PLANNING_CATALOG_ALL_KEY if EXERCISE_PHASE_OPTIONS else ""


def normalize_exercise_phase(raw: str | None) -> str:
    v = (raw or "").strip()
    if v == PLANNING_CATALOG_ALL_KEY:
        return PLANNING_CATALOG_ALL_KEY
    if not v:
        return ""
    if v in _PHASE_LABELS:
        return v
    catalog_key = _LEGACY_TO_CATALOG.get(v)
    if catalog_key and catalog_key in _PHASE_LABELS:
        return catalog_key
    aliased = _PHASE_ALIASES.get(v)
    if aliased and aliased in _PHASE_LABELS:
        return aliased
    if aliased:
        catalog_from_legacy = _LEGACY_TO_CATALOG.get(aliased)
        if catalog_from_legacy and catalog_from_legacy in _PHASE_LABELS:
            return catalog_from_legacy
    return ""


def exercise_phase_label(key: str | None) -> str:
    k = (key or "").strip()
    if not k:
        return ""
    for candidate in _phase_label_lookup_keys(k):
        if candidate in _PHASE_LABELS:
            return _PHASE_LABELS[candidate]
    for candidate in _phase_label_lookup_keys(k):
        if candidate in _STATIC_PHASE_LABELS:
            return _STATIC_PHASE_LABELS[candidate]
    return k


def register_planning_phase_label_aliases() -> None:
    """بعد مزامنة الكتالوج: تسجيل تسميات المفاتيح القديمة (main/reorg) من مفاتيح الكتالوج."""
    for catalog_key, label in list(_PHASE_LABELS.items()):
        legacy_key = _CATALOG_TO_LEGACY.get(catalog_key)
        if legacy_key and legacy_key not in _PHASE_LABELS:
            _PHASE_LABELS[legacy_key] = label
