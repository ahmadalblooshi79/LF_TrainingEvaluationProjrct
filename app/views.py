import hashlib
import io
import json
import mimetypes
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, unquote

from flask import (
    Blueprint,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.utils import secure_filename
from sqlalchemy import delete, desc, func
from sqlalchemy.orm import joinedload

from app.config import CHAT_UPLOAD_DIR, DILEMMA_PDF_DIR, EVALUATION_LIST_XLSX_DIR, VISUAL_DOC_DIR
from app.auth import get_current_user_optional, hash_password, verify_password
from app.models import (
    ChatMessage,
    ChatMessageRead,
    ChatRoom,
    ChatRoomKind,
    ChatRoomMember,
    Exercise,
    ExerciseBattleUnitPersonnel,
    ExerciseObjective,
    ExercisePhase,
    ExerciseRosterKind,
    ExerciseRosterRow,
    ExerciseStatus,
    DilemmaItem,
    EvaluationListPdfItem,
    EvaluationListSavedResult,
    ExerciseNotification,
    VisualDocument,
    JudgeTraineeAssignment,
    Reference,
    RefType,
    RoleDef,
    RoleKey,
    User,
)
from app.permissions import (
    can_access_analyst_hub,
    can_access_control_hub,
    can_access_judge_hub,
    can_access_planner_hub,
    can_approve_evaluation_results,
    can_edit_references,
    can_judge_exercise,
    can_manage_chat_rooms,
    can_manage_users,
    can_plan_exercises,
    can_save_evaluation_results,
    can_use_chat_rooms,
    can_view_notifications_log,
    can_use_visual_documentation,
    is_analyst,
    is_control,
    is_judge,
    is_system_admin,
)
from app import exercise_options as ex_opts
from app.unit_levels_catalog import (
    UNIT_LEVELS,
    coerce_roster_import_position_cell,
    label_for_unit_level_key,
    normalize_unit_level_key,
)
from app.evaluation_list_columns import (
    acquired_select_options,
    grade_label_from_percent,
)
from app.evaluation_sheet_parser import read_evaluation_list_sheet
from app.roster_import import parse_roster_rows_from_upload
from app.exercise_store import (
    export_directory,
    extract_create_form_prefill_from_export_json,
    import_exercise_bundle_from_dict,
    list_export_json_files,
    open_export_directory_in_os,
    purge_all_exercises_and_dilemmas,
    read_exercise_id_from_json_bytes,
    read_exercise_id_from_json_path,
    write_exercise_json_file,
)
from app.seed import DEMO_PASSWORD
from app.battle_organization import BATTLE_ORG_DEMO_ROOT

bp = Blueprint("views", __name__)

def _dilemma_pdf_abspath(relpath: str) -> Path | None:
    """مسار ملف PDF تحت DILEMMA_PDF_DIR دون تجاوز الجذر."""
    if not relpath or not isinstance(relpath, str):
        return None
    norm = relpath.replace("\\", "/").strip()
    if not norm or any(part == ".." for part in norm.split("/")):
        return None
    root = DILEMMA_PDF_DIR.resolve()
    out = (root / norm).resolve()
    try:
        out.relative_to(root)
    except ValueError:
        return None
    return out if out.is_file() else None


def _unlink_dilemma_stored_pdf(relpath: str) -> None:
    p = _dilemma_pdf_abspath(relpath)
    if p is None:
        return
    try:
        p.unlink()
    except OSError:
        pass


def _evaluation_list_file_abspath(relpath: str) -> Path | None:
    if not relpath or not isinstance(relpath, str):
        return None
    norm = relpath.replace("\\", "/").strip()
    if not norm or any(part == ".." for part in norm.split("/")):
        return None
    root = EVALUATION_LIST_XLSX_DIR.resolve()
    out = (root / norm).resolve()
    try:
        out.relative_to(root)
    except ValueError:
        return None
    return out if out.is_file() else None


def _evaluation_sheet_view_context(fspath: Path) -> dict:
    """قراءة ملف قائمة التقييم مع اكتشاف قوالب الصفوف (القصوى/المكتسبة) تلقائيًا."""
    sheet = read_evaluation_list_sheet(fspath)
    es = bool(sheet.get("eval_structured"))
    return {
        "preview_error": sheet.get("error"),
        "sheet_title": sheet.get("sheet_title") or "",
        "header_row": sheet.get("header_row") or [],
        "body_rows": sheet.get("body_rows") or [],
        "eval_structured": es,
        "eval_column_source": sheet.get("eval_column_source"),
        "eval_rows": sheet.get("eval_rows") or [],
        "eval_input_mode": sheet.get("eval_input_mode") or "scale5",
        "eval_layout": sheet.get("eval_layout") or "legacy",
        "acquired_options": acquired_select_options() if es else [],
    }


def _unlink_evaluation_list_stored_file(relpath: str) -> None:
    p = _evaluation_list_file_abspath(relpath)
    if p is None:
        return
    try:
        p.unlink()
    except OSError:
        pass


def _is_pdf_bytes(data: bytes) -> bool:
    return bool(data) and data[:4] == b"%PDF"


def _is_xlsx_bytes(data: bytes) -> bool:
    """ملف Excel (.xlsx) هو أرشيف ZIP يحتوي [Content_Types].xml."""
    if not data or len(data) < 64:
        return False
    if data[:2] != b"PK":
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            return "[Content_Types].xml" in z.namelist()
    except zipfile.BadZipFile:
        return False


def _mimetype_for_eval_list_file(path: Path) -> str:
    n = path.name.lower()
    if n.endswith(".xlsx"):
        return (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    if n.endswith(".pdf"):
        return "application/pdf"
    return "application/octet-stream"


def _hashes_of_unit_pdfs(
    db,
    model,
    unit_key: str,
    abspath_fn,
    exercise_id: int | None = None,
    exercise_phase: str | None = None,
) -> set[str]:
    """SHA-256 لمحتوى كل ملف محفوظ لهذا المستوى داخل التمرين الحالي (لمنع تكرار الملف)."""
    out: set[str] = set()
    q = db.query(model).filter(model.unit_level_key == unit_key)
    if exercise_id is not None and hasattr(model, "exercise_id"):
        q = q.filter(model.exercise_id == exercise_id)
    if exercise_phase is not None and hasattr(model, "exercise_phase"):
        q = q.filter(model.exercise_phase == exercise_phase)
    for row in q.all():
        rel = (row.pdf_relpath or "").strip()
        if not rel:
            continue
        p = abspath_fn(rel)
        if p is None or not p.is_file():
            continue
        try:
            out.add(hashlib.sha256(p.read_bytes()).hexdigest())
        except OSError:
            pass
    return out


def _normalized_exercise_phase(val: str | None) -> str:
    v = (val or "").strip()
    if v == ExercisePhase.REORG.value:
        return ExercisePhase.REORG.value
    return ExercisePhase.MAIN.value


EXERCISE_PHASE_OPTIONS: list[tuple[str, str]] = [
    (ExercisePhase.MAIN.value, "التمرين الرئيسي"),
    (ExercisePhase.REORG.value, "إعادة التنظيم"),
]


def _admin_exercise_form_ctx() -> dict:
    return {
        "exercise_names": ex_opts.EXERCISE_NAMES,
        "exercise_types": ex_opts.EXERCISE_TYPES,
        "exercise_levels": ex_opts.EXERCISE_LEVELS,
        "missions": ex_opts.MISSIONS,
        "trained_units": ex_opts.TRAINED_UNITS,
        "exercise_locations": ex_opts.EXERCISE_LOCATIONS,
    }


def _empty_create_form_prefill() -> dict[str, str]:
    return {
        "trained_unit": "",
        "location_label": "",
        "exercise_name": "",
        "exercise_type": "",
        "exercise_level": "",
        "mission": "",
        "planned_start": "",
        "planned_end": "",
    }


def _dt_for_datetime_local(dt: datetime | None) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt.strftime("%Y-%m-%dT%H:%M")


def _prefill_create_form_from_exercise(ex: Exercise) -> dict[str, str]:
    out = _empty_create_form_prefill()

    def pick(val: str, allowed: list[str]) -> str:
        v = (val or "").strip()
        return v if v in allowed else ""

    out["trained_unit"] = pick(ex.trained_unit, ex_opts.TRAINED_UNITS)
    out["location_label"] = pick(ex.location_label, ex_opts.EXERCISE_LOCATIONS)
    out["exercise_name"] = pick(ex.title, ex_opts.EXERCISE_NAMES)
    out["exercise_type"] = pick(ex.exercise_type, ex_opts.EXERCISE_TYPES)
    out["exercise_level"] = pick(ex.exercise_level, ex_opts.EXERCISE_LEVELS)
    out["mission"] = pick(ex.mission_label, ex_opts.MISSIONS)
    out["planned_start"] = _dt_for_datetime_local(ex.planned_start)
    out["planned_end"] = _dt_for_datetime_local(ex.planned_end)
    return out


def _prefill_create_form_from_request() -> dict[str, str]:
    out = _empty_create_form_prefill()

    def pick(field: str, allowed: list[str]) -> str:
        v = (request.form.get(field) or "").strip()
        return v if v in allowed else ""

    out["trained_unit"] = pick("trained_unit", ex_opts.TRAINED_UNITS)
    out["location_label"] = pick("location_label", ex_opts.EXERCISE_LOCATIONS)
    out["exercise_name"] = pick("exercise_name", ex_opts.EXERCISE_NAMES)
    out["exercise_type"] = pick("exercise_type", ex_opts.EXERCISE_TYPES)
    out["exercise_level"] = pick("exercise_level", ex_opts.EXERCISE_LEVELS)
    out["mission"] = pick("mission", ex_opts.MISSIONS)
    for fld in ("planned_start", "planned_end"):
        raw = (request.form.get(fld) or "").strip()
        if raw:
            try:
                datetime.fromisoformat(raw)
                out[fld] = raw
            except Exception:
                out[fld] = ""
    return out


def _wants_import_json_response() -> bool:
    return "application/json" in (request.headers.get("Accept") or "")


def _import_full_json_error(msg: str, *, status: int = 400):
    if _wants_import_json_response():
        return jsonify({"ok": False, "error": msg}), status
    return redirect("/admin/exercises/create?err=" + quote(msg, safe=""))


def _import_full_json_ok(eid: int):
    if _wants_import_json_response():
        return jsonify({"ok": True, "redirect": f"/exercises/{eid}"})
    return redirect(f"/exercises/{eid}")


def _lines_to_objectives(raw: str) -> list[str]:
    items: list[str] = []
    for line in (raw or "").splitlines():
        s = line.strip().lstrip("•*-").strip()
        if not s:
            continue
        if len(s) > 2000:
            s = s[:2000]
        items.append(s)
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        k = x.casefold()
        if k in seen:
            continue
        seen.add(k)
        out.append(x)
    return out[:200]


def _parse_objectives_file_storage(f) -> list[str]:
    if not f or not getattr(f, "filename", ""):
        return []
    try:
        data = f.read()
    except Exception:
        return []
    if not data:
        return []
    filename = getattr(f, "filename", "") or ""

    from app.objectives_multiformat import extract_objectives_from_file

    parsed = extract_objectives_from_file(filename, data)
    if parsed:
        return parsed

    text = data.decode("utf-8", errors="ignore")
    if "," in text or ";" in text:
        text = text.replace(";", "\n").replace(",", "\n")
    return _lines_to_objectives(text)


def _ctx(user=None, **extra):
    d = {"user": user, "RoleKey": RoleKey}
    d.update(extra)
    return d


def _judge_assignment_for_current_exercise(db, user: User, ex: Exercise | None) -> JudgeTraineeAssignment | None:
    """تخصيص هذا المحكم للتمرين الحالي (إن وجد)."""
    if ex is None:
        return None
    judge_id = int(getattr(user, "id", 0) or 0)
    if judge_id <= 0:
        return None
    return (
        db.query(JudgeTraineeAssignment)
        .filter(
            JudgeTraineeAssignment.exercise_id == ex.id,
            JudgeTraineeAssignment.judge_user_id == judge_id,
        )
        .first()
    )


def _enforce_judge_unit_scope(db, user: User, ex: Exercise | None, unit_key: str) -> None:
    """للمحكمين (غير إدارة النظام): السماح فقط بوحدة المتدرب المخصصة لهم."""
    if ex is None:
        return
    if is_system_admin(user):
        return
    if not is_judge(user):
        return
    a = _judge_assignment_for_current_exercise(db, user, ex)
    assigned = (getattr(a, "unit_level_key", "") or "").strip() if a else ""
    if assigned and assigned != (unit_key or "").strip():
        abort(403)


def _enforce_judge_has_assignment_for_unit(db, user: User, ex: Exercise | None, unit_key: str) -> None:
    """إذا كان المحكم مرتبطاً بوحدة غير موجودة في ملفات المعاضل/التقييم الحالية، امنع الوصول برسالة واضحة."""
    if ex is None or user is None:
        return
    if is_system_admin(user) or not is_judge(user):
        return
    a = _judge_assignment_for_current_exercise(db, user, ex)
    assigned = (getattr(a, "unit_level_key", "") or "").strip() if a else ""
    if not assigned:
        abort(403)
    if assigned != (unit_key or "").strip():
        abort(403)


def _evaluation_canonical_saved_row(db, exercise_id: int, evaluation_item_id: int) -> EvaluationListSavedResult | None:
    """سجل نتيجة التقييم الموحّد لكل عنصر/تمرين (آخر تحديث زمني)."""
    return (
        db.query(EvaluationListSavedResult)
        .filter(
            EvaluationListSavedResult.exercise_id == exercise_id,
            EvaluationListSavedResult.evaluation_item_id == evaluation_item_id,
        )
        .order_by(EvaluationListSavedResult.updated_at.desc(), EvaluationListSavedResult.id.desc())
        .first()
    )


def _evaluation_canonical_map_for_items(db, exercise_id: int, item_ids: list[int]) -> dict[int, EvaluationListSavedResult]:
    if not item_ids:
        return {}
    rows = (
        db.query(EvaluationListSavedResult)
        .filter(
            EvaluationListSavedResult.exercise_id == exercise_id,
            EvaluationListSavedResult.evaluation_item_id.in_(item_ids),
        )
        .order_by(EvaluationListSavedResult.updated_at.desc(), EvaluationListSavedResult.id.desc())
        .all()
    )
    out: dict[int, EvaluationListSavedResult] = {}
    for r in rows:
        iid = int(r.evaluation_item_id)
        if iid not in out:
            out[iid] = r
    return out


def _evaluation_delete_duplicate_saves(db, *, exercise_id: int, evaluation_item_id: int, keep_id: int) -> None:
    db.query(EvaluationListSavedResult).filter(
        EvaluationListSavedResult.exercise_id == exercise_id,
        EvaluationListSavedResult.evaluation_item_id == evaluation_item_id,
        EvaluationListSavedResult.id != keep_id,
    ).delete(synchronize_session=False)


def _evaluation_grade_from_payload_rows(rows: list) -> tuple[float | None, str]:
    """
    نسبة إجمالية واقعية: مجموع المكتسبة ÷ مجموع القصوى لكل بنود التقييم (عدا «لا ينطبق»)،
    مع وزن 5 لكل بند بلا قصوى رقمية — يطابق حساب الواجهة عند وجود row_kind في الحمولة.
    للحمولات القديمة دون row_kind يُحتفظ بمتوسط نسب الصفوف كسلوك سابق.
    """
    safe = [r for r in rows[:2000] if isinstance(r, dict)]
    if not safe:
        return None, ""
    has_row_kind = any((str(r.get("row_kind") or "").strip()) for r in safe)
    if not has_row_kind:
        pcts: list[float] = []
        for r in safe:
            p = _eval_row_score_pct(r)
            if p is not None:
                pcts.append(float(p))
        if not pcts:
            return None, ""
        total_pct = sum(pcts) / len(pcts)
        return total_pct, grade_label_from_percent(total_pct)
    sum_acq = 0.0
    sum_den = 0.0
    for r in safe:
        if str(r.get("row_kind") or "").strip().lower() == "section":
            continue
        acq = r.get("acquired")
        acq_s = ("" if acq is None else str(acq)).strip().lower()
        if acq_s == "na":
            continue
        sum_den += _eval_row_effective_max(r)
        if acq_s:
            try:
                sum_acq += float(str(acq).replace(",", "."))
            except (TypeError, ValueError):
                pass
    if sum_den <= 0:
        return None, ""
    total_pct = (sum_acq / sum_den) * 100.0
    return total_pct, grade_label_from_percent(total_pct)


def _evaluation_commit_payload_save(
    db,
    *,
    user: User,
    item: EvaluationListPdfItem,
    current_exercise: Exercise,
    raw: str,
) -> None:
    """يحدّث أو ينشئ السجل الموحّد لنتائج التقييم؛ بعد الحفظ يُزال أي سجل قديم مكرّر لنفس العنصر."""
    if not can_save_evaluation_results(user):
        abort(403)
    try:
        payload = json.loads(raw)
    except Exception:
        abort(400)
    if not isinstance(payload, dict):
        abort(400)
    rows = payload.get("rows") or []
    if not isinstance(rows, list):
        abort(400)
    total_pct, grade = _evaluation_grade_from_payload_rows(rows)
    saved = _evaluation_canonical_saved_row(db, current_exercise.id, item.id)
    if saved is not None and bool(getattr(saved, "is_approved", False)):
        abort(403)
    if saved is None:
        saved = EvaluationListSavedResult(
            evaluation_item_id=item.id,
            exercise_id=current_exercise.id,
            exercise_phase=_normalized_exercise_phase(getattr(item, "exercise_phase", None)),
            unit_level_key=item.unit_level_key or "",
            saved_by_id=getattr(user, "id", None),
            is_approved=False,
        )
        db.add(saved)
    saved.payload_json = raw
    saved.total_pct = total_pct
    saved.grade_label = grade
    saved.saved_by_id = getattr(user, "id", None)
    db.flush()
    _evaluation_delete_duplicate_saves(db, exercise_id=current_exercise.id, evaluation_item_id=item.id, keep_id=saved.id)
    db.commit()


def _phase_label_ar(phase: str | None) -> str:
    p = (phase or "").strip().lower()
    if p == ExercisePhase.REORG.value:
        return "إعادة التنظيم"
    return "التمرين الرئيسي"


def _parse_saved_eval_rows(payload_json: str | None) -> list[dict]:
    if not (payload_json or "").strip():
        return []
    try:
        data = json.loads(payload_json)
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    rows = data.get("rows") or []
    return rows if isinstance(rows, list) else []


def _parse_saved_eval_max_positive(raw) -> float | None:
    if raw in (None, ""):
        return None
    try:
        v = float(str(raw).replace(",", "."))
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def _evaluation_payload_has_empty_acquired_for_approve(rows: list) -> bool:
    """
    True إذا وُجد بند تقييم (صف score) بمكتسبة فارغة — لا يُقبل الاعتماد.
    «لا ينطبق» يُعتبر إدخالاً صالحاً. صفوف الأقسام تُستثنى.
    للحمولات القديمة دون row_kind: يُفحص الصف إذا وُجدت له قصوى رقمية ولم تُدخل مكتسبة.
    """
    if not isinstance(rows, list):
        return True
    safe = [r for r in rows if isinstance(r, dict)]
    if not safe:
        return True
    has_row_kind = any(str(r.get("row_kind") or "").strip() for r in safe)
    for r in safe:
        rk = str(r.get("row_kind") or "").strip().lower()
        if rk == "section":
            continue
        acq = r.get("acquired")
        empty_acq = acq is None or str(acq).strip() == ""
        if not empty_acq:
            continue
        if rk == "score":
            return True
        if not has_row_kind and _parse_saved_eval_max_positive(r.get("max_val")) is not None:
            return True
    return False


def _eval_row_effective_max(row: dict) -> float:
    """قصوى الصف لحساب النسبة الإجمالية؛ يطابق effectiveMaxForRow في الواجهة (افتراض 5)."""
    mx_raw = row.get("max_val")
    if mx_raw not in (None, ""):
        try:
            mx = float(str(mx_raw).replace(",", "."))
            if mx > 0:
                return mx
        except (TypeError, ValueError):
            pass
    return 5.0


def _eval_row_score_pct(row: dict) -> float | None:
    """تقريب 0..100 من المكتسبة والقصوى (أو منطق 5 درجات)."""
    if not isinstance(row, dict):
        return None
    acq = row.get("acquired")
    if acq is None or acq == "" or str(acq).strip().lower() == "na":
        return None
    try:
        a = float(str(acq).replace(",", "."))
    except (TypeError, ValueError):
        return None
    mx_raw = row.get("max_val")
    mx = None
    if mx_raw not in (None, ""):
        try:
            mx = float(str(mx_raw).replace(",", "."))
        except (TypeError, ValueError):
            mx = None
    if mx is not None and mx > 0:
        return max(0.0, min(100.0, (a / mx) * 100.0))
    return max(0.0, min(100.0, (a / 5.0) * 100.0))


def _pct_status_band(pct: float | None) -> str:
    """حالة عرض: high | mid | low | na"""
    if pct is None:
        return "na"
    if pct >= 75.0:
        return "high"
    if pct >= 50.0:
        return "mid"
    return "low"


def _trainee_commander_for_unit(db, exercise_id: int, unit_key: str) -> str:
    row = (
        db.query(ExerciseRosterRow)
        .filter(
            ExerciseRosterRow.exercise_id == exercise_id,
            ExerciseRosterRow.roster_kind == ExerciseRosterKind.TRAINEE.value,
            ExerciseRosterRow.unit_level_key == unit_key,
        )
        .order_by(ExerciseRosterRow.sort_order, ExerciseRosterRow.id)
        .first()
    )
    if row is None:
        return ""
    return (row.full_name or "").strip()


def _build_analyst_evaluation_results_dashboard(
    db,
    user: User,
    *,
    approved_only: bool = True,
    matrix_mode: str = "objectives",
) -> dict:
    """بيانات صفحة محللين / مصفوفة حالة الأهداف مقابل الوحدات + جانبية."""
    ex0 = _current_workspace_exercise(db, user)
    if ex0 is None:
        return {"has_exercise": False}
    ex = (
        db.query(Exercise)
        .options(joinedload(Exercise.objectives))
        .filter(Exercise.id == ex0.id)
        .first()
    )
    if ex is None:
        return {"has_exercise": False}

    objectives = sorted(
        [o for o in (ex.objectives or []) if o is not None],
        key=lambda o: (int(getattr(o, "sort_order", 0) or 0), int(getattr(o, "id", 0) or 0)),
    )

    eval_items = (
        db.query(EvaluationListPdfItem)
        .filter(EvaluationListPdfItem.exercise_id == ex.id)
        .order_by(
            EvaluationListPdfItem.unit_level_key,
            EvaluationListPdfItem.exercise_phase,
            EvaluationListPdfItem.sort_order,
            EvaluationListPdfItem.id,
        )
        .all()
    )
    saved_by_item: dict[int, EvaluationListSavedResult] = {}
    if eval_items:
        item_ids = [int(it.id) for it in eval_items if getattr(it, "id", None) is not None]
        saved_query = db.query(EvaluationListSavedResult).filter(
            EvaluationListSavedResult.exercise_id == ex.id,
            EvaluationListSavedResult.evaluation_item_id.in_(item_ids),
        )
        if approved_only:
            saved_query = saved_query.filter(EvaluationListSavedResult.is_approved == True)
        saved_rows = (
            saved_query
            .order_by(
                EvaluationListSavedResult.evaluation_item_id,
                EvaluationListSavedResult.approved_at.desc(),
                EvaluationListSavedResult.updated_at.desc(),
                EvaluationListSavedResult.id.desc(),
            )
            .all()
        )
        for sr in saved_rows:
            iid = int(sr.evaluation_item_id)
            if iid not in saved_by_item:
                saved_by_item[iid] = sr
    by_unit: dict[str, list[EvaluationListPdfItem]] = {}
    for it in eval_items:
        uk = (it.unit_level_key or "").strip()
        if not uk:
            continue
        by_unit.setdefault(uk, []).append(it)

    # رؤوس الأعمدة: صفحة النتائج تستخدم قوائم التقييم، أما التحليل الجانبي فيبقى على الأهداف/البنود.
    if matrix_mode == "evaluation_lists":
        matrix_columns = []
        for i, it in enumerate([x for x in eval_items if int(x.id) in saved_by_item]):
            title = (it.text or "قائمة تقييم").strip()
            unit_label = label_for_unit_level_key(it.unit_level_key or "") or (it.unit_level_key or "")
            matrix_columns.append(
                {
                    "idx": i,
                    "code": f"قائمة {i + 1:02d}",
                    "text": title[:220] + ("…" if len(title) > 220 else ""),
                    "full_text": f"{title} — {unit_label} — {_phase_label_ar(getattr(it, 'exercise_phase', None))}",
                    "item_id": int(it.id),
                    "unit_key": (it.unit_level_key or "").strip(),
                }
            )
        n_cols = len(matrix_columns)
    elif objectives:
        matrix_columns: list[dict] = []
        for i, o in enumerate(objectives):
            txt = (o.text or "").strip()
            matrix_columns.append(
                {
                    "idx": i,
                    "code": f"هدف {i + 1:02d}",
                    "text": txt[:220] + ("…" if len(txt) > 220 else ""),
                    "full_text": txt,
                }
            )
        n_cols = len(matrix_columns)
    else:
        max_rows = 0
        for it in eval_items:
            canon = saved_by_item.get(int(it.id))
            if canon is None:
                continue
            rows = _parse_saved_eval_rows(canon.payload_json)
            max_rows = max(max_rows, len(rows))
        n_cols = max(1, min(max_rows, 14))
        matrix_columns = [
            {
                "idx": i,
                "code": f"بند {i + 1:02d}",
                "text": f"عنصر التقييم رقم {i + 1} (بدون أهداف مُعرَّفة في التمرين)",
                "full_text": "",
            }
            for i in range(n_cols)
        ]

    matrix_rows: list[dict] = []
    for ul_pos, ul in enumerate(UNIT_LEVELS):
        uk = ul.get("key") or ""
        ulab = ul.get("label") or uk
        items_u = by_unit.get(uk) or []
        sub = _trainee_commander_for_unit(db, ex.id, uk)
        cells: list[dict] = []
        for j in range(n_cols):
            if matrix_mode == "evaluation_lists":
                col = matrix_columns[j] if j < len(matrix_columns) else {}
                canon = None
                if (col.get("unit_key") or "") == uk:
                    canon = saved_by_item.get(int(col.get("item_id") or 0))
                best_pct = getattr(canon, "total_pct", None) if canon is not None else None
                if best_pct is None and canon is not None:
                    row_scores = [
                        _eval_row_score_pct(r)
                        for r in _parse_saved_eval_rows(canon.payload_json)
                        if isinstance(r, dict)
                    ]
                    row_scores = [x for x in row_scores if x is not None]
                    best_pct = (sum(row_scores) / len(row_scores)) if row_scores else None
                best_updated = (
                    (getattr(canon, "approved_at", None) if bool(getattr(canon, "is_approved", False)) else None)
                    or getattr(canon, "updated_at", None)
                    if canon is not None
                    else None
                )
                best_note = ""
                is_flagged = bool(canon is not None and not bool(getattr(canon, "is_approved", False)))
            else:
                best_pct: float | None = None
                best_updated = None
                best_note = ""
                is_flagged = False
                for it in items_u:
                    canon = saved_by_item.get(int(it.id))
                    if canon is None:
                        continue
                    rows = _parse_saved_eval_rows(canon.payload_json)
                    if not rows:
                        continue
                    ridx = min(j, len(rows) - 1)
                    row = rows[ridx] if isinstance(rows[ridx], dict) else {}
                    pc = _eval_row_score_pct(row)
                    if pc is None:
                        continue
                    if best_pct is None or pc > best_pct:
                        best_pct = pc
                        best_updated = getattr(canon, "approved_at", None) or getattr(canon, "updated_at", None)
                        best_note = (row.get("notes") or "").strip()
            band = _pct_status_band(best_pct)
            h_fill = int(round(best_pct or 0)) if best_pct is not None else 0
            h_rest = max(0, 100 - h_fill) if best_pct is not None else 100
            bar_h = 44
            if best_pct is not None:
                fill_px = max(4, int(round(bar_h * h_fill / 100.0)))
                rest_px = max(4, bar_h - fill_px)
            else:
                fill_px = 4
                rest_px = bar_h - fill_px
            cells.append(
                {
                    "pct": best_pct,
                    "band": band,
                    "is_flagged": is_flagged,
                    "updated_at": best_updated,
                    "note": best_note,
                    "bar_fill": h_fill,
                    "bar_rest": h_rest,
                    "bar_fill_px": fill_px,
                    "bar_rest_px": rest_px,
                }
            )
        matrix_rows.append(
            {
                "unit_key": uk,
                "unit_label": ulab,
                "hierarchy_idx": ul_pos + 1,
                "row_sub": sub or "—",
                "has_lists": bool(items_u),
                "cells": cells,
            }
        )

    # قوائم لم تُعبأ بعد
    not_assessed: list[dict] = []
    for it in eval_items:
        uk = (it.unit_level_key or "").strip()
        canon = saved_by_item.get(int(it.id))
        rows = _parse_saved_eval_rows(getattr(canon, "payload_json", None) if canon else None)
        scored = any(_eval_row_score_pct(r) is not None for r in rows if isinstance(r, dict))
        if canon is None or not rows or not scored:
            not_assessed.append(
                {
                    "objective": ((it.text or "قائمة تقييم").strip()[:100]),
                    "entities": label_for_unit_level_key(uk) or uk or "—",
                    "activity": f"{_phase_label_ar(getattr(it, 'exercise_phase', None))} — بانتظار {'نتيجة معتمدة' if approved_only else 'حفظ نتيجة'}",
                    "open_href": url_for(
                        "views.analyst_evaluation_list_file_viewer",
                        unit_key=uk,
                        item_id=it.id,
                    ),
                }
            )

    # مناطق تحتاج تطويراً (أدنى النِسَب في المصفوفة)
    dev_list: list[tuple[float, dict]] = []
    sustain_list: list[tuple[float, dict]] = []
    for mr in matrix_rows:
        for j, cell in enumerate(mr.get("cells") or []):
            pct = cell.get("pct")
            if pct is None:
                continue
            col = matrix_columns[j] if j < len(matrix_columns) else {}
            row_info = {
                "objective": (col.get("text") or col.get("code") or "—")[:160],
                "entities": mr.get("unit_label") or "—",
                "activity": "نتيجة معتمدة من قوائم التقييم",
                "grade": grade_label_from_percent(pct),
                "pct": pct,
                "note": (cell.get("note") or "").strip(),
            }
            if cell.get("band") == "low":
                dev_list.append((float(pct), row_info))
            elif cell.get("band") == "high":
                sustain_list.append((float(pct), row_info))
    dev_list.sort(key=lambda x: x[0])
    sustain_list.sort(key=lambda x: x[0], reverse=True)
    development_areas = [d for _, d in dev_list[:12]]
    sustainability_areas = [d for _, d in sustain_list[:12]]
    development_notes = [d for d in development_areas if (d.get("note") or "").strip()]
    sustainability_notes = [d for d in sustainability_areas if (d.get("note") or "").strip()]

    # تحليل حسب مستوى الوحدة من النتائج المعتمدة فقط
    unit_eval_analysis: list[dict] = []
    for ul_pos, ul in enumerate(UNIT_LEVELS):
        uk = ul.get("key") or ""
        scores: list[dict] = []
        for it in by_unit.get(uk) or []:
            canon = saved_by_item.get(int(it.id))
            if canon is None:
                continue
            for idx, row in enumerate(_parse_saved_eval_rows(canon.payload_json)):
                if not isinstance(row, dict):
                    continue
                pct = _eval_row_score_pct(row)
                if pct is None:
                    continue
                element = (row.get("element") or "").strip()
                label = element or (it.text or f"بند {idx + 1}").strip()
                scores.append(
                    {
                        "pct": float(pct),
                        "label": label[:180],
                        "note": (row.get("notes") or "").strip(),
                        "grade": grade_label_from_percent(pct),
                        "evaluation_list": (it.text or "قائمة تقييم").strip()[:120],
                    }
                )
        scores.sort(key=lambda x: x["pct"])
        avg_pct = (sum(s["pct"] for s in scores) / len(scores)) if scores else None
        unit_eval_analysis.append(
            {
                "unit_key": uk,
                "unit_label": ul.get("label") or uk,
                "hierarchy_idx": ul_pos + 1,
                "approved_items_count": len([it for it in by_unit.get(uk) or [] if int(it.id) in saved_by_item]),
                "scored_rows_count": len(scores),
                "avg_pct": avg_pct,
                "avg_grade": grade_label_from_percent(avg_pct) if avg_pct is not None else "—",
                "development_points": [s for s in scores if s["pct"] < 50.0][:5],
                "sustainability_points": sorted(
                    [s for s in scores if s["pct"] >= 75.0],
                    key=lambda x: x["pct"],
                    reverse=True,
                )[:5],
            }
        )

    since_dt = getattr(ex, "planned_start", None) or getattr(ex, "created_at", None)

    return {
        "has_exercise": True,
        "exercise": ex,
        "matrix_columns": matrix_columns,
        "matrix_rows": matrix_rows,
        "not_assessed": not_assessed,
        "development_areas": development_areas,
        "sustainability_areas": sustainability_areas,
        "development_notes": development_notes,
        "sustainability_notes": sustainability_notes,
        "unit_eval_analysis": unit_eval_analysis,
        "since_dt": since_dt,
        "n_objectives": n_cols,
        "n_eval_lists": len(eval_items),
        "n_approved_eval_lists": len([r for r in saved_by_item.values() if bool(getattr(r, "is_approved", False))]),
        "n_saved_eval_lists": len(saved_by_item),
        "using_objectives": bool(objectives),
        "using_evaluation_lists": matrix_mode == "evaluation_lists",
    }


def _ensure_judge_roster_synced(db, user: User, ex: Exercise | None) -> None:
    """إذا كانت بيانات قائمة المحكمين موجودة لكن الربط غير مُنشأ، أنشئه تلقائياً.

    هذا مهم في حال تم تحديث النظام بعد إدخال القوائم أو لم يتم إعادة حفظ قائمة المحكمين.
    """
    if ex is None or user is None:
        return
    if is_system_admin(user):
        return
    if not is_judge(user):
        return
    judge_id = int(getattr(user, "id", 0) or 0)
    if judge_id <= 0:
        return
    exists = (
        db.query(JudgeTraineeAssignment)
        .filter(
            JudgeTraineeAssignment.exercise_id == ex.id,
            JudgeTraineeAssignment.judge_user_id == judge_id,
        )
        .first()
    )
    if exists is None:
        _sync_judges_from_roster(db, ex)


@bp.route("/")
def home():
    user = get_current_user_optional()
    if not user:
        return redirect("/login")
    return redirect("/dashboard")


@bp.route("/exercises")
def exercises_removed():
    """الصفحة أُلغيت حسب الطلب."""
    return redirect("/dashboard")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if get_current_user_optional():
            return redirect("/dashboard")
        return render_template("login.html", next_url=request.args.get("next", ""), error="")
    # POST
    from flask import g
    db = g.db
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    next_url = (request.form.get("next") or "").strip()
    u = (
        db.query(User)
        .filter(User.username == username, User.is_active == True)  # noqa: E712
        .first()
    )
    if not u or not verify_password(password, u.password_hash):
        return (
            render_template(
                "login.html",
                next_url=next_url,
                error="بيانات الدخول غير صحيحة",
            ),
            401,
        )
    u.last_login = datetime.utcnow()
    db.add(u)
    db.commit()
    session["user_id"] = u.id
    # للمحكمين: افتح مساحة المحكمين مباشرةً (ما لم يحدد النظام next)
    if (u.role_key or "") == RoleKey.JUDGE.value and not next_url:
        return redirect("/judge")
    return redirect(next_url or "/dashboard")


@bp.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


def _dashboard_role_card_target(role_key: str, user: User) -> tuple[str, str, str]:
    """وجهة البطاقة في الصفحة الرئيسية: (المسار، aria، تلميح) مع احترام صلاحيات المستخدم."""
    if role_key == RoleKey.SYSTEM_ADMIN.value:
        if is_system_admin(user):
            return (
                "/admin/exercises/create",
                "فتح إنشاء تمرين جديد",
                "إبدأ",
            )
        return ("/library", "فتح المكتبة", "إبدأ")
    if role_key == RoleKey.ANALYST.value:
        return ("/analyst", "فتح مساحة المحللين", "إبدأ")
    if role_key == RoleKey.CONTROL.value:
        return ("/control", "فتح مساحة السيطرة", "إبدأ")
    if role_key == RoleKey.PLANNER.value:
        return ("/planner", "فتح مساحة التخطيط", "إبدأ")
    if role_key == RoleKey.JUDGE.value:
        return ("/judge", "فتح مساحة المحكمين", "إبدأ")
    if role_key == RoleKey.STANDARDS_LIBRARY.value:
        return ("/library", "فتح مكتبة المراجع والمعايير", "إبدأ")
    return ("/library", "فتح المكتبة", "إبدأ")


# ترتيب بطاقات الصفحة الرئيسية: المحكمين قبل المحللين ضمن الشبكة
_DASHBOARD_CARD_ORDER: tuple[str, ...] = (
    RoleKey.SYSTEM_ADMIN.value,
    RoleKey.PLANNER.value,
    RoleKey.CONTROL.value,
    RoleKey.JUDGE.value,
    RoleKey.ANALYST.value,
)
_DASHBOARD_CARD_ORDER_RANK: dict[str, int] = {rk: i for i, rk in enumerate(_DASHBOARD_CARD_ORDER)}


@bp.route("/dashboard")
def dashboard():
    user = get_current_user_optional()
    if not user:
        return redirect("/login?next=/dashboard")
    from flask import g
    db = g.db
    roles = db.query(RoleDef).order_by(RoleDef.id).all()
    rk = RoleKey.from_value(user.role_key)
    role_title = next(
        (r.title_ar for r in roles if r.role_key == user.role_key), rk.value
    )
    role_defs_home = [
        r
        for r in roles
        if r.role_key != RoleKey.STANDARDS_LIBRARY.value
    ]
    dashboard_cards: list[dict] = []
    for r in role_defs_home:
        href, aria, hint = _dashboard_role_card_target(r.role_key, user)
        dashboard_cards.append(
            {
                "role_key": r.role_key,
                "title_ar": r.title_ar,
                "duties_ar": r.duties_ar,
                "href": href,
                "aria_label": aria,
                "hint": hint,
            }
        )
    dashboard_cards.sort(
        key=lambda c: _DASHBOARD_CARD_ORDER_RANK.get(c["role_key"], 99)
    )
    return render_template(
        "dashboard.html",
        **_ctx(
            user,
            dashboard_cards=dashboard_cards,
            current_rk=rk,
            role_title=role_title,
            demo_password_note=DEMO_PASSWORD,
        ),
    )


# مساحة المحللين — عناصر الشريط (المعرّف، العنوان، أيقونة Font Awesome)
ANALYST_HUB_ITEMS: tuple[tuple[str, str, str], ...] = (
    ("evaluation-criteria", "معايير التقييم", "fa-list-check"),
    ("positives-negatives", "عرض الإيجابيات والسلبيات", "fa-plus-minus"),
    ("evaluation-results", "عرض نتائج التقييم", "fa-square-poll-vertical"),
    ("judges-eval-analysis", "تحليل وتقييم المحكمين", "fa-chart-column"),
    ("final-evaluation", "إنشاء التقييم النهائي", "fa-file-signature"),
    ("incomplete-tasks", "مهام غير مكتملة", "fa-clipboard-list"),
    ("chat-rooms", "غرف محادثة", "fa-comments"),
    ("after-action-review", "إنشاء مراجعة ما بعد العمل", "fa-people-arrows"),
    ("notifications-log", "سجل الإشعارات", "fa-bell"),
    ("exercise-info", "معلومات التمرين", "fa-circle-info"),
    ("visual-documentation", "التوثيق المرئي", "fa-photo-film"),
)
ANALYST_HUB_SLUGS: dict[str, str] = {s: t for s, t, _ in ANALYST_HUB_ITEMS}


@bp.route("/analyst")
def analyst_hub():
    user = get_current_user_optional()
    if not user:
        return redirect("/login?next=/analyst")
    if not can_access_analyst_hub(user):
        abort(403)
    hub_items = [{"slug": s, "title_ar": t, "icon": ic} for s, t, ic in ANALYST_HUB_ITEMS]
    return render_template(
        "analyst_hub.html",
        **_ctx(
            user,
            hub_items=hub_items,
        ),
    )


@bp.route("/analyst/<slug>")
def analyst_hub_section(slug: str):
    user = get_current_user_optional()
    if not user:
        return redirect(f"/login?next=/analyst/{slug}")
    if not can_access_analyst_hub(user):
        abort(403)
    slug_norm = (slug or "").strip().lower()
    if slug_norm == "chat-rooms":
        return redirect(url_for("views.chat_rooms_list"))
    title = ANALYST_HUB_SLUGS.get(slug_norm)
    if not title:
        abort(404)
    if slug_norm == "positives-negatives":
        from flask import g

        db = g.db
        dash = _build_analyst_evaluation_results_dashboard(db, user)
        if not dash.get("has_exercise"):
            return render_template(
                "analyst_positives_negatives.html",
                **_ctx(user, section_title=title, has_exercise=False),
            )
        return render_template(
            "analyst_positives_negatives.html",
            **_ctx(
                user,
                section_title=title,
                has_exercise=True,
                exercise=dash["exercise"],
                development_areas=dash["development_areas"],
                sustainability_areas=dash["sustainability_areas"],
                development_notes=dash["development_notes"],
                sustainability_notes=dash["sustainability_notes"],
                unit_eval_analysis=dash["unit_eval_analysis"],
                n_eval_lists=dash["n_eval_lists"],
                n_approved_eval_lists=dash["n_approved_eval_lists"],
            ),
        )
    if slug_norm == "evaluation-results":
        from flask import g

        db = g.db
        dash = _build_analyst_evaluation_results_dashboard(
            db,
            user,
            approved_only=False,
            matrix_mode="evaluation_lists",
        )
        if not dash.get("has_exercise"):
            return render_template(
                "analyst_evaluation_results_dashboard.html",
                **_ctx(user, section_title=title, has_exercise=False),
            )
        return render_template(
            "analyst_evaluation_results_dashboard.html",
            **_ctx(
                user,
                section_title=title,
                has_exercise=True,
                exercise=dash["exercise"],
                matrix_columns=dash["matrix_columns"],
                matrix_rows=dash["matrix_rows"],
                not_assessed=dash["not_assessed"],
                development_areas=dash["development_areas"],
                sustainability_areas=dash["sustainability_areas"],
                unit_eval_analysis=dash["unit_eval_analysis"],
                since_dt=dash["since_dt"],
                n_objectives=dash["n_objectives"],
                n_eval_lists=dash["n_eval_lists"],
                n_approved_eval_lists=dash["n_approved_eval_lists"],
                n_saved_eval_lists=dash["n_saved_eval_lists"],
                using_objectives=dash["using_objectives"],
                using_evaluation_lists=dash["using_evaluation_lists"],
            ),
        )
    if slug_norm == "judges-eval-analysis":
        from flask import g

        db = g.db
        ex = _admin_current_workspace_exercise(db, user)
        if ex is None:
            return render_template(
                "analyst_judges_evaluation_analysis.html",
                **_ctx(user, section_title=title, has_exercise=False),
            )

        saved_rows = (
            db.query(EvaluationListSavedResult)
            .filter(EvaluationListSavedResult.exercise_id == ex.id)
            .order_by(EvaluationListSavedResult.updated_at.desc(), EvaluationListSavedResult.id.desc())
            .all()
        )

        eval_items = (
            db.query(EvaluationListPdfItem)
            .filter(EvaluationListPdfItem.exercise_id == ex.id)
            .order_by(
                EvaluationListPdfItem.unit_level_key,
                EvaluationListPdfItem.exercise_phase,
                EvaluationListPdfItem.sort_order,
                EvaluationListPdfItem.id,
            )
            .all()
        )

        # أحدث نتيجة لكل (محكم, ملف تقييم)
        latest_by_judge_item: dict[tuple[int, int], EvaluationListSavedResult] = {}
        for r in saved_rows:
            jid = getattr(r, "saved_by_id", None)
            if jid is None:
                continue
            key = (int(jid), int(r.evaluation_item_id))
            prev = latest_by_judge_item.get(key)
            if prev is None:
                latest_by_judge_item[key] = r
                continue
            pdt = getattr(prev, "updated_at", None)
            rdt = getattr(r, "updated_at", None)
            if (rdt and pdt and rdt > pdt) or (rdt and not pdt) or (rdt == pdt and r.id > prev.id):
                latest_by_judge_item[key] = r

        # إكمال قوائم التقييم لكل وحدة (معبّأة / غير معبّأة)
        saved_by_item_ids = {int(r.evaluation_item_id) for r in saved_rows if (r.payload_json or "").strip()}
        unit_completion: list[dict] = []
        by_unit_items: dict[str, list[EvaluationListPdfItem]] = {}
        for it in eval_items:
            uk = (it.unit_level_key or "").strip()
            if not uk:
                continue
            by_unit_items.setdefault(uk, []).append(it)
        for uk, items in by_unit_items.items():
            filled = []
            unfilled = []
            for it in items:
                x = {
                    "id": it.id,
                    "title": it.text or "تقييم",
                    "phase": getattr(it, "exercise_phase", "main"),
                    "is_filled": int(it.id) in saved_by_item_ids,
                }
                (filled if x["is_filled"] else unfilled).append(x)
            unit_completion.append(
                {
                    "unit_key": uk,
                    "unit_label": label_for_unit_level_key(uk) or uk,
                    "total": len(items),
                    "filled_n": len(filled),
                    "unfilled_n": len(unfilled),
                    "filled": filled,
                    "unfilled": unfilled,
                }
            )
        unit_completion.sort(key=lambda x: (x["unfilled_n"], x["total"]), reverse=True)

        # إحصاءات المحكمين لكل وحدة + نتائج الملفات بشكل منفرد
        from app.models import User

        judge_ids = sorted({int(k[0]) for k in latest_by_judge_item.keys()})
        judge_users: dict[int, User] = {}
        if judge_ids:
            for u in db.query(User).filter(User.id.in_(judge_ids)).all():
                judge_users[int(u.id)] = u

        judge_stats: list[dict] = []
        for jid in judge_ids:
            u = judge_users.get(jid)
            display = (
                (getattr(u, "full_name", "") or "").strip()
                or (getattr(u, "username", "") or "").strip()
                or f"محكم #{jid}"
            )
            rows = [r for (jj, _iid), r in latest_by_judge_item.items() if jj == jid]
            by_unit: dict[str, list[EvaluationListSavedResult]] = {}
            for r in rows:
                uk = (r.unit_level_key or "").strip()
                by_unit.setdefault(uk or "—", []).append(r)
            unit_blocks = []
            for uk, rs in sorted(by_unit.items(), key=lambda x: x[0]):
                unit_blocks.append(
                    {
                        "unit_key": uk,
                        "unit_label": (label_for_unit_level_key(uk) or uk) if uk != "—" else "—",
                        "count": len(rs),
                        "results": [
                            {
                                "saved_id": rr.id,
                                "evaluation_item_id": rr.evaluation_item_id,
                                "exercise_phase": rr.exercise_phase,
                                "total_pct": rr.total_pct,
                                "grade_label": rr.grade_label,
                                "is_approved": bool(getattr(rr, "is_approved", False)),
                                "updated_at": rr.updated_at,
                            }
                            for rr in sorted(
                                rs,
                                key=lambda x: (x.updated_at or datetime.min, x.id),
                                reverse=True,
                            )
                        ],
                    }
                )
            judge_stats.append(
                {
                    "judge_id": jid,
                    "judge_name": display,
                    "total_results": len(rows),
                    "units": unit_blocks,
                }
            )

        # نتائج حسب الوحدة ثم حسب كل ملف تقييم منفرد (أحدث نتيجة لكل محكم)
        unit_item_results: list[dict] = []
        for ublk in unit_completion:
            uk = ublk["unit_key"]
            items = by_unit_items.get(uk) or []
            item_blocks = []
            for it in items:
                per_item = []
                for (jid, iid), r in latest_by_judge_item.items():
                    if int(iid) != int(it.id):
                        continue
                    u = judge_users.get(int(jid))
                    display = (
                        (getattr(u, "full_name", "") or "").strip()
                        or (getattr(u, "username", "") or "").strip()
                        or f"محكم #{jid}"
                    )
                    per_item.append(
                        {
                            "judge_id": jid,
                            "judge_name": display,
                            "saved_id": r.id,
                            "total_pct": r.total_pct,
                            "grade_label": r.grade_label,
                            "is_approved": bool(getattr(r, "is_approved", False)),
                            "updated_at": r.updated_at,
                        }
                    )
                per_item.sort(
                    key=lambda x: (x["is_approved"], x["updated_at"] or datetime.min),
                    reverse=True,
                )
                item_blocks.append(
                    {
                        "item_id": it.id,
                        "title": it.text or "تقييم",
                        "phase": getattr(it, "exercise_phase", "main"),
                        "is_filled": int(it.id) in saved_by_item_ids,
                        "results": per_item,
                    }
                )
            unit_item_results.append(
                {
                    "unit_key": uk,
                    "unit_label": ublk["unit_label"],
                    "items": item_blocks,
                }
            )

        # نتيجة كل وحدة (المجموع العام): من أحدث نتيجة لكل (محكم, ملف) لتجنب التكرار
        by_unit_latest: dict[str, list[float]] = {}
        for (_jid, _iid), r in latest_by_judge_item.items():
            if r.total_pct is None:
                continue
            uk = (r.unit_level_key or "").strip()
            if not uk:
                continue
            try:
                by_unit_latest.setdefault(uk, []).append(float(r.total_pct))
            except Exception:
                continue

        unit_totals: list[dict] = []
        for uk, vals in by_unit_latest.items():
            if not vals:
                continue
            unit_totals.append(
                {
                    "unit_key": uk,
                    "unit_label": label_for_unit_level_key(uk) or uk,
                    "avg_pct": sum(vals) / len(vals),
                    "n": len(vals),
                }
            )
        unit_totals.sort(key=lambda x: x["avg_pct"], reverse=True)

        # نقاط القوة/الضعف على مستوى التمرين (حسب نتيجة الوحدات)
        strengths_units = unit_totals[:3]
        weaknesses_units = list(reversed(unit_totals[-3:])) if len(unit_totals) > 3 else []

        # تبويبات الوحدات: بيانات مختصرة للرسم + عرض كتابي + إكمال لكل محكم
        unit_tabs: list[dict] = []
        # خريطة سريعة: unit_key -> completion block
        completion_by_unit = {u["unit_key"]: u for u in unit_completion}
        # خريطة سريعة: unit_key -> unit_item_results block
        results_by_unit = {u["unit_key"]: u for u in unit_item_results}

        # تجهيز إكمال القوائم لكل محكم لكل وحدة (مخصّص/معبّأ/غير معبّأ)
        judge_name_by_id: dict[int, str] = {}
        for j in judge_stats:
            judge_name_by_id[int(j["judge_id"])] = j.get("judge_name") or f"محكم #{j['judge_id']}"

        unit_judge_completion: dict[str, list[dict]] = {}
        for ukey, items in by_unit_items.items():
            item_ids = {int(it.id) for it in items}
            rows = []
            for jid in judge_ids:
                filled_n = 0
                for iid in item_ids:
                    if (int(jid), int(iid)) in latest_by_judge_item:
                        filled_n += 1
                total_n = len(item_ids)
                rows.append(
                    {
                        "judge_id": jid,
                        "judge_name": judge_name_by_id.get(int(jid), f"محكم #{jid}"),
                        "total": total_n,
                        "filled_n": filled_n,
                        "unfilled_n": max(total_n - filled_n, 0),
                    }
                )
            rows.sort(key=lambda x: (x["unfilled_n"], x["total"]), reverse=True)
            unit_judge_completion[ukey] = rows

        for u in unit_completion:
            ukey = u["unit_key"]
            ures = results_by_unit.get(ukey) or {}
            items = ures.get("items") or []
            chart_items = []
            for it in items:
                vals = []
                for r in (it.get("results") or []):
                    v = r.get("total_pct")
                    if v is None:
                        continue
                    try:
                        vals.append(float(v))
                    except Exception:
                        continue
                avg = (sum(vals) / len(vals)) if vals else None
                chart_items.append(
                    {
                        "item_id": it.get("item_id"),
                        "title": it.get("title") or "تقييم",
                        "phase": it.get("phase") or "main",
                        "is_filled": bool(it.get("is_filled")),
                        "avg_pct": avg,
                        "n": len(vals),
                    }
                )
            chart_items_scored = [x for x in chart_items if x["avg_pct"] is not None]
            chart_items_scored.sort(key=lambda x: float(x["avg_pct"]), reverse=True)
            unit_strengths = chart_items_scored[:3]
            unit_weaknesses = list(reversed(chart_items_scored[-3:])) if len(chart_items_scored) > 3 else []

            unit_vals = by_unit_latest.get(ukey) or []
            unit_total_pct = (sum(unit_vals) / len(unit_vals)) if unit_vals else None
            unit_total_grade = (
                grade_label_from_percent(unit_total_pct) if unit_total_pct is not None else "غير محسوب"
            )

            unit_tabs.append(
                {
                    "unit_key": ukey,
                    "unit_label": u["unit_label"],
                    "completion": u,
                    "unit_total_pct": unit_total_pct,
                    "unit_total_grade": unit_total_grade,
                    "chart_items": chart_items,
                    "strengths": unit_strengths,
                    "weaknesses": unit_weaknesses,
                    # لا نستخدم key اسمها items لأن Jinja تعتبرها dict.items()
                    "eval_lists": items,
                    "judge_completion": unit_judge_completion.get(ukey) or [],
                }
            )
        unit_tabs.sort(key=lambda x: x["unit_label"])

        # متوسط عام
        scored = [float(r.total_pct) for r in saved_rows if r.total_pct is not None]
        overall_avg = (sum(scored) / len(scored)) if scored else None
        overall_grade = grade_label_from_percent(overall_avg) if overall_avg is not None else "غير محسوب"

        # المحكم الأقدم: أول صف في قائمة المحكمين (حسب sort_order) ضمن التمرين الحالي
        oldest_judge = (
            db.query(ExerciseRosterRow)
            .filter(
                ExerciseRosterRow.exercise_id == ex.id,
                ExerciseRosterRow.roster_kind == ExerciseRosterKind.JUDGE.value,
            )
            .order_by(ExerciseRosterRow.sort_order, ExerciseRosterRow.id)
            .first()
        )
        oldest_judge_unit_label = ""
        if oldest_judge is not None:
            uk_m = (getattr(oldest_judge, "unit_level_key", None) or "").strip()
            if uk_m:
                oldest_judge_unit_label = label_for_unit_level_key(uk_m) or uk_m
            else:
                oldest_judge_unit_label = (getattr(oldest_judge, "position_ar", None) or "").strip()

        saved_display = []
        for srow in saved_rows:
            uk_s = (srow.unit_level_key or "").strip()
            saved_display.append(
                {
                    "row": srow,
                    "unit_label_ar": (
                        label_for_unit_level_key(uk_s)
                        if uk_s
                        else ""
                    )
                    or (uk_s if uk_s else "—"),
                }
            )

        # توصية بسيطة
        if overall_avg is None:
            recommendation = "لا توجد نتائج محفوظة بعد. احفظ نتائج التقييم من صفحة قائمة التقييم أولاً."
        elif overall_avg >= 85:
            recommendation = "النتائج مرتفعة؛ يوصى بتثبيت الإجراءات الحالية والتركيز على التحسينات الدقيقة."
        elif overall_avg >= 70:
            recommendation = "النتائج جيدة؛ يوصى بوضع خطة تحسين مركّزة للعناصر الأقل أداءً."
        elif overall_avg >= 55:
            recommendation = "النتائج متوسطة؛ يوصى بإعادة التدريب على العناصر الأساسية وإعادة التقييم."
        else:
            recommendation = "النتائج منخفضة؛ يوصى بخطة تصحيح عاجلة وإعادة تنظيم التدريب قبل الاعتماد."

        return render_template(
            "analyst_judges_evaluation_analysis.html",
            **_ctx(
                user,
                section_title=title,
                has_exercise=True,
                exercise=ex,
                saved_rows=saved_rows,
                saved_display=saved_display,
                unit_totals=unit_totals,
                strengths_units=strengths_units,
                weaknesses_units=weaknesses_units,
                overall_avg=overall_avg,
                overall_grade=overall_grade,
                oldest_judge=oldest_judge,
                oldest_judge_unit_label=oldest_judge_unit_label or "—",
                recommendation=recommendation,
                unit_completion=unit_completion,
                judge_stats=judge_stats,
                unit_item_results=unit_item_results,
                unit_tabs=unit_tabs,
            ),
        )
    return render_template(
        "analyst_section_placeholder.html",
        **_ctx(user, section_title=title, section_slug=slug),
    )


# مساحة التخطيط — عناصر الشريط (المعرّف، العنوان، أيقونة Font Awesome)
PLANNER_HUB_ITEMS: tuple[tuple[str, str, str], ...] = (
    ("new-flow", "إنشاء مجرى جديد", "fa-diagram-project"),
    ("new-evaluation-list", "إنشاء قائمة تقييم", "fa-file-circle-plus"),
    ("evaluation-lists", "قوائم التقييم — إدخال النتائج", "fa-file-excel"),
    ("chat-rooms", "غرف المحادثة", "fa-comments"),
    ("incomplete-tasks", "موقف المهام غير المكتملة", "fa-hourglass-half"),
    ("battle-overview", "الصورة العامة للمعركة", "fa-map"),
    ("judges-location", "موقع المحكمين", "fa-location-dot"),
    ("notifications-log", "سجل الإشعارات", "fa-bell"),
    ("assign-task", "إسناد مهمة جديدة", "fa-user-plus"),
    ("exercise-info", "معلومات التمرين", "fa-circle-info"),
)
PLANNER_HUB_SLUGS: dict[str, str] = {s: t for s, t, _ in PLANNER_HUB_ITEMS}


@bp.route("/planner")
def planner_hub():
    user = get_current_user_optional()
    if not user:
        return redirect("/login?next=/planner")
    if not can_access_planner_hub(user):
        abort(403)
    hub_items = [{"slug": s, "title_ar": t, "icon": ic} for s, t, ic in PLANNER_HUB_ITEMS]
    return render_template(
        "planner_hub.html",
        **_ctx(
            user,
            hub_items=hub_items,
        ),
    )


@bp.route("/planner/<slug>")
def planner_hub_section(slug: str):
    user = get_current_user_optional()
    if not user:
        return redirect(f"/login?next=/planner/{slug}")
    if not can_access_planner_hub(user):
        abort(403)
    slug_norm = (slug or "").strip().lower()
    if slug_norm == "evaluation-lists":
        return redirect(url_for("views.planner_evaluation_lists_home"))
    if slug_norm == "chat-rooms":
        return redirect(url_for("views.chat_rooms_list"))
    if slug_norm == "notifications-log":
        return redirect(url_for("views.notifications_log"))
    if slug_norm == "visual-documentation":
        return redirect(url_for("views.visual_documentation"))
    title = PLANNER_HUB_SLUGS.get(slug_norm)
    if not title:
        abort(404)
    return render_template(
        "planner_section_placeholder.html",
        **_ctx(user, section_title=title, section_slug=slug),
    )


@bp.route("/planner/evaluation-lists", methods=["GET"])
def planner_evaluation_lists_home():
    user = get_current_user_optional()
    if not user:
        return redirect("/login?next=/planner/evaluation-lists")
    if not can_access_planner_hub(user):
        abort(403)
    from flask import g

    db = g.db
    ex = _admin_current_workspace_exercise(db, user)
    return render_template(
        "judge_evaluation_lists_home.html",
        **_ctx(
            user,
            has_exercise=ex is not None,
            exercise=ex,
            unit_levels=UNIT_LEVELS,
            hub_back_href=url_for("views.planner_hub"),
            unit_list_endpoint="views.planner_evaluation_lists",
        ),
    )


@bp.route("/planner/evaluation-lists/<unit_key>", methods=["GET"])
def planner_evaluation_lists(unit_key: str):
    user = get_current_user_optional()
    if not user:
        return redirect(f"/login?next=/planner/evaluation-lists/{unit_key}")
    if not can_access_planner_hub(user):
        abort(403)
    unit = next((x for x in UNIT_LEVELS if x["key"] == unit_key), None)
    if not unit:
        abort(404)
    from flask import g

    db = g.db
    ex = _admin_current_workspace_exercise(db, user)
    if ex is None:
        return redirect("/planner/evaluation-lists")
    items = (
        db.query(EvaluationListPdfItem)
        .filter(EvaluationListPdfItem.exercise_id == ex.id, EvaluationListPdfItem.unit_level_key == unit_key)
        .order_by(EvaluationListPdfItem.exercise_phase, EvaluationListPdfItem.sort_order, EvaluationListPdfItem.id)
        .all()
    )
    item_ids = [int(it.id) for it in items]
    canonical_by_item = _evaluation_canonical_map_for_items(db, ex.id, item_ids)

    evaluation_lists_rows: list[dict] = []
    for it in items:
        iid = int(it.id)
        s = canonical_by_item.get(iid)
        is_done = bool(s and getattr(s, "is_approved", False))
        evaluation_lists_rows.append(
            {
                "item_id": int(it.id),
                "item_title": (it.text or "تقييم").strip(),
                "dt": (getattr(s, "updated_at", None) if s else None) or getattr(it, "created_at", None),
                "exercise_type": (getattr(ex, "exercise_type", "") or "").strip(),
                "trained_unit": (getattr(ex, "trained_unit", "") or "").strip(),
                "delivery_dt": (
                    getattr(s, "approved_at", None)
                    if s is not None and bool(getattr(s, "is_approved", False))
                    else None
                ),
                "status_label": "ينجز" if is_done else "لم ينجز",
                "status_done": is_done,
                "grade_label": (getattr(s, "grade_label", "") or "").strip() if s else "",
                "open_href": url_for("views.planner_evaluation_list_file_viewer", unit_key=unit_key, item_id=it.id),
            }
        )
    return render_template(
        "judge_evaluation_lists.html",
        **_ctx(
            user,
            exercise=ex,
            unit=unit,
            unit_key=unit_key,
            items=items,
            evaluation_lists_rows=evaluation_lists_rows,
            eval_lists_parent_href=url_for("views.planner_evaluation_lists_home"),
        ),
    )


@bp.route("/planner/evaluation-lists/<unit_key>/view/<int:item_id>", methods=["GET"])
def planner_evaluation_list_file_viewer(unit_key: str, item_id: int):
    user = get_current_user_optional()
    if not user:
        return redirect(f"/login?next=/planner/evaluation-lists/{unit_key}/view/{item_id}")
    if not can_access_planner_hub(user):
        abort(403)
    unit = next((x for x in UNIT_LEVELS if x["key"] == unit_key), None)
    if not unit:
        abort(404)
    from flask import g

    db = g.db
    row = db.get(EvaluationListPdfItem, item_id)
    current_exercise = _admin_current_workspace_exercise(db, user)
    if not row or row.unit_level_key != unit_key or current_exercise is None or row.exercise_id != current_exercise.id:
        abort(404)
    list_url = url_for("views.planner_evaluation_lists", unit_key=unit_key)
    if not (row.pdf_relpath or "").strip():
        return redirect(list_url)
    fspath = _evaluation_list_file_abspath(row.pdf_relpath)
    if fspath is None:
        return redirect(list_url)
    ev = _evaluation_sheet_view_context(fspath)

    saved_payload = {}
    saved_updated_at = None
    saved_is_approved = False
    saved_approved_at = None
    saved_row_id = None
    canon = _evaluation_canonical_saved_row(db, current_exercise.id, row.id)

    def _load_payload(sr: EvaluationListSavedResult | None) -> dict:
        if not sr or not (sr.payload_json or "").strip():
            return {}
        try:
            p = json.loads(sr.payload_json)
        except Exception:
            return {}
        return p if isinstance(p, dict) else {}

    if canon is not None:
        saved_payload = _load_payload(canon)
        saved_updated_at = canon.updated_at
        saved_is_approved = bool(getattr(canon, "is_approved", False))
        saved_approved_at = getattr(canon, "approved_at", None)
        saved_row_id = canon.id

    unit_label = (unit.get("label") or "").strip() if isinstance(unit, dict) else ""
    shown_date = getattr(current_exercise, "planned_start", None) or getattr(current_exercise, "created_at", None)

    commander_name = "—"
    commander_row = (
        db.query(ExerciseRosterRow)
        .filter(
            ExerciseRosterRow.exercise_id == current_exercise.id,
            ExerciseRosterRow.roster_kind == ExerciseRosterKind.TRAINEE.value,
            ExerciseRosterRow.unit_level_key == unit_key,
        )
        .order_by(ExerciseRosterRow.sort_order, ExerciseRosterRow.id)
        .first()
    )
    if commander_row is not None:
        commander_name = (commander_row.full_name or "").strip() or commander_name

    judge_name = "—"
    judge_row = (
        db.query(ExerciseRosterRow)
        .filter(
            ExerciseRosterRow.exercise_id == current_exercise.id,
            ExerciseRosterRow.roster_kind == ExerciseRosterKind.JUDGE.value,
            ExerciseRosterRow.unit_level_key == unit_key,
        )
        .order_by(ExerciseRosterRow.sort_order, ExerciseRosterRow.id)
        .first()
    )
    if judge_row is not None:
        judge_name = (judge_row.full_name or "").strip() or judge_name

    eval_save_url = url_for("views.planner_evaluation_list_save_results", unit_key=unit_key, item_id=item_id)
    eval_approve_url = url_for("views.planner_evaluation_list_approve", unit_key=unit_key, item_id=item_id)
    show_eval_approve = can_approve_evaluation_results(user)

    return render_template(
        "judge_evaluation_list_viewer.html",
        **_ctx(
            user,
            unit_key=unit_key,
            item_id=item_id,
            item_title=row.text or "تقييم",
            evaluation_item_id=row.id,
            saved_row_id=saved_row_id,
            saved_payload=saved_payload,
            saved_updated_at=saved_updated_at,
            saved_is_approved=saved_is_approved,
            saved_approved_at=saved_approved_at,
            **ev,
            unit_label=unit_label or "—",
            shown_date=shown_date,
            commander_name=commander_name or "—",
            judge_name=judge_name or "—",
            has_saved_rows=bool(saved_payload and (saved_payload.get("rows") or [])),
            eval_save_url=eval_save_url,
            eval_approve_url=eval_approve_url,
            show_eval_approve=show_eval_approve,
            eval_can_edit=not saved_is_approved,
            eval_approve_incomplete=request.args.get("eval_approve_incomplete", type=int) == 1,
        ),
    )


@bp.route(
    "/planner/evaluation-lists/<unit_key>/view/<int:item_id>/save-results",
    methods=["POST"],
)
def planner_evaluation_list_save_results(unit_key: str, item_id: int):
    user = get_current_user_optional()
    if not user:
        abort(403)
    if not can_access_planner_hub(user):
        abort(403)
    unit = next((x for x in UNIT_LEVELS if x["key"] == unit_key), None)
    if not unit:
        abort(404)
    from flask import g

    db = g.db
    item = db.get(EvaluationListPdfItem, item_id)
    current_exercise = _admin_current_workspace_exercise(db, user)
    if (
        not item
        or item.unit_level_key != unit_key
        or current_exercise is None
        or item.exercise_id != current_exercise.id
    ):
        abort(404)

    raw = (request.form.get("payload_json") or "").strip()
    if not raw:
        return redirect(url_for("views.planner_evaluation_list_file_viewer", unit_key=unit_key, item_id=item_id))
    if len(raw) > 250_000:
        abort(400)
    _evaluation_commit_payload_save(db, user=user, item=item, current_exercise=current_exercise, raw=raw)
    return redirect(url_for("views.planner_evaluation_list_file_viewer", unit_key=unit_key, item_id=item_id))


@bp.route(
    "/planner/evaluation-lists/<unit_key>/view/<int:item_id>/approve",
    methods=["POST"],
)
def planner_evaluation_list_approve(unit_key: str, item_id: int):
    user = get_current_user_optional()
    if not user:
        abort(403)
    if not can_access_planner_hub(user):
        abort(403)
    if not can_approve_evaluation_results(user):
        abort(403)
    unit = next((x for x in UNIT_LEVELS if x["key"] == unit_key), None)
    if not unit:
        abort(404)
    from flask import g

    db = g.db
    item = db.get(EvaluationListPdfItem, item_id)
    current_exercise = _admin_current_workspace_exercise(db, user)
    if (
        not item
        or item.unit_level_key != unit_key
        or current_exercise is None
        or item.exercise_id != current_exercise.id
    ):
        abort(404)

    saved = _evaluation_canonical_saved_row(db, current_exercise.id, item.id)
    if saved is None or not (saved.payload_json or "").strip():
        abort(400)
    if bool(getattr(saved, "is_approved", False)):
        return redirect(url_for("views.planner_evaluation_list_file_viewer", unit_key=unit_key, item_id=item_id))
    rows = _parse_saved_eval_rows(saved.payload_json)
    if _evaluation_payload_has_empty_acquired_for_approve(rows):
        return redirect(
            url_for(
                "views.planner_evaluation_list_file_viewer",
                unit_key=unit_key,
                item_id=item_id,
                eval_approve_incomplete=1,
            )
        )
    saved.is_approved = True
    saved.approved_by_id = getattr(user, "id", None)
    saved.approved_at = datetime.utcnow()
    db.commit()
    return redirect(url_for("views.planner_evaluation_list_file_viewer", unit_key=unit_key, item_id=item_id))


# مساحة المحكمين — عناصر الشريط (المعرّف، العنوان، أيقونة Font Awesome)
JUDGE_HUB_ITEMS: tuple[tuple[str, str, str], ...] = (
    ("dilemmas", "قوائم المعاضل", "fa-file-pdf"),
    ("evaluation-lists", "قوائم التقييم", "fa-file-excel"),
    ("visual-documentation", "التوثيق المرئي", "fa-photo-film"),
    ("chat-rooms", "غرف المحادثة", "fa-comments"),
    ("incomplete-tasks", "مهام غير مكتملة", "fa-clipboard-list"),
    ("battle-overview", "الصورة العامة للمعركة", "fa-map"),
    ("judges-location", "موقع المحكمين", "fa-location-dot"),
    ("notifications-log", "سجل الإشعارات", "fa-bell"),
    ("exercise-info", "معلومات التمرين", "fa-circle-info"),
)
JUDGE_HUB_SLUGS: dict[str, str] = {s: t for s, t, _ in JUDGE_HUB_ITEMS}


@bp.route("/judge")
def judge_hub():
    user = get_current_user_optional()
    if not user:
        return redirect("/login?next=/judge")
    if not can_access_judge_hub(user):
        abort(403)
    # للمحكمين (غير إدارة النظام): نظهر فقط مساحة "قوائم التقييم" وما يرتبط بها
    from flask import g

    db = g.db
    ex = _current_workspace_exercise(db, user)
    _ensure_judge_roster_synced(db, user, ex)

    items_src = JUDGE_HUB_ITEMS if is_system_admin(user) else tuple(
        x
        for x in JUDGE_HUB_ITEMS
        if x[0] in ("dilemmas", "evaluation-lists", "incomplete-tasks", "chat-rooms")
    )
    hub_items = [{"slug": s, "title_ar": t, "icon": ic} for s, t, ic in items_src]
    return render_template(
        "judge_hub.html",
        **_ctx(user, hub_items=hub_items),
    )


@bp.route("/judge/<slug>")
def judge_hub_section(slug: str):
    user = get_current_user_optional()
    if not user:
        return redirect(f"/login?next=/judge/{slug}")
    if not can_access_judge_hub(user):
        abort(403)
    title = JUDGE_HUB_SLUGS.get((slug or "").strip().lower())
    if not title:
        abort(404)
    if slug == "evaluation-lists":
        return redirect("/judge/evaluation-lists")
    if slug == "dilemmas":
        return redirect("/judge/dilemmas")
    if slug == "chat-rooms":
        return redirect(url_for("views.chat_rooms_list"))
    if slug == "visual-documentation":
        return redirect(url_for("views.visual_documentation"))
    if slug == "notifications-log":
        return redirect(url_for("views.notifications_log"))
    if slug == "incomplete-tasks":
        from flask import g

        db = g.db
        ex = _admin_current_workspace_exercise(db, user)
        if ex is None:
            return render_template(
                "judge_incomplete_tasks.html",
                **_ctx(user, section_title=title, has_exercise=False, tasks=[]),
            )

        from app.models import JudgeIncompleteTaskStatus

        judge_id = int(getattr(user, "id", 0) or 0)
        # اسم المستخدم الحالي كقيمة احتياطية فقط في حال غياب أي محكم في قائمة المحكمين
        fallback_judge_name = (
            (getattr(user, "full_name", "") or "").strip()
            or (getattr(user, "username", "") or "").strip()
            or f"محكم #{judge_id}"
        )

        # خريطة: مفتاح مستوى الوحدة -> اسم المحكم المسجّل في "إدارة النظام/قوائم المحكمين"
        # (الربط مع المتدرب يتم عبر unit_level_key نفسه؛ نفس المفتاح المستخدم في قائمة المتدربين)
        judge_roster_rows = (
            db.query(ExerciseRosterRow)
            .filter(
                ExerciseRosterRow.exercise_id == ex.id,
                ExerciseRosterRow.roster_kind == ExerciseRosterKind.JUDGE.value,
            )
            .order_by(ExerciseRosterRow.sort_order, ExerciseRosterRow.id)
            .all()
        )
        judge_name_by_unit: dict[str, str] = {}
        for jr in judge_roster_rows:
            uk2 = (jr.unit_level_key or "").strip()
            if not uk2:
                continue
            display = (jr.full_name or "").strip()
            rank2 = (jr.rank_ar or "").strip()
            if rank2 and display:
                display = f"{rank2} {display}"
            elif not display:
                display = (jr.military_number or "").strip()
            if uk2 and display and uk2 not in judge_name_by_unit:
                judge_name_by_unit[uk2] = display

        # نقرأ الربط للمرحلتين (الرئيسي/إعادة التنظيم) لتكوين قائمة مهام شاملة
        phases = [ExercisePhase.MAIN.value, ExercisePhase.REORG.value]
        report_blocks = []
        for ph in phases:
            report_blocks.extend(_build_dilemma_evaluation_unit_report(db, ex.id, exercise_phase=ph))

        # تقليص العرض للمحكم إلى وحدته المخصصة (إن وجدت)
        a = _judge_assignment_for_current_exercise(db, user, ex)
        assigned_uk = (getattr(a, "unit_level_key", "") or "").strip() if a else ""
        if assigned_uk and not is_system_admin(user):
            report_blocks = [b for b in report_blocks if (b.get("unit_key") or "") == assigned_uk]

        # overrides المحفوظة
        overrides = (
            db.query(JudgeIncompleteTaskStatus)
            .filter(JudgeIncompleteTaskStatus.exercise_id == ex.id, JudgeIncompleteTaskStatus.judge_id == judge_id)
            .all()
        )
        override_map: dict[tuple[str, str, int], JudgeIncompleteTaskStatus] = {}
        for o in overrides:
            override_map[(o.unit_level_key or "", o.exercise_phase or "", int(o.pair_index or 0))] = o

        # نتائج التقييم الموحّدة (سجل واحد لكل عنصر يظهر لجميع المستخدمين)
        eval_item_ids: list[int] = []
        for blk in report_blocks:
            for p in blk.get("pairs") or []:
                ev = p.get("evaluation")
                if ev and ev.get("id") is not None:
                    try:
                        eval_item_ids.append(int(ev["id"]))
                    except Exception:
                        pass
        eval_item_ids = sorted(set(eval_item_ids))
        canonical_by_item = _evaluation_canonical_map_for_items(db, ex.id, eval_item_ids)

        now = datetime.utcnow()
        tasks: list[dict] = []
        for blk in report_blocks:
            uk = blk.get("unit_key") or ""
            ul = blk.get("unit_label") or ""
            for p in blk.get("pairs") or []:
                di = p.get("dilemma")
                ev = p.get("evaluation")
                if not di:
                    continue
                if not ev:
                    continue
                dilemma_id = int(di.get("id")) if di and di.get("id") is not None else None
                eval_item_id = int(ev.get("id")) if ev and ev.get("id") is not None else None
                if eval_item_id is None:
                    continue
                canon = canonical_by_item.get(eval_item_id)
                saved = canon
                done_dt = None
                is_done = False
                if canon is not None:
                    is_done = bool(getattr(canon, "is_approved", False))
                    done_dt = (
                        getattr(canon, "approved_at", None)
                        if is_done
                        else getattr(canon, "updated_at", None)
                    )

                # مؤشر حالة تلقائي (مع إمكانية override محفوظ)
                # القاعدة: إن كان التقييم معتمد -> مكتملة، وإلا ضمن الوقت (افتراضي).
                auto_status = "done" if is_done else "ontime"

                ph = (getattr(saved, "exercise_phase", None) if saved is not None else None) or ExercisePhase.MAIN.value
                ph = _normalized_exercise_phase(ph)
                ph_ar = "إعادة التنظيم" if ph == ExercisePhase.REORG.value else "التمرين الرئيسي"

                key = (uk, ph, int(p.get("index") or 0))
                ov = override_map.get(key)
                status_key = (ov.status_key if ov else "") or auto_status

                # درجة الأسبقية تعتمد على مؤشر الحالة
                if status_key == "late":
                    prio = "high"
                elif status_key == "done":
                    prio = "low"
                else:
                    prio = "medium"

                tasks.append(
                    {
                        "task_name": (di.get("text") or "مهمة").strip(),
                        "judge_name": judge_name_by_unit.get(uk, fallback_judge_name),
                        "done_dt": done_dt,
                        "priority_key": prio,
                        "status_key": status_key,
                        "unit_key": uk,
                        "unit_label": ul,
                        "phase": ph,
                        "phase_ar": ph_ar,
                        "pair_index": int(p.get("index") or 0),
                        "dilemma_id": dilemma_id,
                        "evaluation_item_id": eval_item_id,
                        "open_eval_href": url_for("views.judge_evaluation_list_file_viewer", unit_key=uk, item_id=eval_item_id),
                    }
                )

        # ترتيب الجدول حسب "اسم المهمة"
        tasks.sort(key=lambda x: ((x.get("task_name") or "").strip().lower()))

        return render_template(
            "judge_incomplete_tasks.html",
            **_ctx(
                user,
                section_title=title,
                has_exercise=True,
                exercise=ex,
                tasks=tasks,
            ),
        )
    return render_template(
        "judge_section_placeholder.html",
        **_ctx(user, section_title=title, section_slug=slug),
    )


@bp.route("/judge/incomplete-tasks/update", methods=["POST"])
def judge_incomplete_tasks_update():
    user = get_current_user_optional()
    if not user:
        return redirect("/login?next=/judge/incomplete-tasks")
    if not can_access_judge_hub(user):
        abort(403)
    from flask import g

    db = g.db
    ex = _admin_current_workspace_exercise(db, user)
    if ex is None:
        return redirect("/judge/incomplete-tasks")

    from app.models import JudgeIncompleteTaskStatus, JudgeTaskStatusKey

    unit_key = (request.form.get("unit_key") or "").strip()
    phase = _normalized_exercise_phase(request.form.get("phase"))
    pair_index_raw = (request.form.get("pair_index") or "").strip()
    status_key = (request.form.get("status_key") or "").strip().lower()
    if status_key not in (
        JudgeTaskStatusKey.LATE.value,
        JudgeTaskStatusKey.ONTIME.value,
        JudgeTaskStatusKey.DONE.value,
    ):
        status_key = JudgeTaskStatusKey.ONTIME.value
    try:
        pair_index = int(pair_index_raw)
    except Exception:
        pair_index = 0
    dilemma_id_raw = (request.form.get("dilemma_id") or "").strip()
    evaluation_item_id_raw = (request.form.get("evaluation_item_id") or "").strip()
    dilemma_id = int(dilemma_id_raw) if dilemma_id_raw.isdigit() else None
    evaluation_item_id = int(evaluation_item_id_raw) if evaluation_item_id_raw.isdigit() else None

    judge_id = int(getattr(user, "id", 0) or 0)
    row = (
        db.query(JudgeIncompleteTaskStatus)
        .filter(
            JudgeIncompleteTaskStatus.exercise_id == ex.id,
            JudgeIncompleteTaskStatus.judge_id == judge_id,
            JudgeIncompleteTaskStatus.unit_level_key == unit_key,
            JudgeIncompleteTaskStatus.exercise_phase == phase,
            JudgeIncompleteTaskStatus.pair_index == pair_index,
        )
        .first()
    )
    if row is None:
        row = JudgeIncompleteTaskStatus(
            exercise_id=ex.id,
            judge_id=judge_id,
            unit_level_key=unit_key,
            exercise_phase=phase,
            pair_index=pair_index,
        )
        db.add(row)
    row.dilemma_id = dilemma_id
    row.evaluation_item_id = evaluation_item_id
    row.status_key = status_key
    db.commit()
    return redirect("/judge/incomplete-tasks")


def _notifications_scope_exercise(db, user: User) -> Exercise | None:
    """التمرين المرتبط بسجل الإشعارات (نفس منطق غرف المحادثة)."""
    if is_system_admin(user):
        return _admin_current_workspace_exercise(db, user)
    return _current_workspace_exercise(db, user)


@bp.route("/notifications", methods=["GET"])
def notifications_log():
    user = get_current_user_optional()
    if not user:
        return redirect("/login?next=/notifications")
    if not can_view_notifications_log(user):
        abort(403)
    from flask import g

    db = g.db
    ex = _notifications_scope_exercise(db, user)
    rows: list[ExerciseNotification] = []
    if ex is not None:
        rows = (
            db.query(ExerciseNotification)
            .filter(
                ExerciseNotification.user_id == int(user.id),
                ExerciseNotification.exercise_id == int(ex.id),
            )
            .order_by(desc(ExerciseNotification.created_at), desc(ExerciseNotification.id))
            .limit(500)
            .all()
        )
    return render_template(
        "notifications_log.html",
        **_ctx(user, has_exercise=ex is not None, exercise=ex, notifications=rows),
    )


@bp.route("/notifications/<int:nid>/read", methods=["POST"])
def notification_mark_read(nid: int):
    user = get_current_user_optional()
    if not user:
        return redirect("/login?next=/notifications")
    if not can_view_notifications_log(user):
        abort(403)
    from flask import g

    db = g.db
    ex = _notifications_scope_exercise(db, user)
    if ex is None:
        return redirect(url_for("views.notifications_log"))
    row = db.get(ExerciseNotification, nid)
    if (
        row
        and int(row.user_id) == int(user.id)
        and int(row.exercise_id) == int(ex.id)
    ):
        row.is_read = True
        db.add(row)
        db.commit()
    return redirect(url_for("views.notifications_log"))


@bp.route("/notifications/read-all", methods=["POST"])
def notifications_mark_all_read():
    user = get_current_user_optional()
    if not user:
        return redirect("/login?next=/notifications")
    if not can_view_notifications_log(user):
        abort(403)
    from flask import g

    db = g.db
    ex = _notifications_scope_exercise(db, user)
    if ex is not None:
        for row in (
            db.query(ExerciseNotification)
            .filter(
                ExerciseNotification.user_id == int(user.id),
                ExerciseNotification.exercise_id == int(ex.id),
                ExerciseNotification.is_read == False,
            )
            .all()
        ):
            row.is_read = True
            db.add(row)
        db.commit()
    return redirect(url_for("views.notifications_log"))


@bp.route("/api/notifications/summary", methods=["GET"])
def api_notifications_summary():
    user = get_current_user_optional()
    if not user:
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    if not can_view_notifications_log(user):
        return jsonify({"ok": False, "error": "forbidden"}), 403
    from flask import g

    db = g.db
    ex = _notifications_scope_exercise(db, user)
    if ex is None:
        return jsonify({"ok": True, "unread_count": 0, "latest": []})
    unread = (
        db.query(func.count(ExerciseNotification.id))
        .filter(
            ExerciseNotification.user_id == int(user.id),
            ExerciseNotification.exercise_id == int(ex.id),
            ExerciseNotification.is_read == False,
        )
        .scalar()
        or 0
    )
    latest_rows = (
        db.query(ExerciseNotification)
        .filter(
            ExerciseNotification.user_id == int(user.id),
            ExerciseNotification.exercise_id == int(ex.id),
        )
        .order_by(desc(ExerciseNotification.created_at), desc(ExerciseNotification.id))
        .limit(8)
        .all()
    )
    latest = [
        {
            "id": r.id,
            "title": r.title,
            "type": r.type,
            "is_read": bool(r.is_read),
            "action_url": r.action_url or "",
            "created_at": r.created_at.isoformat() if r.created_at else "",
        }
        for r in latest_rows
    ]
    return jsonify({"ok": True, "unread_count": int(unread), "latest": latest})


def _visual_scope_exercise(db, user: User) -> Exercise | None:
    """نطاق التمرين للتوثيق المرئي (نفس منطق المحادثة/الإشعارات)."""
    if is_system_admin(user):
        return _admin_current_workspace_exercise(db, user)
    return _current_workspace_exercise(db, user)


def _visual_doc_disk_path(relpath: str) -> Path | None:
    if not relpath or ".." in relpath.replace("\\", "/"):
        return None
    root = VISUAL_DOC_DIR.resolve()
    p = (root / relpath).resolve()
    if str(p).startswith(str(root)):
        return p
    return None


_VISUAL_ALLOWED_SUFFIX = {
    ".jpg",
    ".jpeg",
    ".png",
    ".mp4",
    ".mp3",
    ".wav",
    ".m4a",
    ".ogg",
    ".webm",
}
_VISUAL_MAX_UPLOAD_BYTES = 80 * 1024 * 1024  # 80MB


@bp.route("/visual-documentation", methods=["GET"])
def visual_documentation():
    user = get_current_user_optional()
    if not user:
        return redirect("/login?next=/visual-documentation")
    if not can_use_visual_documentation(user):
        abort(403)
    from flask import g

    db = g.db
    ex = _visual_scope_exercise(db, user)
    if ex is None:
        return render_template(
            "visual_documentation.html",
            **_ctx(user, has_exercise=False, exercise=None, unit_levels=[], selected_unit_key="", docs=[], dilemmas=[]),
        )

    # نطاق الوحدة للمحكم غير إدارة النظام
    a = _judge_assignment_for_current_exercise(db, user, ex)
    assigned_uk = (getattr(a, "unit_level_key", "") or "").strip() if a else ""
    unit_key = (request.args.get("unit_key") or "").strip()
    if assigned_uk and not is_system_admin(user):
        unit_key = assigned_uk
    if not unit_key:
        unit_key = assigned_uk or (UNIT_LEVELS[0]["key"] if UNIT_LEVELS else "")

    q = db.query(VisualDocument).filter(VisualDocument.exercise_id == int(ex.id))
    if unit_key:
        q = q.filter(VisualDocument.unit_level_key == unit_key)
    if assigned_uk and not is_system_admin(user):
        q = q.filter(VisualDocument.unit_level_key == assigned_uk)
    docs = q.order_by(desc(VisualDocument.created_at), desc(VisualDocument.id)).limit(400).all()

    dilemmas = (
        db.query(DilemmaItem)
        .filter(DilemmaItem.exercise_id == int(ex.id), DilemmaItem.unit_level_key == unit_key)
        .order_by(DilemmaItem.sort_order, DilemmaItem.id)
        .all()
        if unit_key
        else []
    )
    unit_levels = [u for u in UNIT_LEVELS if not assigned_uk or u.get("key") == assigned_uk]
    return render_template(
        "visual_documentation.html",
        **_ctx(
            user,
            has_exercise=True,
            exercise=ex,
            unit_levels=unit_levels,
            selected_unit_key=unit_key,
            docs=docs,
            dilemmas=dilemmas,
            assigned_unit_key=assigned_uk,
        ),
    )


@bp.route("/visual-documentation/upload", methods=["POST"])
def visual_documentation_upload():
    user = get_current_user_optional()
    if not user:
        return redirect("/login?next=/visual-documentation")
    if not can_use_visual_documentation(user):
        abort(403)
    from flask import g

    db = g.db
    ex = _visual_scope_exercise(db, user)
    if ex is None:
        return redirect(url_for("views.visual_documentation"))

    a = _judge_assignment_for_current_exercise(db, user, ex)
    assigned_uk = (getattr(a, "unit_level_key", "") or "").strip() if a else ""
    unit_key = normalize_unit_level_key(request.form.get("unit_key") or "")
    if assigned_uk and not is_system_admin(user):
        unit_key = assigned_uk
    if not unit_key:
        unit_key = assigned_uk

    f = request.files.get("media_file")
    if not f or not (getattr(f, "filename", "") or "").strip():
        return redirect(url_for("views.visual_documentation", unit_key=unit_key))
    raw_name = secure_filename(f.filename)
    suf = Path(raw_name).suffix.lower()
    if suf not in _VISUAL_ALLOWED_SUFFIX:
        return redirect(url_for("views.visual_documentation", unit_key=unit_key))
    data = f.read()
    if not data or len(data) > _VISUAL_MAX_UPLOAD_BYTES:
        return redirect(url_for("views.visual_documentation", unit_key=unit_key))

    uploaded_mime = (getattr(f, "mimetype", "") or "").lower()
    if suf in (".mp4",) or uploaded_mime.startswith("video/"):
        ft = "video"
    elif suf in (".mp3", ".wav", ".m4a", ".ogg", ".webm") or uploaded_mime.startswith("audio/"):
        ft = "audio"
    else:
        ft = "image"

    desc_txt = (request.form.get("description") or "").strip()[:5000]
    loc = (request.form.get("location_label") or "").strip()[:400]
    dilemma_id_raw = (request.form.get("dilemma_id") or "").strip()
    event_id_raw = (request.form.get("event_id") or "").strip()
    dilemma_id = int(dilemma_id_raw) if dilemma_id_raw.isdigit() else None
    event_id = int(event_id_raw) if event_id_raw.isdigit() else None

    VISUAL_DOC_DIR.mkdir(parents=True, exist_ok=True)
    sub = VISUAL_DOC_DIR / str(int(ex.id)) / (unit_key or "misc")
    sub.mkdir(parents=True, exist_ok=True)
    store_name = f"{uuid.uuid4().hex}{suf}"
    disk_path = (sub / store_name).resolve()
    disk_path.write_bytes(data)
    rel = f"{int(ex.id)}/{(unit_key or 'misc')}/{store_name}".replace("\\", "/")

    row = VisualDocument(
        exercise_id=int(ex.id),
        event_id=event_id,
        dilemma_id=dilemma_id,
        unit_level_key=(unit_key or "").strip(),
        uploaded_by_id=int(user.id),
        file_type=ft,
        file_relpath=rel,
        description=desc_txt,
        location_label=loc,
    )
    db.add(row)
    db.commit()

    # إشعار للمستخدمين المعنيين
    try:
        from app.notifications_service import notify_visual_document_added

        unit_label = label_for_unit_level_key(unit_key) or unit_key
        notify_visual_document_added(
            db,
            exercise_id=int(ex.id),
            unit_key=unit_key,
            unit_label=unit_label,
            file_type=ft,
            action_url=url_for("views.visual_documentation", unit_key=unit_key),
        )
        db.commit()
    except Exception:
        db.rollback()

    return redirect(url_for("views.visual_documentation", unit_key=unit_key))


@bp.route("/visual-documents/<int:doc_id>/file", methods=["GET"])
def visual_document_file(doc_id: int):
    user = get_current_user_optional()
    if not user:
        return redirect(f"/login?next=/visual-documents/{doc_id}/file")
    if not can_use_visual_documentation(user):
        abort(403)
    from flask import g

    db = g.db
    row = db.get(VisualDocument, doc_id)
    if row is None:
        abort(404)
    ex = _visual_scope_exercise(db, user)
    if ex is None or int(row.exercise_id) != int(ex.id):
        abort(404)
    if not is_system_admin(user) and is_judge(user):
        a = _judge_assignment_for_current_exercise(db, user, ex)
        assigned_uk = (getattr(a, "unit_level_key", "") or "").strip() if a else ""
        if assigned_uk and (row.unit_level_key or "").strip() != assigned_uk:
            abort(403)

    p = _visual_doc_disk_path((row.file_relpath or "").strip())
    if p is None or not p.is_file():
        abort(404)
    mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    return send_file(p, mimetype=mime)


# مساحة السيطرة — عناصر الشريط (المعرّف، العنوان، أيقونة Font Awesome)
CONTROL_HUB_ITEMS: tuple[tuple[str, str, str], ...] = (
    ("evaluation-lists-status", "موقف قوائم التقييم", "fa-file-excel"),
    ("top-positives-negatives", "عرض أبرز الإيجابيات والسلبيات", "fa-star"),
    ("evaluation-results", "عرض نتائج التقييم", "fa-square-poll-vertical"),
    ("chat-rooms", "غرف المحادثة", "fa-comments"),
    ("incomplete-tasks-status", "موقف المهام غير المكتملة", "fa-hourglass-half"),
    ("visual-doc-status", "موقف التوثيق المرئي", "fa-photo-film"),
    ("battle-overview", "الصورة العامة للمعركة", "fa-map"),
    ("judges-location", "موقع المحكمين", "fa-location-dot"),
    ("notifications-log", "سجل الإشعارات", "fa-bell"),
    ("assign-task", "إسناد مهمة جديدة", "fa-user-plus"),
)
CONTROL_HUB_SLUGS: dict[str, str] = {s: t for s, t, _ in CONTROL_HUB_ITEMS}


def _control_exercise_performance_report(db, user: User) -> dict:
    """تقرير السيطرة الشامل وفق النموذج التشغيلي المعتمد في الصورة المرجعية.

    ملاحظة: التصميم يُحافظ عليه كما هو، بينما تُحسب القيم من نتائج التقييم المحفوظة/المعتمدة.
    """

    def _ar_month_name(m: int) -> str:
        return {
            1: "يناير",
            2: "فبراير",
            3: "مارس",
            4: "أبريل",
            5: "مايو",
            6: "يونيو",
            7: "يوليو",
            8: "أغسطس",
            9: "سبتمبر",
            10: "أكتوبر",
            11: "نوفمبر",
            12: "ديسمبر",
        }.get(int(m or 0), "")

    def _fmt_m_ss(seconds: float | None) -> str:
        if seconds is None:
            return "—"
        s = int(round(max(0.0, float(seconds))))
        mm = s // 60
        ss = s % 60
        return f"{mm}:{ss:02d}"

    def _avg(xs: list[float]) -> float | None:
        xs2 = [float(x) for x in xs if x is not None]
        return (sum(xs2) / len(xs2)) if xs2 else None

    def _radar_points(values_pct: list[float | None]) -> str:
        # نقاط سداسية (مثل SVG في القالب): أعلى ثم يمين-أعلى ثم يمين-أسفل ثم أسفل ثم يسار-أسفل ثم يسار-أعلى.
        cx, cy = 200.0, 127.5
        outer = [(200.0, 35.0), (285.0, 80.0), (285.0, 170.0), (200.0, 220.0), (115.0, 170.0), (115.0, 80.0)]
        pts: list[str] = []
        for i in range(6):
            v = values_pct[i] if i < len(values_pct) else None
            p = max(0.0, min(100.0, float(v))) / 100.0 if v is not None else 0.0
            ox, oy = outer[i]
            x = cx + (ox - cx) * p
            y = cy + (oy - cy) * p
            pts.append(f"{x:.0f},{y:.0f}")
        if pts:
            pts.append(pts[0])
        return " ".join(pts)

    ex0 = _current_workspace_exercise(db, user)
    if ex0 is None:
        return {
            "exercise": None,
            "crumb": "",
            "criteria_count": 0,
            "report_title": "تقرير شامل لأداء التمرين",
            "exercise_label": "—",
            "exercise_code": "—",
            "meta": [],
            "kpis": [],
            "axis_scores": [],
            "group_scores": [],
            "timeline": [],
            "distribution": [],
            "table_rows": [],
            "table_headers": [],
            "radar_series": [],
        }

    ex = db.query(Exercise).filter(Exercise.id == ex0.id).first()
    eval_items = (
        db.query(EvaluationListPdfItem)
        .filter(EvaluationListPdfItem.exercise_id == ex0.id)
        .order_by(
            EvaluationListPdfItem.unit_level_key,
            EvaluationListPdfItem.exercise_phase,
            EvaluationListPdfItem.sort_order,
            EvaluationListPdfItem.id,
        )
        .all()
    )

    item_ids = [int(it.id) for it in eval_items if getattr(it, "id", None) is not None]
    canon_by_item = _evaluation_canonical_map_for_items(db, ex0.id, item_ids) if item_ids else {}
    approved_by_item = {iid: sr for iid, sr in canon_by_item.items() if bool(getattr(sr, "is_approved", False))}

    n_eval_lists = len(eval_items)
    n_saved = len(canon_by_item)
    n_approved = len(approved_by_item)

    # متوسط زمن التنفيذ لكل تقييم (تقريب من إنشاء السجل حتى آخر تحديث/اعتماد)
    durations: list[float] = []
    for sr in approved_by_item.values():
        t0 = getattr(sr, "created_at", None)
        t1 = getattr(sr, "approved_at", None) or getattr(sr, "updated_at", None)
        if not t0 or not t1:
            continue
        try:
            sec = (t1 - t0).total_seconds()
        except Exception:
            continue
        if 0 <= sec <= 60 * 60 * 24:
            durations.append(float(sec))
    avg_duration = _avg(durations)

    # إجمالي المعايير/البنود المحسوبة + توزيعها
    scored_row_pcts: list[float] = []
    for sr in approved_by_item.values():
        for r in _parse_saved_eval_rows(getattr(sr, "payload_json", None)):
            if not isinstance(r, dict):
                continue
            pc = _eval_row_score_pct(r)
            if pc is None:
                continue
            scored_row_pcts.append(float(pc))
    criteria_count = len(scored_row_pcts)

    def _band_for_pct(p: float) -> str:
        if p >= 90:
            return "excellent"
        if p >= 80:
            return "vgood"
        if p >= 70:
            return "good"
        if p >= 60:
            return "mid"
        return "low"

    band_defs = [
        ("excellent", "ممتاز (90% - 100%)", "#7bd86f"),
        ("vgood", "جيد جداً (80% - 89%)", "#38bdf8"),
        ("good", "جيد (70% - 79%)", "#f59e0b"),
        ("mid", "متوسط (60% - 69%)", "#fb923c"),
        ("low", "أقل من 60%", "#ef4444"),
    ]
    band_counts = {k: 0 for k, _, _ in band_defs}
    for p in scored_row_pcts:
        band_counts[_band_for_pct(float(p))] += 1
    total_scored = max(1, sum(band_counts.values()))
    distribution = []
    for k, label, color in band_defs:
        c = int(band_counts.get(k, 0) or 0)
        pct = int(round((c / total_scored) * 100.0)) if total_scored else 0
        distribution.append({"label": label, "pct": pct, "count": c, "color": color})

    # حالة الإنجاز: نسبة المعتمد مقابل الإجمالي (وأي عنصر غير معتمد يعتبر "قيد التقييم")
    pending_pct = int(round(((n_eval_lists - n_approved) / n_eval_lists) * 100.0)) if n_eval_lists else 0
    done_pct = max(0, 100 - pending_pct) if n_eval_lists else 0

    # متوسط عام من نتائج العناصر المعتمدة (إن وجدت)
    approved_totals: list[float] = []
    for sr in approved_by_item.values():
        v = getattr(sr, "total_pct", None)
        if v is None:
            # fallback: متوسط البنود داخل نفس العنصر
            rows = [float(x) for x in (_eval_row_score_pct(r) for r in _parse_saved_eval_rows(sr.payload_json)) if x is not None]
            v = (sum(rows) / len(rows)) if rows else None
        if v is not None:
            approved_totals.append(float(v))
    overall_avg = _avg(approved_totals) or (_avg(scored_row_pcts) if scored_row_pcts else None)
    overall_avg_i = int(round(overall_avg)) if overall_avg is not None else 0

    # متوسط كل وحدة (مجموعات) من العناصر المعتمدة
    by_unit_vals: dict[str, list[float]] = {}
    for it in eval_items:
        sr = approved_by_item.get(int(getattr(it, "id", 0) or 0))
        if sr is None:
            continue
        uk = (getattr(it, "unit_level_key", "") or "").strip()
        if not uk:
            continue
        v = getattr(sr, "total_pct", None)
        if v is None:
            rows = [float(x) for x in (_eval_row_score_pct(r) for r in _parse_saved_eval_rows(sr.payload_json)) if x is not None]
            v = (sum(rows) / len(rows)) if rows else None
        if v is None:
            continue
        by_unit_vals.setdefault(uk, []).append(float(v))

    palette = ["#7bd86f", "#38bdf8", "#a855f7", "#f59e0b", "#67e8f9", "#ef4444", "#84cc16", "#fb923c"]
    unit_avg_rows: list[dict] = []
    for i, ul in enumerate(UNIT_LEVELS):
        uk = (ul.get("key") or "").strip()
        if not uk:
            continue
        vals = by_unit_vals.get(uk) or []
        avg_u = _avg(vals)
        if avg_u is None:
            continue
        unit_avg_rows.append(
            {
                "unit_key": uk,
                "label": (ul.get("label") or uk),
                "value": int(round(avg_u)),
                "raw": float(avg_u),
                "color": palette[i % len(palette)],
            }
        )
    unit_avg_rows.sort(key=lambda r: float(r.get("raw", 0.0)), reverse=True)
    top_unit = unit_avg_rows[0] if unit_avg_rows else None
    bottom_unit = unit_avg_rows[-1] if unit_avg_rows else None
    group_scores = [{"label": r["label"], "value": r["value"], "color": r["color"]} for r in unit_avg_rows[:6]]

    # محور/جدول: نستخدم مصفوفة الأهداف إن وجدت لتوليد 8 محاور بنفس عناوين الصورة.
    axis_labels = [
        ("القيادة والسيطرة", "#64b5f6"),
        ("التخطيط", "#7bd86f"),
        ("جمع المعلومات", "#78d06a"),
        ("العمليات", "#8b5cf6"),
        ("الاستطلاع", "#f59e0b"),
        ("الدعم اللوجستي", "#d7b735"),
        ("الاتصالات", "#fb923c"),
        ("الأمن والدفاع", "#ef4444"),
    ]
    dash = _build_analyst_evaluation_results_dashboard(db, user, approved_only=True, matrix_mode="objectives")
    matrix_rows = dash.get("matrix_rows") or []

    def _axis_value_for_unit(unit_key: str, axis_idx: int) -> float | None:
        for mr in matrix_rows:
            if (mr.get("unit_key") or "").strip() != (unit_key or "").strip():
                continue
            cells = mr.get("cells") or []
            if axis_idx < len(cells):
                v = cells[axis_idx].get("pct")
                return float(v) if v is not None else None
        return None

    axis_scores: list[dict] = []
    for i, (lbl, col) in enumerate(axis_labels):
        vals_i: list[float] = []
        for mr in matrix_rows:
            cells = mr.get("cells") or []
            if i < len(cells):
                v = cells[i].get("pct")
                if v is not None:
                    vals_i.append(float(v))
        vavg = _avg(vals_i)
        if vavg is None:
            vavg = float(overall_avg_i)
        axis_scores.append({"label": lbl, "value": int(round(vavg)), "color": col})

    table_headers = [
        "الوحدة / المحور",
        "القيادة والسيطرة",
        "جمع المعلومات",
        "العمليات",
        "المعلومات",
        "الاستطلاع",
        "الدعم اللوجستي",
        "الاتصالات",
        "المتوسط",
    ]

    # اختيار 6 وحدات للجدول (نفس الظاهر في عمود المجموعات، مع fallback لأول وحدات الكتالوج)
    units_for_table = []
    for r in unit_avg_rows[:6]:
        units_for_table.append({"unit_key": r["unit_key"], "label": r["label"]})
    if not units_for_table:
        for ul in UNIT_LEVELS[:6]:
            units_for_table.append({"unit_key": (ul.get("key") or ""), "label": (ul.get("label") or ul.get("key") or "—")})

    table_rows: list[list] = []
    # ملاحظة: الأعمدة الوسطية في الجدول تشمل "المعلومات" كعنوان مستقل في الصورة؛ نربطه بمحور التخطيط (index=1) إذا لم تتوفر أهداف كافية.
    for u in units_for_table:
        uk = (u.get("unit_key") or "").strip()
        if not uk:
            continue
        axis_vals = []
        # الأعمدة: القيادة(0), جمع المعلومات(2), العمليات(3), المعلومات(2 fallback), الاستطلاع(4), اللوجستي(5), الاتصالات(6)
        mapping = [0, 2, 3, 2, 4, 5, 6]
        for ax in mapping:
            v = _axis_value_for_unit(uk, ax)
            axis_vals.append(int(round(v)) if v is not None else 0)
        avg_row = int(round(sum(axis_vals) / len(axis_vals))) if axis_vals else 0
        table_rows.append([u["label"], *axis_vals, avg_row])

    # تقدم زمني: نسبة المعتمد تراكميًا حسب آخر 8 أيام بيانات
    end_dates: list[datetime] = []
    for sr in canon_by_item.values():
        t = getattr(sr, "approved_at", None) or getattr(sr, "updated_at", None) or getattr(sr, "created_at", None)
        if isinstance(t, datetime):
            end_dates.append(t)
    if end_dates:
        max_dt = max(end_dates)
        # اجمع آخر 8 أيام مميزة
        seen = set()
        cur = datetime(max_dt.year, max_dt.month, max_dt.day, 0, 0, 0)
        while len(seen) < 8:
            key = (cur.year, cur.month, cur.day)
            seen.add(key)
            cur = cur.replace()  # no-op for clarity
            cur = cur.fromtimestamp((cur.timestamp() - 86400))
            if len(seen) >= 8:
                break
        # إعادة بناء قائمة مرتبة تصاعديًا
        days = sorted(seen)
        day_dts = [datetime(y, m, d, 23, 59, 59) for (y, m, d) in days][-8:]
    else:
        day_dts = []

    def _approved_count_upto(dt: datetime) -> int:
        n = 0
        for sr in approved_by_item.values():
            t = getattr(sr, "approved_at", None) or getattr(sr, "updated_at", None)
            if not isinstance(t, datetime):
                continue
            if t <= dt:
                n += 1
        return n

    timeline = []
    for dt in day_dts:
        c = _approved_count_upto(dt)
        v = int(round((c / n_eval_lists) * 100.0)) if n_eval_lists else 0
        label = f"{dt.day} {_ar_month_name(dt.month)}"
        timeline.append({"label": label, "value": v})

    # رادار: أعلى 4 وحدات (6 محاور) — نأخذ أول 6 محاور من axis_scores.
    radar_palette = ["#3b82f6", "#84cc16", "#f59e0b", "#8b5cf6"]
    radar_series = []
    for i, u in enumerate(unit_avg_rows[:4]):
        uk = u.get("unit_key") or ""
        vals6 = []
        for ax in range(6):
            v = _axis_value_for_unit(uk, ax)
            vals6.append(v if v is not None else float(overall_avg_i))
        radar_series.append({"label": u.get("label") or uk, "color": radar_palette[i % len(radar_palette)], "points": _radar_points(vals6)})

    # بيانات Meta أعلى التقرير
    n_specialists = int(
        db.query(func.count(ExerciseRosterRow.id))
        .filter(
            ExerciseRosterRow.exercise_id == ex0.id,
            ExerciseRosterRow.roster_kind == ExerciseRosterKind.JUDGE.value,
        )
        .scalar()
        or 0
    )
    ex_dt = getattr(ex, "planned_start", None) or getattr(ex, "created_at", None)
    dt_label = ex_dt.strftime("%d-%m-%Y") if isinstance(ex_dt, datetime) else "—"

    crumb = f"التمرين الحالي / {(getattr(ex, 'title', None) or 'تمرين')}"
    exercise_label = (getattr(ex, "title", "") or "تمرين").strip()
    exercise_code = (getattr(ex, "code", "") or "—").strip()

    meta = [
        f"قوائم التقييم: {n_eval_lists}",
        f"المحفوظة: {n_saved}",
        f"المختصين: {n_specialists}",
        f"تاريخ التمرين: {dt_label}",
    ]

    kpis = [
        {"label": "متوسط الزمن", "value": _fmt_m_ss(avg_duration), "hint": "لكل تقييم", "icon": "fa-clock", "tone": "blue"},
        {"label": "قيد التقييم", "value": f"{pending_pct}%", "hint": "منفذة", "icon": "fa-hexagon-nodes", "tone": "violet"},
        {"label": "متأخر التقييم", "value": f"{done_pct}%", "hint": "من إجمالي التقييم", "icon": "fa-circle-check", "tone": "purple"},
        {"label": "أقل مجموعة", "value": f"{int(bottom_unit['value']) if bottom_unit else 0}%", "hint": (bottom_unit["label"] if bottom_unit else "—"), "icon": "fa-arrow-down", "tone": "red"},
        {"label": "أعلى مجموعة", "value": f"{int(top_unit['value']) if top_unit else 0}%", "hint": (top_unit["label"] if top_unit else "—"), "icon": "fa-trophy", "tone": "cyan"},
        {"label": "المتوسط العام", "value": f"{overall_avg_i}%", "hint": "أداء التمرين", "icon": "fa-chart-line", "tone": "green"},
        {"label": "معايير التقييم", "value": str(criteria_count), "hint": "إجمالي المعايير", "icon": "fa-list", "tone": "indigo"},
    ]

    return {
        "exercise": ex,
        "crumb": crumb,
        "criteria_count": criteria_count,
        "report_title": "تقرير شامل لأداء التمرين",
        "exercise_label": exercise_label,
        "exercise_code": exercise_code,
        "meta": meta,
        "kpis": kpis,
        "axis_scores": axis_scores,
        "group_scores": group_scores,
        "timeline": timeline,
        "distribution": distribution,
        "table_rows": table_rows,
        "table_headers": table_headers,
        "radar_series": radar_series,
    }


@bp.route("/control")
def control_hub():
    user = get_current_user_optional()
    if not user:
        return redirect("/login?next=/control")
    if not can_access_control_hub(user):
        abort(403)
    hub_items = [{"slug": s, "title_ar": t, "icon": ic} for s, t, ic in CONTROL_HUB_ITEMS]
    return render_template(
        "control_hub.html",
        **_ctx(
            user,
            hub_items=hub_items,
        ),
    )


@bp.route("/control/<slug>")
def control_hub_section(slug: str):
    user = get_current_user_optional()
    if not user:
        return redirect(f"/login?next=/control/{slug}")
    if not can_access_control_hub(user):
        abort(403)
    slug_norm = (slug or "").strip().lower()
    if slug_norm == "chat-rooms":
        return redirect(url_for("views.chat_rooms_list"))
    if slug_norm == "notifications-log":
        return redirect(url_for("views.notifications_log"))
    if slug_norm in ("visual-doc-status", "visual-documentation"):
        return redirect(url_for("views.visual_documentation"))
    title = CONTROL_HUB_SLUGS.get(slug_norm)
    if not title:
        abort(404)
    if slug_norm == "evaluation-results":
        from flask import g

        return render_template(
            "control_evaluation_results_report.html",
            **_ctx(
                user,
                section_title=title,
                report=_control_exercise_performance_report(g.db, user),
            ),
        )
    return render_template(
        "control_section_placeholder.html",
        **_ctx(user, section_title=title, section_slug=slug),
    )


@bp.route("/admin")
def admin_root_redirect():
    """لوحة /admin أُلغيت؛ إعادة التوجيه للصفحة الرئيسية أو تسجيل الدخول."""
    user = get_current_user_optional()
    if not user:
        return redirect("/login?next=/dashboard")
    if not is_system_admin(user):
        abort(403)
    return redirect("/dashboard")


def _system_checklist_rows() -> list[dict]:
    """Checklist تشغيلي يغطي محتويات النظام من الدخول حتى الخروج."""
    rows: list[dict] = []

    def add(stage: str, page: str, path: str, role: str, contents: str, actions: str, check: str) -> None:
        rows.append(
            {
                "idx": len(rows) + 1,
                "reviewed": False,
                "stage": stage,
                "page": page,
                "path": path,
                "role": role,
                "contents": contents,
                "actions": actions,
                "check": check,
            }
        )

    add("الدخول", "تسجيل الدخول", "/login", "جميع المستخدمين", "اسم المستخدم، كلمة المرور، رسالة خطأ عند فشل الدخول.", "تسجيل دخول، الانتقال للصفحة المطلوبة بعد الدخول.", "الدخول بحساب إدارة النظام وبحساب دور تشغيلي.")
    add("الدخول", "الصفحة الرئيسية", "/dashboard", "جميع المستخدمين", "بطاقات الأدوار المتاحة للمستخدم، رابط المكتبة، رابط الخروج.", "فتح مساحة الدور المناسبة حسب الصلاحية.", "ظهور البطاقات حسب الدور فقط.")
    add("إدارة النظام", "إنشاء تمرين جديد", "/admin/exercises/create", "إدارة النظام", "بيانات التمرين، النوع، المستوى، المهمة، الوحدة المتدربة، الموقع، التاريخ، استيراد/تصدير JSON.", "إنشاء تمرين، فتح تمرين، استبدال تمرين، فتح مجلد التصدير.", "حفظ تمرين وظهوره كتمرين حالي.")
    add("إدارة النظام", "الأهداف التدريبية", "/admin/exercises/objectives", "إدارة النظام", "قائمة أهداف تدريبية، إدخال يدوي أو ملف خارجي.", "إضافة، حفظ، حذف جميع الأهداف.", "ظهور الأهداف في تحليلات المحللين.")
    add("إدارة النظام", "قائمة المحكمين", "/admin/exercises/judge-unit-roster", "إدارة النظام", "الرقم العسكري، الرتبة، الاسم، مستوى الوحدة.", "حفظ القائمة، الاستيراد من ملف، إنشاء/تحديث حسابات المحكمين تلقائياً.", "تسجيل دخول المحكم بالرقم العسكري.")
    add("إدارة النظام", "قائمة الوحدة المتدربة", "/admin/exercises/trainee-unit-roster", "إدارة النظام", "الرقم العسكري، الرتبة، الاسم، مستوى الوحدة.", "حفظ القائمة، الاستيراد من ملف، ربط المتدرب بمستوى الوحدة.", "ظهور الوحدة في تقارير الربط والتحليل.")
    add("إدارة النظام", "قائمة المعاضل", "/admin/dilemmas", "إدارة النظام", "رفع ملفات PDF حسب مستوى الوحدة ومرحلة التمرين.", "رفع، فتح، حذف، تغيير المرحلة، مسح المستوى.", "فتح القوائم من مساحة المحكمين.")
    add("إدارة النظام", "قوائم التقييم", "/admin/evaluation-lists", "إدارة النظام", "رفع ملفات Excel حسب مستوى الوحدة ومرحلة التمرين.", "رفع، فتح، حذف، تغيير المرحلة، مسح المستوى.", "فتح القائمة من المحكم وإدخال النتائج.")
    add("إدارة النظام", "إدارة تقييمات الوحدات", "/admin/evaluation-lists/saved-results", "إدارة النظام", "نتائج التقييم المحفوظة والمعتمدة.", "عرض، حذف نتيجة محفوظة.", "تطابق الحالة مع اعتماد المحكم.")
    add("إدارة النظام", "ربط المعاضل والتقييم", "/admin/dilemmas-evaluation-unit-report", "إدارة النظام", "تقرير ربط المعاضل بقوائم التقييم حسب مستوى الوحدة والمرحلة.", "مراجعة الربط واكتشاف النواقص.", "ظهور المهام غير المكتملة من هذا الربط.")
    add("إدارة النظام", "تنظيم المعركة", "/admin/battle-organization", "إدارة النظام", "رموز الوحدات، بيانات المتدربين، بيانات المحكمين، المواقع/التنظيم.", "تعبئة وحفظ تنظيم المعركة.", "انعكاس البيانات في الصورة العامة.")
    add("إدارة النظام", "إدارة المستخدمين", "/admin/users", "إدارة النظام", "المستخدمون، الأدوار، الحالة، كلمة المرور.", "إضافة، تعديل، تعطيل/حذف.", "تطبيق الصلاحيات بعد التعديل.")
    add("إدارة النظام", "غرف المحادثة", "/admin/chat-rooms", "إدارة النظام", "غرف حسب التمرين، النوع، مستوى الوحدة، الأعضاء.", "إنشاء غرفة، إضافة/إزالة أعضاء، أرشفة.", "ظهور الغرفة للأعضاء فقط.")
    add("إدارة النظام", "Checklist محتويات النظام", "/admin/system-checklist", "إدارة النظام", "جدول spreadsheet لمراجعة صفحات ووظائف النظام.", "تحديد المراجعة، البحث، الطباعة/التصدير من المتصفح.", "اكتمال مراجعة جميع الصفوف.")
    add("المحكمين", "مساحة المحكمين", "/judge", "محكم / إدارة النظام", "أوامر المحكمين: المعاضل، التقييم، المحادثات، المهام، التوثيق، الإشعارات.", "فتح أقسام المحكم حسب الصلاحية.", "ظهور الأقسام المطلوبة للمحكم.")
    add("المحكمين", "قوائم المعاضل", "/judge/dilemmas", "محكم", "مستويات الوحدة المتاحة وملفات PDF للمعاضل.", "فتح القوائم وملفات PDF.", "حصر المحكم في وحدته المخصصة.")
    add("المحكمين", "قوائم التقييم", "/judge/evaluation-lists", "محكم", "قوائم Excel، إدخال المكتسبة، النسبة، النتيجة، ملاحظات المحكم.", "حفظ النتيجة واعتمادها.", "ظهور النتيجة المعتمدة في المحللين.")
    add("المحكمين", "مهام غير مكتملة", "/judge/incomplete-tasks", "محكم", "المهام الناتجة من ربط المعاضل والتقييم، الحالة، الأولوية، المكلف.", "تغيير الحالة وفتح قائمة التقييم.", "تطابق اسم المحكم مع قائمة المحكمين.")
    add("المحكمين", "التوثيق المرئي", "/visual-documentation", "محكم / سيطرة / تخطيط / إدارة", "رفع ملف، تصوير بالكاميرا، تسجيل صوتي، وصف، موقع، ربط بمعضلة.", "رفع صورة/فيديو/صوت وفتح السجل.", "ظهور المادة في سجل التوثيق.")
    add("المحادثات", "غرف المحادثة", "/chat-rooms", "الأعضاء حسب الغرفة", "قائمة غرف المستخدم، آخر نشاط، نوع الغرفة.", "فتح غرفة وإرسال رسائل/ملفات.", "وصول الإشعار للعضو عند رسالة جديدة.")
    add("المحادثات", "تفاصيل غرفة", "/chat-rooms/<id>", "الأعضاء حسب الغرفة", "رسائل نصية، ملفات، قراءات الأعضاء.", "إرسال رسالة، رفع ملف، تنزيل ملف.", "حفظ الرسالة وظهور حالة القراءة.")
    add("المحللين", "مساحة المحللين", "/analyst", "محلل / إدارة النظام", "أدوات التحليل: النتائج، الإيجابيات والسلبيات، تحليل المحكمين، المراجعة.", "فتح أدوات التحليل.", "ظهور الأدوات حسب صلاحية المحلل.")
    add("المحللين", "عرض نتائج التقييم", "/analyst/evaluation-results", "محلل", "مصفوفة نتائج قوائم التقييم المعتمدة حسب مستوى الوحدة والأهداف.", "عرض الحالة والقوائم غير المعبأة.", "عدم إدراج النتائج غير المعتمدة.")
    add("المحللين", "عرض الإيجابيات والسلبيات", "/analyst/positives-negatives", "محلل", "نقاط الاستدامة والتطوير حسب مستوى الوحدة، وملاحظات المحكمين.", "اختيار مستوى الوحدة، عرض الإيجابيات أعلى والسلبيات أسفل.", "ظهور لا يوجد ملاحظات عند عدم وجود ملاحظات.")
    add("المحللين", "تحليل وتقييم المحكمين", "/analyst/judges-eval-analysis", "محلل", "تحليل إنجاز المحكمين، القوائم المعتمدة وغير المعتمدة.", "عرض وفتح تقييمات المحكمين.", "تطابق بيانات الاعتماد مع المحكم.")
    add("التخطيط", "مساحة التخطيط", "/planner", "مخطط / إدارة النظام", "قوائم التقييم، المحادثات، المهام، معلومات التمرين.", "فتح أقسام التخطيط وإدخال نتائج عند السماح.", "التحقق من صلاحيات التخطيط.")
    add("السيطرة", "مساحة السيطرة", "/control", "سيطرة / إدارة النظام", "موقف التقييم، المحادثات، المهام، التوثيق المرئي، الإشعارات.", "متابعة المواقف وفتح التوثيق والمحادثات.", "ظهور البيانات المرتبطة بالتمرين الحالي.")
    add("الإشعارات", "سجل الإشعارات", "/notifications", "محكم / سيطرة / تخطيط / إدارة", "إشعارات الرسائل، الملفات، التوثيق، الحالة مقروء/غير مقروء.", "فتح الإشعار، تعليم كمقروء، تعليم الكل.", "عداد الجرس يطابق غير المقروء.")
    add("المكتبة", "المكتبة", "/library", "جميع المستخدمين", "المراجع والمعايير المتاحة.", "تصفح المراجع حسب الصلاحية.", "فتح المكتبة من الشريط العلوي.")
    add("الخروج", "تسجيل الخروج", "/logout", "جميع المستخدمين", "إنهاء الجلسة والرجوع لتسجيل الدخول.", "خروج آمن ومنع الرجوع لصفحات محمية بدون دخول.", "بعد الخروج تُطلب المصادقة عند فتح صفحة محمية.")
    return rows


_SYSTEM_CHECKLIST_HEADERS = [
    "مراجعة",
    "#",
    "المرحلة",
    "الصفحة / الوظيفة",
    "المسار",
    "الدور",
    "المحتويات بالتفصيل",
    "الإجراءات",
    "نقطة التحقق",
]


def _system_checklist_export_xlsx(rows: list[dict]):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "System Checklist"
    ws.sheet_view.rightToLeft = True
    ws.append(_SYSTEM_CHECKLIST_HEADERS)

    for r in rows:
        ws.append(
            [
                "تم" if bool(r.get("reviewed")) else "",
                r.get("idx", ""),
                r.get("stage", ""),
                r.get("page", ""),
                r.get("path", ""),
                r.get("role", ""),
                r.get("contents", ""),
                r.get("actions", ""),
                r.get("check", ""),
            ]
        )

    font = Font(name="Arial", size=12)
    header_font = Font(name="Arial", size=12, bold=True)
    header_fill = PatternFill("solid", fgColor="F4E9DC")
    align_center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    align_text = Alignment(horizontal="right", vertical="center", wrap_text=True)
    for row in ws.iter_rows():
        for cell in row:
            cell.font = header_font if cell.row == 1 else font
            cell.alignment = align_center if cell.column <= 6 else align_text
            if cell.row == 1:
                cell.fill = header_fill

    widths = [12, 8, 18, 28, 24, 24, 48, 42, 42]
    for i, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.freeze_panes = "A2"

    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)
    return bio


def _system_checklist_rows_from_xlsx(file_storage) -> list[dict]:
    from openpyxl import load_workbook

    if not file_storage or not (getattr(file_storage, "filename", "") or "").strip():
        return []
    raw = file_storage.read()
    if not raw:
        return []
    wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    ws = wb.active
    out: list[dict] = []
    for i, row in enumerate(ws.iter_rows(values_only=True), start=1):
        if i == 1:
            continue
        vals = [("" if v is None else str(v).strip()) for v in row[:9]]
        vals.extend([""] * (9 - len(vals)))
        if not any(vals):
            continue
        reviewed_raw = vals[0].strip().lower()
        out.append(
            {
                "idx": len(out) + 1,
                "reviewed": reviewed_raw in ("تم", "نعم", "yes", "true", "1", "x", "✓"),
                "stage": vals[2],
                "page": vals[3],
                "path": vals[4],
                "role": vals[5],
                "contents": vals[6],
                "actions": vals[7],
                "check": vals[8],
            }
        )
    return out


@bp.route("/admin/system-checklist", methods=["GET"])
def admin_system_checklist():
    user = get_current_user_optional()
    if not user:
        return redirect("/login?next=/admin/system-checklist")
    if not can_manage_users(user):
        abort(403)
    return render_template(
        "admin_system_checklist.html",
        **_ctx(user, checklist_rows=_system_checklist_rows(), imported=False, import_error=""),
    )


@bp.route("/admin/system-checklist/export", methods=["POST"])
def admin_system_checklist_export():
    user = get_current_user_optional()
    if not user:
        return redirect("/login?next=/admin/system-checklist")
    if not can_manage_users(user):
        abort(403)
    checked = set(request.form.getlist("reviewed_idx"))
    rows = _system_checklist_rows()
    for r in rows:
        r["reviewed"] = str(r.get("idx")) in checked
    bio = _system_checklist_export_xlsx(rows)
    return send_file(
        bio,
        as_attachment=True,
        download_name="system_checklist.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@bp.route("/admin/system-checklist/import", methods=["POST"])
def admin_system_checklist_import():
    user = get_current_user_optional()
    if not user:
        return redirect("/login?next=/admin/system-checklist")
    if not can_manage_users(user):
        abort(403)
    import_error = ""
    try:
        rows = _system_checklist_rows_from_xlsx(request.files.get("checklist_file"))
    except Exception:
        rows = []
        import_error = "تعذر قراءة ملف Excel. تأكد من أن الملف بصيغة .xlsx وبنفس أعمدة التصدير."
    if not rows and not import_error:
        import_error = "لم يتم العثور على صفوف صالحة داخل ملف Excel."
        rows = _system_checklist_rows()
    return render_template(
        "admin_system_checklist.html",
        **_ctx(user, checklist_rows=rows, imported=not bool(import_error), import_error=import_error),
    )


@bp.route("/admin/exercises/create", methods=["GET", "POST"])
def admin_exercise_create():
    user = get_current_user_optional()
    if not user:
        return redirect("/login?next=/admin/exercises/create")
    if not can_manage_users(user):
        abort(403)
    from flask import g

    db = g.db

    def _render_create_page(*, error: str):
        ex_cur = _admin_current_workspace_exercise(db, user)
        if request.method == "GET":
            form_prefill = (
                _prefill_create_form_from_exercise(ex_cur)
                if ex_cur
                else _empty_create_form_prefill()
            )
        else:
            form_prefill = _prefill_create_form_from_request()
        return render_template(
            "admin_exercise_create.html",
            **_ctx(
                user,
                error=error,
                export_dir=str(export_directory()),
                form_prefill=form_prefill,
                has_current_exercise=ex_cur is not None,
                **_admin_exercise_form_ctx(),
            ),
        )

    if request.method == "GET":
        qerr = (request.args.get("err") or "").strip()
        return _render_create_page(error=qerr)

    def _pick(field: str, allowed: list[str]) -> str | None:
        v = (request.form.get(field) or "").strip()
        return v if v in allowed else None

    def _parse_dt_local(field: str):
        raw = (request.form.get(field) or "").strip()
        if not raw:
            return None
        try:
            # صيغة input datetime-local: 2026-04-30T13:45
            return datetime.fromisoformat(raw)
        except Exception:
            return None

    title = _pick("exercise_name", ex_opts.EXERCISE_NAMES)
    et = _pick("exercise_type", ex_opts.EXERCISE_TYPES)
    el = _pick("exercise_level", ex_opts.EXERCISE_LEVELS)
    mission = _pick("mission", ex_opts.MISSIONS)
    unit = _pick("trained_unit", ex_opts.TRAINED_UNITS)
    loc = _pick("location_label", ex_opts.EXERCISE_LOCATIONS)
    planned_start = _parse_dt_local("planned_start")
    planned_end = _parse_dt_local("planned_end")

    if planned_start and planned_end and planned_end < planned_start:
        return _render_create_page(error="تاريخ/وقت النهاية يجب أن يكون بعد البداية."), 400

    if not all([title, et, el, mission, unit, loc]):
        return (
            _render_create_page(error="يرجى اختيار قيمة صحيحة لكل حقل من القوائم."),
            400,
        )

    desc = "\n".join(
        [
            f"نوع التمرين: {et}",
            f"مستوى التمرين: {el}",
            f"المهمة: {mission}",
            f"اسم الوحدة المتدربة: {unit}",
            f"مكان التمرين: {loc}",
        ]
    )
    purge_all_exercises_and_dilemmas(db)
    ex = Exercise(
        code=f"EX-{uuid.uuid4().hex[:8].upper()}",
        title=title,
        description=desc,
        exercise_type=et,
        exercise_level=el,
        mission_label=mission,
        trained_unit=unit,
        location_label=loc,
        status=ExerciseStatus.DRAFT.value,
        owner_id=user.id,
        planned_start=planned_start,
        planned_end=planned_end,
    )
    db.add(ex)
    db.commit()
    db.refresh(ex)
    write_exercise_json_file(db, ex.id)

    return redirect("/admin/exercises/objectives")


@bp.route("/admin/exercises/import-full-json", methods=["POST"])
def admin_exercise_import_full_json():
    """مسح التمارين السابقة واستيراد تمرين كامل من ملف JSON في مجلد التصدير."""
    user = get_current_user_optional()
    if not user:
        if _wants_import_json_response():
            return jsonify({"ok": False, "error": "يجب تسجيل الدخول"}), 401
        return redirect("/login?next=/admin/exercises/create")
    if not can_manage_users(user):
        if _wants_import_json_response():
            return jsonify({"ok": False, "error": "غير مسموح"}), 403
        abort(403)
    from flask import g

    db = g.db
    up = request.files.get("json_file")
    if not up or not getattr(up, "filename", ""):
        return _import_full_json_error("يرجى اختيار ملف JSON من مجلد التمارين.")
    try:
        raw = up.read()
    except Exception:
        raw = b""
    if not raw:
        return _import_full_json_error("الملف فارغ.")
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        return _import_full_json_error("ملف JSON غير صالح أو تالف.")
    if not isinstance(data, dict) or not isinstance(data.get("exercise"), dict):
        return _import_full_json_error(
            "الملف لا يحتوي على كائن «exercise» كما في ملفات التصدير."
        )

    cur = _admin_current_workspace_exercise(db, user)
    if cur is not None:
        pwd = (request.form.get("system_admin_password") or "").strip()
        if not pwd:
            return _import_full_json_error(
                "يجب إدخال كلمة مرور إدارة النظام لتغيير التمرين الحالي."
            )
        if not verify_password(pwd, user.password_hash):
            return _import_full_json_error("كلمة مرور إدارة النظام غير صحيحة.")

    try:
        purge_all_exercises_and_dilemmas(db)
        eid = import_exercise_bundle_from_dict(db, data, user.id)
        if eid is None:
            db.rollback()
            return _import_full_json_error(
                "تعذر استيراد البيانات من الملف (بنية غير متوقعة)."
            )
        db.commit()
    except Exception:
        db.rollback()
        return _import_full_json_error("حدث خطأ أثناء استيراد التمرين.")
    return _import_full_json_ok(eid)


@bp.route("/admin/exercises/open-export-dir", methods=["POST"])
def admin_open_export_dir():
    user = get_current_user_optional()
    if not user:
        return jsonify({"ok": False, "error": "يجب تسجيل الدخول"}), 401
    if not can_manage_users(user):
        return jsonify({"ok": False, "error": "غير مسموح"}), 403
    ok, err = open_export_directory_in_os()
    if ok:
        return jsonify({"ok": True, "path": str(export_directory())})
    return jsonify({"ok": False, "error": err or "تعذر فتح المجلد"}), 500


@bp.route("/admin/exercises/import-json-prefill", methods=["POST"])
def admin_exercise_import_json_prefill():
    """رفع ملف JSON (تصدير تمرين) واستخراج حقول تطابق نموذج الإنشاء."""
    user = get_current_user_optional()
    if not user:
        return jsonify({"ok": False, "error": "يجب تسجيل الدخول"}), 401
    if not can_manage_users(user):
        return jsonify({"ok": False, "error": "غير مسموح"}), 403
    f = request.files.get("json_file")
    if not f or not getattr(f, "filename", None):
        return jsonify({"ok": False, "error": "لم يُرفع ملف."}), 400
    raw = f.read()
    if not raw or not raw.strip():
        return jsonify({"ok": False, "error": "الملف فارغ."}), 400
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return jsonify({"ok": False, "error": "صيغة JSON غير صالحة."}), 400
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "ملف غير صالح."}), 400
    fields, warnings = extract_create_form_prefill_from_export_json(data)
    select_keys = (
        "exercise_name",
        "exercise_type",
        "exercise_level",
        "mission",
        "trained_unit",
        "location_label",
    )
    has_select = any(fields.get(k) for k in select_keys)
    has_dt = bool(fields.get("planned_start") or fields.get("planned_end"))
    if not has_select and not has_dt:
        msg = "لم تُطابق أي قيمة من الملف القوائم الحالية في النظام."
        if warnings:
            msg = warnings[0]
        return jsonify({"ok": False, "error": msg, "warnings": warnings}), 400
    out_fields = {k: v for k, v in fields.items() if v is not None and v != ""}
    return jsonify({"ok": True, "fields": out_fields, "warnings": warnings})


