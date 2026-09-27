"""مطابقة هوية قوائم التقييم — مفاتيح متعددة وليست المعرّف وحده.

مصدر واحد لـ:
Excel Import / Recovery Import / Server Pull / Server Push validation.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable

from sqlalchemy.orm import Session

STATUS_AR = {
    "MATCHED_EXACT": "مطابقة مؤكدة",
    "MATCHED_BY_UNIT_LIST": "مطابقة بالوحدة والقائمة",
    "MATCHED_BY_CONTEXT": "مطابقة بالسياق",
    "REVIEW_REQUIRED": "يتطلب مراجعة",
    "AMBIGUOUS": "أكثر من مطابقة محتملة",
    "NOT_FOUND": "غير موجود",
    "CONFLICT": "تعارض",
    "LOCAL_WORK_EXISTS": "يوجد عمل محلي",
}

APPROVED_CONFLICT_AR = "تعارض مع نتيجة معتمدة"

_TATWEEL = "\u0640"
_DIACRITICS_RE = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]")
_SPACE_RE = re.compile(r"\s+")
_ALEF_MAP = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا"})


def normalize_ar_text(value: Any) -> str:
    """تطبيع عربي آمن: قص، مسافات، همزات، ياء، بدون مطابقة ضبابية."""
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace(_TATWEEL, "")
    text = _DIACRITICS_RE.sub("", text)
    text = text.translate(_ALEF_MAP)
    text = text.replace("ى", "ي")
    text = text.replace("ئ", "ي")
    text = _SPACE_RE.sub(" ", text).strip()
    return text.casefold()


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


@dataclass
class SourceIdentity:
    exercise_id: int | None = None
    exercise_name: str = ""
    unit_id: str = ""
    unit_name: str = ""
    evaluation_list_id: int | None = None
    evaluation_list_name: str = ""
    eval_item_id: int | None = None
    evaluation_type: str = ""
    stage_id: str = ""
    stage_name: str = ""
    dilemma_id: int | None = None
    dilemma_name: str = ""
    judge_id: int | None = None
    judge_name: str = ""
    client_op_id: str = ""
    device_id: str = ""

    def fingerprint(self) -> str:
        return "|".join(
            [
                str(self.exercise_id or ""),
                normalize_ar_text(self.unit_id or self.unit_name),
                str(self.eval_item_id or ""),
                normalize_ar_text(self.evaluation_list_name),
                normalize_ar_text(self.evaluation_type),
                normalize_ar_text(self.stage_id or self.stage_name),
                str(self.dilemma_id or ""),
                normalize_ar_text(self.dilemma_name),
            ]
        )


@dataclass
class CandidateTarget:
    eval_item_id: int
    unit_id: str
    unit_name: str
    list_name: str
    evaluation_type: str
    stage_id: str
    stage_name: str
    dilemma_id: int | None
    dilemma_name: str
    exercise_id: int | None
    judge_id: int | None = None
    judge_name: str = ""
    approved: bool = False
    chief_approved: bool = False


@dataclass
class MatchResult:
    status: str
    match_method: str
    status_ar: str
    target: CandidateTarget | None = None
    candidates: list[CandidateTarget] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    used_mapping_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        def _c(c: CandidateTarget | None) -> dict[str, Any] | None:
            if c is None:
                return None
            return {
                "eval_item_id": c.eval_item_id,
                "unit_id": c.unit_id,
                "unit_name": c.unit_name,
                "list_name": c.list_name,
                "evaluation_type": c.evaluation_type,
                "stage_id": c.stage_id,
                "stage_name": c.stage_name,
                "dilemma_id": c.dilemma_id,
                "dilemma_name": c.dilemma_name,
                "exercise_id": c.exercise_id,
                "judge_id": c.judge_id,
                "judge_name": c.judge_name,
                "approved": c.approved,
                "chief_approved": c.chief_approved,
            }

        return {
            "status": self.status,
            "match_method": self.match_method,
            "status_ar": self.status_ar,
            "target": _c(self.target),
            "candidates": [_c(c) for c in self.candidates],
            "conflicts": list(self.conflicts),
            "used_mapping_id": self.used_mapping_id,
        }


def _result(
    status: str,
    method: str,
    *,
    target: CandidateTarget | None = None,
    candidates: list[CandidateTarget] | None = None,
    conflicts: list[str] | None = None,
    mapping_id: int | None = None,
) -> MatchResult:
    return MatchResult(
        status=status,
        match_method=method,
        status_ar=STATUS_AR.get(status, status),
        target=target,
        candidates=list(candidates or []),
        conflicts=list(conflicts or []),
        used_mapping_id=mapping_id,
    )


def _item_to_candidate(db: Session, item, saved=None) -> CandidateTarget:
    from app.models import User
    from app.unit_levels_catalog import label_for_unit_level_key

    unit_key = (getattr(item, "unit_level_key", "") or "").strip()
    unit_label = (getattr(item, "unit_level_label", "") or "").strip()
    if not unit_label:
        unit_label = label_for_unit_level_key(unit_key, db=db) or unit_key
    phase = (getattr(item, "exercise_phase", "") or "").strip()
    judge_id = None
    judge_name = ""
    approved = False
    chief_approved = False
    if saved is not None:
        judge_id = getattr(saved, "saved_by_id", None)
        approved = bool(getattr(saved, "is_approved", False))
        chief_approved = bool(getattr(saved, "is_chief_approved", False))
        if judge_id:
            u = db.get(User, int(judge_id))
            if u is not None:
                judge_name = (getattr(u, "full_name", None) or getattr(u, "username", "") or "")
    return CandidateTarget(
        eval_item_id=int(item.id),
        unit_id=unit_key,
        unit_name=unit_label,
        list_name=(getattr(item, "text", "") or "").strip(),
        evaluation_type="evaluation_list",
        stage_id=phase,
        stage_name=phase,
        dilemma_id=None,
        dilemma_name="",
        exercise_id=getattr(item, "exercise_id", None),
        judge_id=judge_id,
        judge_name=judge_name,
        approved=approved,
        chief_approved=chief_approved,
    )


def _saved_for(db: Session, exercise_id: int | None, item_id: int):
    from app.models import EvaluationListSavedResult

    q = db.query(EvaluationListSavedResult).filter(
        EvaluationListSavedResult.evaluation_item_id == int(item_id)
    )
    if exercise_id:
        q = q.filter(EvaluationListSavedResult.exercise_id == int(exercise_id))
    return q.order_by(EvaluationListSavedResult.id.desc()).first()


def _relationships_valid(item, source: SourceIdentity, current_exercise_id: int | None) -> bool:
    item_ex = getattr(item, "exercise_id", None)
    if current_exercise_id and item_ex and int(item_ex) != int(current_exercise_id):
        return False
    src_unit = (source.unit_id or "").strip()
    item_unit = (getattr(item, "unit_level_key", "") or "").strip()
    if src_unit and item_unit and src_unit != item_unit:
        return False
    return True


def _unit_matches(cand: CandidateTarget, source: SourceIdentity) -> bool:
    src_key = (source.unit_id or "").strip()
    if src_key and cand.unit_id and src_key == cand.unit_id:
        return True
    src_name = normalize_ar_text(source.unit_name)
    if src_name and src_name == normalize_ar_text(cand.unit_name):
        return True
    if src_name and src_name == normalize_ar_text(cand.unit_id):
        return True
    return False


def _list_name_matches(cand: CandidateTarget, source: SourceIdentity) -> bool:
    src = normalize_ar_text(source.evaluation_list_name)
    if not src:
        return False
    return src == normalize_ar_text(cand.list_name)


def _type_matches(cand: CandidateTarget, source: SourceIdentity) -> bool:
    src = normalize_ar_text(source.evaluation_type)
    if not src:
        return True
    return src == normalize_ar_text(cand.evaluation_type)


def _stage_matches(cand: CandidateTarget, source: SourceIdentity) -> bool:
    src = normalize_ar_text(source.stage_id) or normalize_ar_text(source.stage_name)
    if not src:
        return True
    return src in (
        normalize_ar_text(cand.stage_id),
        normalize_ar_text(cand.stage_name),
    )


def _dilemma_matches(cand: CandidateTarget, source: SourceIdentity) -> bool:
    if source.dilemma_id and cand.dilemma_id and int(source.dilemma_id) == int(cand.dilemma_id):
        return True
    src = normalize_ar_text(source.dilemma_name)
    if not src:
        return True
    return src == normalize_ar_text(cand.dilemma_name)


def _judge_matches(cand: CandidateTarget, source: SourceIdentity) -> bool:
    if source.judge_id and cand.judge_id and int(source.judge_id) == int(cand.judge_id):
        return True
    src = normalize_ar_text(source.judge_name)
    if src and src == normalize_ar_text(cand.judge_name):
        return True
    return False


def _lookup_mapping(db: Session, source: SourceIdentity, current_exercise_id: int | None):
    from app.models.tablet_transfer import TabletIdentityMapping

    q = db.query(TabletIdentityMapping)
    if current_exercise_id:
        q = q.filter(TabletIdentityMapping.target_exercise_id == int(current_exercise_id))
    src_ex = source.exercise_id
    src_eval = source.eval_item_id
    src_unit = (source.unit_id or "").strip() or normalize_ar_text(source.unit_name)
    rows = q.order_by(TabletIdentityMapping.id.desc()).all()
    for row in rows:
        if src_ex and row.source_exercise_id and int(row.source_exercise_id) != int(src_ex):
            continue
        if src_eval and row.source_eval_item_id and int(row.source_eval_item_id) != int(src_eval):
            continue
        row_unit = (row.source_unit_id or "").strip() or normalize_ar_text(row.source_unit_name)
        if src_unit and row_unit and normalize_ar_text(src_unit) != normalize_ar_text(row_unit):
            continue
        src_list = normalize_ar_text(source.evaluation_list_name)
        row_list = normalize_ar_text(row.source_eval_name)
        if src_list and row_list and src_list != row_list:
            continue
        return row
    return None


def load_candidates(
    db: Session,
    *,
    current_exercise_id: int | None,
    evaluation_type: str = "",
) -> list[CandidateTarget]:
    from app.models import EvaluationListPdfItem

    q = db.query(EvaluationListPdfItem)
    if current_exercise_id:
        q = q.filter(EvaluationListPdfItem.exercise_id == int(current_exercise_id))
    items = q.all()
    out: list[CandidateTarget] = []
    for item in items:
        saved = _saved_for(db, current_exercise_id, int(item.id))
        cand = _item_to_candidate(db, item, saved)
        if evaluation_type and not _type_matches(cand, SourceIdentity(evaluation_type=evaluation_type)):
            if normalize_ar_text(evaluation_type) not in ("", "evaluation_list", "قائمة تقييم الإجراءات"):
                continue
        out.append(cand)
    return out


def match_evaluation(
    db: Session,
    source: SourceIdentity,
    *,
    current_exercise_id: int | None,
    candidates: Iterable[CandidateTarget] | None = None,
    allow_approved_overwrite: bool = False,
) -> MatchResult:
    pool = list(candidates) if candidates is not None else load_candidates(
        db, current_exercise_id=current_exercise_id, evaluation_type=source.evaluation_type
    )

    mapping = _lookup_mapping(db, source, current_exercise_id)
    if mapping is not None:
        target_id = int(mapping.target_eval_item_id)
        mapped = next((c for c in pool if c.eval_item_id == target_id), None)
        if mapped is None:
            from app.models import EvaluationListPdfItem

            item = db.get(EvaluationListPdfItem, target_id)
            if item is not None and _relationships_valid(item, source, current_exercise_id):
                mapped = _item_to_candidate(
                    db, item, _saved_for(db, current_exercise_id, target_id)
                )
        if mapped is not None:
            return _finish(
                mapped,
                "MATCHED_EXACT",
                "MANUAL_MAPPING",
                allow_approved_overwrite=allow_approved_overwrite,
                mapping_id=int(mapping.id),
            )

    if source.eval_item_id:
        from_pool = next(
            (c for c in pool if int(c.eval_item_id) == int(source.eval_item_id)),
            None,
        )
        if from_pool is not None:
            if source.unit_id and from_pool.unit_id and source.unit_id != from_pool.unit_id:
                from_pool = None
            elif current_exercise_id and from_pool.exercise_id and int(from_pool.exercise_id) != int(current_exercise_id):
                from_pool = None
        if from_pool is not None:
            return _finish(
                from_pool,
                "MATCHED_EXACT",
                "EXACT_ID",
                allow_approved_overwrite=allow_approved_overwrite,
            )
        from app.models import EvaluationListPdfItem

        item = db.get(EvaluationListPdfItem, int(source.eval_item_id))
        if item is not None and _relationships_valid(item, source, current_exercise_id):
            cand = _item_to_candidate(
                db, item, _saved_for(db, current_exercise_id, int(item.id))
            )
            return _finish(
                cand,
                "MATCHED_EXACT",
                "EXACT_ID",
                allow_approved_overwrite=allow_approved_overwrite,
            )

    unit_hits = [c for c in pool if _unit_matches(c, source)]
    if not unit_hits:
        return _result("NOT_FOUND", "NO_UNIT")

    named = [c for c in unit_hits if _list_name_matches(c, source)]
    typed = [c for c in named if _type_matches(c, source)] if named else []
    working = typed or named

    if working:
        staged = [c for c in working if _stage_matches(c, source)]
        if source.stage_id or source.stage_name:
            if len(staged) == 1:
                return _finish(
                    staged[0],
                    "MATCHED_BY_CONTEXT",
                    "UNIT+LIST+STAGE",
                    allow_approved_overwrite=allow_approved_overwrite,
                )
            if len(staged) > 1:
                working = staged
        dilemmaed = [c for c in working if _dilemma_matches(c, source)]
        if source.dilemma_id or source.dilemma_name:
            if len(dilemmaed) == 1:
                return _finish(
                    dilemmaed[0],
                    "MATCHED_BY_CONTEXT",
                    "UNIT+LIST+DILEMMA",
                    allow_approved_overwrite=allow_approved_overwrite,
                )
            if len(dilemmaed) > 1:
                working = dilemmaed
        if len(working) == 1:
            method = "UNIT+LIST+TYPE" if typed else "UNIT+LIST"
            return _finish(
                working[0],
                "MATCHED_BY_UNIT_LIST",
                method,
                allow_approved_overwrite=allow_approved_overwrite,
            )
        judged = [c for c in working if _judge_matches(c, source)]
        if len(judged) == 1 and len(working) > 1:
            return _result(
                "AMBIGUOUS",
                "JUDGE_SUPPORT_ONLY",
                candidates=working,
                conflicts=["القاضي إشارة داعمة فقط — القوائم المتشابهة تتطلب مراجعة"],
            )
        return _result("AMBIGUOUS", "MULTIPLE_LIST_NAME", candidates=working)

    if source.evaluation_list_name:
        similar = unit_hits
        if len(similar) == 1:
            return _result(
                "REVIEW_REQUIRED",
                "UNIT_ONLY",
                candidates=similar,
            )
        return _result(
            "REVIEW_REQUIRED",
            "UNIT_NO_UNIQUE_LIST",
            candidates=similar[:20],
        )

    if len(unit_hits) == 1:
        return _result("REVIEW_REQUIRED", "UNIT_ONLY", candidates=unit_hits)
    return _result("REVIEW_REQUIRED", "UNIT_MANY", candidates=unit_hits[:20])


def _finish(
    target: CandidateTarget,
    status: str,
    method: str,
    *,
    allow_approved_overwrite: bool,
    mapping_id: int | None = None,
) -> MatchResult:
    if (target.approved or target.chief_approved) and not allow_approved_overwrite:
        return _result(
            "CONFLICT",
            method,
            target=target,
            candidates=[target],
            conflicts=[APPROVED_CONFLICT_AR],
            mapping_id=mapping_id,
        )
    return _result(status, method, target=target, candidates=[target], mapping_id=mapping_id)


def remember_mapping(
    db: Session,
    source: SourceIdentity,
    target: CandidateTarget,
    *,
    operator_id: int | None,
    current_exercise_id: int | None,
) -> int:
    from app.models.tablet_transfer import TabletIdentityMapping

    row = TabletIdentityMapping(
        source_exercise_id=source.exercise_id,
        source_exercise_name=source.exercise_name[:256],
        source_unit_id=(source.unit_id or "")[:128],
        source_unit_name=(source.unit_name or "")[:256],
        source_eval_item_id=source.eval_item_id,
        source_eval_name=(source.evaluation_list_name or "")[:500],
        source_eval_type=(source.evaluation_type or "")[:64],
        source_device_id=(source.device_id or "")[:128],
        target_exercise_id=current_exercise_id or target.exercise_id,
        target_unit_id=(target.unit_id or "")[:128],
        target_eval_item_id=int(target.eval_item_id),
        created_by_id=operator_id,
    )
    db.add(row)
    db.flush()
    return int(row.id)


def record_transfer_audit(
    db: Session,
    *,
    operation_type: str,
    device_id: str = "",
    judge_id: int | None = None,
    unit_id: str = "",
    exercise_id: int | None = None,
    source_eval_item_id: int | None = None,
    target_eval_item_id: int | None = None,
    match_method: str = "",
    match_status: str = "",
    mapping_id: int | None = None,
    operator_id: int | None = None,
    package_hash: str = "",
    client_op_id: str = "",
    details: str = "",
) -> None:
    from app.models.tablet_transfer import TabletTransferAudit

    db.add(
        TabletTransferAudit(
            operation_type=(operation_type or "")[:32],
            device_id=(device_id or "")[:128],
            judge_id=judge_id,
            unit_id=(unit_id or "")[:128],
            exercise_id=exercise_id,
            source_eval_item_id=source_eval_item_id,
            target_eval_item_id=target_eval_item_id,
            match_method=(match_method or "")[:64],
            match_status=(match_status or "")[:32],
            mapping_id=mapping_id,
            operator_id=operator_id,
            package_hash=(package_hash or "")[:64],
            client_op_id=(client_op_id or "")[:128],
            details=(details or "")[:4000],
        )
    )
