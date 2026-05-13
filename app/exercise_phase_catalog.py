"""خيارات مراحل التمرين المستخدمة في المعاضل وقوائم التقييم."""

EXERCISE_PHASE_OPTIONS: list[tuple[str, str]] = [
    ("preparation", "مرحلة التحضير"),
    ("opening", "مرحلة الإنفتاح"),
    ("main", "مرحلة المعركة التعرضية"),
    ("reorg", "مرحلة إعادة التنظيم"),
]

DEFAULT_EXERCISE_PHASE = EXERCISE_PHASE_OPTIONS[0][0]

_PHASE_LABELS = dict(EXERCISE_PHASE_OPTIONS)

# مفاتيح قديمة/مرادفة ظهرت في أجزاء أخرى من النظام.
_PHASE_ALIASES = {
    "battle_exposure": "main",
    "reorganization": "reorg",
}


def exercise_phase_keys() -> list[str]:
    return [key for key, _ in EXERCISE_PHASE_OPTIONS]


def normalize_exercise_phase(raw: str | None) -> str:
    v = (raw or "").strip()
    if not v:
        return DEFAULT_EXERCISE_PHASE
    v = _PHASE_ALIASES.get(v, v)
    if v in _PHASE_LABELS:
        return v
    return DEFAULT_EXERCISE_PHASE


def exercise_phase_label(key: str | None) -> str:
    return _PHASE_LABELS.get(normalize_exercise_phase(key), _PHASE_LABELS[DEFAULT_EXERCISE_PHASE])