def _admin_current_workspace_exercise(db, user: User) -> Exercise | None:
    """التمرين الحالي لمسؤول النظام: آخر تمرين مملوك له (بعد مسح السجل يبقى واحد فقط)."""
    return (
        db.query(Exercise)
        .options(
            joinedload(Exercise.objectives),
            joinedload(Exercise.roster_rows),
        )
        .filter(Exercise.owner_id == user.id)
        .order_by(Exercise.id.desc())
        .first()
    )


def _current_workspace_exercise(db, user: User) -> Exercise | None:
    """التمرين الحالي.

    - لإدارة النظام: آخر تمرين مملوك له (سلوك سابق)
    - لباقي الأدوار: آخر تمرين في قاعدة البيانات (عادة يوجد تمرين واحد فقط)
    """
    if user and is_system_admin(user):
        return _admin_current_workspace_exercise(db, user)
    return db.query(Exercise).order_by(Exercise.id.desc()).first()


def _sync_judges_from_roster(db, ex: Exercise) -> None:
    """مزامنة حسابات المحكمين وتخصيصاتهم اعتماداً على قائمة المحكمين + قائمة المتدربين للتمرين الحالي.

    القاعدة المطلوبة:
    - username = الرقم العسكري
    - password = الرقم العسكري
    - ربط المحكم بوحدة/متدرب عبر unit_level_key (نفس مفتاح المعاضل والتقييم)
    """
    if ex is None:
        return

    trainees = (
        db.query(ExerciseRosterRow)
        .filter(
            ExerciseRosterRow.exercise_id == ex.id,
            ExerciseRosterRow.roster_kind == ExerciseRosterKind.TRAINEE.value,
        )
        .all()
    )
    trainee_by_unit: dict[str, ExerciseRosterRow] = {}
    for tr in trainees:
        uk = (tr.unit_level_key or "").strip()
        if uk and uk not in trainee_by_unit:
            trainee_by_unit[uk] = tr

    judges = (
        db.query(ExerciseRosterRow)
        .filter(
            ExerciseRosterRow.exercise_id == ex.id,
            ExerciseRosterRow.roster_kind == ExerciseRosterKind.JUDGE.value,
        )
        .all()
    )
    for jr in judges:
        mil = (jr.military_number or "").strip()
        if not mil:
            continue
        uk = (jr.unit_level_key or "").strip()
        # إن لم تتوفر ملفات معاضل/تقييم لهذا المفتاح، لا ننشئ تخصيصاً "فارغاً" لأن المحكم لن يرى شيئاً.
        has_any = (
            db.query(DilemmaItem)
            .filter(DilemmaItem.exercise_id == ex.id, DilemmaItem.unit_level_key == uk)
            .first()
            is not None
        ) or (
            db.query(EvaluationListPdfItem)
            .filter(EvaluationListPdfItem.exercise_id == ex.id, EvaluationListPdfItem.unit_level_key == uk)
            .first()
            is not None
        )
        if not uk or not has_any:
            # نترك الحساب يُنشأ/يُحدّث، لكن بدون تخصيص وحدة حتى يتم تصحيح القائمة.
            uk = ""

        u = db.query(User).filter(User.username == mil).first()
        if u is None:
            u = User(
                username=mil,
                full_name=(jr.full_name or "").strip(),
                role_key=RoleKey.JUDGE.value,
                password_hash=hash_password(mil),
                is_active=True,
            )
            db.add(u)
            db.commit()
            db.refresh(u)
        else:
            # لا نغيّر الأدوار الأخرى
            if (u.role_key or "") != RoleKey.JUDGE.value:
                continue
            u.full_name = (jr.full_name or "").strip() or u.full_name
            u.is_active = True
            # ضمان أن كلمة المرور = الرقم العسكري (حسب الطلب)
            u.password_hash = hash_password(mil)
            db.add(u)
            db.commit()

        # Upsert تخصيص المحكم لهذا التمرين
        db.execute(
            delete(JudgeTraineeAssignment).where(
                JudgeTraineeAssignment.exercise_id == ex.id,
                JudgeTraineeAssignment.judge_user_id == u.id,
            )
        )
        tr = trainee_by_unit.get(uk) if uk else None
        db.add(
            JudgeTraineeAssignment(
                exercise_id=ex.id,
                judge_user_id=u.id,
                unit_level_key=uk,
                trainee_name=(tr.full_name or "").strip() if tr else "",
                trainee_military_number=(tr.military_number or "").strip() if tr else "",
            )
        )
        db.commit()


