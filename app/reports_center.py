"""مركز التقارير — قراءة فقط لعناصر التقييم في التمرين الحالي."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.eval_judge_attribution import user_is_admin_attribution_source
from app.evaluation_list_columns import (
    display_grade_label,
    grade_label_from_percent,
    payload_row_score_pct,
)
from app.evaluation_workflow import (
    _evaluation_home_items_bundle,
    filter_evaluation_items_by_phase,
)
from app.exercise_phase_catalog import (
    exercise_phase_keys,
    exercise_phase_label,
    normalize_exercise_phase,
)
from app.models import (
    Exercise,
    ExercisePlannerFlowBundle,
    ExercisePlannerFlowBundleActionEval,
    ExerciseRosterKind,
    ExerciseRosterRow,
    PlannerFlowBundleEvalSavedResult,
    User,
)
from app.unit_levels_catalog import UNIT_LEVELS, label_for_unit_level_key

KIND_PROCEDURE = "procedure"
KIND_DILEMMA = "dilemma"
KIND_LABELS = {
    KIND_PROCEDURE: "قوائم تقييم الإجراءات",
    KIND_DILEMMA: "قوائم تقييم المعاضل",
}
CONTEXT_TITLES = {
    KIND_PROCEDURE: "تقارير قوائم تقييم الإجراءات",
    KIND_DILEMMA: "تقارير قوائم تقييم المعاضل",
}

# مصطلحات النظام الفعلية (grade_label_from_percent) — ليست «جيد جداً».
RATING_ORDER = ("ممتاز", "جيد جدا", "جيد", "مقبول", "راسب")
RATING_ALIASES = {
    "جيد جداً": "جيد جدا",
    "جيد جداٌ": "جيد جدا",
    "متوسط": "مقبول",
}

ORGANIZE_UNIFIED = "unified"
ORGANIZE_UNIT = "unit"
ORGANIZE_JUDGE = "judge"
ORGANIZE_LIST = "list"
ORGANIZE_LABELS = {
    ORGANIZE_UNIFIED: "جدول موحد",
    ORGANIZE_UNIT: "حسب الوحدة",
    ORGANIZE_JUDGE: "حسب المحكم",
    ORGANIZE_LIST: "حسب قائمة التقييم",
}

REPORT_TYPE_EXISTING = "existing_excel"
REPORT_TYPE_DETAILED = "detailed"
REPORT_TYPE_WEAKNESS = "weakness"
REPORT_TYPE_HIGH = "high_performance"
REPORT_TYPE_FULL = "full"
REPORT_TYPE_LABELS = {
    REPORT_TYPE_EXISTING: "تصدير النتائج إلى Excel",
    REPORT_TYPE_DETAILED: "تقرير نتائج التقييم التفصيلي",
    REPORT_TYPE_WEAKNESS: "تقرير نقاط الضعف",
    REPORT_TYPE_HIGH: "تقرير الأداء العالي",
    REPORT_TYPE_FULL: "التقرير الشامل",
}
PRESET_RATINGS = {
    REPORT_TYPE_WEAKNESS: ("مقبول", "راسب"),
    REPORT_TYPE_HIGH: ("ممتاز", "جيد جدا"),
    REPORT_TYPE_FULL: RATING_ORDER,
    REPORT_TYPE_DETAILED: RATING_ORDER,
}

ALL_PHASES = ""
ALL_UNITS = ""
ALL_JUDGES = ""
ALL_LISTS = ""

SCOPE_NOTE = (
    "النتائج المحفوظة (المعتمدة وبانتظار الاعتماد). "
    "البنود غير المدخلة و«لا ينطبق» غير مدرجة."
)

_UNSAFE_FILE_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def normalize_rating_label(raw: str | None) -> str:
    g = display_grade_label(raw)
    return RATING_ALIASES.get(g, g)


def ratings_from_preset(report_type: str) -> tuple[str, ...]:
    return PRESET_RATINGS.get(report_type, RATING_ORDER)


@dataclass
class ReportScope:
    exercise_id: int
    exercise_name: str
    kind: str
    allow_unit_keys: set[str] | None = None
    allow_phase_key: str | None = None
    owned_item_ids: set[int] | None = None


@dataclass
class ReportFilters:
    phase_key: str = ALL_PHASES
    unit_key: str = ALL_UNITS
    judge_key: str = ALL_JUDGES
    list_key: str = ALL_LISTS
    ratings: tuple[str, ...] = RATING_ORDER
    show_notes: bool = True
    notes_only: bool = False
    organize: str = ORGANIZE_UNIFIED
    report_type: str = REPORT_TYPE_DETAILED

    def rating_set(self) -> set[str]:
        return {normalize_rating_label(r) for r in self.ratings if normalize_rating_label(r)}


@dataclass
class ReportItem:
    kind: str
    phase_key: str
    phase_label: str
    unit_key: str
    unit_label: str
    judge_key: str
    judge_label: str
    list_key: str
    list_title: str
    element: str
    rating: str
    notes: str
    pct: float | None = None


@dataclass
class ReportListRecord:
    kind: str
    list_key: str
    list_title: str
    phase_key: str
    phase_label: str
    unit_key: str
    unit_label: str
    judge_key: str
    judge_label: str
    payload_json: str


def parse_report_filters(payload: dict | None) -> ReportFilters:
    data = payload if isinstance(payload, dict) else {}
    report_type = str(data.get("report_type") or REPORT_TYPE_DETAILED).strip()
    if report_type not in REPORT_TYPE_LABELS:
        report_type = REPORT_TYPE_DETAILED
    raw_ratings = data.get("ratings")
    if raw_ratings is None and report_type in PRESET_RATINGS:
        ratings = ratings_from_preset(report_type)
    elif isinstance(raw_ratings, (list, tuple)):
        ratings = tuple(
            normalize_rating_label(str(x))
            for x in raw_ratings
            if normalize_rating_label(str(x)) in RATING_ORDER
        )
    else:
        ratings = RATING_ORDER
    organize = str(data.get("organize") or ORGANIZE_UNIFIED).strip()
    if organize not in ORGANIZE_LABELS:
        organize = ORGANIZE_UNIFIED
    show_notes = _as_bool(data.get("show_notes"), default=True)
    notes_only = _as_bool(data.get("notes_only"), default=False)
    return ReportFilters(
        phase_key=str(data.get("phase_key") or "").strip(),
        unit_key=str(data.get("unit_key") or "").strip(),
        judge_key=str(data.get("judge_key") or "").strip(),
        list_key=str(data.get("list_key") or "").strip(),
        ratings=ratings,
        show_notes=show_notes,
        notes_only=notes_only,
        organize=organize,
        report_type=report_type,
    )


def _as_bool(raw, *, default: bool) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    s = str(raw).strip().lower()
    if s in {"1", "true", "yes", "on"}:
        return True
    if s in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_payload_rows(payload_json: str | None) -> list[dict]:
    if not (payload_json or "").strip():
        return []
    try:
        data = json.loads(payload_json)
    except (TypeError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    rows = data.get("rows") or []
    return rows if isinstance(rows, list) else []


def _row_element_label(row: dict) -> str:
    for key in ("element", "text", "criterion", "label", "title"):
        val = str(row.get(key) or "").strip()
        if val:
            return val
    return ""


def _is_na_acquired(acq) -> bool:
    s = ("" if acq is None else str(acq)).strip().lower()
    return s in {"na", "n/a", "لا ينطبق"}


def _phase_label(phase_key: str) -> str:
    pk = (phase_key or "").strip()
    if not pk:
        return "بدون مرحلة"
    return (exercise_phase_label(pk) or pk).strip() or pk


def _unit_label(unit_key: str) -> str:
    uk = (unit_key or "").strip()
    return (label_for_unit_level_key(uk) or uk or "—").strip() or "—"


def _judge_label_from_user(user: User | None) -> str:
    if user is None or user_is_admin_attribution_source(user):
        return ""
    return (user.full_name or "").strip() or (user.username or "").strip()


def _judge_label_from_roster(row: ExerciseRosterRow | None) -> str:
    if row is None:
        return ""
    name = (row.full_name or "").strip()
    rank = (row.rank_ar or "").strip()
    if rank and name and rank not in name:
        return f"{rank} {name}"
    return name or rank


def _judge_key(label: str) -> str:
    return (label or "").strip() or "—"


class _JudgeResolver:
    def __init__(self, db: Session, exercise_id: int):
        self._users: dict[int, User] = {}
        self._roster: list[ExerciseRosterRow] = (
            db.query(ExerciseRosterRow)
            .filter(
                ExerciseRosterRow.exercise_id == int(exercise_id),
                ExerciseRosterRow.roster_kind == ExerciseRosterKind.JUDGE.value,
            )
            .order_by(ExerciseRosterRow.sort_order, ExerciseRosterRow.id)
            .all()
        )

    def preload_users(self, db: Session, user_ids: set[int]) -> None:
        want = [i for i in user_ids if i and i not in self._users]
        if not want:
            return
        for u in db.query(User).filter(User.id.in_(want)).all():
            self._users[int(u.id)] = u

    def resolve(self, *, unit_key: str, phase_key: str, saved) -> str:
        if saved is not None:
            for attr in ("approved_by_id", "saved_by_id"):
                uid = getattr(saved, attr, None)
                if uid is None:
                    continue
                label = _judge_label_from_user(self._users.get(int(uid)))
                if label:
                    return label
        uk = (unit_key or "").strip()
        pk = normalize_exercise_phase(phase_key) or (phase_key or "").strip()
        if pk:
            for jr in self._roster:
                if (jr.unit_level_key or "").strip() != uk:
                    continue
                jr_pk = normalize_exercise_phase(jr.exercise_phase) or (jr.exercise_phase or "").strip()
                if jr_pk == pk:
                    label = _judge_label_from_roster(jr)
                    if label:
                        return label
        for jr in self._roster:
            if (jr.unit_level_key or "").strip() == uk:
                label = _judge_label_from_roster(jr)
                if label:
                    return label
        return "—"


def collect_report_lists(db: Session, ex: Exercise, scope: ReportScope) -> list[ReportListRecord]:
    if scope.kind == KIND_DILEMMA:
        return _collect_dilemma_lists(db, ex, scope)
    return _collect_procedure_lists(db, ex, scope)


def _scope_allows_unit(scope: ReportScope, unit_key: str) -> bool:
    if scope.allow_unit_keys is None:
        return True
    return (unit_key or "").strip() in scope.allow_unit_keys


def _collect_procedure_lists(db: Session, ex: Exercise, scope: ReportScope) -> list[ReportListRecord]:
    items, canonical = _evaluation_home_items_bundle(db, ex)
    if scope.owned_item_ids is not None:
        items = [it for it in items if int(it.id) in scope.owned_item_ids]
    items = [
        it
        for it in items
        if _scope_allows_unit(scope, getattr(it, "unit_level_key", None) or "")
    ]
    if scope.allow_phase_key:
        items = filter_evaluation_items_by_phase(items, scope.allow_phase_key)
    user_ids: set[int] = set()
    for it in items:
        saved = canonical.get(int(it.id))
        if saved is None:
            continue
        for attr in ("approved_by_id", "saved_by_id"):
            uid = getattr(saved, attr, None)
            if uid is not None:
                user_ids.add(int(uid))
    resolver = _JudgeResolver(db, int(ex.id))
    resolver.preload_users(db, user_ids)
    out: list[ReportListRecord] = []
    for it in items:
        uk = (getattr(it, "unit_level_key", None) or "").strip()
        raw_phase = (getattr(it, "exercise_phase", None) or "").strip()
        pk = normalize_exercise_phase(raw_phase) or raw_phase
        saved = canonical.get(int(it.id))
        judge = resolver.resolve(unit_key=uk, phase_key=pk, saved=saved)
        title = (getattr(it, "text", None) or "قائمة تقييم إجراءات").strip() or "قائمة تقييم إجراءات"
        out.append(
            ReportListRecord(
                kind=KIND_PROCEDURE,
                list_key=f"proc:{int(it.id)}",
                list_title=title,
                phase_key=pk,
                phase_label=_phase_label(pk),
                unit_key=uk,
                unit_label=_unit_label(uk),
                judge_key=_judge_key(judge),
                judge_label=judge,
                payload_json=(getattr(saved, "payload_json", None) or "") if saved is not None else "",
            )
        )
    return out


def _collect_dilemma_lists(db: Session, ex: Exercise, scope: ReportScope) -> list[ReportListRecord]:
    from app.action_eval_ibank_sync import format_action_eval_judge_list_title

    bundles = (
        db.query(ExercisePlannerFlowBundle)
        .filter(ExercisePlannerFlowBundle.exercise_id == int(ex.id))
        .all()
    )
    if not bundles:
        return []
    bundle_by_id = {int(b.id): b for b in bundles}
    slots = (
        db.query(ExercisePlannerFlowBundleActionEval)
        .filter(ExercisePlannerFlowBundleActionEval.bundle_id.in_(list(bundle_by_id)))
        .order_by(
            ExercisePlannerFlowBundleActionEval.slot_index,
            ExercisePlannerFlowBundleActionEval.id,
        )
        .all()
    )
    saved_rows = (
        db.query(PlannerFlowBundleEvalSavedResult)
        .filter(PlannerFlowBundleEvalSavedResult.exercise_id == int(ex.id))
        .order_by(
            PlannerFlowBundleEvalSavedResult.updated_at.desc(),
            PlannerFlowBundleEvalSavedResult.id.desc(),
        )
        .all()
    )
    saved_by_slot: dict[int, PlannerFlowBundleEvalSavedResult] = {}
    user_ids: set[int] = set()
    for row in saved_rows:
        sid = int(row.bundle_action_eval_id)
        if sid in saved_by_slot:
            continue
        saved_by_slot[sid] = row
        for attr in ("approved_by_id", "saved_by_id"):
            uid = getattr(row, attr, None)
            if uid is not None:
                user_ids.add(int(uid))
    resolver = _JudgeResolver(db, int(ex.id))
    resolver.preload_users(db, user_ids)
    out: list[ReportListRecord] = []
    seen: set[int] = set()
    for slot in slots:
        sid = int(slot.id)
        if sid in seen:
            continue
        seen.add(sid)
        bundle = bundle_by_id.get(int(slot.bundle_id))
        if bundle is None:
            continue
        uk = (bundle.unit_level_key or "").strip()
        if not _scope_allows_unit(scope, uk):
            continue
        raw_phase = (bundle.exercise_phase or "").strip()
        pk = normalize_exercise_phase(raw_phase) or raw_phase
        if scope.allow_phase_key:
            want = normalize_exercise_phase(scope.allow_phase_key) or scope.allow_phase_key
            if pk != want:
                continue
        saved = saved_by_slot.get(sid)
        judge = resolver.resolve(unit_key=uk, phase_key=pk, saved=saved)
        title = format_action_eval_judge_list_title(
            stored_title=slot.title,
            source_title=slot.title,
        )
        title = (title or slot.title or "قائمة تقييم معضلة").strip() or "قائمة تقييم معضلة"
        out.append(
            ReportListRecord(
                kind=KIND_DILEMMA,
                list_key=f"dil:{sid}",
                list_title=title,
                phase_key=pk,
                phase_label=_phase_label(pk),
                unit_key=uk,
                unit_label=(bundle.unit_level_label or "").strip() or _unit_label(uk),
                judge_key=_judge_key(judge),
                judge_label=judge,
                payload_json=(getattr(saved, "payload_json", None) or "") if saved is not None else "",
            )
        )
    return out


def explode_scored_items(record: ReportListRecord) -> list[ReportItem]:
    items: list[ReportItem] = []
    for idx, row in enumerate(_parse_payload_rows(record.payload_json)):
        if not isinstance(row, dict):
            continue
        if str(row.get("row_kind") or "score").strip().lower() == "section":
            continue
        if _is_na_acquired(row.get("acquired")):
            continue
        pct = payload_row_score_pct(row)
        if pct is None:
            continue
        rating = normalize_rating_label(grade_label_from_percent(pct))
        if rating not in RATING_ORDER:
            continue
        notes = str(row.get("notes") or "").strip()
        element = _row_element_label(row) or f"بند {idx + 1}"
        items.append(
            ReportItem(
                kind=record.kind,
                phase_key=record.phase_key,
                phase_label=record.phase_label,
                unit_key=record.unit_key,
                unit_label=record.unit_label,
                judge_key=record.judge_key,
                judge_label=record.judge_label,
                list_key=record.list_key,
                list_title=record.list_title,
                element=element,
                rating=rating,
                notes=notes,
                pct=pct,
            )
        )
    return items


def _list_matches_filters(record: ReportListRecord, filters: ReportFilters) -> bool:
    if filters.phase_key and (record.phase_key or "") != filters.phase_key:
        return False
    if filters.unit_key and (record.unit_key or "") != filters.unit_key:
        return False
    if filters.judge_key and record.judge_key != filters.judge_key:
        return False
    if filters.list_key and record.list_key != filters.list_key:
        return False
    return True


def filter_report_items(items: list[ReportItem], filters: ReportFilters) -> list[ReportItem]:
    wanted = filters.rating_set()
    out: list[ReportItem] = []
    for it in items:
        if wanted and it.rating not in wanted:
            continue
        if filters.notes_only and not (it.notes or "").strip():
            continue
        if not filters.show_notes:
            it = ReportItem(
                kind=it.kind,
                phase_key=it.phase_key,
                phase_label=it.phase_label,
                unit_key=it.unit_key,
                unit_label=it.unit_label,
                judge_key=it.judge_key,
                judge_label=it.judge_label,
                list_key=it.list_key,
                list_title=it.list_title,
                element=it.element,
                rating=it.rating,
                notes="",
                pct=it.pct,
            )
        out.append(it)
    return out


def query_report_items(
    db: Session, ex: Exercise, scope: ReportScope, filters: ReportFilters
) -> list[ReportItem]:
    records = [r for r in collect_report_lists(db, ex, scope) if _list_matches_filters(r, filters)]
    items: list[ReportItem] = []
    for rec in records:
        items.extend(explode_scored_items(rec))
    return filter_report_items(items, filters)


def rating_counts(items: list[ReportItem]) -> dict[str, int]:
    counts = {k: 0 for k in RATING_ORDER}
    for it in items:
        if it.rating in counts:
            counts[it.rating] += 1
    return counts


def rating_percentages(counts: dict[str, int]) -> dict[str, float]:
    total = sum(counts.values())
    if total <= 0:
        return {k: 0.0 for k in RATING_ORDER}
    return {k: round(100.0 * counts[k] / total, 1) for k in RATING_ORDER}


def _group_counts(items: list[ReportItem], key_fn) -> list[dict]:
    buckets: dict[tuple, dict] = {}
    order: list[tuple] = []
    for it in items:
        key = key_fn(it)
        if key not in buckets:
            buckets[key] = {
                "total": 0,
                "counts": {k: 0 for k in RATING_ORDER},
                "meta": key,
            }
            order.append(key)
        buckets[key]["total"] += 1
        if it.rating in buckets[key]["counts"]:
            buckets[key]["counts"][it.rating] += 1
    rows = []
    for key in order:
        b = buckets[key]
        total = b["total"]
        pcts = {
            k: (round(100.0 * b["counts"][k] / total, 1) if total else 0.0)
            for k in RATING_ORDER
        }
        rows.append({"key": key, "total": total, "counts": b["counts"], "pcts": pcts})
    return rows


def unit_summary_rows(items: list[ReportItem]) -> list[dict]:
    rows = []
    for block in _group_counts(items, lambda it: (it.unit_label, it.unit_key)):
        unit_label, unit_key = block["key"]
        rows.append(
            {
                "unit_label": unit_label,
                "unit_key": unit_key,
                "total": block["total"],
                "counts": block["counts"],
                "pcts": block["pcts"],
            }
        )
    return rows


def judge_summary_rows(items: list[ReportItem]) -> list[dict]:
    rows = []
    for block in _group_counts(
        items, lambda it: (it.judge_label, it.unit_label, it.judge_key)
    ):
        judge_label, unit_label, judge_key = block["key"]
        rows.append(
            {
                "judge_label": judge_label,
                "unit_label": unit_label,
                "judge_key": judge_key,
                "total": block["total"],
                "counts": block["counts"],
            }
        )
    return rows


def list_summary_rows(items: list[ReportItem]) -> list[dict]:
    rows = []
    for block in _group_counts(
        items,
        lambda it: (it.list_title, it.unit_label, it.judge_label, it.list_key),
    ):
        list_title, unit_label, judge_label, list_key = block["key"]
        rows.append(
            {
                "list_title": list_title,
                "unit_label": unit_label,
                "judge_label": judge_label,
                "list_key": list_key,
                "total": block["total"],
                "counts": block["counts"],
            }
        )
    return rows


def filter_catalog(records: list[ReportListRecord]) -> dict:
    phases: dict[str, str] = {}
    for key in exercise_phase_keys():
        phases[key] = _phase_label(key)
    units: dict[str, str] = {}
    for row in UNIT_LEVELS:
        uk = (row.get("key") or "").strip()
        if uk:
            units[uk] = (row.get("label") or uk).strip() or uk
    judges: dict[str, str] = {}
    lists: list[dict] = []
    for rec in records:
        if rec.phase_key and rec.phase_key not in phases:
            phases[rec.phase_key] = rec.phase_label
        if rec.unit_key and rec.unit_key not in units:
            units[rec.unit_key] = rec.unit_label
        judges[rec.judge_key] = rec.judge_label
        lists.append(
            {
                "list_key": rec.list_key,
                "list_label": rec.list_title,
                "phase_key": rec.phase_key,
                "phase_label": rec.phase_label,
                "unit_key": rec.unit_key,
                "unit_label": rec.unit_label,
                "judge_key": rec.judge_key,
                "judge_label": rec.judge_label,
            }
        )
    used_phases = {r.phase_key for r in records if r.phase_key}
    used_units = {r.unit_key for r in records if r.unit_key}
    phase_options = [
        {"key": k, "label": phases[k]}
        for k in list(phases)
        if k in used_phases or k in exercise_phase_keys()
    ]
    if used_phases:
        extra = [k for k in used_phases if k not in {p["key"] for p in phase_options}]
        for k in extra:
            phase_options.append({"key": k, "label": phases.get(k) or _phase_label(k)})
    unit_options = []
    seen_units: set[str] = set()
    for row in UNIT_LEVELS:
        uk = (row.get("key") or "").strip()
        if uk and uk in used_units and uk not in seen_units:
            unit_options.append({"key": uk, "label": units.get(uk) or _unit_label(uk)})
            seen_units.add(uk)
    for k in used_units:
        if k not in seen_units:
            unit_options.append({"key": k, "label": units.get(k) or _unit_label(k)})
            seen_units.add(k)
    judge_options = [{"key": k, "label": v} for k, v in judges.items()]
    return {
        "phases": phase_options,
        "units": unit_options,
        "judges": judge_options,
        "lists": lists,
        "ratings": list(RATING_ORDER),
        "scope_note": SCOPE_NOTE,
    }


def item_to_preview_row(item: ReportItem, seq: int) -> dict:
    return {
        "seq": seq,
        "phase": item.phase_label,
        "unit": item.unit_label,
        "judge": item.judge_label,
        "list_title": item.list_title,
        "element": item.element,
        "rating": item.rating,
        "notes": item.notes,
        "kind": item.kind,
        "phase_key": item.phase_key,
        "unit_key": item.unit_key,
        "judge_key": item.judge_key,
        "list_key": item.list_key,
    }


def build_report_payload(
    *,
    scope: ReportScope,
    filters: ReportFilters,
    items: list[ReportItem],
    generated_at: datetime | None = None,
) -> dict:
    counts = rating_counts(items)
    pcts = rating_percentages(counts)
    generated = generated_at or datetime.now()
    return {
        "exercise_name": scope.exercise_name,
        "kind": scope.kind,
        "kind_label": KIND_LABELS.get(scope.kind, scope.kind),
        "context_title": CONTEXT_TITLES.get(scope.kind, "التقارير"),
        "report_type": filters.report_type,
        "report_type_label": REPORT_TYPE_LABELS.get(filters.report_type, filters.report_type),
        "phase_label": _phase_label(filters.phase_key) if filters.phase_key else "جميع المراحل",
        "unit_label": _unit_label(filters.unit_key) if filters.unit_key else "جميع الوحدات",
        "judge_label": filters.judge_key or "جميع المحكمين",
        "list_label": "جميع القوائم",
        "ratings_selected": list(filters.ratings),
        "show_notes": filters.show_notes,
        "notes_only": filters.notes_only,
        "organize": filters.organize,
        "organize_label": ORGANIZE_LABELS.get(filters.organize, filters.organize),
        "generated_at": generated.strftime("%Y-%m-%d %H:%M"),
        "generated_date": generated.strftime("%Y-%m-%d"),
        "scope_note": SCOPE_NOTE,
        "total": len(items),
        "counts": counts,
        "percentages": pcts,
        "unit_summary": unit_summary_rows(items),
        "judge_summary": judge_summary_rows(items),
        "list_summary": list_summary_rows(items),
        "rows": [item_to_preview_row(it, i) for i, it in enumerate(items, start=1)],
        "items": items,
    }


def run_report(db: Session, ex: Exercise, scope: ReportScope, filters: ReportFilters) -> dict:
    items = query_report_items(db, ex, scope, filters)
    payload = build_report_payload(scope=scope, filters=filters, items=items)
    if filters.list_key:
        for rec in collect_report_lists(db, ex, scope):
            if rec.list_key == filters.list_key:
                payload["list_label"] = rec.list_title
                break
    if filters.judge_key:
        payload["judge_label"] = filters.judge_key
        for it in items:
            payload["judge_label"] = it.judge_label
            break
        if not items:
            for rec in collect_report_lists(db, ex, scope):
                if rec.judge_key == filters.judge_key:
                    payload["judge_label"] = rec.judge_label
                    break
    return payload


def report_filename(kind: str, report_type: str, when: datetime | None = None) -> str:
    stamp = (when or datetime.now()).strftime("%Y-%m-%d")
    kind_part = "الإجراءات" if kind == KIND_PROCEDURE else "المعاضل"
    type_part = {
        REPORT_TYPE_WEAKNESS: "نقاط_الضعف",
        REPORT_TYPE_HIGH: "الأداء_العالي",
        REPORT_TYPE_FULL: "الشامل",
    }.get(report_type, "نتائج")
    name = f"تقرير_{type_part}_قوائم_{kind_part}_{stamp}.xlsx"
    return _UNSAFE_FILE_RE.sub("_", name)
