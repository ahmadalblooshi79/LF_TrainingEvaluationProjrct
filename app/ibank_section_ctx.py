"""عزل أقسام بنك المعلومات (جاهزية المهمة / لعبات الحرب) — بدون أي ربط بينهما."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy import event
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria

from app.ibank_ui import (
    IBANK_SECTION_MISSION,
    IBANK_SECTION_WARGAMES,
    ibank_section_from_exercise_type,
    normalize_ibank_section,
)

_section: ContextVar[str] = ContextVar("ibank_section", default=IBANK_SECTION_MISSION)
_bypass: ContextVar[bool] = ContextVar("ibank_section_bypass", default=False)
_events_registered = False

_IBANK_SECTION_MODELS: tuple[type, ...] | None = None


def is_ibank_section_bypass() -> bool:
    return bool(_bypass.get())


def current_ibank_section() -> str:
    return normalize_ibank_section(_section.get())


def set_ibank_section(raw: str | None) -> None:
    _section.set(normalize_ibank_section(raw))


def bind_ibank_section_from_exercise(exercise_type: str | None) -> str:
    sec = ibank_section_from_exercise_type(exercise_type)
    set_ibank_section(sec)
    return sec


@contextmanager
def ibank_section_scope(raw: str | None):
    token = _section.set(normalize_ibank_section(raw))
    try:
        yield current_ibank_section()
    finally:
        _section.reset(token)


@contextmanager
def ibank_section_bypass():
    """قراءة/كتابة كل الأقسام (نسخ احتياطي، استنساخ أولي)."""
    token = _bypass.set(True)
    try:
        yield
    finally:
        _bypass.reset(token)


def ibank_file_relpath(kind_relative: str) -> str:
    """مسار الملف داخل INFO_BANK_DIR — لعبات الحرب تحت مجلد مستقل."""
    rel = (kind_relative or "").replace("\\", "/").strip().lstrip("/")
    sec = current_ibank_section()
    if not rel:
        return f"{sec}/" if sec != IBANK_SECTION_MISSION else ""
    if sec == IBANK_SECTION_MISSION:
        return rel
    if rel.startswith(f"{sec}/"):
        return rel
    return f"{sec}/{rel}"


def _section_models() -> tuple[type, ...]:
    global _IBANK_SECTION_MODELS
    if _IBANK_SECTION_MODELS is not None:
        return _IBANK_SECTION_MODELS
    from app.models.domain import (
        InfoBankActionEvalXlsx,
        InfoBankDilemmaEvalXlsx,
        InfoBankEventFlowPdf,
        InformationBankDilemmaListUnit,
        InformationBankEventFlowTable,
        InformationBankPhaseNote,
        InformationBankTrainingPhase,
        InformationBankTreeNode,
        InformationBankUnitLevel,
        InformationBankUnitNote,
    )

    _IBANK_SECTION_MODELS = (
        InformationBankPhaseNote,
        InformationBankUnitNote,
        InformationBankTrainingPhase,
        InformationBankUnitLevel,
        InformationBankTreeNode,
        InformationBankDilemmaListUnit,
        InformationBankEventFlowTable,
        InfoBankEventFlowPdf,
        InfoBankActionEvalXlsx,
        InfoBankDilemmaEvalXlsx,
    )
    return _IBANK_SECTION_MODELS


def _on_do_orm_execute(orm_execute_state: ORMExecuteState) -> None:
    if _bypass.get():
        return
    if not orm_execute_state.is_select:
        return
    sec = current_ibank_section()
    opts = []
    for model in _section_models():
        col = getattr(model, "ibank_section", None)
        if col is None:
            continue
        opts.append(
            with_loader_criteria(
                model,
                lambda cls, s=sec: cls.ibank_section == s,
                include_aliases=True,
            )
        )
    if opts:
        orm_execute_state.statement = orm_execute_state.statement.options(*opts)


def _set_section_on_insert(_mapper, _connection, target) -> None:
    if _bypass.get():
        return
    current = (getattr(target, "ibank_section", None) or "").strip()
    if not current:
        target.ibank_section = current_ibank_section()


def register_ibank_section_session_events() -> None:
    global _events_registered
    if _events_registered:
        return
    event.listen(Session, "do_orm_execute", _on_do_orm_execute)
    for model in _section_models():
        event.listen(model, "before_insert", _set_section_on_insert)
    _events_registered = True