@bp.route("/admin/exercises/objectives", methods=["GET", "POST"])
def admin_exercise_objectives():
    user = get_current_user_optional()
    if not user:
        return redirect("/login?next=/admin/exercises/objectives")
    if not can_manage_users(user):
        abort(403)
    from flask import g

    db = g.db

    def _render(*, error: str, ok_msg: str, exercise: Exercise | None):
        return render_template(
            "admin_exercise_objectives.html",
            **_ctx(user, error=error, ok_msg=ok_msg, current_exercise=exercise),
        )

    if request.method == "GET":
        ex = _admin_current_workspace_exercise(db, user)
        return _render(error="", ok_msg="", exercise=ex)

    ex = _admin_current_workspace_exercise(db, user)
    if not ex:
        return (
            _render(
                error="لا يوجد تمرين حالي. أنشئ تمريناً جديداً أو افتح تمريناً من ملف JSON من صفحة «إنشاء تمرين جديد».",
                ok_msg="",
                exercise=None,
            ),
            400,
        )

    if (request.form.get("objectives_action") or "").strip() == "clear_all":
        db.execute(
            delete(ExerciseObjective).where(ExerciseObjective.exercise_id == ex.id)
        )
        db.commit()
        ex_show = (
            db.query(Exercise)
            .options(joinedload(Exercise.objectives))
            .filter(Exercise.id == ex.id)
            .one()
        )
        write_exercise_json_file(db, ex_show.id)
        return _render(
            error="",
            ok_msg="تم حذف جميع الأهداف التدريبية وتحديث ملف JSON في مجلد التصدير.",
            exercise=ex_show,
        )

    source = (request.form.get("objectives_source") or "manual").strip()
    if source == "excel":
        objectives = _parse_objectives_file_storage(request.files.get("objectives_file"))
    else:
        objectives = []
        for s in request.form.getlist("objective_items"):
            t = (s or "").strip()[:2000]
            if t:
                objectives.append(t)
        objectives = objectives[:200]

    if not objectives:
        return (
            _render(
                error="لم يُرسل أي هدف. اختر «إدخال يدوي» وأدخل النصوص، أو «إدراج ملف خارجي» وارفع ملفاً (Excel أو PDF أو CSV أو XML أو نص).",
                ok_msg="",
                exercise=ex,
            ),
            400,
        )

    db.execute(
        delete(ExerciseObjective).where(ExerciseObjective.exercise_id == ex.id)
    )
    for i, txt in enumerate(objectives):
        db.add(ExerciseObjective(exercise_id=ex.id, sort_order=i, text=txt))
    db.commit()
    ex_show = (
        db.query(Exercise)
        .options(joinedload(Exercise.objectives))
        .filter(Exercise.id == ex.id)
        .one()
    )
    write_exercise_json_file(db, ex_show.id)
    n = len(objectives)
    return _render(
        error="",
        ok_msg=f"تم حفظ {n} هدفاً (استبدال كامل للقائمة). تم تحديث ملف JSON في مجلد التصدير.",
        exercise=ex_show,
    )


def _zip_roster_rows_from_manual_form() -> list[tuple[str, str, str, str]]:
    ms = request.form.getlist("roster_military")
    rs = request.form.getlist("roster_rank")
    ns = request.form.getlist("roster_full_name")
    uls = request.form.getlist("roster_unit_level")
    n = max(len(ms), len(rs), len(ns), len(uls))
    out: list[tuple[str, str, str, str]] = []
    for i in range(n):
        a = (ms[i] if i < len(ms) else "").strip()[:128]
        b = (rs[i] if i < len(rs) else "").strip()[:256]
        c = (ns[i] if i < len(ns) else "").strip()[:256]
        uk = normalize_unit_level_key(uls[i] if i < len(uls) else "")
        if a or b or c or uk:
            out.append((a, b, c, uk))
    return out[:500]


def _exercise_roster_page(roster_kind: str):
    user = get_current_user_optional()
    if not user:
        nxt = (
            "/admin/exercises/trainee-unit-roster"
            if roster_kind == ExerciseRosterKind.TRAINEE.value
            else "/admin/exercises/judge-unit-roster"
        )
        return redirect(f"/login?next={nxt}")
    if not can_manage_users(user):
        abort(403)
    from flask import g

    db = g.db

    meta = {
        ExerciseRosterKind.TRAINEE.value: {
            "page_title": "قائمة الوحدة المتدربة",
            "h1": "قائمة الوحدة المتدربة",
            "icon": "fa-users",
            "form_action": "/admin/exercises/trainee-unit-roster",
            "add_label": "إضافة سطر",
            "save_label": "حفظ القائمة",
            "clear_label": "حذف جميع الأسطر",
            "file_panel_hint": "CSV أو TXT أو Excel (.xlsx): الرقم العسكري، الرتبة، الاسم، ثم عمود مستوى الوحدة (المفتاح بالإنجليزية أو التسمية العربية كما في قوائم المعاضل).",
        },
        ExerciseRosterKind.JUDGE.value: {
            "page_title": "قائمة المحكمين",
            "h1": "قائمة المحكمين",
            "icon": "fa-gavel",
            "form_action": "/admin/exercises/judge-unit-roster",
            "add_label": "إضافة سطر",
            "save_label": "حفظ القائمة",
            "clear_label": "حذف جميع الأسطر",
            "file_panel_hint": "كقائمة المتدربين: العمود الرابع هو مستوى الوحدة (نفس قائمة المعاضل والتقييم).",
        },
    }[roster_kind]

    def _render(*, error: str, ok_msg: str, exercise: Exercise | None):
        rows_f = []
        if exercise and exercise.roster_rows:
            rows_f = sorted(
                [r for r in exercise.roster_rows if r.roster_kind == roster_kind],
                key=lambda r: (r.sort_order, r.id),
            )
        return render_template(
            "admin_exercise_unit_roster.html",
            **_ctx(
                user,
                error=error,
                ok_msg=ok_msg,
                current_exercise=exercise,
                roster_kind=roster_kind,
                roster_meta=meta,
                roster_rows=rows_f,
                unit_levels=UNIT_LEVELS,
            ),
        )

    if request.method == "GET":
        ex = _admin_current_workspace_exercise(db, user)
        return _render(error="", ok_msg="", exercise=ex)

    ex = _admin_current_workspace_exercise(db, user)
    if not ex:
        return (
            _render(
                error="لا يوجد تمرين حالي. أنشئ تمريناً أو افتحه من ملف JSON.",
                ok_msg="",
                exercise=None,
            ),
            400,
        )

    if (request.form.get("roster_action") or "").strip() == "clear_all":
        db.execute(
            delete(ExerciseRosterRow).where(
                ExerciseRosterRow.exercise_id == ex.id,
                ExerciseRosterRow.roster_kind == roster_kind,
            )
        )
        db.commit()
        ex_show = (
            db.query(Exercise)
            .options(joinedload(Exercise.roster_rows))
            .filter(Exercise.id == ex.id)
            .one()
        )
        write_exercise_json_file(db, ex_show.id)
        return _render(
            error="",
            ok_msg="تم حذف جميع الأسطر لهذه القائمة وتحديث ملف التصدير.",
            exercise=ex_show,
        )

    source = (request.form.get("roster_source") or "manual").strip()
    if source == "excel":
        tuples = parse_roster_rows_from_upload(request.files.get("roster_file"))
    else:
        tuples = _zip_roster_rows_from_manual_form()

    if not tuples:
        return (
            _render(
                error="لم يُرسل أي صف. اختر «إدخال يدوي» واملأ الحقول، أو «إدراج ملف خارجي» وارفع ملفاً صالحاً.",
                ok_msg="",
                exercise=ex,
            ),
            400,
        )

    db.execute(
        delete(ExerciseRosterRow).where(
            ExerciseRosterRow.exercise_id == ex.id,
            ExerciseRosterRow.roster_kind == roster_kind,
        )
    )
    for i, (mil, rk, nm, cell4) in enumerate(tuples):
        uk, pos_ar = coerce_roster_import_position_cell(cell4)
        db.add(
            ExerciseRosterRow(
                exercise_id=ex.id,
                roster_kind=roster_kind,
                sort_order=i,
                military_number=mil,
                rank_ar=rk,
                full_name=nm,
                unit_level_key=uk,
                position_ar=pos_ar,
            )
        )
    db.commit()
    # بعد حفظ قائمة المحكمين: أنشئ/حدّث حساباتهم وتخصيصاتهم تلقائياً
    if roster_kind == ExerciseRosterKind.JUDGE.value:
        _sync_judges_from_roster(db, ex)
    ex_show = (
        db.query(Exercise)
        .options(joinedload(Exercise.roster_rows))
        .filter(Exercise.id == ex.id)
        .one()
    )
    write_exercise_json_file(db, ex_show.id)
    return _render(
        error="",
        ok_msg=f"تم حفظ {len(tuples)} صفاً. تم تحديث ملف JSON في مجلد التصدير.",
        exercise=ex_show,
    )


@bp.route("/admin/exercises/trainee-unit-roster", methods=["GET", "POST"])
def admin_exercise_trainee_unit_roster():
    return _exercise_roster_page(ExerciseRosterKind.TRAINEE.value)


@bp.route("/admin/exercises/judge-unit-roster", methods=["GET", "POST"])
def admin_exercise_judge_unit_roster():
    return _exercise_roster_page(ExerciseRosterKind.JUDGE.value)


@bp.route("/admin/exercises/exports", methods=["GET", "POST"])
def admin_exercise_exports():
    user = get_current_user_optional()
    if not user:
        return redirect("/login?next=/admin/exercises/exports")
    if not can_manage_users(user):
        abort(403)
    from flask import g

    db = g.db
    error = ""
    ok_msg = ""
    if request.method == "POST":
        up = request.files.get("json_file")
        if not up or not getattr(up, "filename", ""):
            error = "يرجى اختيار ملف JSON."
        else:
            try:
                raw = up.read()
            except Exception:
                raw = b""
            eid = read_exercise_id_from_json_bytes(raw)
            if eid is None:
                error = "الملف لا يحتوي على معرف تمرين صالح (exercise.id)."
            elif not db.get(Exercise, eid):
                error = "التمرين المذكور في الملف غير موجود في قاعدة البيانات."
            else:
                return redirect(f"/exercises/{eid}")
    files = list_export_json_files()
    return render_template(
        "admin_exercise_exports.html",
        **_ctx(
            user,
            error=error,
            ok_msg=ok_msg,
            export_files=files,
            export_dir=str(export_directory()),
        ),
    )


@bp.route("/admin/exercises/open-export")
def admin_exercise_open_export():
    user = get_current_user_optional()
    if not user:
        return redirect("/login?next=/admin/exercises/exports")
    if not can_manage_users(user):
        abort(403)
    from flask import g

    db = g.db
    raw = unquote((request.args.get("f") or "").strip())
    if not raw or raw != Path(raw).name:
        abort(400)
    if not raw.lower().endswith(".json"):
        abort(400)
    base = export_directory().resolve()
    path = (base / raw).resolve()
    try:
        path.relative_to(base)
    except ValueError:
        abort(400)
    if not path.is_file():
        abort(404)
    eid = read_exercise_id_from_json_path(path)
    if eid is None:
        abort(400)
    if not db.get(Exercise, eid):
        abort(404)
    return redirect(f"/exercises/{eid}")


@bp.route("/admin/evaluation-lists/<unit_key>/view/<int:item_id>", methods=["GET"])
def admin_evaluation_list_file_viewer(unit_key: str, item_id: int):
    user = get_current_user_optional()
    if not user or not is_system_admin(user):
        abort(403)
    unit = next((x for x in UNIT_LEVELS if x["key"] == unit_key), None)
    if not unit:
        abort(404)
    from flask import g

    db = g.db
    row = db.get(EvaluationListPdfItem, item_id)
    current_exercise = _admin_current_workspace_exercise(db, user)
    if not row or row.unit_level_key != unit_key or (current_exercise is not None and row.exercise_id != current_exercise.id):
        abort(404)
    list_url = url_for("views.admin_evaluation_lists", unit_key=unit_key)
    if not (row.pdf_relpath or "").strip():
        return redirect(list_url)
    fspath = _evaluation_list_file_abspath(row.pdf_relpath)
    if fspath is None:
        return redirect(list_url)
    ev = _evaluation_sheet_view_context(fspath)

    saved_payload = {}
    saved_updated_at = None
    saved_row_id = None
    saved_is_approved = False
    saved_approved_at = None
    saved_by_id = None

    # معلومات إضافية أعلى مربع قائمة التقييم (تعريف افتراضي لتجنب NameError)
    unit_label = (unit.get("label") or "").strip() if isinstance(unit, dict) else ""
    shown_date = getattr(current_exercise, "planned_start", None) if current_exercise is not None else None
    if shown_date is None and current_exercise is not None:
        shown_date = getattr(current_exercise, "created_at", None)
    commander_name = "—"
    judge_name = "—"
    if current_exercise is not None:
        commander_row = (
            db.query(ExerciseRosterRow)
            .filter(
                ExerciseRosterRow.exercise_id == current_exercise.id,
                ExerciseRosterRow.roster_kind == ExerciseRosterKind.TRAINEE.value,
                ExerciseRosterRow.unit_level_key == unit_key,
            )
            .order_by(ExerciseRosterRow.sort_order, ExerciseRosterRow.id)
            .first()
        )
        if commander_row is not None:
            commander_name = (commander_row.full_name or "").strip() or commander_name
        judge_row = (
            db.query(ExerciseRosterRow)
            .filter(
                ExerciseRosterRow.exercise_id == current_exercise.id,
                ExerciseRosterRow.roster_kind == ExerciseRosterKind.JUDGE.value,
                ExerciseRosterRow.unit_level_key == unit_key,
            )
            .order_by(ExerciseRosterRow.sort_order, ExerciseRosterRow.id)
            .first()
        )
        if judge_row is not None:
            judge_name = (judge_row.full_name or "").strip() or judge_name

    if current_exercise is not None:
        saved_id_raw = (request.args.get("saved_id") or "").strip()
        saved_id = None
        if saved_id_raw.isdigit():
            try:
                saved_id = int(saved_id_raw)
            except Exception:
                saved_id = None
        saved_row = (
            db.query(EvaluationListSavedResult)
            .filter(
                EvaluationListSavedResult.evaluation_item_id == row.id,
                EvaluationListSavedResult.exercise_id == current_exercise.id,
            )
            .order_by(EvaluationListSavedResult.updated_at.desc(), EvaluationListSavedResult.id.desc())
            .first()
        )
        if saved_id is not None:
            picked = (
                db.query(EvaluationListSavedResult)
                .filter(
                    EvaluationListSavedResult.id == saved_id,
                    EvaluationListSavedResult.evaluation_item_id == row.id,
                    EvaluationListSavedResult.exercise_id == current_exercise.id,
                )
                .first()
            )
            if picked is not None:
                saved_row = picked
        if saved_row and (saved_row.payload_json or "").strip():
            try:
                saved_payload = json.loads(saved_row.payload_json)
            except Exception:
                saved_payload = {}
            saved_updated_at = saved_row.updated_at
            saved_row_id = saved_row.id
            saved_is_approved = bool(getattr(saved_row, "is_approved", False))
            saved_approved_at = getattr(saved_row, "approved_at", None)
            saved_by_id = getattr(saved_row, "saved_by_id", None)
    return render_template(
        "admin_evaluation_list_viewer.html",
        **_ctx(
            user,
            unit_key=unit_key,
            item_id=item_id,
            item_title=row.text or "تقييم",
            evaluation_item_id=row.id,
            can_edit=not saved_is_approved,
            close_href=url_for("views.admin_evaluation_lists", unit_key=unit_key),
            close_label="إغلاق والعودة",
            saved_row_id=saved_row_id,
            saved_payload=saved_payload,
            saved_updated_at=saved_updated_at,
            saved_is_approved=saved_is_approved,
            saved_approved_at=saved_approved_at,
            saved_by_id=saved_by_id,
            eval_save_url=url_for("views.admin_evaluation_list_save_results", unit_key=unit_key, item_id=item_id),
            eval_approve_url=url_for("views.admin_evaluation_list_approve", unit_key=unit_key, item_id=item_id),
            show_eval_approve=can_approve_evaluation_results(user),
            **ev,
            unit_label=unit_label or "—",
            shown_date=shown_date,
            commander_name=commander_name or "—",
            judge_name=judge_name or "—",
            has_saved_rows=bool(saved_payload and (saved_payload.get("rows") or [])),
            eval_can_edit=not saved_is_approved,
            eval_approve_incomplete=request.args.get("eval_approve_incomplete", type=int) == 1,
        ),
    )


@bp.route("/analyst/evaluation-lists/<unit_key>/view/<int:item_id>", methods=["GET"])
def analyst_evaluation_list_file_viewer(unit_key: str, item_id: int):
    """عرض ملف التقييم للمحلل (قراءة فقط)."""
    user = get_current_user_optional()
    if not user:
        return redirect(f"/login?next=/analyst/evaluation-lists/{unit_key}/view/{item_id}")
    # نسمح للمحلل (وأيضاً إدارة النظام) بالعرض
    if not (can_access_analyst_hub(user) or is_system_admin(user)):
        abort(403)
    unit = next((x for x in UNIT_LEVELS if x["key"] == unit_key), None)
    if not unit:
        abort(404)
    from flask import g

    db = g.db
    row = db.get(EvaluationListPdfItem, item_id)
    current_exercise = _admin_current_workspace_exercise(db, user)
    if not row or row.unit_level_key != unit_key or (
        current_exercise is not None and row.exercise_id != current_exercise.id
    ):
        abort(404)
    if not (row.pdf_relpath or "").strip():
        abort(404)
    fspath = _evaluation_list_file_abspath(row.pdf_relpath)
    if fspath is None:
        abort(404)

    ev = _evaluation_sheet_view_context(fspath)

    # نعرض أحدث نتيجة محفوظة إن وجدت (اختيار saved_id اختياري)
    saved_payload = {}
    saved_updated_at = None
    saved_row_id = None
    saved_is_approved = False
    saved_approved_at = None
    saved_by_id = None
    if current_exercise is not None:
        saved_id_raw = (request.args.get("saved_id") or "").strip()
        saved_id = int(saved_id_raw) if saved_id_raw.isdigit() else None
        saved_row = (
            db.query(EvaluationListSavedResult)
            .filter(
                EvaluationListSavedResult.evaluation_item_id == row.id,
                EvaluationListSavedResult.exercise_id == current_exercise.id,
            )
            .order_by(EvaluationListSavedResult.updated_at.desc(), EvaluationListSavedResult.id.desc())
            .first()
        )
        if saved_id is not None:
            picked = (
                db.query(EvaluationListSavedResult)
                .filter(
                    EvaluationListSavedResult.id == saved_id,
                    EvaluationListSavedResult.evaluation_item_id == row.id,
                    EvaluationListSavedResult.exercise_id == current_exercise.id,
                )
                .first()
            )
            if picked is not None:
                saved_row = picked
        if saved_row and (saved_row.payload_json or "").strip():
            try:
                saved_payload = json.loads(saved_row.payload_json)
            except Exception:
                saved_payload = {}
            saved_updated_at = saved_row.updated_at
            saved_row_id = saved_row.id
            saved_is_approved = bool(getattr(saved_row, "is_approved", False))
            saved_approved_at = getattr(saved_row, "approved_at", None)
            saved_by_id = getattr(saved_row, "saved_by_id", None)

    # معلومات إضافية أعلى مربع قائمة التقييم
    unit_label = (unit.get("label") or "").strip() if isinstance(unit, dict) else ""
    shown_date = None
    commander_name = "—"
    judge_name = "—"
    if current_exercise is not None:
        shown_date = getattr(current_exercise, "planned_start", None) or getattr(current_exercise, "created_at", None)
        commander_row = (
            db.query(ExerciseRosterRow)
            .filter(
                ExerciseRosterRow.exercise_id == current_exercise.id,
                ExerciseRosterRow.roster_kind == ExerciseRosterKind.TRAINEE.value,
                ExerciseRosterRow.unit_level_key == unit_key,
            )
            .order_by(ExerciseRosterRow.sort_order, ExerciseRosterRow.id)
            .first()
        )
        if commander_row is not None:
            commander_name = (commander_row.full_name or "").strip() or commander_name
        judge_row = (
            db.query(ExerciseRosterRow)
            .filter(
                ExerciseRosterRow.exercise_id == current_exercise.id,
                ExerciseRosterRow.roster_kind == ExerciseRosterKind.JUDGE.value,
                ExerciseRosterRow.unit_level_key == unit_key,
            )
            .order_by(ExerciseRosterRow.sort_order, ExerciseRosterRow.id)
            .first()
        )
        if judge_row is not None:
            judge_name = (judge_row.full_name or "").strip() or judge_name

    return render_template(
        "admin_evaluation_list_viewer.html",
        **_ctx(
            user,
            unit_key=unit_key,
            item_id=item_id,
            item_title=row.text or "تقييم",
            evaluation_item_id=row.id,
            can_edit=False,
            close_href="/analyst/judges-eval-analysis",
            close_label="إغلاق والعودة للتحليل",
            saved_row_id=saved_row_id,
            saved_payload=saved_payload,
            saved_updated_at=saved_updated_at,
            saved_is_approved=saved_is_approved,
            saved_approved_at=saved_approved_at,
            saved_by_id=saved_by_id,
            **ev,
            unit_label=unit_label or "—",
            shown_date=shown_date,
            commander_name=commander_name or "—",
            judge_name=judge_name or "—",
            has_saved_rows=bool(saved_payload and (saved_payload.get("rows") or [])),
            eval_save_url="#",
            eval_approve_url="#",
            show_eval_approve=False,
            eval_can_edit=False,
        ),
    )


@bp.route("/admin/evaluation-lists/<unit_key>/item/<int:item_id>/file", methods=["GET"])
def admin_evaluation_list_file(unit_key: str, item_id: int):
    user = get_current_user_optional()
    if not user or not is_system_admin(user):
        abort(403)
    unit = next((x for x in UNIT_LEVELS if x["key"] == unit_key), None)
    if not unit:
        abort(404)
    from flask import g

    db = g.db
    row = db.get(EvaluationListPdfItem, item_id)
    current_exercise = _admin_current_workspace_exercise(db, user)
    if not row or row.unit_level_key != unit_key or (current_exercise is not None and row.exercise_id != current_exercise.id):
        abort(404)
    rel = (row.pdf_relpath or "").strip()
    if not rel:
        abort(404)
    path = _evaluation_list_file_abspath(rel)
    if path is None:
        abort(404)
    mt = _mimetype_for_eval_list_file(path)
    return send_file(
        path,
        mimetype=mt,
        as_attachment=True,
        download_name=path.name,
    )


@bp.route(
    "/admin/evaluation-lists/<unit_key>/item/<int:item_id>/delete",
    methods=["POST"],
)
def admin_evaluation_list_delete_item(unit_key: str, item_id: int):
    user = get_current_user_optional()
    if not user or not is_system_admin(user):
        abort(403)
    unit = next((x for x in UNIT_LEVELS if x["key"] == unit_key), None)
    if not unit:
        abort(404)
    from flask import g

    db = g.db
    row = db.get(EvaluationListPdfItem, item_id)
    current_exercise = _admin_current_workspace_exercise(db, user)
    if (
        not row
        or row.unit_level_key != unit_key
        or (current_exercise is not None and row.exercise_id != current_exercise.id)
    ):
        abort(404)
    if row.pdf_relpath:
        _unlink_evaluation_list_stored_file(row.pdf_relpath)
    db.delete(row)
    db.commit()
    return redirect(url_for("views.admin_evaluation_lists", unit_key=unit_key))


@bp.route(
    "/admin/evaluation-lists/<unit_key>/item/<int:item_id>/phase",
    methods=["POST"],
)
def admin_evaluation_list_set_phase(unit_key: str, item_id: int):
    user = get_current_user_optional()
    if not user or not is_system_admin(user):
        abort(403)
    unit = next((x for x in UNIT_LEVELS if x["key"] == unit_key), None)
    if not unit:
        abort(404)
    from flask import g

    db = g.db
    row = db.get(EvaluationListPdfItem, item_id)
    current_exercise = _admin_current_workspace_exercise(db, user)
    if (
        not row
        or row.unit_level_key != unit_key
        or (current_exercise is not None and row.exercise_id != current_exercise.id)
    ):
        abort(404)
    row.exercise_phase = _normalized_exercise_phase(request.form.get("exercise_phase"))
    db.commit()
    return redirect(url_for("views.admin_evaluation_lists", unit_key=unit_key))


@bp.route(
    "/admin/evaluation-lists/<unit_key>/view/<int:item_id>/save-results",
    methods=["POST"],
)
def admin_evaluation_list_save_results(unit_key: str, item_id: int):
    user = get_current_user_optional()
    if not user or not is_system_admin(user):
        abort(403)
    unit = next((x for x in UNIT_LEVELS if x["key"] == unit_key), None)
    if not unit:
        abort(404)
    from flask import g

    db = g.db
    item = db.get(EvaluationListPdfItem, item_id)
    current_exercise = _admin_current_workspace_exercise(db, user)
    if (
        not item
        or item.unit_level_key != unit_key
        or current_exercise is None
        or item.exercise_id != current_exercise.id
    ):
        abort(404)

    raw = (request.form.get("payload_json") or "").strip()
    if not raw:
        return redirect(url_for("views.admin_evaluation_list_file_viewer", unit_key=unit_key, item_id=item_id))
    if len(raw) > 250_000:
        abort(400)
    _evaluation_commit_payload_save(db, user=user, item=item, current_exercise=current_exercise, raw=raw)
    return redirect(url_for("views.admin_evaluation_list_file_viewer", unit_key=unit_key, item_id=item_id))


@bp.route(
    "/admin/evaluation-lists/<unit_key>/view/<int:item_id>/approve",
    methods=["POST"],
)
def admin_evaluation_list_approve(unit_key: str, item_id: int):
    user = get_current_user_optional()
    if not user or not is_system_admin(user):
        abort(403)
    if not can_approve_evaluation_results(user):
        abort(403)
    unit = next((x for x in UNIT_LEVELS if x["key"] == unit_key), None)
    if not unit:
        abort(404)
    from flask import g

    db = g.db
    item = db.get(EvaluationListPdfItem, item_id)
    current_exercise = _admin_current_workspace_exercise(db, user)
    if (
        not item
        or item.unit_level_key != unit_key
        or current_exercise is None
        or item.exercise_id != current_exercise.id
    ):
        abort(404)

    saved = _evaluation_canonical_saved_row(db, current_exercise.id, item.id)
    if saved is None or not (saved.payload_json or "").strip():
        abort(400)
    if bool(getattr(saved, "is_approved", False)):
        return redirect(url_for("views.admin_evaluation_list_file_viewer", unit_key=unit_key, item_id=item_id))
    rows = _parse_saved_eval_rows(saved.payload_json)
    if _evaluation_payload_has_empty_acquired_for_approve(rows):
        return redirect(
            url_for(
                "views.admin_evaluation_list_file_viewer",
                unit_key=unit_key,
                item_id=item_id,
                eval_approve_incomplete=1,
            )
        )
    saved.is_approved = True
    saved.approved_by_id = getattr(user, "id", None)
    saved.approved_at = datetime.utcnow()
    db.commit()
    return redirect(url_for("views.admin_evaluation_list_file_viewer", unit_key=unit_key, item_id=item_id))


@bp.route("/judge/evaluation-lists", methods=["GET"])
def judge_evaluation_lists_home():
    user = get_current_user_optional()
    if not user:
        return redirect("/login?next=/judge/evaluation-lists")
    if not can_access_judge_hub(user):
        abort(403)
    from flask import g

    db = g.db
    ex = _current_workspace_exercise(db, user)
    _ensure_judge_roster_synced(db, user, ex)
    # إن كان المحكم مخصصاً لوحدة واحدة، افتحها مباشرة
    a = _judge_assignment_for_current_exercise(db, user, ex)
    assigned_uk = (getattr(a, "unit_level_key", "") or "").strip() if a else ""
    if assigned_uk and not is_system_admin(user):
        return redirect(url_for("views.judge_evaluation_lists", unit_key=assigned_uk))
    return render_template(
        "judge_evaluation_lists_home.html",
        **_ctx(
            user,
            has_exercise=ex is not None,
            exercise=ex,
            unit_levels=[u for u in UNIT_LEVELS if not assigned_uk or u.get("key") == assigned_uk],
            hub_back_href=url_for("views.judge_hub"),
            unit_list_endpoint="views.judge_evaluation_lists",
        ),
    )


@bp.route("/judge/dilemmas", methods=["GET"])
def judge_dilemmas_home():
    user = get_current_user_optional()
    if not user:
        return redirect("/login?next=/judge/dilemmas")
    if not can_access_judge_hub(user):
        abort(403)
    from flask import g

    db = g.db
    ex = _current_workspace_exercise(db, user)
    _ensure_judge_roster_synced(db, user, ex)
    a = _judge_assignment_for_current_exercise(db, user, ex)
    assigned_uk = (getattr(a, "unit_level_key", "") or "").strip() if a else ""
    if assigned_uk and not is_system_admin(user):
        return redirect(url_for("views.judge_dilemmas", unit_key=assigned_uk))
    return render_template(
        "judge_dilemmas_home.html",
        **_ctx(
            user,
            has_exercise=ex is not None,
            exercise=ex,
            unit_levels=[u for u in UNIT_LEVELS if not assigned_uk or u.get("key") == assigned_uk],
        ),
    )


@bp.route("/judge/dilemmas/<unit_key>", methods=["GET"])
def judge_dilemmas(unit_key: str):
    user = get_current_user_optional()
    if not user:
        return redirect(f"/login?next=/judge/dilemmas/{unit_key}")
    if not can_access_judge_hub(user):
        abort(403)
    unit = next((x for x in UNIT_LEVELS if x["key"] == unit_key), None)
    if not unit:
        abort(404)
    from flask import g

    db = g.db
    ex = _current_workspace_exercise(db, user)
    if ex is None:
        return redirect("/judge/dilemmas")
    _enforce_judge_unit_scope(db, user, ex, unit_key)
    items = (
        db.query(DilemmaItem)
        .filter(DilemmaItem.exercise_id == ex.id, DilemmaItem.unit_level_key == unit_key)
        .order_by(DilemmaItem.exercise_phase, DilemmaItem.sort_order, DilemmaItem.id)
        .all()
    )
    return render_template(
        "judge_dilemmas.html",
        **_ctx(
            user,
            exercise=ex,
            unit=unit,
            unit_key=unit_key,
            items=items,
        ),
    )


@bp.route("/judge/dilemmas/<unit_key>/view/<int:item_id>", methods=["GET"])
def judge_dilemma_viewer(unit_key: str, item_id: int):
    user = get_current_user_optional()
    if not user:
        return redirect(f"/login?next=/judge/dilemmas/{unit_key}/view/{item_id}")
    if not can_access_judge_hub(user):
        abort(403)
    unit = next((x for x in UNIT_LEVELS if x["key"] == unit_key), None)
    if not unit:
        abort(404)
    from flask import g

    db = g.db
    row = db.get(DilemmaItem, item_id)
    current_exercise = _current_workspace_exercise(db, user)
    if not row or row.unit_level_key != unit_key or current_exercise is None or row.exercise_id != current_exercise.id:
        abort(404)
    _enforce_judge_unit_scope(db, user, current_exercise, unit_key)
    if _dilemma_pdf_abspath(row.pdf_relpath) is None:
        return redirect(url_for("views.judge_dilemmas", unit_key=unit_key))
    pdf_url = url_for("views.judge_dilemma_pdf_file", unit_key=unit_key, item_id=item_id)
    return render_template(
        "judge_dilemma_viewer.html",
        **_ctx(
            user,
            unit_key=unit_key,
            item_id=item_id,
            item_title=row.text or "معضلة",
            pdf_url=pdf_url,
        ),
    )


@bp.route("/judge/dilemmas/<unit_key>/item/<int:item_id>/pdf", methods=["GET"])
def judge_dilemma_pdf_file(unit_key: str, item_id: int):
    user = get_current_user_optional()
    if not user:
        abort(403)
    if not can_access_judge_hub(user):
        abort(403)
    from flask import g

    db = g.db
    row = db.get(DilemmaItem, item_id)
    ex = _current_workspace_exercise(db, user)
    if not row or row.unit_level_key != unit_key or ex is None or row.exercise_id != ex.id:
        abort(404)
    _enforce_judge_unit_scope(db, user, ex, unit_key)
    rel = (row.pdf_relpath or "").strip()
    path = _dilemma_pdf_abspath(rel)
    if path is None:
        abort(404)
    return send_file(path, mimetype="application/pdf", as_attachment=False)


@bp.route("/judge/evaluation-lists/<unit_key>", methods=["GET"])
def judge_evaluation_lists(unit_key: str):
    user = get_current_user_optional()
    if not user:
        return redirect(f"/login?next=/judge/evaluation-lists/{unit_key}")
    if not can_access_judge_hub(user):
        abort(403)
    unit = next((x for x in UNIT_LEVELS if x["key"] == unit_key), None)
    if not unit:
        abort(404)
    from flask import g

    db = g.db
    ex = _current_workspace_exercise(db, user)
    if ex is None:
        return redirect("/judge/evaluation-lists")
    _enforce_judge_unit_scope(db, user, ex, unit_key)
    items = (
        db.query(EvaluationListPdfItem)
        .filter(EvaluationListPdfItem.exercise_id == ex.id, EvaluationListPdfItem.unit_level_key == unit_key)
        .order_by(EvaluationListPdfItem.exercise_phase, EvaluationListPdfItem.sort_order, EvaluationListPdfItem.id)
        .all()
    )

    item_ids = [int(it.id) for it in items]
    canonical_by_item = _evaluation_canonical_map_for_items(db, ex.id, item_ids)

    a = _judge_assignment_for_current_exercise(db, user, ex)
    assigned_uk = (getattr(a, "unit_level_key", "") or "").strip() if a else ""
    if assigned_uk and not is_system_admin(user):
        eval_lists_parent_href = url_for("views.judge_hub")
    else:
        eval_lists_parent_href = url_for("views.judge_evaluation_lists_home")

    evaluation_lists_rows: list[dict] = []
    for it in items:
        iid = int(it.id)
        s = canonical_by_item.get(iid)
        is_done = bool(s and getattr(s, "is_approved", False))
        evaluation_lists_rows.append(
            {
                "item_id": int(it.id),
                "item_title": (it.text or "تقييم").strip(),
                # التاريخ والوقت: إن وُجد حفظ/اعتماد نعرضه، وإلا تاريخ إنشاء النموذج
                "dt": (getattr(s, "updated_at", None) if s else None) or getattr(it, "created_at", None),
                "exercise_type": (getattr(ex, "exercise_type", "") or "").strip(),
                "trained_unit": (getattr(ex, "trained_unit", "") or "").strip(),
                "delivery_dt": (
                    getattr(s, "approved_at", None)
                    if s is not None and bool(getattr(s, "is_approved", False))
                    else None
                ),
                "status_label": "ينجز" if is_done else "لم ينجز",
                "status_done": is_done,
                "grade_label": (getattr(s, "grade_label", "") or "").strip() if s else "",
                "open_href": url_for("views.judge_evaluation_list_file_viewer", unit_key=unit_key, item_id=it.id),
            }
        )
    return render_template(
        "judge_evaluation_lists.html",
        **_ctx(
            user,
            exercise=ex,
            unit=unit,
            unit_key=unit_key,
            items=items,
            evaluation_lists_rows=evaluation_lists_rows,
            eval_lists_parent_href=eval_lists_parent_href,
        ),
    )


@bp.route("/judge/evaluation-lists/<unit_key>/view/<int:item_id>", methods=["GET"])
def judge_evaluation_list_file_viewer(unit_key: str, item_id: int):
    user = get_current_user_optional()
    if not user:
        return redirect(f"/login?next=/judge/evaluation-lists/{unit_key}/view/{item_id}")
    if not can_access_judge_hub(user):
        abort(403)
    unit = next((x for x in UNIT_LEVELS if x["key"] == unit_key), None)
    if not unit:
        abort(404)
    from flask import g

    db = g.db
    row = db.get(EvaluationListPdfItem, item_id)
    current_exercise = _current_workspace_exercise(db, user)
    if not row or row.unit_level_key != unit_key or current_exercise is None or row.exercise_id != current_exercise.id:
        abort(404)
    _enforce_judge_unit_scope(db, user, current_exercise, unit_key)
    list_url = url_for("views.judge_evaluation_lists", unit_key=unit_key)
    if not (row.pdf_relpath or "").strip():
        return redirect(list_url)
    fspath = _evaluation_list_file_abspath(row.pdf_relpath)
    if fspath is None:
        return redirect(list_url)
    ev = _evaluation_sheet_view_context(fspath)

    saved_payload = {}
    saved_updated_at = None
    saved_is_approved = False
    saved_approved_at = None
    saved_row_id = None
    canon = _evaluation_canonical_saved_row(db, current_exercise.id, row.id)

    def _load_payload(sr: EvaluationListSavedResult | None) -> dict:
        if not sr or not (sr.payload_json or "").strip():
            return {}
        try:
            p = json.loads(sr.payload_json)
        except Exception:
            return {}
        return p if isinstance(p, dict) else {}

    if canon is not None:
        saved_payload = _load_payload(canon)
        saved_updated_at = canon.updated_at
        saved_is_approved = bool(getattr(canon, "is_approved", False))
        saved_approved_at = getattr(canon, "approved_at", None)
        saved_row_id = canon.id

    eval_save_url = url_for("views.judge_evaluation_list_save_results", unit_key=unit_key, item_id=item_id)
    eval_approve_url = url_for("views.judge_evaluation_list_approve", unit_key=unit_key, item_id=item_id)
    show_eval_approve = can_approve_evaluation_results(user)

    # معلومات إضافية أعلى مربع قائمة التقييم
    unit_label = (unit.get("label") or "").strip() if isinstance(unit, dict) else ""
    shown_date = getattr(current_exercise, "planned_start", None) or getattr(current_exercise, "created_at", None)

    commander_name = "—"
    commander_row = (
        db.query(ExerciseRosterRow)
        .filter(
            ExerciseRosterRow.exercise_id == current_exercise.id,
            ExerciseRosterRow.roster_kind == ExerciseRosterKind.TRAINEE.value,
            ExerciseRosterRow.unit_level_key == unit_key,
        )
        .order_by(ExerciseRosterRow.sort_order, ExerciseRosterRow.id)
        .first()
    )
    if commander_row is not None:
        commander_name = (commander_row.full_name or "").strip() or commander_name

    judge_name = (
        (getattr(user, "full_name", "") or "").strip()
        or (getattr(user, "username", "") or "").strip()
        or f"محكم #{getattr(user, 'id', '')}"
    )
    judge_row = (
        db.query(ExerciseRosterRow)
        .filter(
            ExerciseRosterRow.exercise_id == current_exercise.id,
            ExerciseRosterRow.roster_kind == ExerciseRosterKind.JUDGE.value,
            ExerciseRosterRow.unit_level_key == unit_key,
        )
        .order_by(ExerciseRosterRow.sort_order, ExerciseRosterRow.id)
        .first()
    )
    if judge_row is not None:
        judge_name = (judge_row.full_name or "").strip() or judge_name

    return render_template(
        "judge_evaluation_list_viewer.html",
        **_ctx(
            user,
            unit_key=unit_key,
            item_id=item_id,
            item_title=row.text or "تقييم",
            evaluation_item_id=row.id,
            saved_row_id=saved_row_id,
            saved_payload=saved_payload,
            saved_updated_at=saved_updated_at,
            saved_is_approved=saved_is_approved,
            saved_approved_at=saved_approved_at,
            **ev,
            unit_label=unit_label or "—",
            shown_date=shown_date,
            commander_name=commander_name or "—",
            judge_name=judge_name or "—",
            has_saved_rows=bool(saved_payload and (saved_payload.get("rows") or [])),
            eval_save_url=eval_save_url,
            eval_approve_url=eval_approve_url,
            show_eval_approve=show_eval_approve,
            eval_can_edit=not saved_is_approved,
            eval_approve_incomplete=request.args.get("eval_approve_incomplete", type=int) == 1,
        ),
    )


@bp.route(
    "/judge/evaluation-lists/<unit_key>/view/<int:item_id>/save-results",
    methods=["POST"],
)
def judge_evaluation_list_save_results(unit_key: str, item_id: int):
    user = get_current_user_optional()
    if not user:
        abort(403)
    if not can_access_judge_hub(user):
        abort(403)
    unit = next((x for x in UNIT_LEVELS if x["key"] == unit_key), None)
    if not unit:
        abort(404)
    from flask import g

    db = g.db
    item = db.get(EvaluationListPdfItem, item_id)
    current_exercise = _current_workspace_exercise(db, user)
    if (
        not item
        or item.unit_level_key != unit_key
        or current_exercise is None
        or item.exercise_id != current_exercise.id
    ):
        abort(404)
    _enforce_judge_unit_scope(db, user, current_exercise, unit_key)

    raw = (request.form.get("payload_json") or "").strip()
    if not raw:
        return redirect(url_for("views.judge_evaluation_list_file_viewer", unit_key=unit_key, item_id=item_id))
    if len(raw) > 250_000:
        abort(400)
    _evaluation_commit_payload_save(db, user=user, item=item, current_exercise=current_exercise, raw=raw)
    return redirect(url_for("views.judge_evaluation_list_file_viewer", unit_key=unit_key, item_id=item_id))


@bp.route(
    "/judge/evaluation-lists/<unit_key>/view/<int:item_id>/approve",
    methods=["POST"],
)
def judge_evaluation_list_approve(unit_key: str, item_id: int):
    user = get_current_user_optional()
    if not user:
        abort(403)
    if not can_approve_evaluation_results(user):
        abort(403)
    if not can_access_judge_hub(user):
        abort(403)
    unit = next((x for x in UNIT_LEVELS if x["key"] == unit_key), None)
    if not unit:
        abort(404)
    from flask import g

    db = g.db
    item = db.get(EvaluationListPdfItem, item_id)
    current_exercise = _current_workspace_exercise(db, user)
    if (
        not item
        or item.unit_level_key != unit_key
        or current_exercise is None
        or item.exercise_id != current_exercise.id
    ):
        abort(404)
    _enforce_judge_unit_scope(db, user, current_exercise, unit_key)

    saved = _evaluation_canonical_saved_row(db, current_exercise.id, item.id)
    if saved is None or not (saved.payload_json or "").strip():
        abort(400)
    if bool(getattr(saved, "is_approved", False)):
        return redirect(url_for("views.judge_evaluation_list_file_viewer", unit_key=unit_key, item_id=item_id))
    rows = _parse_saved_eval_rows(saved.payload_json)
    if _evaluation_payload_has_empty_acquired_for_approve(rows):
        return redirect(
            url_for(
                "views.judge_evaluation_list_file_viewer",
                unit_key=unit_key,
                item_id=item_id,
                eval_approve_incomplete=1,
            )
        )
    saved.is_approved = True
    saved.approved_by_id = getattr(user, "id", None)
    saved.approved_at = datetime.utcnow()
    db.commit()
    return redirect(url_for("views.judge_evaluation_list_file_viewer", unit_key=unit_key, item_id=item_id))


@bp.route("/admin/evaluation-lists/saved-results", methods=["GET"])
def admin_evaluation_saved_results():
    user = get_current_user_optional()
    if not user:
        return redirect("/login?next=/admin/evaluation-lists/saved-results")
    if not is_system_admin(user):
        abort(403)
    from flask import g

    db = g.db
    ex = _admin_current_workspace_exercise(db, user)
    if ex is None:
        return render_template(
            "admin_evaluation_saved_results.html",
            **_ctx(user, has_exercise=False),
        )
    saved_rows = (
        db.query(EvaluationListSavedResult)
        .filter(EvaluationListSavedResult.exercise_id == ex.id)
        .order_by(EvaluationListSavedResult.updated_at.desc(), EvaluationListSavedResult.id.desc())
        .all()
    )
    saved_display = []
    for r in saved_rows:
        uk = (r.unit_level_key or "").strip()
        saved_display.append(
            {
                "row": r,
                "unit_label": label_for_unit_level_key(uk) if uk else "",
            }
        )
    return render_template(
        "admin_evaluation_saved_results.html",
        **_ctx(
            user,
            has_exercise=True,
            exercise=ex,
            saved_display=saved_display,
        ),
    )


@bp.route("/admin/evaluation-lists/saved-results/<int:saved_id>/delete", methods=["POST"])
def admin_evaluation_saved_results_delete(saved_id: int):
    user = get_current_user_optional()
    if not user or not is_system_admin(user):
        abort(403)
    from flask import g

    db = g.db
    row = db.get(EvaluationListSavedResult, saved_id)
    ex = _admin_current_workspace_exercise(db, user)
    if row is None or ex is None or row.exercise_id != ex.id:
        abort(404)
    db.delete(row)
    db.commit()
    return redirect("/admin/evaluation-lists/saved-results")


@bp.route("/admin/evaluation-lists/<unit_key>/clear", methods=["POST"])
def admin_evaluation_list_clear(unit_key: str):
    user = get_current_user_optional()
    if not user or not is_system_admin(user):
        abort(403)
    unit = next((x for x in UNIT_LEVELS if x["key"] == unit_key), None)
    if not unit:
        abort(404)
    from flask import g

    db = g.db
    current_exercise = _admin_current_workspace_exercise(db, user)
    q = db.query(EvaluationListPdfItem).filter(EvaluationListPdfItem.unit_level_key == unit_key)
    if current_exercise is not None:
        q = q.filter(EvaluationListPdfItem.exercise_id == current_exercise.id)
    else:
        q = q.filter(EvaluationListPdfItem.exercise_id == -1)
    for row in q.all():
        if row.pdf_relpath:
            _unlink_evaluation_list_stored_file(row.pdf_relpath)
    q.delete(synchronize_session=False)
    db.commit()
    return redirect(url_for("views.admin_evaluation_lists", unit_key=unit_key))


@bp.route("/admin/evaluation-lists/<unit_key>", methods=["GET", "POST"])
def admin_evaluation_lists(unit_key: str):
    user = get_current_user_optional()
    if not user or not is_system_admin(user):
        abort(403)
    from flask import g

    db = g.db
    unit = next((x for x in UNIT_LEVELS if x["key"] == unit_key), None)
    if not unit:
        abort(404)
    current_exercise = _admin_current_workspace_exercise(db, user)

    def _display_name_for_upload(filename: str) -> str:
        base = Path(filename or "").name.strip()
        if not base:
            return "تقييم"
        return base[:2000]

    error = ""
    ok_msg = ""
    if request.method == "POST":
        phase = _normalized_exercise_phase(request.form.get("exercise_phase"))
        if current_exercise is None:
            error = "لا يوجد تمرين حالي. أنشئ تمريناً جديداً قبل إدراج قوائم التقييم."
            files = []
        else:
            files = request.files.getlist("evaluation_lists_file")
        valid_files: list[tuple[bytes, str]] = []
        for f in files:
            if not f or not getattr(f, "filename", ""):
                continue
            try:
                data = f.read()
            except Exception:
                error = "تعذر قراءة أحد الملفات."
                break
            fn = (getattr(f, "filename", "") or "").strip()
            if not fn.lower().endswith(".xlsx"):
                error = "يُقبل فقط ملف Excel بصيغة .xlsx."
                break
            if not _is_xlsx_bytes(data):
                error = "الملف ليس مصنفاً Excel صالحاً (.xlsx)."
                break
            if len(data) > 30 * 1024 * 1024:
                error = "الملف كبير جداً (الحد 30 ميغابايت لكل ملف)."
                break
            valid_files.append((data, _display_name_for_upload(f.filename)))
        if not error and not valid_files:
            error = "اختر ملفاً بصيغة .xlsx (يمكن اختيار عدة ملفات دفعة واحدة)."
        if not error and valid_files:
            stored_hashes = _hashes_of_unit_pdfs(
                db,
                EvaluationListPdfItem,
                unit_key,
                _evaluation_list_file_abspath,
                current_exercise.id if current_exercise else None,
                exercise_phase=phase,
            )
            batch_hashes: set[str] = set()
            to_add: list[tuple[bytes, str]] = []
            skipped_labels: list[str] = []
            for data, label in valid_files:
                h = hashlib.sha256(data).hexdigest()
                if h in stored_hashes or h in batch_hashes:
                    skipped_labels.append(label)
                    continue
                to_add.append((data, label))
                batch_hashes.add(h)
                stored_hashes.add(h)

            if not to_add and skipped_labels:
                error = (
                    "لا يمكن الإضافة: الملف (أو الملفات) مطابق لملف موجود مسبقاً في القائمة الحالية "
                    "(No Duplicate)."
                )
            elif to_add:
                EVALUATION_LIST_XLSX_DIR.mkdir(parents=True, exist_ok=True)
                udir = EVALUATION_LIST_XLSX_DIR / unit_key
                udir.mkdir(parents=True, exist_ok=True)
                mx = (
                    db.query(func.max(EvaluationListPdfItem.sort_order))
                    .filter(
                        EvaluationListPdfItem.unit_level_key == unit_key,
                        EvaluationListPdfItem.exercise_id == current_exercise.id,
                    )
                    .scalar()
                )
                start = (int(mx) if mx is not None else -1) + 1
                n = 0
                for i, (data, label) in enumerate(to_add):
                    rel_name = f"{unit_key}/{uuid.uuid4().hex}.xlsx"
                    full = (EVALUATION_LIST_XLSX_DIR / rel_name).resolve()
                    try:
                        full.parent.mkdir(parents=True, exist_ok=True)
                        full.write_bytes(data)
                    except OSError:
                        error = "تعذر حفظ الملفات على الخادم."
                        db.rollback()
                        break
                    db.add(
                        EvaluationListPdfItem(
                            exercise_id=current_exercise.id if current_exercise else None,
                            exercise_phase=phase,
                            unit_level_key=unit_key,
                            unit_level_label=unit["label"],
                            sort_order=start + i,
                            text=label,
                            pdf_relpath=rel_name.replace("\\", "/"),
                        )
                    )
                    n += 1
                if not error:
                    db.commit()
                    if n > 0 and current_exercise is not None:
                        from app.notifications_service import notify_evaluation_lists_added

                        notify_evaluation_lists_added(
                            db,
                            exercise_id=int(current_exercise.id),
                            unit_key=unit_key,
                            unit_label=unit["label"],
                            n_files=n,
                        )
                        db.commit()
                    if skipped_labels:
                        preview = "، ".join(skipped_labels[:8])
                        if len(skipped_labels) > 8:
                            preview += " …"
                        ok_msg = (
                            f"تمت إضافة {n} ملفاً إلى قوائم التقييم لهذا المستوى. "
                            f"تُرك دون إضافة — مكرر (No Duplicate): {preview}"
                        )
                    else:
                        ok_msg = f"تمت إضافة {n} ملفاً إلى قوائم التقييم لهذا المستوى."

    existing_q = db.query(EvaluationListPdfItem).filter(EvaluationListPdfItem.unit_level_key == unit_key)
    if current_exercise is not None:
        existing_q = existing_q.filter(EvaluationListPdfItem.exercise_id == current_exercise.id)
    else:
        existing_q = existing_q.filter(EvaluationListPdfItem.exercise_id == -1)
    existing = existing_q.order_by(
        EvaluationListPdfItem.exercise_phase,
        EvaluationListPdfItem.sort_order,
        EvaluationListPdfItem.id,
    ).all()
    return render_template(
        "admin_evaluation_lists.html",
        **_ctx(
            user,
            unit_levels=UNIT_LEVELS,
            selected_unit_key=unit_key,
            selected_unit_label=unit["label"],
            exercise_phase_options=EXERCISE_PHASE_OPTIONS,
            upload_phase_default=ExercisePhase.MAIN.value,
            items=existing,
            error=error,
            ok_msg=ok_msg,
        ),
    )


@bp.route("/admin/evaluation-lists")
@bp.route("/admin/evaluation-lists/")
def admin_evaluation_lists_home():
    user = get_current_user_optional()
    if not user:
        return redirect("/login?next=/admin/evaluation-lists")
    if not is_system_admin(user):
        abort(403)
    first = UNIT_LEVELS[0]["key"] if UNIT_LEVELS else "brigade_group"
    return redirect(url_for("views.admin_evaluation_lists", unit_key=first))


def _build_dilemma_evaluation_unit_report(
    db,
    exercise_id: int | None = None,
    *,
    exercise_phase: str | None = None,
) -> list[dict]:
    """يجمع المعاضل وقوائم التقييم لكل مستوى وحدة داخل التمرين الحالي ويقترنها حسب ترتيب الحفظ (sort_order)."""
    phase = _normalized_exercise_phase(exercise_phase)
    out: list[dict] = []
    for unit in UNIT_LEVELS:
        uk = unit["key"]
        ul = unit["label"]
        d_q = db.query(DilemmaItem).filter(DilemmaItem.unit_level_key == uk)
        e_q = db.query(EvaluationListPdfItem).filter(EvaluationListPdfItem.unit_level_key == uk)
        d_q = d_q.filter(DilemmaItem.exercise_phase == phase)
        e_q = e_q.filter(EvaluationListPdfItem.exercise_phase == phase)
        if exercise_id is not None:
            d_q = d_q.filter(DilemmaItem.exercise_id == exercise_id)
            e_q = e_q.filter(EvaluationListPdfItem.exercise_id == exercise_id)
        else:
            d_q = d_q.filter(DilemmaItem.exercise_id == -1)
            e_q = e_q.filter(EvaluationListPdfItem.exercise_id == -1)
        d_rows = d_q.order_by(DilemmaItem.sort_order, DilemmaItem.id).all()
        e_rows = e_q.order_by(EvaluationListPdfItem.sort_order, EvaluationListPdfItem.id).all()

        def _d_pack(r: DilemmaItem) -> dict:
            return {
                "id": r.id,
                "text": (r.text or "")[:220],
                "sort_order": r.sort_order,
                "has_file": bool((r.pdf_relpath or "").strip()),
            }

        dilemmas = [_d_pack(r) for r in d_rows]
        evals = [
            {
                "id": r.id,
                "text": (r.text or "")[:220],
                "sort_order": r.sort_order,
                "has_file": bool((r.pdf_relpath or "").strip()),
            }
            for r in e_rows
        ]
        n_d, n_e = len(dilemmas), len(evals)
        max_n = max(n_d, n_e)
        pairs: list[dict] = []
        for i in range(max_n):
            d = dilemmas[i] if i < n_d else None
            e = evals[i] if i < n_e else None
            if d and e:
                st, st_ar = "paired", "صف مقترَح — معضلة وتقييم في نفس موضع الترتيب"
            elif d and not e:
                st, st_ar = "dilemma_only", "معضلة دون عنصر تقييم في نفس الموضع"
            elif e and not d:
                st, st_ar = "eval_only", "تقييم دون معضلة في نفس الموضع"
            else:
                st, st_ar = "empty", ""
            pairs.append(
                {
                    "index": i + 1,
                    "dilemma": d,
                    "evaluation": e,
                    "status": st,
                    "status_ar": st_ar,
                }
            )

        if n_d == 0 and n_e == 0:
            balance_ar, balance_key = "لا عناصر في هذا المستوى", "empty"
        elif n_d == n_e and n_d > 0:
            balance_ar, balance_key = (
                f"عدد متساوٍ ({n_d}) — يمكن قراءة الصفوف كأزواج بالترتيب",
                "balanced",
            )
        elif n_d > n_e:
            balance_ar, balance_key = (
                f"المعاضل أكثر ({n_d} مقابل {n_e})",
                "more_dilemmas",
            )
        else:
            balance_ar, balance_key = (
                f"قوائم التقييم أكثر ({n_e} مقابل {n_d})",
                "more_evals",
            )

        def _pack_roster_row(r: ExerciseRosterRow) -> dict:
            return {
                "id": r.id,
                "military_number": r.military_number or "",
                "rank_ar": r.rank_ar or "",
                "full_name": r.full_name or "",
                "sort_order": r.sort_order,
            }

        if exercise_id is not None:
            tr_rows = (
                db.query(ExerciseRosterRow)
                .filter(
                    ExerciseRosterRow.exercise_id == exercise_id,
                    ExerciseRosterRow.roster_kind == ExerciseRosterKind.TRAINEE.value,
                    ExerciseRosterRow.unit_level_key == uk,
                )
                .order_by(ExerciseRosterRow.sort_order, ExerciseRosterRow.id)
                .all()
            )
            j_rows = (
                db.query(ExerciseRosterRow)
                .filter(
                    ExerciseRosterRow.exercise_id == exercise_id,
                    ExerciseRosterRow.roster_kind == ExerciseRosterKind.JUDGE.value,
                    ExerciseRosterRow.unit_level_key == uk,
                )
                .order_by(ExerciseRosterRow.sort_order, ExerciseRosterRow.id)
                .all()
            )
            trainees = [_pack_roster_row(r) for r in tr_rows]
            judges = [_pack_roster_row(r) for r in j_rows]
        else:
            trainees, judges = [], []

        out.append(
            {
                "unit_key": uk,
                "unit_label": ul,
                "n_dilemmas": n_d,
                "n_evaluations": n_e,
                "n_trainees": len(trainees),
                "n_judges": len(judges),
                "balance_key": balance_key,
                "balance_ar": balance_ar,
                "pairs": pairs,
                "trainees": trainees,
                "judges": judges,
            }
        )
    return out


@bp.route("/admin/dilemmas-evaluation-unit-report", methods=["GET"])
def admin_dilemma_evaluation_unit_report():
    user = get_current_user_optional()
    if not user:
        return redirect("/login?next=/admin/dilemmas-evaluation-unit-report")
    if not is_system_admin(user):
        abort(403)
    from flask import g

    db = g.db
    current_exercise = _admin_current_workspace_exercise(db, user)
    phase = _normalized_exercise_phase(request.args.get("phase"))
    report_rows = _build_dilemma_evaluation_unit_report(
        db,
        current_exercise.id if current_exercise else None,
        exercise_phase=phase,
    )
    return render_template(
        "admin_dilemma_evaluation_unit_report.html",
        **_ctx(
            user,
            report_rows=report_rows,
            exercise_phase_options=EXERCISE_PHASE_OPTIONS,
            selected_exercise_phase=phase,
        ),
    )


@bp.route("/admin/battle-organization", methods=["GET"])
def admin_battle_organization():
    user = get_current_user_optional()
    if not user or not is_system_admin(user):
        abort(403)
    from flask import g

    db = g.db
    ex = _admin_current_workspace_exercise(db, user)
    personnel_by_unit: dict[str, dict[str, str]] = {}
    if ex:
        for row in (
            db.query(ExerciseBattleUnitPersonnel)
            .filter(ExerciseBattleUnitPersonnel.exercise_id == ex.id)
            .all()
        ):
            personnel_by_unit[row.unit_id] = {
                "trainee_name": row.trainee_name or "",
                "trainee_military_number": row.trainee_military_number or "",
                "rank_ar": row.rank_ar or "",
                "position_ar": row.position_ar or "",
                "judge_trainee_name": row.judge_trainee_name or "",
                "judge_military_number": row.judge_military_number or "",
                "judge_rank_ar": row.judge_rank_ar or "",
                "judge_position_ar": row.judge_position_ar or "",
            }
    ok_msg = (request.args.get("ok") or "").strip()
    err = (request.args.get("err") or "").strip()
    err_msgs = {
        "no_exercise": "لا يوجد تمرين حالي. أنشئ تمريناً أو اختر مساحة عمل قبل الحفظ.",
        "exercise": "معرّف التمرين غير مطابق للتمرين الحالي.",
        "unit": "معرّف الوحدة غير صالح.",
    }
    return render_template(
        "admin_battle_organization.html",
        **_ctx(
            user,
            battle_tree=BATTLE_ORG_DEMO_ROOT,
            current_exercise=ex,
            personnel_by_unit=personnel_by_unit,
            battle_ok_msg="تم حفظ البيانات." if ok_msg == "1" else "",
            battle_error_msg=err_msgs.get(err, "") if err else "",
        ),
    )


@bp.route("/admin/battle-organization/save", methods=["POST"])
def admin_battle_organization_save():
    user = get_current_user_optional()
    if not user or not is_system_admin(user):
        abort(403)
    from flask import g

    db = g.db
    ex = _admin_current_workspace_exercise(db, user)
    if not ex:
        return redirect("/admin/battle-organization?err=no_exercise")
    try:
        exercise_id = int(request.form.get("exercise_id") or "0")
    except ValueError:
        exercise_id = 0
    if exercise_id != ex.id:
        return redirect("/admin/battle-organization?err=exercise")
    unit_id = (request.form.get("unit_id") or "").strip()
    if not unit_id or len(unit_id) > 64:
        return redirect("/admin/battle-organization?err=unit")
    trainee_name = (request.form.get("trainee_name") or "").strip()[:256]
    trainee_military_number = (
        (request.form.get("trainee_military_number") or "").strip()[:128]
    )
    rank_ar = (request.form.get("rank_ar") or "").strip()[:256]
    position_ar = (request.form.get("position_ar") or "").strip()[:512]
    judge_trainee_name = (request.form.get("judge_trainee_name") or "").strip()[:256]
    judge_military_number = (
        (request.form.get("judge_military_number") or "").strip()[:128]
    )
    judge_rank_ar = (request.form.get("judge_rank_ar") or "").strip()[:256]
    judge_position_ar = (request.form.get("judge_position_ar") or "").strip()[:512]
    row = (
        db.query(ExerciseBattleUnitPersonnel)
        .filter(
            ExerciseBattleUnitPersonnel.exercise_id == ex.id,
            ExerciseBattleUnitPersonnel.unit_id == unit_id,
        )
        .first()
    )
    if row is None:
        row = ExerciseBattleUnitPersonnel(
            exercise_id=ex.id,
            unit_id=unit_id,
        )
        db.add(row)
    row.trainee_name = trainee_name
    row.trainee_military_number = trainee_military_number
    row.rank_ar = rank_ar
    row.position_ar = position_ar
    row.judge_trainee_name = judge_trainee_name
    row.judge_military_number = judge_military_number
    row.judge_rank_ar = judge_rank_ar
    row.judge_position_ar = judge_position_ar
    db.commit()
    return redirect("/admin/battle-organization?ok=1")


@bp.route("/admin/dilemmas")
@bp.route("/admin/dilemmas/")
def admin_dilemmas_home():
    user = get_current_user_optional()
    if not user or not is_system_admin(user):
        abort(403)
    first = UNIT_LEVELS[0]["key"] if UNIT_LEVELS else "brigade_group"
    return redirect(url_for("views.admin_dilemmas", unit_key=first))


@bp.route("/admin/dilemmas/<unit_key>", methods=["GET", "POST"])
def admin_dilemmas(unit_key: str):
    user = get_current_user_optional()
    if not user or not is_system_admin(user):
        abort(403)
    from flask import g

    db = g.db
    unit = next((x for x in UNIT_LEVELS if x["key"] == unit_key), None)
    if not unit:
        abort(404)
    current_exercise = _admin_current_workspace_exercise(db, user)

    def _display_name_for_upload(filename: str) -> str:
        base = Path(filename or "").name.strip()
        if not base:
            return "معضلة"
        return base[:2000]

    error = ""
    ok_msg = ""
    if request.method == "POST":
        phase = _normalized_exercise_phase(request.form.get("exercise_phase"))
        if current_exercise is None:
            error = "لا يوجد تمرين حالي. أنشئ تمريناً جديداً قبل إدراج قوائم المعاضل."
            files = []
        else:
            files = request.files.getlist("dilemmas_file")
        valid_files: list[tuple[bytes, str]] = []
        for f in files:
            if not f or not getattr(f, "filename", ""):
                continue
            try:
                data = f.read()
            except Exception:
                error = "تعذر قراءة أحد الملفات."
                break
            if not _is_pdf_bytes(data):
                error = "يُقبل فقط PDF (تعذر التحقق من الملف كـ PDF)."
                break
            if len(data) > 30 * 1024 * 1024:
                error = "الملف كبير جداً (الحد 30 ميغابايت لكل ملف)."
                break
            valid_files.append((data, _display_name_for_upload(f.filename)))
        if not error and not valid_files:
            error = "اختر ملفاً بصيغة PDF (يمكن اختيار عدة ملفات دفعة واحدة)."
        if not error and valid_files:
            stored_hashes = _hashes_of_unit_pdfs(
                db,
                DilemmaItem,
                unit_key,
                _dilemma_pdf_abspath,
                current_exercise.id if current_exercise else None,
                exercise_phase=phase,
            )
            batch_hashes: set[str] = set()
            to_add: list[tuple[bytes, str]] = []
            skipped_labels: list[str] = []
            for data, label in valid_files:
                h = hashlib.sha256(data).hexdigest()
                if h in stored_hashes or h in batch_hashes:
                    skipped_labels.append(label)
                    continue
                to_add.append((data, label))
                batch_hashes.add(h)
                stored_hashes.add(h)

            if not to_add and skipped_labels:
                error = (
                    "لا يمكن الإضافة: الملف (أو الملفات) مطابق لملف موجود مسبقاً في القائمة الحالية "
                    "(No Duplicate)."
                )
            elif to_add:
                DILEMMA_PDF_DIR.mkdir(parents=True, exist_ok=True)
                udir = DILEMMA_PDF_DIR / unit_key
                udir.mkdir(parents=True, exist_ok=True)
                mx = (
                    db.query(func.max(DilemmaItem.sort_order))
                    .filter(
                        DilemmaItem.unit_level_key == unit_key,
                        DilemmaItem.exercise_id == current_exercise.id,
                    )
                    .scalar()
                )
                start = (int(mx) if mx is not None else -1) + 1
                n = 0
                for i, (data, label) in enumerate(to_add):
                    rel_name = f"{unit_key}/{uuid.uuid4().hex}.pdf"
                    full = (DILEMMA_PDF_DIR / rel_name).resolve()
                    try:
                        full.parent.mkdir(parents=True, exist_ok=True)
                        full.write_bytes(data)
                    except OSError:
                        error = "تعذر حفظ الملفات على الخادم."
                        db.rollback()
                        break
                    db.add(
                        DilemmaItem(
                            exercise_id=current_exercise.id if current_exercise else None,
                            exercise_phase=phase,
                            unit_level_key=unit_key,
                            unit_level_label=unit["label"],
                            sort_order=start + i,
                            text=label,
                            pdf_relpath=rel_name.replace("\\", "/"),
                        )
                    )
                    n += 1
                if not error:
                    db.commit()
                    if n > 0 and current_exercise is not None:
                        from app.notifications_service import notify_dilemma_files_added

                        notify_dilemma_files_added(
                            db,
                            exercise_id=int(current_exercise.id),
                            unit_key=unit_key,
                            unit_label=unit["label"],
                            n_files=n,
                        )
                        db.commit()
                    if skipped_labels:
                        preview = "، ".join(skipped_labels[:8])
                        if len(skipped_labels) > 8:
                            preview += " …"
                        ok_msg = (
                            f"تمت إضافة {n} ملفاً معضلة لهذا المستوى. "
                            f"تُرك دون إضافة — مكرر (No Duplicate): {preview}"
                        )
                    else:
                        ok_msg = f"تمت إضافة {n} ملفاً معضلة لهذا المستوى."

    existing_q = db.query(DilemmaItem).filter(DilemmaItem.unit_level_key == unit_key)
    if current_exercise is not None:
        existing_q = existing_q.filter(DilemmaItem.exercise_id == current_exercise.id)
    else:
        existing_q = existing_q.filter(DilemmaItem.exercise_id == -1)
    existing = existing_q.order_by(
        DilemmaItem.exercise_phase,
        DilemmaItem.sort_order,
        DilemmaItem.id,
    ).all()
    return render_template(
        "admin_dilemmas.html",
        **_ctx(
            user,
            unit_levels=UNIT_LEVELS,
            selected_unit_key=unit_key,
            selected_unit_label=unit["label"],
            exercise_phase_options=EXERCISE_PHASE_OPTIONS,
            upload_phase_default=ExercisePhase.MAIN.value,
            items=existing,
            error=error,
            ok_msg=ok_msg,
        ),
    )


@bp.route("/admin/dilemmas/<unit_key>/view/<int:item_id>", methods=["GET"])
def admin_dilemma_viewer(unit_key: str, item_id: int):
    user = get_current_user_optional()
    if not user or not is_system_admin(user):
        abort(403)
    unit = next((x for x in UNIT_LEVELS if x["key"] == unit_key), None)
    if not unit:
        abort(404)
    from flask import g

    db = g.db
    row = db.get(DilemmaItem, item_id)
    current_exercise = _admin_current_workspace_exercise(db, user)
    if not row or row.unit_level_key != unit_key or (current_exercise is not None and row.exercise_id != current_exercise.id):
        abort(404)
    list_url = url_for("views.admin_dilemmas", unit_key=unit_key)
    if not (row.pdf_relpath or "").strip():
        return redirect(list_url)
    if _dilemma_pdf_abspath(row.pdf_relpath) is None:
        return redirect(list_url)
    pdf_url = url_for(
        "views.admin_dilemma_pdf_file", unit_key=unit_key, item_id=item_id
    )
    return render_template(
        "admin_dilemma_viewer.html",
        **_ctx(
            user,
            unit_key=unit_key,
            item_id=item_id,
            item_title=row.text or "معضلة",
            pdf_url=pdf_url,
        ),
    )


@bp.route("/admin/dilemmas/<unit_key>/item/<int:item_id>/pdf", methods=["GET"])
def admin_dilemma_pdf_file(unit_key: str, item_id: int):
    user = get_current_user_optional()
    if not user or not is_system_admin(user):
        abort(403)
    unit = next((x for x in UNIT_LEVELS if x["key"] == unit_key), None)
    if not unit:
        abort(404)
    from flask import g

    db = g.db
    row = db.get(DilemmaItem, item_id)
    current_exercise = _admin_current_workspace_exercise(db, user)
    if not row or row.unit_level_key != unit_key or (current_exercise is not None and row.exercise_id != current_exercise.id):
        abort(404)
    rel = (row.pdf_relpath or "").strip()
    if not rel:
        abort(404)
    path = _dilemma_pdf_abspath(rel)
    if path is None:
        abort(404)
    return send_file(path, mimetype="application/pdf", as_attachment=False)


@bp.route("/admin/dilemmas/<unit_key>/item/<int:item_id>/delete", methods=["POST"])
def admin_dilemmas_delete_item(unit_key: str, item_id: int):
    user = get_current_user_optional()
    if not user or not is_system_admin(user):
        abort(403)
    unit = next((x for x in UNIT_LEVELS if x["key"] == unit_key), None)
    if not unit:
        abort(404)
    from flask import g

    db = g.db
    row = db.get(DilemmaItem, item_id)
    current_exercise = _admin_current_workspace_exercise(db, user)
    if (
        not row
        or row.unit_level_key != unit_key
        or (current_exercise is not None and row.exercise_id != current_exercise.id)
    ):
        abort(404)
    if row.pdf_relpath:
        _unlink_dilemma_stored_pdf(row.pdf_relpath)
    db.delete(row)
    db.commit()
    return redirect(url_for("views.admin_dilemmas", unit_key=unit_key))


@bp.route(
    "/admin/dilemmas/<unit_key>/item/<int:item_id>/phase",
    methods=["POST"],
)
def admin_dilemmas_set_phase(unit_key: str, item_id: int):
    user = get_current_user_optional()
    if not user or not is_system_admin(user):
        abort(403)
    unit = next((x for x in UNIT_LEVELS if x["key"] == unit_key), None)
    if not unit:
        abort(404)
    from flask import g

    db = g.db
    row = db.get(DilemmaItem, item_id)
    current_exercise = _admin_current_workspace_exercise(db, user)
    if (
        not row
        or row.unit_level_key != unit_key
        or (current_exercise is not None and row.exercise_id != current_exercise.id)
    ):
        abort(404)
    row.exercise_phase = _normalized_exercise_phase(request.form.get("exercise_phase"))
    db.commit()
    return redirect(url_for("views.admin_dilemmas", unit_key=unit_key))


@bp.route("/admin/dilemmas/<unit_key>/clear", methods=["POST"])
def admin_dilemmas_clear(unit_key: str):
    user = get_current_user_optional()
    if not user or not is_system_admin(user):
        abort(403)
    unit = next((x for x in UNIT_LEVELS if x["key"] == unit_key), None)
    if not unit:
        abort(404)
    from flask import g

    db = g.db
    current_exercise = _admin_current_workspace_exercise(db, user)
    q = db.query(DilemmaItem).filter(DilemmaItem.unit_level_key == unit_key)
    if current_exercise is not None:
        q = q.filter(DilemmaItem.exercise_id == current_exercise.id)
    else:
        q = q.filter(DilemmaItem.exercise_id == -1)
    for row in q.all():
        if row.pdf_relpath:
            _unlink_dilemma_stored_pdf(row.pdf_relpath)
    q.delete(synchronize_session=False)
    db.commit()
    return redirect(url_for("views.admin_dilemmas", unit_key=unit_key))


@bp.route("/exercises/<int:eid>")
def exercise_detail(eid):
    user = get_current_user_optional()
    if not user:
        return redirect(f"/login?next=/exercises/{eid}")
    from flask import g
    db = g.db
    ex = (
        db.query(Exercise)
        .options(
            joinedload(Exercise.objectives),
        )
        .filter(Exercise.id == eid)
        .first()
    )
    if not ex:
        abort(404)
    return render_template(
        "exercise_detail.html",
        **_ctx(
            user,
            ex=ex,
            can_plan=can_plan_exercises(user),
            can_ref=can_edit_references(user),
        ),
    )


@bp.route("/library", methods=["GET", "POST"])
def library():
    user = get_current_user_optional()
    if not user:
        return redirect("/login?next=/library")
    if request.method == "POST":
        if not can_edit_references(user):
            abort(403)
        from flask import g
        db = g.db
        r = Reference(
            title=(request.form.get("title") or "").strip() or "مرجع",
            ref_type=request.form.get("ref_type") or "standard",
            standard_code=(request.form.get("standard_code") or "").strip(),
            body=(request.form.get("body") or "").strip(),
            url=(request.form.get("url") or "").strip(),
            created_by_id=user.id,
        )
        db.add(r)
        db.commit()
        return redirect("/library")
    from flask import g
    refs = g.db.query(Reference).order_by(Reference.id.desc()).all()
    return render_template(
        "library.html",
        **_ctx(user, references=refs, can_edit=can_edit_references(user), RefType=RefType),
    )


@bp.route("/admin/users", methods=["GET", "POST"])
def admin_users():
    user = get_current_user_optional()
    if not user or not can_manage_users(user):
        abort(403)
    from flask import g
    db = g.db
    if request.method == "POST":
        rk = (request.form.get("role_key") or "judge").strip()
        if not any(rk == m.value for m in RoleKey):
            rk = RoleKey.JUDGE.value
        if rk == RoleKey.STANDARDS_LIBRARY.value:
            rk = RoleKey.JUDGE.value
        username = (request.form.get("username") or "").strip() or f"u{user.id}-new"
        # الافتراضي: demo123، أما المحكم فمطلوب (username=password=الرقم العسكري)
        temp_pwd = (request.form.get("temp_password") or "").strip()
        if not temp_pwd:
            temp_pwd = username if rk == RoleKey.JUDGE.value else "demo123"
        u = User(
            username=username,
            full_name=(request.form.get("full_name") or "").strip(),
            role_key=rk,
            password_hash=hash_password(temp_pwd),
        )
        db.add(u)
        db.commit()
        # ربط المحكم بمتدرب (اختياري) ضمن التمرين الحالي
        if rk == RoleKey.JUDGE.value:
            ex = _admin_current_workspace_exercise(db, user)
            trainee_row_id_raw = (request.form.get("trainee_row_id") or "").strip()
            if ex is not None and trainee_row_id_raw.isdigit():
                tr = db.get(ExerciseRosterRow, int(trainee_row_id_raw))
                if (
                    tr is not None
                    and tr.exercise_id == ex.id
                    and (tr.roster_kind or "") == ExerciseRosterKind.TRAINEE.value
                    and (tr.unit_level_key or "").strip()
                ):
                    db.add(
                        JudgeTraineeAssignment(
                            exercise_id=ex.id,
                            judge_user_id=u.id,
                            unit_level_key=(tr.unit_level_key or "").strip(),
                            trainee_name=(tr.full_name or "").strip(),
                            trainee_military_number=(tr.military_number or "").strip(),
                        )
                    )
                    db.commit()
        return redirect("/admin/users")
    us = db.query(User).order_by(User.id).all()
    rdefs = {r.role_key: r for r in db.query(RoleDef).all()}
    role_choices = [
        {
            "value": m.value,
            "label": rdefs[m.value].title_ar if m.value in rdefs else m.value,
        }
        for m in RoleKey
        if m != RoleKey.STANDARDS_LIBRARY
    ]
    ex = _admin_current_workspace_exercise(db, user)
    trainee_choices: list[dict] = []
    if ex is not None:
        trs = (
            db.query(ExerciseRosterRow)
            .filter(
                ExerciseRosterRow.exercise_id == ex.id,
                ExerciseRosterRow.roster_kind == ExerciseRosterKind.TRAINEE.value,
            )
            .order_by(ExerciseRosterRow.sort_order, ExerciseRosterRow.id)
            .all()
        )
        for tr in trs:
            uk = (tr.unit_level_key or "").strip()
            trainee_choices.append(
                {
                    "id": int(tr.id),
                    "label": f"{(tr.full_name or '').strip() or 'متدرب'} — {(tr.military_number or '').strip() or '—'} — {label_for_unit_level_key(uk) or uk or '—'}",
                }
            )
    return render_template(
        "admin_users.html",
        **_ctx(
            user,
            users=us,
            rdefs=rdefs,
            role_choices=role_choices,
            has_exercise=ex is not None,
            trainee_choices=trainee_choices,
        ),
    )


@bp.route("/admin/users/<int:uid>/edit", methods=["GET", "POST"])
def admin_user_edit(uid: int):
    user = get_current_user_optional()
    if not user or not can_manage_users(user):
        abort(403)
    from flask import g

    db = g.db
    target = db.query(User).filter(User.id == uid).first()
    if not target:
        abort(404)

    rdefs = {r.role_key: r for r in db.query(RoleDef).all()}
    role_choices = [
        {
            "value": m.value,
            "label": rdefs[m.value].title_ar if m.value in rdefs else m.value,
        }
        for m in RoleKey
        if m != RoleKey.STANDARDS_LIBRARY
    ]

    ex = _admin_current_workspace_exercise(db, user)
    existing_assignment = None
    trainee_choices: list[dict] = []
    if ex is not None:
        existing_assignment = (
            db.query(JudgeTraineeAssignment)
            .filter(
                JudgeTraineeAssignment.exercise_id == ex.id,
                JudgeTraineeAssignment.judge_user_id == target.id,
            )
            .first()
        )
        trs = (
            db.query(ExerciseRosterRow)
            .filter(
                ExerciseRosterRow.exercise_id == ex.id,
                ExerciseRosterRow.roster_kind == ExerciseRosterKind.TRAINEE.value,
            )
            .order_by(ExerciseRosterRow.sort_order, ExerciseRosterRow.id)
            .all()
        )
        for tr in trs:
            uk = (tr.unit_level_key or "").strip()
            trainee_choices.append(
                {
                    "id": int(tr.id),
                    "label": f"{(tr.full_name or '').strip() or 'متدرب'} — {(tr.military_number or '').strip() or '—'} — {label_for_unit_level_key(uk) or uk or '—'}",
                    "unit_key": uk,
                }
            )

    if request.method == "GET":
        return render_template(
            "admin_user_edit.html",
            **_ctx(
                user,
                target=target,
                role_choices=role_choices,
                error="",
                has_exercise=ex is not None,
                trainee_choices=trainee_choices,
                assignment=existing_assignment,
            ),
        )

    # POST: update
    full_name = (request.form.get("full_name") or "").strip()
    rk = (request.form.get("role_key") or target.role_key or RoleKey.JUDGE.value).strip()
    if not any(rk == m.value for m in RoleKey):
        rk = RoleKey.JUDGE.value
    if rk == RoleKey.STANDARDS_LIBRARY.value:
        rk = RoleKey.JUDGE.value

    is_active = (request.form.get("is_active") or "").strip() in ("1", "true", "on", "yes")
    temp_pwd = (request.form.get("temp_password") or "").strip()

    target.full_name = full_name
    target.role_key = rk
    target.is_active = is_active
    if temp_pwd:
        target.password_hash = hash_password(temp_pwd)
    db.add(target)
    db.commit()
    # تحديث تخصيص المحكم (ضمن التمرين الحالي) إن كانت الصلاحية محكم
    if ex is not None and rk == RoleKey.JUDGE.value:
        trainee_row_id_raw = (request.form.get("trainee_row_id") or "").strip()
        # حذف أي تخصيص سابق
        db.execute(
            delete(JudgeTraineeAssignment).where(
                JudgeTraineeAssignment.exercise_id == ex.id,
                JudgeTraineeAssignment.judge_user_id == target.id,
            )
        )
        db.commit()
        if trainee_row_id_raw.isdigit():
            tr = db.get(ExerciseRosterRow, int(trainee_row_id_raw))
            if (
                tr is not None
                and tr.exercise_id == ex.id
                and (tr.roster_kind or "") == ExerciseRosterKind.TRAINEE.value
                and (tr.unit_level_key or "").strip()
            ):
                db.add(
                    JudgeTraineeAssignment(
                        exercise_id=ex.id,
                        judge_user_id=target.id,
                        unit_level_key=(tr.unit_level_key or "").strip(),
                        trainee_name=(tr.full_name or "").strip(),
                        trainee_military_number=(tr.military_number or "").strip(),
                    )
                )
                db.commit()
    return redirect("/admin/users")


@bp.route("/admin/users/<int:uid>/delete", methods=["POST"])
def admin_user_delete(uid: int):
    user = get_current_user_optional()
    if not user or not can_manage_users(user):
        abort(403)
    if getattr(user, "id", None) == uid:
        abort(400)
    from flask import g

    db = g.db
    target = db.query(User).filter(User.id == uid).first()
    if not target:
        abort(404)
    # "حذف" آمن: تعطيل الحساب
    target.is_active = False
    db.add(target)
    db.commit()
    return redirect("/admin/users")


@bp.route("/api/admin/generate-username", methods=["POST"])
def api_admin_generate_username():
    user = get_current_user_optional()
    if not user or not can_manage_users(user):
        return jsonify({"ok": False, "error": "forbidden"}), 403
    from flask import g

    db = g.db
    rk = (request.form.get("role_key") or "").strip()
    if not any(rk == m.value for m in RoleKey):
        rk = ""

    prefix_map = {
        RoleKey.SYSTEM_ADMIN.value: "admin",
        RoleKey.ANALYST.value: "analyst",
        RoleKey.PLANNER.value: "planner",
        RoleKey.JUDGE.value: "judge",
        RoleKey.CONTROL.value: "control",
    }
    prefix = prefix_map.get(rk, "user")

    # توليد اسم فريد: prefix + رقم متسلسل
    for i in range(1, 5000):
        cand = f"{prefix}{i:03d}"
        if not db.query(User).filter(User.username == cand).first():
            return jsonify({"ok": True, "username": cand})

    # احتياط: في حال امتلاء النطاق
    cand = f"{prefix}-{uuid.uuid4().hex[:6]}"
    return jsonify({"ok": True, "username": cand})


@bp.route("/api/admin/generate-usernames-batch", methods=["POST"])
def api_admin_generate_usernames_batch():
    user = get_current_user_optional()
    if not user or not can_manage_users(user):
        return jsonify({"ok": False, "error": "forbidden"}), 403
    from flask import g

    db = g.db
    prefix_map = {
        RoleKey.SYSTEM_ADMIN.value: "admin",
        RoleKey.ANALYST.value: "analyst",
        RoleKey.PLANNER.value: "planner",
        RoleKey.JUDGE.value: "judge",
        RoleKey.CONTROL.value: "control",
    }

    f = request.files.get("names_file")
    if not f:
        return jsonify({"ok": False, "error": "missing_file"}), 400
    try:
        data = f.read()
    except Exception:
        data = b""
    if not data:
        return jsonify({"ok": False, "error": "empty_file"}), 400

    def _norm(s: str) -> str:
        return (
            (s or "")
            .replace("\u200f", "")
            .replace("\u200e", "")
            .replace("ـ", "")
            .strip()
            .casefold()
        )

    # خريطة أدوار عربية/مفاتيح إلى RoleKey.value
    rdefs = {r.role_key: r for r in db.query(RoleDef).all()}
    title_to_role = {_norm(r.title_ar): r.role_key for r in rdefs.values() if r.title_ar}
    # مرادفات شائعة
    title_to_role.update(
        {
            _norm("إدارة النظام"): RoleKey.SYSTEM_ADMIN.value,
            _norm("المحللين"): RoleKey.ANALYST.value,
            _norm("المحلّلون"): RoleKey.ANALYST.value,
            _norm("المحللون"): RoleKey.ANALYST.value,
            _norm("التخطيط"): RoleKey.PLANNER.value,
            _norm("المحكمين"): RoleKey.JUDGE.value,
            _norm("المحكّمون"): RoleKey.JUDGE.value,
            _norm("المحكمون"): RoleKey.JUDGE.value,
            _norm("السيطرة"): RoleKey.CONTROL.value,
        }
    )

    def _resolve_role(raw: str) -> str:
        r = (raw or "").strip()
        if not r:
            return ""
        if any(r == m.value for m in RoleKey):
            return r
        k = _norm(r)
        return title_to_role.get(k, "")

    def _parse_records_from_bytes(filename_lower: str, blob: bytes) -> list[tuple[str, str]]:
        # returns (name, role_raw)
        if filename_lower.endswith(".xlsx"):
            try:
                from io import BytesIO
                from openpyxl import load_workbook

                wb = load_workbook(BytesIO(blob), data_only=True)
                ws = wb[wb.sheetnames[0]]
                rows = list(ws.iter_rows(values_only=True))
                if not rows:
                    return []
                # محاولة إيجاد رأس أعمدة: الاسم + الدور/الوظيفة
                name_idx = role_idx = None
                for ridx, row in enumerate(rows[:10]):
                    vals = [str(c).strip() if c is not None else "" for c in row]
                    for i, v in enumerate(vals):
                        nv = _norm(v)
                        if name_idx is None and ("الاسم" in nv or "name" in nv):
                            name_idx = i
                        if role_idx is None and ("الدور" in nv or "الوظيفة" in nv or "role" in nv):
                            role_idx = i
                    if name_idx is not None:
                        start = ridx + 1
                        break
                else:
                    start = 0
                out: list[tuple[str, str]] = []
                for row in rows[start:]:
                    vals = [str(c).strip() if c is not None else "" for c in row]
                    name = vals[name_idx] if name_idx is not None and name_idx < len(vals) else ""
                    role = vals[role_idx] if role_idx is not None and role_idx < len(vals) else ""
                    name = name.strip()
                    role = role.strip()
                    if not name:
                        continue
                    out.append((name, role))
                return out
            except Exception:
                return []

        text = blob.decode("utf-8", errors="ignore")
        out: list[tuple[str, str]] = []
        for line in text.splitlines():
            s = line.strip()
            if not s:
                continue
            # CSV/TSV/pipe: الاسم,الدور
            for sep in ("\t", "|", ";", ","):
                if sep in s:
                    parts = [p.strip() for p in s.split(sep) if p.strip()]
                    if len(parts) >= 2:
                        out.append((parts[0], parts[1]))
                    else:
                        out.append((parts[0], ""))
                    break
            else:
                # دعم "الاسم - الدور" أو "الاسم — الدور"
                if "—" in s:
                    parts = [p.strip() for p in s.split("—") if p.strip()]
                    out.append((parts[0], parts[1] if len(parts) > 1 else ""))
                elif "-" in s:
                    parts = [p.strip() for p in s.split("-") if p.strip()]
                    out.append((parts[0], parts[1] if len(parts) > 1 else ""))
                else:
                    out.append((s, ""))
        return out

    filename_lower = (getattr(f, "filename", "") or "").lower()
    records = _parse_records_from_bytes(filename_lower, data)

    # إزالة التكرار مع الحفاظ على الترتيب (حسب الاسم+الدور)
    seen: set[str] = set()
    items_in: list[tuple[str, str, str]] = []  # name, role_raw, role_key
    for name, role_raw in records:
        key = f"{_norm(name)}|{_norm(role_raw)}"
        if key in seen:
            continue
        seen.add(key)
        role_key = _resolve_role(role_raw)
        items_in.append((name, role_raw, role_key))
    items_in = items_in[:300]

    taken = {row[0] for row in db.query(User.username).all()}
    counters: dict[str, int] = {}

    def _next_for_prefix(prefix: str) -> str:
        start = counters.get(prefix, 1)
        i = start
        while i < 5000:
            cand = f"{prefix}{i:03d}"
            if cand not in taken:
                taken.add(cand)
                counters[prefix] = i + 1
                return cand
            i += 1
        cand = f"{prefix}-{uuid.uuid4().hex[:6]}"
        while cand in taken:
            cand = f"{prefix}-{uuid.uuid4().hex[:6]}"
        taken.add(cand)
        return cand

    def _gen_password() -> str:
        import secrets
        import string

        alphabet = string.ascii_letters + string.digits
        # استبعاد أحرف قد تسبب لبساً بصرياً
        for ch in "O0Il1":
            alphabet = alphabet.replace(ch, "")
        return "".join(secrets.choice(alphabet) for _ in range(10))

    out = []
    for name, role_raw, role_key in items_in:
        prefix = prefix_map.get(role_key, "user")
        uname = _next_for_prefix(prefix)
        role_label = rdefs[role_key].title_ar if role_key in rdefs else (role_raw or role_key or "غير محدد")
        out.append(
            {
                "name": name,
                "role": role_label,
                "username": uname,
                "temp_password": _gen_password(),
            }
        )
    return jsonify({"ok": True, "items": out})


@bp.route("/api/ai/suggest", methods=["POST"])
def api_ai_suggest():
    user = get_current_user_optional()
    if not user:
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    if not (
        can_judge_exercise(user)
        or can_plan_exercises(user)
        or is_analyst(user)
        or is_control(user)
        or is_system_admin(user)
    ):
        return jsonify({"ok": False, "error": "forbidden"}), 403
    purpose = (request.form.get("purpose") or "").strip() or "تعليمات/ملاحظات تقييم"
    context = (request.form.get("context") or "").strip()
    out = suggest_instructions_or_notes(purpose=purpose, context=context)
    return jsonify({"ok": True, "text": out})


# ——————————————————————————————————————————————————————————————
# غرف المحادثة (مرتبطة بالتمرين الحالي — إدارة النظام + الأعضاء)
# ——————————————————————————————————————————————————————————————

_CHAT_ALLOWED_SUFFIX = frozenset(
    {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".xlsx", ".xls", ".txt", ".mp4"}
)
_CHAT_MAX_UPLOAD_BYTES = 15 * 1024 * 1024

_CHAT_KIND_LABELS_AR: dict[str, str] = {
    ChatRoomKind.JUDGE_BRIGADE: "محكمي اللواء",
    ChatRoomKind.JUDGE_BN: "محكمي الكتيبة",
    ChatRoomKind.CONTROL: "هيئة السيطرة",
    ChatRoomKind.ADMIN_SUPPORT: "إدارة النظام والدعم الفني",
    ChatRoomKind.CUSTOM: "مخصصة",
}


def _chat_workspace_exercise(db, user: User) -> Exercise | None:
    if is_system_admin(user):
        return _admin_current_workspace_exercise(db, user)
    return _current_workspace_exercise(db, user)


def _chat_member_ids(db, room_id: int) -> set[int]:
    rows = db.query(ChatRoomMember.user_id).filter(ChatRoomMember.room_id == room_id).all()
    return {int(r[0]) for r in rows}


def _chat_user_can_access_room(db, user: User, room: ChatRoom) -> bool:
    if not user or room is None:
        return False
    ex = _chat_workspace_exercise(db, user)
    if ex is None or int(room.exercise_id) != int(ex.id):
        return False
    if is_system_admin(user):
        return True
    return int(user.id) in _chat_member_ids(db, int(room.id))


def _chat_file_disk_path(exercise_id: int, room_id: int, relpath: str) -> Path | None:
    if not relpath or ".." in relpath.replace("\\", "/"):
        return None
    root = CHAT_UPLOAD_DIR.resolve()
    expected_prefix = f"{int(exercise_id)}/{int(room_id)}/"
    norm = relpath.replace("\\", "/").strip().lstrip("/")
    if not norm.startswith(expected_prefix):
        return None
    out = (root / norm).resolve()
    try:
        out.relative_to(root)
    except ValueError:
        return None
    return out if out.is_file() else None


def _chat_touch_room_activity(db, room: ChatRoom) -> None:
    room.last_activity_at = datetime.utcnow()


def _chat_mark_messages_read(db, user: User, room_id: int) -> None:
    mids = [
        int(m[0])
        for m in db.query(ChatMessage.id)
        .filter(ChatMessage.room_id == room_id, ChatMessage.sender_id != int(user.id))
        .all()
    ]
    for mid in mids:
        exists = (
            db.query(ChatMessageRead)
            .filter(ChatMessageRead.message_id == mid, ChatMessageRead.user_id == int(user.id))
            .first()
        )
        if exists is None:
            db.add(ChatMessageRead(message_id=mid, user_id=int(user.id)))
    db.commit()


@bp.route("/chat-rooms", methods=["GET"])
def chat_rooms_list():
    user = get_current_user_optional()
    if not user:
        return redirect("/login?next=/chat-rooms")
    if not can_use_chat_rooms(user):
        abort(403)
    from flask import g

    db = g.db
    ex = _chat_workspace_exercise(db, user)
    rooms: list[ChatRoom] = []
    if ex is not None:
        if is_system_admin(user):
            rooms = (
                db.query(ChatRoom)
                .filter(ChatRoom.exercise_id == ex.id, ChatRoom.is_archived == False)
                .order_by(desc(ChatRoom.last_activity_at), desc(ChatRoom.id))
                .all()
            )
        else:
            rooms = (
                db.query(ChatRoom)
                .join(ChatRoomMember, ChatRoomMember.room_id == ChatRoom.id)
                .filter(
                    ChatRoom.exercise_id == ex.id,
                    ChatRoom.is_archived == False,
                    ChatRoomMember.user_id == int(user.id),
                )
                .order_by(desc(ChatRoom.last_activity_at), desc(ChatRoom.id))
                .all()
            )
    room_cards = []
    for r in rooms:
        uk = (r.unit_level_key or "").strip()
        room_cards.append(
            {
                "room": r,
                "unit_label": label_for_unit_level_key(uk) if uk else "",
                "kind_label": _CHAT_KIND_LABELS_AR.get((r.room_kind or "").strip(), (r.room_kind or "مخصصة")),
            }
        )
    return render_template(
        "chat_rooms_list.html",
        **_ctx(
            user,
            has_exercise=ex is not None,
            exercise=ex,
            room_cards=room_cards,
            can_manage=can_manage_chat_rooms(user),
        ),
    )


@bp.route("/chat-rooms/<int:room_id>", methods=["GET"])
def chat_room_detail(room_id: int):
    user = get_current_user_optional()
    if not user:
        return redirect(f"/login?next=/chat-rooms/{room_id}")
    if not can_use_chat_rooms(user):
        abort(403)
    from flask import g

    db = g.db
    room = db.get(ChatRoom, room_id)
    if room is None or room.is_archived:
        abort(404)
    if not _chat_user_can_access_room(db, user, room):
        abort(403)
    _chat_mark_messages_read(db, user, room_id)

    msgs = (
        db.query(ChatMessage)
        .filter(ChatMessage.room_id == room_id)
        .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
        .limit(500)
        .all()
    )
    member_ids = _chat_member_ids(db, room_id)
    uids = member_ids | {int(m.sender_id) for m in msgs}
    users_by_id: dict[int, User] = {}
    if uids:
        for u in db.query(User).filter(User.id.in_(uids)).all():
            users_by_id[int(u.id)] = u

    message_rows: list[dict] = []
    for m in msgs:
        reads = (
            db.query(ChatMessageRead)
            .filter(ChatMessageRead.message_id == m.id)
            .order_by(ChatMessageRead.read_at.asc())
            .all()
        )
        reader_ids = {int(r.user_id) for r in reads}
        others = {uid for uid in member_ids if uid != int(m.sender_id)}
        n_others = len(others)
        read_by_others = len(reader_ids & others)
        tick_level = "read" if n_others > 0 and read_by_others >= n_others else ("delivered" if read_by_others > 0 else "sent")
        sender = users_by_id.get(int(m.sender_id))
        sender_label = (
            (getattr(sender, "full_name", "") or "").strip()
            or (getattr(sender, "username", "") or "").strip()
            or f"مستخدم #{m.sender_id}"
        )
        reader_names = []
        for r in reads:
            if int(r.user_id) == int(m.sender_id):
                continue
            ru = users_by_id.get(int(r.user_id))
            reader_names.append(
                (getattr(ru, "full_name", "") or "").strip()
                or (getattr(ru, "username", "") or "").strip()
                or f"#{r.user_id}"
            )
        message_rows.append(
            {
                "msg": m,
                "sender_label": sender_label,
                "is_mine": int(m.sender_id) == int(user.id),
                "tick_level": tick_level,
                "reader_names": reader_names,
            }
        )

    ex = _chat_workspace_exercise(db, user)
    return render_template(
        "chat_room_detail.html",
        **_ctx(
            user,
            room=room,
            exercise=ex,
            message_rows=message_rows,
            can_manage=can_manage_chat_rooms(user),
        ),
    )


@bp.route("/chat-rooms/<int:room_id>/message", methods=["POST"])
def chat_room_post_message(room_id: int):
    user = get_current_user_optional()
    if not user:
        abort(403)
    if not can_use_chat_rooms(user):
        abort(403)
    from flask import g

    db = g.db
    room = db.get(ChatRoom, room_id)
    if room is None or room.is_archived or not _chat_user_can_access_room(db, user, room):
        abort(404)
    body = (request.form.get("body") or "").strip()
    if not body or len(body) > 8000:
        return redirect(url_for("views.chat_room_detail", room_id=room_id))
    m = ChatMessage(
        room_id=room.id,
        sender_id=int(user.id),
        message_type="text",
        body_text=body,
    )
    db.add(m)
    _chat_touch_room_activity(db, room)
    from app.notifications_service import notify_chat_new_message

    notify_chat_new_message(db, room=room, message=m, sender_id=int(user.id))
    db.commit()
    return redirect(url_for("views.chat_room_detail", room_id=room_id))


@bp.route("/chat-rooms/<int:room_id>/upload", methods=["POST"])
def chat_room_upload(room_id: int):
    user = get_current_user_optional()
    if not user:
        abort(403)
    if not can_use_chat_rooms(user):
        abort(403)
    from flask import g

    db = g.db
    room = db.get(ChatRoom, room_id)
    if room is None or room.is_archived or not _chat_user_can_access_room(db, user, room):
        abort(404)
    f = request.files.get("file")
    if not f or not (f.filename or "").strip():
        return redirect(url_for("views.chat_room_detail", room_id=room_id))
    raw_name = secure_filename(f.filename)
    suf = Path(raw_name).suffix.lower()
    if suf not in _CHAT_ALLOWED_SUFFIX:
        return redirect(url_for("views.chat_room_detail", room_id=room_id))
    data = f.read()
    if len(data) > _CHAT_MAX_UPLOAD_BYTES:
        return redirect(url_for("views.chat_room_detail", room_id=room_id))
    CHAT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    sub = CHAT_UPLOAD_DIR / str(int(room.exercise_id)) / str(int(room.id))
    sub.mkdir(parents=True, exist_ok=True)
    store_name = f"{uuid.uuid4().hex}{suf}"
    disk_path = sub / store_name
    disk_path.write_bytes(data)
    rel = f"{int(room.exercise_id)}/{int(room.id)}/{store_name}"
    mime = mimetypes.guess_type(raw_name)[0] or "application/octet-stream"
    m = ChatMessage(
        room_id=room.id,
        sender_id=int(user.id),
        message_type="file",
        body_text="",
        file_relpath=rel,
        original_filename=(f.filename or store_name)[:500],
        mime_type=(mime or "")[:200],
        file_size=len(data),
    )
    db.add(m)
    _chat_touch_room_activity(db, room)
    from app.notifications_service import notify_chat_new_message

    notify_chat_new_message(db, room=room, message=m, sender_id=int(user.id))
    db.commit()
    return redirect(url_for("views.chat_room_detail", room_id=room_id))


@bp.route("/chat-rooms/<int:room_id>/files/<int:message_id>", methods=["GET"])
def chat_room_download(room_id: int, message_id: int):
    user = get_current_user_optional()
    if not user:
        return redirect(f"/login?next=/chat-rooms/{room_id}/files/{message_id}")
    if not can_use_chat_rooms(user):
        abort(403)
    from flask import g

    db = g.db
    room = db.get(ChatRoom, room_id)
    msg = db.get(ChatMessage, message_id)
    if room is None or msg is None or int(msg.room_id) != int(room.id):
        abort(404)
    if not _chat_user_can_access_room(db, user, room):
        abort(404)
    if (msg.message_type or "") != "file" or not (msg.file_relpath or "").strip():
        abort(404)
    path = _chat_file_disk_path(int(room.exercise_id), int(room.id), msg.file_relpath)
    if path is None:
        abort(404)
    return send_file(
        path,
        as_attachment=True,
        download_name=(msg.original_filename or path.name)[:200],
        mimetype=(msg.mime_type or None) or "application/octet-stream",
    )


@bp.route("/admin/chat-rooms", methods=["GET", "POST"])
def admin_chat_rooms():
    user = get_current_user_optional()
    if not user or not can_manage_chat_rooms(user):
        abort(403)
    from flask import g

    db = g.db
    ex = _admin_current_workspace_exercise(db, user)
    err = ""
    ok_msg = ""
    if request.method == "POST":
        act = (request.form.get("action") or "").strip()
        if ex is None:
            err = "لا يوجد تمرين حالي لإدارة الغرف."
        elif act == "create_room":
            title = (request.form.get("title") or "").strip()[:500]
            rk = (request.form.get("room_kind") or ChatRoomKind.CUSTOM).strip()
            if rk not in _CHAT_KIND_LABELS_AR:
                rk = ChatRoomKind.CUSTOM
            uk = normalize_unit_level_key(request.form.get("unit_level_key") or "")
            if not title:
                err = "أدخل عنواناً للغرفة."
            else:
                room = ChatRoom(
                    exercise_id=ex.id,
                    title=title,
                    room_kind=rk,
                    unit_level_key=uk,
                    created_by_id=int(user.id),
                    last_activity_at=datetime.utcnow(),
                )
                db.add(room)
                db.flush()
                db.add(
                    ChatRoomMember(
                        room_id=room.id,
                        user_id=int(user.id),
                        role_in_room="moderator",
                    )
                )
                db.commit()
                ok_msg = "تم إنشاء الغرفة وإضافتك كمشرف."
        elif act == "add_member" and (request.form.get("room_id") or "").strip().isdigit():
            rid = int(request.form.get("room_id"))
            uid_raw = (request.form.get("user_id") or "").strip()
            room = db.get(ChatRoom, rid)
            if room is None or int(room.exercise_id) != int(ex.id):
                err = "غرفة غير صالحة."
            elif not uid_raw.isdigit():
                err = "اختر مستخدماً."
            else:
                uid = int(uid_raw)
                exists = (
                    db.query(ChatRoomMember)
                    .filter(ChatRoomMember.room_id == rid, ChatRoomMember.user_id == uid)
                    .first()
                )
                if exists is None:
                    db.add(ChatRoomMember(room_id=rid, user_id=uid, role_in_room="member"))
                    db.commit()
                    ok_msg = "تمت إضافة العضو."
                else:
                    err = "المستخدم عضو مسبقاً."
        elif act == "remove_member" and (request.form.get("room_id") or "").strip().isdigit():
            rid = int(request.form.get("room_id"))
            uid_raw = (request.form.get("user_id") or "").strip()
            room = db.get(ChatRoom, rid)
            if room is None or int(room.exercise_id) != int(ex.id):
                err = "غرفة غير صالحة."
            elif not uid_raw.isdigit():
                err = "معرّف مستخدم غير صالح."
            else:
                uid = int(uid_raw)
                if uid == int(user.id):
                    err = "لا يمكنك إزالة نفسك بهذه الطريقة."
                else:
                    db.query(ChatRoomMember).filter(
                        ChatRoomMember.room_id == rid, ChatRoomMember.user_id == uid
                    ).delete(synchronize_session=False)
                    db.commit()
                    ok_msg = "تمت إزالة العضو."

    rooms: list[ChatRoom] = []
    all_users: list[User] = []
    if ex is not None:
        rooms = (
            db.query(ChatRoom)
            .filter(ChatRoom.exercise_id == ex.id)
            .order_by(desc(ChatRoom.last_activity_at), desc(ChatRoom.id))
            .all()
        )
        all_users = db.query(User).order_by(User.id.asc()).limit(400).all()

    room_admin_rows: list[dict] = []
    for r in rooms:
        members = (
            db.query(ChatRoomMember)
            .filter(ChatRoomMember.room_id == r.id)
            .order_by(ChatRoomMember.joined_at.asc())
            .all()
        )
        mrows = []
        for mm in members:
            u = db.get(User, mm.user_id)
            mrows.append(
                {
                    "member": mm,
                    "user_label": (
                        (getattr(u, "full_name", "") or "").strip()
                        or (getattr(u, "username", "") or "").strip()
                        or f"#{mm.user_id}"
                    ),
                }
            )
        uk = (r.unit_level_key or "").strip()
        room_admin_rows.append(
            {
                "room": r,
                "kind_label": _CHAT_KIND_LABELS_AR.get((r.room_kind or "").strip(), r.room_kind or "—"),
                "unit_label": label_for_unit_level_key(uk) if uk else "—",
                "members": mrows,
            }
        )

    return render_template(
        "admin_chat_rooms.html",
        **_ctx(
            user,
            has_exercise=ex is not None,
            exercise=ex,
            error=err,
            ok_msg=ok_msg,
            room_kind_options=_CHAT_KIND_LABELS_AR,
            unit_levels=UNIT_LEVELS,
            room_admin_rows=room_admin_rows,
            all_users=all_users,
        ),
    )
