import hashlib
import io
import json
import mimetypes
import re
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
from sqlalchemy import case, delete, desc, func
from sqlalchemy.orm import joinedload

from app.config import (
    CHAT_UPLOAD_DIR,
    DILEMMA_PDF_DIR,
    EVALUATION_LIST_XLSX_DIR,
    INFO_BANK_DIR,
    PLANNER_FLOW_BUNDLE_DIR,
    VISUAL_DOC_DIR,
)
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
    ExercisePlannerFlowBundle,
    ExercisePlannerFlowBundleEventFlow,
    ExercisePlannerFlowBundleActionEval,
    PlannerFlowBundleEvalSavedResult,
    ExerciseStatus,
    DilemmaItem,
    EvaluationCriterionMedia,
    EvaluationListPdfItem,
    EvaluationListSavedResult,
    AnalystEvaluationCriteriaResult,
    AnalystEvaluationCriteriaUnit,
    AnalystEvaluationCriteriaPhaseItem,
    AnalystFinalEvaluationAllocatedMax,
    AnalystFinalEvaluationPhaseAllocatedMax,
    ExerciseNotification,
    VisualDocument,
    InformationBankPhaseNote,
    InformationBankUnitNote,
    InformationBankTrainingPhase,
    InformationBankUnitLevel,
    InformationBankTreeNode,
    InfoBankEventFlowPdf,
    InfoBankActionEvalXlsx,
    InfoBankDilemmaEvalXlsx,
    JudgeTraineeAssignment,
    Reference,
    RefType,
    RoleDef,
    RoleKey,
    User,
)
from app.eval_criterion_media import (
    criterion_media_absolute_path,
    group_media_rows,
    persist_criterion_medium,
)
from app.evaluation_workflow import (
    apply_chief_approve,
    apply_chief_reopen,
    apply_judge_save_after_reopen,
    apply_judge_approve,
    build_evaluation_list_row,
    evaluation_unit_home_rows,
    build_evaluation_list_row,
    evaluation_unit_home_totals,
    eval_chief_approved,
    eval_chief_can_approve,
    eval_chief_can_reopen,
    eval_control_approved,
    eval_judge_approved,
    eval_judge_can_approve,
    eval_judge_can_edit,
    eval_reopened_for_judge,
    eval_workflow_label_ar,
)
from app.permissions import (
    can_access_analyst_hub,
    can_access_chief_judge_hub,
    can_access_control_hub,
    can_access_judge_hub,
    can_access_planner_hub,
    can_approve_evaluation_results,
    can_chief_approve_evaluation_results,
    can_chief_reopen_evaluation_for_judge,
    can_edit_references,
    can_judge_exercise,
    can_manage_chat_rooms,
    can_manage_information_bank,
    can_oversee_judge_planner_flow_materials,
    can_manage_users,
    can_plan_exercises,
    can_save_evaluation_results,
    can_use_chat_rooms,
    can_view_information_bank,
    can_view_notifications_log,
    can_use_visual_documentation,
    is_analyst,
    is_chief_judge,
    is_control,
    is_judge,
    is_planner,
    is_system_admin,
)
from app import exercise_options as ex_opts
from app.exercise_phase_catalog import (
    DEFAULT_EXERCISE_PHASE,
    EXERCISE_PHASE_OPTIONS,
    exercise_phase_keys,
    exercise_phase_label,
    normalize_exercise_phase,
)
from app.unit_levels_catalog import (
    UNIT_LEVELS,
    coerce_roster_import_position_cell,
    label_for_unit_level_key,
    normalize_unit_level_key,
)
from app.information_bank_catalog import (
    INFO_BANK_UNIT_LEVELS,
    TRAINING_PHASES,
    info_bank_unit_label,
    training_phase_label,
)
from app.evaluation_list_columns import (
    acquired_select_options,
    grade_label_from_percent,
    parse_max_cell,
)
from app.evaluation_sheet_parser import read_evaluation_list_sheet
from app.roster_import import parse_roster_rows_from_upload
from app.exercise_store import (
    archive_and_clear_current_exercise,
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
    from app.evaluation_element_display import enrich_eval_rows_element_styles

    sheet = read_evaluation_list_sheet(fspath)
    es = bool(sheet.get("eval_structured"))
    raw_eval = sheet.get("eval_rows") or []
    eval_rows = enrich_eval_rows_element_styles(raw_eval) if es else raw_eval
    return {
        "preview_error": sheet.get("error"),
        "sheet_title": sheet.get("sheet_title") or "",
        "header_row": sheet.get("header_row") or [],
        "body_rows": sheet.get("body_rows") or [],
        "eval_structured": es,
        "eval_column_source": sheet.get("eval_column_source"),
        "eval_rows": eval_rows,
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


def _is_docx_bytes(data: bytes) -> bool:
    """Word .docx — أرشيف ZIP يحتوي مجلد word/."""
    if not data or len(data) < 64:
        return False
    if data[:2] != b"PK":
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            return any(n.startswith("word/") for n in z.namelist())
    except zipfile.BadZipFile:
        return False


def _is_doc_bytes(data: bytes) -> bool:
    """Word .doc — مركب OLE (CF)."""
    if not data or len(data) < 512:
        return False
    return data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _info_bank_event_flow_sniff_ext(data: bytes) -> str | None:
    """يحدد امتداد الحفظ الآمن (.pdf / .docx / .doc) من محتوى الملف."""
    if _is_pdf_bytes(data):
        return ".pdf"
    if _is_docx_bytes(data):
        return ".docx"
    if _is_doc_bytes(data):
        return ".doc"
    return None


def _mimetype_info_bank_event_flow(path: Path) -> str:
    n = path.name.lower()
    if n.endswith(".pdf"):
        return "application/pdf"
    if n.endswith(".docx"):
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if n.endswith(".doc"):
        return "application/msword"
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


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


_INFO_BANK_KIND_DIRS = {"event_flow": "event_flow", "action_eval": "action_eval", "dilemma_eval": "dilemma_eval"}


def _info_bank_file_abspath(kind: str, relpath: str) -> Path | None:
    if kind not in _INFO_BANK_KIND_DIRS:
        return None
    if not relpath or not isinstance(relpath, str):
        return None
    norm = relpath.replace("\\", "/").strip()
    if not norm or any(part == ".." for part in norm.split("/")):
        return None
    root = INFO_BANK_DIR.resolve()
    out = (root / norm).resolve()
    try:
        out.relative_to(root)
    except ValueError:
        return None
    return out if out.is_file() else None


def _unlink_info_bank_file(kind: str, relpath: str) -> None:
    p = _info_bank_file_abspath(kind, relpath)
    if p is None:
        return
    try:
        p.unlink()
    except OSError:
        pass


def _mimetype_for_eval_list_file(path: Path) -> str:
    n = path.name.lower()
    if n.endswith(".xlsx"):
        return (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    if n.endswith(".pdf"):
        return "application/pdf"
    return "application/octet-stream"


def _planner_flow_bundle_root() -> Path:
    PLANNER_FLOW_BUNDLE_DIR.mkdir(parents=True, exist_ok=True)
    return PLANNER_FLOW_BUNDLE_DIR.resolve()


def _planner_bundle_file_abspath(relpath: str | None) -> Path | None:
    if not relpath or not isinstance(relpath, str):
        return None
    norm = relpath.replace("\\", "/").strip()
    if not norm or any(part == ".." for part in norm.split("/")):
        return None
    root = _planner_flow_bundle_root()
    out = (root / norm).resolve()
    try:
        out.relative_to(root)
    except ValueError:
        return None
    return out if out.is_file() else None


# عناوين ناتجة عن secure_filename لأسماء عربية/غريبة (pdf.1، xlsx_2، …)
_DEGENERATE_UPLOAD_TITLE_RE = re.compile(
    r"^(?:pdf|xlsx|excel|file)(?:[\s._-]+\d*)?$",
    re.IGNORECASE,
)


def _is_degenerate_upload_title(s: str) -> bool:
    t = (s or "").strip()
    if not t or len(t) <= 1:
        return True
    return bool(_DEGENERATE_UPLOAD_TITLE_RE.match(t))


def _planner_blob_display_filename(
    *, stored_title: str, relpath: str, fallback: str
) -> str:
    """اسم عرض مقروء: يفضّل العنوان المحفوظ إن كان معبّراً، وإلا اسم الملف من المسار النسبي."""
    rp = (relpath or "").replace("\\", "/").strip()
    base = Path(rp).name if rp else ""
    st = (stored_title or "").strip()
    if st and not _is_degenerate_upload_title(st):
        return st
    if base:
        return base
    return st or fallback


def _unlink_planner_bundle_file(relpath: str) -> None:
    p = _planner_bundle_file_abspath(relpath)
    if p is None:
        return
    try:
        p.unlink()
    except OSError:
        pass


def _sanitize_planner_bundle_orphan_event_flow(
    db, bundle: ExercisePlannerFlowBundle | None
) -> bool:
    """إزالة مسار مجرى الأحداث من السجل إذا لم يعد الملف موجوداً على القرص."""
    if bundle is None:
        return False
    rel = (bundle.event_flow_file_relpath or "").strip()
    if not rel:
        return False
    if _planner_bundle_file_abspath(rel) is not None:
        return False
    bundle.event_flow_file_relpath = ""
    bundle.event_flow_title = ""
    bundle.linked_at = None
    bundle.updated_at = datetime.utcnow()
    db.commit()
    return True


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
    return normalize_exercise_phase(val)


def _exercise_phase_order_expr(column):
    return case(
        {key: idx for idx, key in enumerate(exercise_phase_keys())},
        value=column,
        else_=len(exercise_phase_keys()),
    )


def _unit_level_order_expr(column):
    return case(
        {row["key"]: idx for idx, row in enumerate(UNIT_LEVELS)},
        value=column,
        else_=len(UNIT_LEVELS),
    )


def _can_manage_dilemma_eval_catalog(user: User) -> bool:
    return is_system_admin(user) or is_planner(user)


def _require_planner_hub_catalog_access(user: User | None) -> None:
    """رفع وإدارة ملفات المعاضل وقوائم التقييم — مساحة التخطيط فقط (مخطّط أو إدارة النظام)."""
    if not user:
        abort(403)
    if not can_access_planner_hub(user) or not _can_manage_dilemma_eval_catalog(user):
        abort(403)


def _admin_exercise_form_ctx() -> dict:
    return {
        "exercise_types": ex_opts.EXERCISE_TYPES,
        "exercise_levels": ex_opts.EXERCISE_LEVELS,
        "missions": ex_opts.MISSIONS,
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


def _clip_create_text(val: str | None, max_len: int) -> str:
    return (val or "").strip()[:max_len]


def _prefill_create_form_from_exercise(ex: Exercise) -> dict[str, str]:
    out = _empty_create_form_prefill()

    def pick(val: str, allowed: list[str]) -> str:
        v = (val or "").strip()
        return v if v in allowed else ""

    out["trained_unit"] = _clip_create_text(ex.trained_unit, 400)
    out["location_label"] = _clip_create_text(ex.location_label, 400)
    out["exercise_name"] = _clip_create_text(ex.title, 500)
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

    out["trained_unit"] = _clip_create_text(request.form.get("trained_unit"), 400)
    out["location_label"] = _clip_create_text(request.form.get("location_label"), 400)
    out["exercise_name"] = _clip_create_text(request.form.get("exercise_name"), 500)
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
    d = {
        "user": user,
        "RoleKey": RoleKey,
        "normalize_exercise_phase": _normalized_exercise_phase,
        "phase_label_ar": _phase_label_ar,
    }
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
    """أحدث نتيجة محفوظة لكل عنصر — مع تفضيل السجلات المرتبطة بالتمرين الحالي."""
    if not item_ids:
        return {}
    rows = (
        db.query(EvaluationListSavedResult)
        .filter(EvaluationListSavedResult.evaluation_item_id.in_(item_ids))
        .order_by(EvaluationListSavedResult.updated_at.desc(), EvaluationListSavedResult.id.desc())
        .all()
    )
    out: dict[int, EvaluationListSavedResult] = {}
    for r in rows:
        iid = int(r.evaluation_item_id)
        prev = out.get(iid)
        if prev is None:
            out[iid] = r
            continue
        rid = int(getattr(r, "exercise_id", 0) or 0)
        pid = int(getattr(prev, "exercise_id", 0) or 0)
        if rid == int(exercise_id) and pid != int(exercise_id):
            out[iid] = r
    return out


def _evaluation_saved_total_pct(sr: EvaluationListSavedResult | None) -> float | None:
    if sr is None:
        return None
    v = getattr(sr, "total_pct", None)
    if v is not None:
        return float(v)
    rows = _parse_saved_eval_rows(getattr(sr, "payload_json", None))
    pcts = [float(x) for x in (_eval_row_score_pct(r) for r in rows) if x is not None]
    return (sum(pcts) / len(pcts)) if pcts else None


_CONTROL_REPORT_PHASE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("preparation", "مرحلة التحضير"),
    ("opening", "مرحلة الإنفتاح"),
    ("main", "مرحلة المعركة التعرضية"),
)
_CONTROL_REPORT_PHASE_KEYS: tuple[str, ...] = tuple(pk for pk, _ in _CONTROL_REPORT_PHASE_COLUMNS)
_CONTROL_REPORT_PHASE_KEYS_SET: frozenset[str] = frozenset(_CONTROL_REPORT_PHASE_KEYS)

# مفتاح ألوان نتائج القوائم — متوافق مع grade_label_from_percent
_CONTROL_REPORT_GRADE_LEGEND: tuple[tuple[str, str, str], ...] = (
    ("راسب", "أقل من 60%", "#ef4444"),
    ("متوسط", "60% – 69%", "#f97316"),
    ("جيد", "70% – 79%", "#eab308"),
    ("جيد جدا", "80% – 89%", "#38bdf8"),
    ("ممتاز", "90% – 100%", "#22c55e"),
)


def _control_report_grade_legend() -> list[dict]:
    return [{"label": lbl, "range": rng, "color": col} for lbl, rng, col in _CONTROL_REPORT_GRADE_LEGEND]


def _control_report_dot_color(pct: float) -> str:
    p = float(pct)
    if p >= 90:
        return "#22c55e"
    if p >= 80:
        return "#38bdf8"
    if p >= 70:
        return "#eab308"
    if p >= 60:
        return "#f97316"
    return "#ef4444"


def _control_report_approval_location_ar(saved: EvaluationListSavedResult | None) -> str:
    if saved is None or not (getattr(saved, "payload_json", None) or "").strip():
        return "—"
    if eval_control_approved(saved):
        return "موقع الاعتماد: هيئة السيطرة"
    if eval_chief_approved(saved):
        return "موقع الاعتماد: كبير المحكمين"
    if eval_judge_approved(saved):
        return "موقع الاعتماد: المحكم"
    if eval_reopened_for_judge(saved):
        return "معاد للمحكم — بانتظار الاعتماد"
    return "محفوظ — بانتظار اعتماد المحكم"


def _control_build_unit_detail_rows(
    db,
    exercise_id: int,
    eval_items: list,
    saved_by_item: dict[int, EvaluationListSavedResult],
) -> list[dict]:
    """صفوف جدول أداء الوحدات التفصيلي: نقطة ملونة لكل قائمة تقييم محفوظة ضمن مرحلة."""
    phase_keys = set(_CONTROL_REPORT_PHASE_KEYS)
    dots_by_unit_phase: dict[tuple[str, str], list[dict]] = {}

    user_ids = {
        int(sr.saved_by_id)
        for sr in saved_by_item.values()
        if getattr(sr, "saved_by_id", None) is not None
    }
    users_by_id: dict[int, str] = {}
    if user_ids:
        for u in db.query(User).filter(User.id.in_(user_ids)).all():
            users_by_id[int(u.id)] = (getattr(u, "full_name", "") or "").strip() or f"مستخدم #{u.id}"

    judge_roster: dict[str, str] = {}
    for jr in (
        db.query(ExerciseRosterRow)
        .filter(
            ExerciseRosterRow.exercise_id == exercise_id,
            ExerciseRosterRow.roster_kind == ExerciseRosterKind.JUDGE.value,
        )
        .order_by(ExerciseRosterRow.sort_order, ExerciseRosterRow.id)
        .all()
    ):
        uk = (jr.unit_level_key or "").strip()
        if uk and uk not in judge_roster:
            judge_roster[uk] = (jr.full_name or "").strip() or "—"

    for it in eval_items:
        iid = int(getattr(it, "id", 0) or 0)
        sr = saved_by_item.get(iid)
        if sr is None:
            continue
        pct_f = _evaluation_saved_total_pct(sr)
        if pct_f is None:
            continue
        uk = (getattr(it, "unit_level_key", None) or "").strip()
        ph = _normalized_exercise_phase(getattr(it, "exercise_phase", None))
        if not uk or ph not in phase_keys:
            continue
        title = (getattr(it, "text", None) or "قائمة تقييم").strip()
        jid = getattr(sr, "saved_by_id", None)
        jname = users_by_id.get(int(jid)) if jid is not None else None
        if not jname:
            jname = judge_roster.get(uk, "—")
        approval_loc = _control_report_approval_location_ar(sr)
        pv = int(round(float(pct_f)))
        dot = {
            "item_id": iid,
            "unit_key": uk,
            "pct": pv,
            "color": _control_report_dot_color(pv),
            "list_title": title,
            "judge_name": jname,
            "approval_location": approval_loc,
            "view_url": url_for(
                "views.control_evaluation_list_file_viewer",
                unit_key=uk,
                item_id=iid,
            ),
        }
        dots_by_unit_phase.setdefault((uk, ph), []).append(dot)

    units_with_data: list[str] = []
    seen_uk: set[str] = set()
    for ul in UNIT_LEVELS:
        uk = (ul.get("key") or "").strip()
        if not uk or uk in seen_uk:
            continue
        if any(dots_by_unit_phase.get((uk, pk)) for pk, _ in _CONTROL_REPORT_PHASE_COLUMNS):
            units_with_data.append(uk)
            seen_uk.add(uk)
    for uk in sorted({k[0] for k in dots_by_unit_phase}):
        if uk not in seen_uk:
            units_with_data.append(uk)

    unit_rows: list[dict] = []
    for uk in units_with_data:
        phases_out = []
        for pk, plbl in _CONTROL_REPORT_PHASE_COLUMNS:
            phases_out.append(
                {
                    "key": pk,
                    "label": plbl,
                    "dots": sorted(
                        dots_by_unit_phase.get((uk, pk)) or [],
                        key=lambda d: int(d.get("item_id") or 0),
                    ),
                }
            )
        unit_rows.append(
            {
                "unit_key": uk,
                "unit_label": label_for_unit_level_key(uk) or uk,
                "phases": phases_out,
            }
        )
    return unit_rows


def _control_phase_max_dot_counts(unit_detail_rows: list[dict]) -> list[int]:
    """أقصى عدد نقاط تقييم لكل عمود مرحلة — لضبط عرض العمود في التقرير."""
    n_phases = len(_CONTROL_REPORT_PHASE_COLUMNS)
    maxes = [0] * n_phases
    for urow in unit_detail_rows:
        for i, ph in enumerate(urow.get("phases") or []):
            if i < n_phases:
                maxes[i] = max(maxes[i], len(ph.get("dots") or []))
    return [max(1, m) for m in maxes]


def _control_build_list_number_row(phase_max_dots: list[int]) -> list[dict]:
    """صف ترقيم قوائم التقييم — لكل مرحلة تسلسل مستقل يبدأ من 1."""
    out: list[dict] = []
    for max_dots in phase_max_dots:
        count = max(0, int(max_dots or 0))
        out.append({"slots": list(range(1, count + 1)), "max_dots": count})
    return out


def _control_group_label_lines(label: str) -> tuple[str, str]:
    """تقسيم اسم الوحدة لسطرين في رسم «أداء المجموعات»."""
    s = (label or "").strip() or "—"
    parts = [p.strip() for p in re.split(r"\s*/\s*", s) if p.strip()]
    if len(parts) >= 3:
        mid = (len(parts) + 1) // 2
        return (" / ".join(parts[:mid]), " / ".join(parts[mid:]))
    if len(parts) == 2:
        return (parts[0], parts[1])
    words = s.split()
    if len(words) >= 2:
        best_idx = 1
        best_diff = len(s)
        for i in range(1, len(words)):
            diff = abs(len(" ".join(words[:i])) - len(" ".join(words[i:])))
            if diff < best_diff:
                best_diff = diff
                best_idx = i
        return (" ".join(words[:best_idx]), " ".join(words[best_idx:]))
    return (s, "\u00a0")


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


def _evaluation_payload_mark_totals(rows: list) -> tuple[float, float]:
    """مجموع القصوى والمكتسبة لحمولة تقييم محفوظة، بنفس منطق حساب النسبة."""
    safe = [r for r in rows[:2000] if isinstance(r, dict)]
    if not safe:
        return 0.0, 0.0
    sum_max = 0.0
    sum_acquired = 0.0
    for r in safe:
        if str(r.get("row_kind") or "").strip().lower() == "section":
            continue
        acq = r.get("acquired")
        acq_s = ("" if acq is None else str(acq)).strip().lower()
        if acq_s == "na":
            continue
        sum_max += _eval_row_effective_max(r)
        if acq_s:
            try:
                sum_acquired += float(str(acq).replace(",", "."))
            except (TypeError, ValueError):
                pass
    return sum_max, sum_acquired


def _evaluation_list_template_rows(item) -> list[dict]:
    """صفوف قالب Excel لقائمة التقييم (كما في واجهة المحكم)."""
    relpath = (getattr(item, "pdf_relpath", None) or "").strip()
    if not relpath:
        return []
    fspath = _evaluation_list_file_abspath(relpath)
    if fspath is None:
        return []
    sheet = read_evaluation_list_sheet(fspath)
    return list(sheet.get("eval_rows") or [])


def _evaluation_list_judge_sum_totals(
    saved_rows: list | None,
    template_rows: list | None = None,
) -> tuple[float, float]:
    """
    مجموع القصوى والمكتسبة كما في صفحة المحكم (eval-sum-max / eval-sum-acquired):
    - القصوى: مجموع max_num لكل بند score من قالب Excel.
    - المكتسبة: مجموع acquired المحفوظة (أو الأولية من Excel) لكل بند غير «لا ينطبق».
    """
    saved_rows = [r for r in (saved_rows or [])[:2000] if isinstance(r, dict)]
    template_rows = [r for r in (template_rows or [])[:2000] if isinstance(r, dict)]

    def _round_mark(value: float) -> float:
        return round(float(value) * 100.0) / 100.0

    if template_rows:
        sum_max = 0.0
        sum_acquired = 0.0
        any_acquired = False
        for idx, trow in enumerate(template_rows):
            rk = str(trow.get("row_kind") or "score").strip().lower()
            if rk == "section":
                continue
            mx = trow.get("max_num")
            if mx is None:
                mx = parse_max_cell(trow.get("max_val"))
            if mx is not None and float(mx) > 0:
                sum_max += float(mx)
            saved_row = saved_rows[idx] if idx < len(saved_rows) else {}
            acq = saved_row.get("acquired") if isinstance(saved_row, dict) else None
            if acq is None or str(acq).strip() == "":
                acq = trow.get("acquired_initial")
            acq_s = ("" if acq is None else str(acq)).strip().lower()
            if acq_s and acq_s != "na":
                try:
                    sum_acquired += float(str(acq).replace(",", "."))
                    any_acquired = True
                except (TypeError, ValueError):
                    pass
        sum_max = _round_mark(sum_max) if sum_max > 0 else 0.0
        if not any_acquired:
            return sum_max, 0.0
        return sum_max, _round_mark(sum_acquired)

    sum_max = 0.0
    sum_acquired = 0.0
    any_acquired = False
    for r in saved_rows:
        if str(r.get("row_kind") or "").strip().lower() == "section":
            continue
        mx = parse_max_cell(r.get("max_val"))
        if mx is not None and mx > 0:
            sum_max += float(mx)
        acq = r.get("acquired")
        acq_s = ("" if acq is None else str(acq)).strip().lower()
        if acq_s and acq_s != "na":
            try:
                sum_acquired += float(str(acq).replace(",", "."))
                any_acquired = True
            except (TypeError, ValueError):
                pass
    sum_max = _round_mark(sum_max) if sum_max > 0 else 0.0
    if not any_acquired:
        return sum_max, 0.0
    return sum_max, _round_mark(sum_acquired)


def _final_report_phase_summary(rows: list[dict]) -> dict:
    max_mark = sum(float(r.get("max_mark") or 0.0) for r in rows)
    acquired_mark = sum(float(r.get("acquired_mark") or 0.0) for r in rows)
    pct = (acquired_mark / max_mark) * 100.0 if max_mark > 0 else None
    return {
        "max_mark": max_mark,
        "acquired_mark": acquired_mark,
        "pct": pct,
        "grade": grade_label_from_percent(pct) if pct is not None else "—",
    }


_FINAL_EVAL_REPORT_PHASE_MAX_PREFIX = "report_phase_max__"


def _report_phase_max_field_name(unit_key: str, phase_key: str) -> str:
    """اسم حقل فريد لكل وحدة+مرحلة في نموذج التقرير النهائي."""
    return f"{_FINAL_EVAL_REPORT_PHASE_MAX_PREFIX}{(unit_key or '').strip()}|{_normalized_exercise_phase(phase_key)}"


def _parse_report_phase_max_field_name(name: str) -> tuple[str, str] | None:
    if not name.startswith(_FINAL_EVAL_REPORT_PHASE_MAX_PREFIX):
        return None
    rest = name[len(_FINAL_EVAL_REPORT_PHASE_MAX_PREFIX) :]
    if "|" not in rest:
        return None
    unit_key, phase_key = rest.split("|", 1)
    unit_key = (unit_key or "").strip()
    phase_key = _normalized_exercise_phase(phase_key)
    if not unit_key or not phase_key:
        return None
    return unit_key, phase_key


def _final_eval_phase_manual_max_map(db, exercise_id: int) -> dict[tuple[str, str], float]:
    rows = (
        db.query(AnalystFinalEvaluationPhaseAllocatedMax)
        .filter(AnalystFinalEvaluationPhaseAllocatedMax.exercise_id == int(exercise_id))
        .all()
    )
    out: dict[tuple[str, str], float] = {}
    for row in rows:
        if row.max_mark is None:
            continue
        uk = (row.unit_level_key or "").strip()
        pk = _normalized_exercise_phase(row.phase_key)
        if uk and pk:
            out[(uk, pk)] = float(row.max_mark)
    return out


def _upsert_final_eval_report_phase_max(
    db,
    *,
    exercise_id: int,
    unit_key: str,
    phase_key: str,
    mark_raw: str | None,
) -> float | None:
    """حفظ/حذف علامة قصوى يدوية لصف وحدة+مرحلة؛ يُرجع القيمة المحفوظة أو None."""
    unit_key = (unit_key or "").strip()
    phase_key = _normalized_exercise_phase(phase_key)
    if not unit_key or not phase_key:
        return None
    raw = (mark_raw or "").strip().replace(",", ".")
    mark = _parse_mark_form_value(raw) if raw else None
    row = (
        db.query(AnalystFinalEvaluationPhaseAllocatedMax)
        .filter(
            AnalystFinalEvaluationPhaseAllocatedMax.exercise_id == int(exercise_id),
            AnalystFinalEvaluationPhaseAllocatedMax.unit_level_key == unit_key,
            AnalystFinalEvaluationPhaseAllocatedMax.phase_key == phase_key,
        )
        .first()
    )
    if mark is None:
        if row is not None:
            db.delete(row)
        return None
    if row is None:
        row = AnalystFinalEvaluationPhaseAllocatedMax(
            exercise_id=int(exercise_id),
            unit_level_key=unit_key,
            phase_key=phase_key,
        )
        db.add(row)
    row.max_mark = float(mark)
    row.unit_level_key = unit_key
    row.phase_key = phase_key
    return float(mark)


def _final_eval_phase_acquired_total(
    db, *, exercise_id: int, unit_key: str, phase_key: str
) -> float:
    """مجموع المكتسبة من قوائم التقييم المحفوظة/المعتمدة لوحدة ومرحلة."""
    unit_key = (unit_key or "").strip()
    phase_key = _normalized_exercise_phase(phase_key)
    if not unit_key or not phase_key:
        return 0.0
    items = (
        db.query(EvaluationListPdfItem)
        .filter(
            EvaluationListPdfItem.exercise_id == int(exercise_id),
            EvaluationListPdfItem.unit_level_key == unit_key,
        )
        .all()
    )
    item_ids = [
        int(it.id)
        for it in items
        if _normalized_exercise_phase(getattr(it, "exercise_phase", None)) == phase_key
    ]
    if not item_ids:
        return 0.0
    latest_by_item = _evaluation_canonical_map_for_items(db, int(exercise_id), item_ids)
    acquired = 0.0
    for item_id in item_ids:
        saved = latest_by_item.get(int(item_id))
        if saved is None or not (getattr(saved, "payload_json", "") or "").strip():
            continue
        rows = _parse_saved_eval_rows(saved.payload_json)
        _payload_max, item_acquired = _evaluation_payload_mark_totals(rows)
        if item_acquired > 0:
            acquired += item_acquired
    return acquired


def _final_eval_phase_row_metrics(
    db,
    *,
    exercise_id: int,
    unit_key: str,
    phase_key: str,
    manual_max: float | None = None,
) -> dict:
    """مقاييس صف مرحلة بعد إدخال القصوى اليدوية."""
    unit_key = (unit_key or "").strip()
    phase_key = _normalized_exercise_phase(phase_key)
    acquired_mark = _final_eval_phase_acquired_total(
        db, exercise_id=int(exercise_id), unit_key=unit_key, phase_key=phase_key
    )
    if manual_max is None:
        stored = _final_eval_phase_manual_max_map(db, int(exercise_id)).get((unit_key, phase_key))
        manual_max = float(stored) if stored is not None else None
    max_mark = float(manual_max) if manual_max is not None else 0.0
    phase_pct: float | None = None
    if max_mark > 0 and acquired_mark > 0:
        phase_pct = (acquired_mark / max_mark) * 100.0
    elif max_mark > 0 and acquired_mark <= 0:
        phase_pct = 0.0
    return {
        "acquired_mark": acquired_mark,
        "manual_max_mark": float(manual_max) if manual_max is not None else None,
        "phase_pct": phase_pct,
        "phase_grade": grade_label_from_percent(phase_pct) if phase_pct is not None else "—",
    }


def _save_final_eval_report_phase_maxes(db, *, exercise_id: int) -> None:
    """حفظ علامات القصوى اليدوية لجدول التقرير النهائي (حقل مستقل لكل وحدة ومرحلة)."""
    for field_name in request.form:
        parsed = _parse_report_phase_max_field_name(field_name)
        if parsed is None:
            continue
        unit_key, phase_key = parsed
        _upsert_final_eval_report_phase_max(
            db,
            exercise_id=int(exercise_id),
            unit_key=unit_key,
            phase_key=phase_key,
            mark_raw=request.form.get(field_name),
        )
    db.commit()


def _final_eval_manual_max_map(db, exercise_id: int) -> dict[int, float]:
    rows = (
        db.query(AnalystFinalEvaluationAllocatedMax)
        .filter(AnalystFinalEvaluationAllocatedMax.exercise_id == int(exercise_id))
        .all()
    )
    out: dict[int, float] = {}
    for row in rows:
        if row.max_mark is None:
            continue
        out[int(row.evaluation_item_id)] = float(row.max_mark)
    return out


def _upsert_final_eval_item_allocated_max(
    db,
    *,
    exercise_id: int,
    unit_key: str,
    item_id: int,
    mark_raw: str | None,
) -> float | None:
    """حفظ/حذف علامة قصوى مخصصة لقائمة تقييم واحدة."""
    unit_key = (unit_key or "").strip()
    item = db.get(EvaluationListPdfItem, int(item_id))
    if item is None or int(item.exercise_id or 0) != int(exercise_id):
        return None
    if (item.unit_level_key or "").strip() != unit_key:
        return None
    raw = (mark_raw or "").strip().replace(",", ".")
    mark = _parse_mark_form_value(raw) if raw else None
    phase_key = _normalized_exercise_phase(item.exercise_phase)
    row = (
        db.query(AnalystFinalEvaluationAllocatedMax)
        .filter(
            AnalystFinalEvaluationAllocatedMax.exercise_id == int(exercise_id),
            AnalystFinalEvaluationAllocatedMax.evaluation_item_id == int(item_id),
        )
        .first()
    )
    if mark is None:
        if row is not None:
            db.delete(row)
        return None
    if row is None:
        row = AnalystFinalEvaluationAllocatedMax(
            exercise_id=int(exercise_id),
            evaluation_item_id=int(item_id),
            unit_level_key=unit_key,
            phase_key=phase_key,
        )
        db.add(row)
    row.max_mark = float(mark)
    row.unit_level_key = unit_key
    row.phase_key = phase_key
    return float(mark)


def _save_final_eval_manual_maxes(
    db,
    *,
    exercise_id: int,
    unit_key: str,
    item_ids: list[int],
) -> None:
    """حفظ علامات القصوى المخصصة من نموذج التقييم النهائي (حقول allocated_max__{item_id})."""
    unit_key = (unit_key or "").strip()
    for item_id in item_ids:
        _upsert_final_eval_item_allocated_max(
            db,
            exercise_id=int(exercise_id),
            unit_key=unit_key,
            item_id=int(item_id),
            mark_raw=request.form.get(f"allocated_max__{item_id}"),
        )
    db.commit()


def _final_report_detail_summary(rows: list[dict]) -> dict:
    max_rows = [r for r in rows if r.get("has_allocated_max")]
    acq_rows = [r for r in rows if r.get("has_saved_payload")]
    list_source_rows = [r for r in rows if r.get("has_saved_payload")]
    allocated_max_mark = sum(float(r.get("allocated_max_mark") or 0.0) for r in max_rows)
    allocated_acquired_mark = sum(float(r.get("allocated_acquired_mark") or 0.0) for r in acq_rows)
    evaluation_list_max_mark = sum(float(r.get("evaluation_list_max_mark") or 0.0) for r in list_source_rows)
    evaluation_list_acquired_mark = sum(
        float(r.get("evaluation_list_acquired_mark") or 0.0) for r in list_source_rows
    )
    pct = (
        (allocated_acquired_mark / allocated_max_mark) * 100.0
        if allocated_max_mark > 0
        else None
    )
    return {
        "allocated_max_mark": allocated_max_mark,
        "allocated_acquired_mark": allocated_acquired_mark,
        "allocated_pct": pct,
        "allocated_grade": grade_label_from_percent(pct) if pct is not None else "—",
        "evaluation_list_max_mark": evaluation_list_max_mark,
        "evaluation_list_acquired_mark": evaluation_list_acquired_mark,
    }


def _round_pct_display(value: float) -> float:
    """تقريب النسبة كما في الجدول (منزلتان) قبل تجميع المربعات."""
    return round(float(value), 2)


def _build_final_report_exercise_summary(final_rows: list[dict]) -> dict:
    """نسب المربعات = مجموع نسب صفوف الجدول (لكل مرحلة) ÷ عدد الوحدات؛ المجموع العام = مجموع نسب المراحل ÷ عدد المراحل."""
    by_phase_units: dict[str, dict[str, float]] = {}
    phase_labels: dict[str, str] = {}
    for row in final_rows:
        phase_key = (row.get("phase_key") or "").strip()
        if not phase_key:
            continue
        pct = row.get("phase_pct")
        if pct is None:
            continue
        unit_key = (row.get("unit_key") or "").strip() or "—"
        phase_labels[phase_key] = (row.get("phase_label") or _phase_label_ar(phase_key))
        by_phase_units.setdefault(phase_key, {})[unit_key] = _round_pct_display(float(pct))

    phase_order = {key: idx for idx, key in enumerate(exercise_phase_keys())}
    phase_summaries: list[dict] = []
    phase_pcts_for_exercise: list[float] = []
    for phase_key in sorted(by_phase_units.keys(), key=lambda k: phase_order.get(k, len(phase_order))):
        unit_pcts = list(by_phase_units[phase_key].values())
        if not unit_pcts:
            continue
        phase_pct = _round_pct_display(sum(unit_pcts) / len(unit_pcts))
        phase_pcts_for_exercise.append(phase_pct)
        phase_summaries.append(
            {
                "phase_key": phase_key,
                "phase_label": phase_labels.get(phase_key) or _phase_label_ar(phase_key),
                "pct": phase_pct,
                "grade": grade_label_from_percent(phase_pct),
                "unit_count": len(unit_pcts),
            }
        )

    exercise_pct = (
        _round_pct_display(sum(phase_pcts_for_exercise) / len(phase_pcts_for_exercise))
        if phase_pcts_for_exercise
        else None
    )
    return {
        "phase_summaries": phase_summaries,
        "exercise_pct": exercise_pct,
        "exercise_grade": grade_label_from_percent(exercise_pct) if exercise_pct is not None else "—",
        "phase_count": len(phase_pcts_for_exercise),
    }


_CONTROL_DONUT_FILL_VARS: dict[str, str] = {
    "preparation": "--control-donut-preparation",
    "opening": "--control-donut-opening",
    "main": "--control-donut-main",
    "reorg": "--control-donut-reorg",
}
_CONTROL_DONUT_TOTAL_FILL_VAR = "--control-donut-total"


def _control_donut_slice_color(phase_key: str, *, is_total: bool = False) -> str:
    if is_total:
        return f"var({_CONTROL_DONUT_TOTAL_FILL_VAR})"
    var_name = _CONTROL_DONUT_FILL_VARS.get((phase_key or "").strip())
    return f"var({var_name})" if var_name else "var(--tint-300)"


def _phase_summary_from_eval_items(
    eval_items: list,
    saved_by_item: dict[int, object],
) -> dict:
    """ملخص نسب المراحل (نفس منطق التقييم النهائي للمحللين) من قوائم التقييم المحفوظة."""
    phase_totals: dict[tuple[str, str], dict] = {}
    for item in eval_items:
        saved = saved_by_item.get(int(getattr(item, "id", 0) or 0))
        if saved is None:
            continue
        rows = _parse_saved_eval_rows(getattr(saved, "payload_json", None))
        max_mark, acquired_mark = _evaluation_payload_mark_totals(rows)
        if max_mark <= 0:
            continue
        unit_key = (getattr(item, "unit_level_key", None) or getattr(saved, "unit_level_key", None) or "").strip()
        phase_key = _normalized_exercise_phase(
            getattr(item, "exercise_phase", None) or getattr(saved, "exercise_phase", None)
        )
        block = phase_totals.setdefault(
            (unit_key, phase_key),
            {
                "unit_key": unit_key,
                "phase_key": phase_key,
                "phase_label": _phase_label_ar(phase_key),
                "max_mark": 0.0,
                "acquired_mark": 0.0,
            },
        )
        block["max_mark"] += max_mark
        block["acquired_mark"] += acquired_mark

    final_rows: list[dict] = []
    for block in phase_totals.values():
        max_mark = float(block.get("max_mark") or 0.0)
        phase_pct = (float(block["acquired_mark"]) / max_mark) * 100.0 if max_mark > 0 else None
        final_rows.append({**block, "phase_pct": phase_pct})
    return _build_final_report_exercise_summary(final_rows)


def _distribution_from_phase_summary(summary: dict) -> list[dict]:
    """وسيلة دائرة «نسب مراحل التمرين» — المراحل الثلاث فقط (بدون المجموع العام)."""
    phase_order = {key: idx for idx, key in enumerate(_CONTROL_REPORT_PHASE_KEYS)}
    phase_labels = {pk: plbl for pk, plbl in _CONTROL_REPORT_PHASE_COLUMNS}
    items: list[dict] = []
    for ps in summary.get("phase_summaries") or []:
        phase_key = (ps.get("phase_key") or "").strip()
        if phase_key not in _CONTROL_REPORT_PHASE_KEYS_SET:
            continue
        pct = ps.get("pct")
        if pct is None:
            continue
        pct_f = float(pct)
        items.append(
            {
                "phase_key": phase_key,
                "label": ps.get("phase_label") or phase_labels.get(phase_key) or _phase_label_ar(phase_key),
                "pct": pct_f,
                "pct_display": _round_pct_display(pct_f),
                "count": int(ps.get("unit_count") or 0),
                "color": _control_donut_slice_color(phase_key),
                "_order": phase_order.get(phase_key, 99),
            }
        )
    items.sort(key=lambda x: x.get("_order", 99))
    for row in items:
        row.pop("_order", None)
    return items


def _donut_conic_gradient_from_distribution(distribution: list[dict]) -> str:
    phase_slices = [
        item
        for item in (distribution or [])
        if (item.get("phase_key") or "").strip() not in ("", "total")
    ]
    if not phase_slices:
        return "conic-gradient(var(--tint-200) 0 100%)"
    weights = [max(0.0, float(item.get("pct") or 0.0)) for item in phase_slices]
    total = sum(weights) or 1.0
    stops: list[str] = []
    start = 0.0
    for item, weight in zip(phase_slices, weights):
        end = start + (weight / total) * 100.0
        color = item.get("color") or "#c4c4c4"
        stops.append(f"{color} {start:.2f}% {end:.2f}%")
        start = end
    return f"conic-gradient({', '.join(stops)})"


FINAL_EVALUATION_TRACK_UNIT_KEYS: set[str] = {
    "mech_infantry_bn",
    "mech_infantry_bn_3",
    "mech_infantry_bn_13",
    "tank_bn",
    "tank_bn_4",
}
FINAL_EVALUATION_TRACK_PHASE_KEY = "reorg"
FINAL_EVALUATION_TRACK_PHASE_LABEL = "مرحلة مسارات التقييم"


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
    if saved is not None and not eval_judge_can_edit(saved):
        abort(403)
    was_reopened = eval_reopened_for_judge(saved) if saved is not None else False
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
    if was_reopened:
        apply_judge_save_after_reopen(saved)
    db.flush()
    _evaluation_delete_duplicate_saves(db, exercise_id=current_exercise.id, evaluation_item_id=item.id, keep_id=saved.id)
    db.commit()


def _planner_bundle_eval_canonical_saved(
    db, exercise_id: int, bundle_action_eval_id: int
) -> PlannerFlowBundleEvalSavedResult | None:
    return (
        db.query(PlannerFlowBundleEvalSavedResult)
        .filter(
            PlannerFlowBundleEvalSavedResult.exercise_id == exercise_id,
            PlannerFlowBundleEvalSavedResult.bundle_action_eval_id
            == int(bundle_action_eval_id),
        )
        .order_by(
            PlannerFlowBundleEvalSavedResult.updated_at.desc(),
            PlannerFlowBundleEvalSavedResult.id.desc(),
        )
        .first()
    )


def _planner_bundle_eval_delete_duplicate_saves(
    db, *, exercise_id: int, bundle_action_eval_id: int, keep_id: int
) -> None:
    db.query(PlannerFlowBundleEvalSavedResult).filter(
        PlannerFlowBundleEvalSavedResult.exercise_id == exercise_id,
        PlannerFlowBundleEvalSavedResult.bundle_action_eval_id
        == int(bundle_action_eval_id),
        PlannerFlowBundleEvalSavedResult.id != keep_id,
    ).delete(synchronize_session=False)


def _planner_bundle_eval_commit_payload_save(
    db,
    *,
    user: User,
    action_row: ExercisePlannerFlowBundleActionEval,
    bundle: ExercisePlannerFlowBundle,
    current_exercise: Exercise,
    raw: str,
) -> None:
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
    saved = _planner_bundle_eval_canonical_saved(
        db, current_exercise.id, action_row.id
    )
    if saved is not None and not eval_judge_can_edit(saved):
        abort(403)
    was_reopened = eval_reopened_for_judge(saved) if saved is not None else False
    if saved is None:
        saved = PlannerFlowBundleEvalSavedResult(
            bundle_action_eval_id=action_row.id,
            exercise_id=current_exercise.id,
            exercise_phase=_normalized_exercise_phase(bundle.exercise_phase),
            unit_level_key=bundle.unit_level_key or "",
            saved_by_id=getattr(user, "id", None),
            is_approved=False,
        )
        db.add(saved)
    saved.payload_json = raw
    saved.total_pct = total_pct
    saved.grade_label = grade
    saved.saved_by_id = getattr(user, "id", None)
    saved.unit_level_key = bundle.unit_level_key or ""
    saved.exercise_phase = _normalized_exercise_phase(bundle.exercise_phase)
    if was_reopened:
        apply_judge_save_after_reopen(saved)
    db.flush()
    _planner_bundle_eval_delete_duplicate_saves(
        db,
        exercise_id=current_exercise.id,
        bundle_action_eval_id=action_row.id,
        keep_id=saved.id,
    )
    db.commit()


def _judge_planner_flow_action_bundle_row(
    db, user: User, ex: Exercise | None, slot: int
) -> tuple[ExercisePlannerFlowBundle, ExercisePlannerFlowBundleActionEval] | None:
    """حزمة المحكم وفتحة الإجراء إن وُجد الملف ومطابقة التخصيص."""
    if ex is None:
        return None
    oversee_jid = (
        _planner_flow_oversee_judge_id_from_request()
        if can_oversee_judge_planner_flow_materials(user)
        else None
    )
    bundle = _judge_assigned_planner_bundle(
        db, user, ex, judge_user_id=oversee_jid
    )
    if bundle is None:
        return None
    if not can_oversee_judge_planner_flow_materials(user):
        _enforce_judge_unit_scope(db, user, ex, bundle.unit_level_key)
        _enforce_judge_has_assignment_for_unit(db, user, ex, bundle.unit_level_key)
    row = (
        db.query(ExercisePlannerFlowBundleActionEval)
        .filter(
            ExercisePlannerFlowBundleActionEval.bundle_id == bundle.id,
            ExercisePlannerFlowBundleActionEval.slot_index == int(slot),
        )
        .first()
    )
    if row is None or not (row.file_relpath or "").strip():
        return None
    return bundle, row


def _phase_label_ar(phase: str | None) -> str:
    return exercise_phase_label(phase)


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


def _eval_list_viewer_ctx(user: User, saved) -> dict:
    """سياق مشترك لعرض/تعديل قائمة تقييم (محكم أو كبير محكمين)."""
    return {
        "saved_is_approved": eval_judge_approved(saved),
        "saved_approved_at": getattr(saved, "approved_at", None) if saved else None,
        "saved_is_chief_approved": eval_chief_approved(saved),
        "saved_chief_approved_at": getattr(saved, "chief_approved_at", None) if saved else None,
        "saved_reopened_for_judge": eval_reopened_for_judge(saved),
        "eval_workflow_label": eval_workflow_label_ar(saved),
        "eval_can_edit": bool(can_save_evaluation_results(user) and eval_judge_can_edit(saved)),
        "show_eval_approve": bool(
            can_approve_evaluation_results(user) and eval_judge_can_approve(saved)
        ),
        "show_chief_approve": bool(
            can_chief_approve_evaluation_results(user) and eval_chief_can_approve(saved)
        ),
        "show_chief_reopen": bool(
            can_chief_reopen_evaluation_for_judge(user) and eval_chief_can_reopen(saved)
        ),
    }


def _eval_crit_media_sheet_ctx(
    db,
    user: User | None,
    *,
    exercise: Exercise | None,
    list_item_id: int | None,
    bundle_action_eval_id: int | None,
    eval_can_edit: bool,
) -> dict:
    ctx = {
        "eval_crit_media_by_row": {},
        "eval_crit_list_item_id": None,
        "eval_crit_bundle_action_id": None,
        "eval_crit_upload_url": "",
    }
    if exercise is None or (list_item_id is None and bundle_action_eval_id is None):
        return ctx
    ex_id = int(exercise.id)
    ctx["eval_crit_media_by_row"] = group_media_rows(
        db,
        ex_id,
        list_item_id=list_item_id,
        bundle_action_eval_id=bundle_action_eval_id,
    )
    ctx["eval_crit_list_item_id"] = int(list_item_id) if list_item_id is not None else None
    ctx["eval_crit_bundle_action_id"] = (
        int(bundle_action_eval_id) if bundle_action_eval_id is not None else None
    )
    if eval_can_edit and user and can_save_evaluation_results(user):
        ctx["eval_crit_upload_url"] = url_for("views.eval_criterion_media_upload")
    return ctx


def _eval_crit_user_can_stream_media(db, user: User | None, m: EvaluationCriterionMedia) -> bool:
    """إطلاع/تشغيل: إدارة النظام، السيطرة، التخطيط، كبير المحكمين، المحللين، والمحكم ضمن النطاق."""
    if user is None:
        return False
    if not db.get(Exercise, m.exercise_id):
        return False
    if is_system_admin(user):
        return True
    ex_id = int(m.exercise_id)
    if can_access_analyst_hub(user):
        ws = _admin_current_workspace_exercise(db, user)
        return ws is not None and int(ws.id) == ex_id
    if can_access_planner_hub(user):
        ws = _admin_current_workspace_exercise(db, user)
        return ws is not None and int(ws.id) == ex_id
    if can_access_control_hub(user):
        ws = _current_workspace_exercise(db, user)
        return ws is not None and int(ws.id) == ex_id
    if can_access_chief_judge_hub(user):
        ws = _current_workspace_exercise(db, user)
        return ws is not None and int(ws.id) == ex_id
    if not can_access_judge_hub(user):
        return False
    ws = _current_workspace_exercise(db, user)
    if ws is None or int(ws.id) != ex_id:
        return False
    if m.evaluation_list_item_id is not None:
        pdf = db.get(EvaluationListPdfItem, int(m.evaluation_list_item_id))
        if pdf is None or int(pdf.exercise_id or 0) != ex_id:
            return False
        _enforce_judge_unit_scope(db, user, ws, pdf.unit_level_key or "")
        return True
    if m.bundle_action_eval_id is not None:
        ar = db.get(ExercisePlannerFlowBundleActionEval, int(m.bundle_action_eval_id))
        if ar is None:
            return False
        b = db.get(ExercisePlannerFlowBundle, int(ar.bundle_id))
        if b is None or int(b.exercise_id) != ex_id:
            return False
        _enforce_judge_unit_scope(db, user, ws, b.unit_level_key or "")
        return True
    return False


def _eval_crit_user_can_upload_media(
    db,
    user: User | None,
    *,
    exercise_id: int,
    unit_level_key: str,
    list_item_id: int | None,
    bundle_action_eval_id: int | None,
    canonical_saved: EvaluationListSavedResult | PlannerFlowBundleEvalSavedResult | None,
) -> bool:
    if user is None or not can_save_evaluation_results(user):
        return False
    if not eval_judge_can_edit(canonical_saved):
        return False
    ex = db.get(Exercise, int(exercise_id))
    if ex is None:
        return False
    if is_system_admin(user):
        return True
    if can_access_planner_hub(user):
        ws = _admin_current_workspace_exercise(db, user)
        return ws is not None and int(ws.id) == int(exercise_id)
    if not can_access_judge_hub(user):
        return False
    ws = _current_workspace_exercise(db, user)
    if ws is None or int(ws.id) != int(exercise_id):
        return False
    _enforce_judge_unit_scope(db, user, ex, unit_level_key or "")
    return True


def _eval_row_canonical_saved_for_crit_upload(
    db, *, exercise_id: int, list_item_id: int | None, bundle_action_eval_id: int | None
) -> EvaluationListSavedResult | PlannerFlowBundleEvalSavedResult | None:
    if list_item_id is not None:
        return _evaluation_canonical_saved_row(db, int(exercise_id), int(list_item_id))
    if bundle_action_eval_id is not None:
        return _planner_bundle_eval_canonical_saved(
            db, int(exercise_id), int(bundle_action_eval_id)
        )
    return None


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
            _exercise_phase_order_expr(EvaluationListPdfItem.exercise_phase),
            _unit_level_order_expr(EvaluationListPdfItem.unit_level_key),
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


def _build_analyst_evaluation_criteria_distribution(db, user: User) -> dict:
    """توزيع نتائج مراحل التقييم اليدوية، مستقل عن قوائم التقييم."""
    ex0 = _current_workspace_exercise(db, user)
    if ex0 is None:
        return {"has_exercise": False}
    ex = db.query(Exercise).filter(Exercise.id == ex0.id).first()
    if ex is None:
        return {"has_exercise": False}

    criteria_units = _ensure_analyst_evaluation_criteria_units(db, ex)
    phase_items = (
        db.query(AnalystEvaluationCriteriaPhaseItem)
        .filter(AnalystEvaluationCriteriaPhaseItem.exercise_id == ex.id)
        .all()
    )
    marks_by_unit_phase: dict[tuple[int, str], list[float]] = {}
    for item in phase_items:
        if item.allocated_mark is None:
            continue
        marks_by_unit_phase.setdefault(
            (int(item.criteria_unit_id), item.phase_key or ""),
            [],
        ).append(float(item.allocated_mark))

    rows: list[dict] = []
    grand_total = 0.0
    for unit in criteria_units:
        prep_marks = marks_by_unit_phase.get((unit.id, "preparation"), [])
        ops_marks = marks_by_unit_phase.get((unit.id, "main"), [])
        preparation_total = sum(prep_marks) if prep_marks else None
        operations_total = sum(ops_marks) if ops_marks else None
        parts = [x for x in (preparation_total, operations_total) if x is not None]
        total_mark = sum(parts) if parts else None
        if total_mark is not None:
            grand_total += total_mark
        rows.append(
            {
                "unit_id": unit.id,
                "unit_label": unit.label or "—",
                "preparation_total": preparation_total,
                "operations_total": operations_total,
                "total_mark": total_mark,
                "allocated_pct": None,
            }
        )

    if grand_total > 0:
        for row in rows:
            if row["total_mark"] is not None:
                row["allocated_pct"] = (float(row["total_mark"]) / grand_total) * 100.0

    return {
        "has_exercise": True,
        "exercise": ex,
        "distribution_rows": rows,
        "grand_total": grand_total if grand_total > 0 else None,
    }


def _build_analyst_final_evaluation_report(db, user: User) -> dict:
    """ملخص نهائي من مساحة المحكمين/قوائم التقييم، سواء كانت النتيجة محفوظة أو معتمدة."""
    ex0 = _current_workspace_exercise(db, user)
    if ex0 is None and is_system_admin(user):
        ex0 = db.query(Exercise).order_by(Exercise.id.desc()).first()
    if ex0 is None:
        return {"has_exercise": False}
    ex = db.query(Exercise).filter(Exercise.id == ex0.id).first()
    if ex is None:
        return {"has_exercise": False}

    eval_items = (
        db.query(EvaluationListPdfItem)
        .filter(EvaluationListPdfItem.exercise_id == ex.id)
        .order_by(
            _unit_level_order_expr(EvaluationListPdfItem.unit_level_key),
            _exercise_phase_order_expr(EvaluationListPdfItem.exercise_phase),
            EvaluationListPdfItem.sort_order,
            EvaluationListPdfItem.id,
        )
        .all()
    )
    latest_by_item = _evaluation_canonical_map_for_items(
        db,
        int(ex.id),
        [int(it.id) for it in eval_items],
    )
    saved_source_rows = [
        row
        for row in latest_by_item.values()
        if (getattr(row, "payload_json", "") or "").strip()
    ]
    approved_source_count = len([row for row in saved_source_rows if bool(getattr(row, "is_approved", False))])
    saved_pending_source_count = len(saved_source_rows) - approved_source_count
    manual_max_by_item = _final_eval_manual_max_map(db, int(ex.id))
    phase_manual_max_map = _final_eval_phase_manual_max_map(db, int(ex.id))

    phase_acquired_totals: dict[tuple[str, str], dict] = {}
    unit_phase_slots: dict[tuple[str, str], dict] = {}
    list_rows_by_unit_phase: dict[tuple[str, str], list[dict]] = {}
    template_rows_cache: dict[str, list[dict]] = {}
    for item in eval_items:
        unit_key = (item.unit_level_key or "").strip()
        phase_key = _normalized_exercise_phase(getattr(item, "exercise_phase", None))
        if unit_key and phase_key:
            unit_phase_slots.setdefault(
                (unit_key, phase_key),
                {
                    "unit_key": unit_key,
                    "unit_label": label_for_unit_level_key(unit_key) or unit_key or "—",
                    "phase_key": phase_key,
                    "phase_label": _phase_label_ar(phase_key),
                    "acquired_mark": 0.0,
                },
            )
        list_label = (item.text or "").strip() or "—"
        saved = latest_by_item.get(int(item.id))
        item_id = int(item.id)
        manual_max = manual_max_by_item.get(item_id)
        allocated_max_mark: float | None = float(manual_max) if manual_max is not None else None
        has_allocated_max = manual_max is not None
        allocated_acquired_mark = 0.0
        allocated_pct: float | None = None
        allocated_grade = "—"
        evaluation_list_max_mark = 0.0
        evaluation_list_acquired_mark = 0.0
        has_saved_payload = False
        acquired_mark = 0.0
        if saved is not None and (getattr(saved, "payload_json", "") or "").strip():
            has_saved_payload = True
            rows = _parse_saved_eval_rows(saved.payload_json)
            _payload_max, acquired_mark = _evaluation_payload_mark_totals(rows)
            relpath = (item.pdf_relpath or "").strip()
            if relpath not in template_rows_cache:
                template_rows_cache[relpath] = _evaluation_list_template_rows(item)
            list_max_mark, list_acquired_mark = _evaluation_list_judge_sum_totals(
                rows,
                template_rows_cache.get(relpath) or [],
            )
            evaluation_list_max_mark = list_max_mark
            evaluation_list_acquired_mark = list_acquired_mark
            allocated_acquired_mark = acquired_mark
        if has_allocated_max and allocated_max_mark is not None and allocated_max_mark > 0 and acquired_mark > 0:
            allocated_pct = (acquired_mark / allocated_max_mark) * 100.0
            allocated_grade = grade_label_from_percent(allocated_pct)
        if has_saved_payload and acquired_mark > 0 and unit_key and phase_key:
            block = phase_acquired_totals.setdefault(
                (unit_key, phase_key),
                {
                    "unit_key": unit_key,
                    "unit_label": label_for_unit_level_key(unit_key) or unit_key or "—",
                    "phase_key": phase_key,
                    "phase_label": _phase_label_ar(phase_key),
                    "acquired_mark": 0.0,
                },
            )
            block["acquired_mark"] += acquired_mark
            slot = unit_phase_slots.setdefault((unit_key, phase_key), {**block})
            slot["acquired_mark"] = block["acquired_mark"]
        list_rows_by_unit_phase.setdefault((unit_key, phase_key), []).append(
            {
                "unit_key": unit_key,
                "unit_label": label_for_unit_level_key(unit_key) or unit_key or "—",
                "phase_key": phase_key,
                "phase_label": _phase_label_ar(phase_key),
                "list_label": list_label,
                "item_sort_order": int(item.sort_order or 0),
                "item_id": item_id,
                "allocated_max_mark": allocated_max_mark,
                "allocated_acquired_mark": allocated_acquired_mark,
                "allocated_pct": allocated_pct,
                "allocated_grade": allocated_grade,
                "evaluation_list_max_mark": evaluation_list_max_mark,
                "evaluation_list_acquired_mark": evaluation_list_acquired_mark,
                "has_allocated_max": has_allocated_max,
                "has_saved_payload": has_saved_payload,
            }
        )

    unit_order = {row["key"]: idx for idx, row in enumerate(UNIT_LEVELS)}
    phase_order = {key: idx for idx, key in enumerate(exercise_phase_keys())}
    unit_phase_pcts: dict[str, list[float]] = {}

    final_rows: list[dict] = []
    for slot_key in sorted(
        unit_phase_slots.keys(),
        key=lambda k: (
            unit_order.get(k[0], len(unit_order)),
            phase_order.get(k[1], len(phase_order)),
            unit_phase_slots[k].get("unit_label") or k[0],
        ),
    ):
        block = unit_phase_slots[slot_key]
        unit_key = block["unit_key"]
        phase_key = block["phase_key"]
        acquired_mark = float(
            phase_acquired_totals.get(slot_key, {}).get("acquired_mark")
            or block.get("acquired_mark")
            or 0.0
        )
        manual_max = phase_manual_max_map.get(slot_key)
        has_phase_manual_max = manual_max is not None
        max_mark = float(manual_max) if manual_max is not None else 0.0
        phase_pct: float | None = None
        if max_mark > 0 and acquired_mark > 0:
            phase_pct = (acquired_mark / max_mark) * 100.0
            unit_phase_pcts.setdefault(unit_key, []).append(phase_pct)
        elif max_mark > 0 and acquired_mark <= 0:
            phase_pct = 0.0
            unit_phase_pcts.setdefault(unit_key, []).append(phase_pct)
        final_rows.append(
            {
                **block,
                "acquired_mark": acquired_mark,
                "max_mark": max_mark,
                "manual_max_mark": float(manual_max) if manual_max is not None else None,
                "has_phase_manual_max": has_phase_manual_max,
                "phase_max_field": _report_phase_max_field_name(unit_key, phase_key),
                "phase_pct": phase_pct,
                "phase_grade": grade_label_from_percent(phase_pct) if phase_pct is not None else "—",
                "unit_total_pct": None,
                "unit_grade": "—",
            }
        )

    unit_pcts_computed: dict[str, float] = {}
    for unit_key, pcts in unit_phase_pcts.items():
        if pcts:
            unit_pcts_computed[unit_key] = sum(pcts) / len(pcts)
    for row in final_rows:
        uk = row.get("unit_key") or ""
        if uk in unit_pcts_computed:
            row["unit_total_pct"] = unit_pcts_computed[uk]
            row["unit_grade"] = grade_label_from_percent(unit_pcts_computed[uk])

    detail_rows: list[dict] = []
    for rows in list_rows_by_unit_phase.values():
        rows.sort(key=lambda x: (x.get("item_sort_order", 0), x.get("item_id", 0)))
        detail_rows.extend(rows)
    detail_rows.sort(
        key=lambda x: (
            unit_order.get(x["unit_key"], len(unit_order)),
            phase_order.get(x["phase_key"], len(phase_order)),
            x.get("item_sort_order", 0),
            x.get("item_id", 0),
        ),
    )

    unit_keys: list[str] = []
    for row in UNIT_LEVELS:
        key = (row.get("key") or "").strip()
        if key and key not in unit_keys:
            unit_keys.append(key)
    for item in eval_items:
        key = (item.unit_level_key or "").strip()
        if key and key not in unit_keys:
            unit_keys.append(key)
    for row in final_rows:
        key = (row.get("unit_key") or "").strip()
        if key and key not in unit_keys:
            unit_keys.append(key)

    rows_by_unit: dict[str, list[dict]] = {}
    for row in final_rows:
        rows_by_unit.setdefault(row["unit_key"], []).append(row)
    details_by_unit_phase = list_rows_by_unit_phase

    report_units: list[dict] = []
    final_rows_all: list[dict] = []
    for idx, unit_key in enumerate(unit_keys):
        anchor = f"final-unit-{idx + 1}"
        unit_label = label_for_unit_level_key(unit_key) or unit_key or "—"
        unit_phase_rows = rows_by_unit.get(unit_key) or []
        if not unit_phase_rows:
            unit_phase_rows = [
                {
                    "unit_key": unit_key,
                    "unit_label": unit_label,
                    "phase_key": "",
                    "phase_label": "—",
                    "max_mark": 0.0,
                    "acquired_mark": 0.0,
                    "phase_pct": None,
                    "unit_total_pct": None,
                    "phase_grade": "—",
                    "unit_grade": "—",
                }
            ]
        for row_idx, row in enumerate(unit_phase_rows):
            row["unit_anchor"] = anchor
            row["show_unit_total"] = row_idx == 0
            row["unit_rowspan"] = len(unit_phase_rows)
            final_rows_all.append(row)
        phase_rows = [r for r in unit_phase_rows if r.get("phase_key")]
        preparation_detail_rows = details_by_unit_phase.get((unit_key, "preparation"), [])
        opening_detail_rows = details_by_unit_phase.get((unit_key, "opening"), [])
        main_detail_rows = details_by_unit_phase.get((unit_key, "main"), [])
        evaluation_tracks_detail_rows = [
            {**r, "phase_label": FINAL_EVALUATION_TRACK_PHASE_LABEL}
            for r in details_by_unit_phase.get((unit_key, FINAL_EVALUATION_TRACK_PHASE_KEY), [])
        ]
        report_units.append(
            {
                "unit_key": unit_key,
                "unit_label": unit_label,
                "anchor": anchor,
                "show_evaluation_tracks": unit_key in FINAL_EVALUATION_TRACK_UNIT_KEYS,
                "phase_rows": phase_rows,
                "phase_summary": _final_report_phase_summary(phase_rows),
                "preparation_detail_rows": preparation_detail_rows,
                "preparation_detail_summary": _final_report_detail_summary(preparation_detail_rows),
                "opening_detail_rows": opening_detail_rows,
                "opening_detail_summary": _final_report_detail_summary(opening_detail_rows),
                "main_detail_rows": main_detail_rows,
                "main_detail_summary": _final_report_detail_summary(main_detail_rows),
                "evaluation_tracks_detail_rows": evaluation_tracks_detail_rows,
                "evaluation_tracks_detail_summary": _final_report_detail_summary(evaluation_tracks_detail_rows),
            }
        )

    return {
        "has_exercise": True,
        "exercise": ex,
        "final_rows": final_rows_all,
        "report_summary": _build_final_report_exercise_summary(final_rows_all),
        "report_units": report_units,
        "all_phase_rows": final_rows_all,
        "detail_rows": detail_rows,
        "preparation_detail_rows": [r for r in detail_rows if r["phase_key"] == "preparation"],
        "opening_detail_rows": [r for r in detail_rows if r["phase_key"] == "opening"],
        "main_detail_rows": [r for r in detail_rows if r["phase_key"] == "main"],
        "n_eval_lists": len(eval_items),
        "n_saved_eval_lists": len(saved_source_rows),
        "n_approved_eval_lists": approved_source_count,
        "n_saved_pending_eval_lists": saved_pending_source_count,
    }


DEFAULT_ANALYST_EVALUATION_CRITERIA_UNITS: tuple[str, ...] = (
    "قيادة مجموعة اللواء",
    "كتيبة المشاة الآلية/1",
    "كتيبة المشاة الآلية /2",
    "كتيبة الدبابات/3",
    "سرية الاستطلاع",
    "سرية الـ م/د",
    "كتيبة المدفعية",
    "سرية الهاون",
    "سرية هندسة الميدان",
    "سرية الإشارة",
    "سرية الدفاع الجوي",
    "كتيبة الاسناد الإداري",
    "سرية الدفاع الكيميائي",
    "تقييم إدارة التمرين",
)

ANALYST_EVALUATION_CRITERIA_PHASES: dict[str, str] = {
    "preparation": "مرحلة التحضير",
    "main": "مرحلة العمليات التعرضية",
}


def _ensure_analyst_evaluation_criteria_units(
    db,
    ex: Exercise,
) -> list[AnalystEvaluationCriteriaUnit]:
    rows = (
        db.query(AnalystEvaluationCriteriaUnit)
        .filter(AnalystEvaluationCriteriaUnit.exercise_id == ex.id)
        .order_by(AnalystEvaluationCriteriaUnit.sort_order, AnalystEvaluationCriteriaUnit.id)
        .all()
    )
    if rows:
        return rows
    for idx, label in enumerate(DEFAULT_ANALYST_EVALUATION_CRITERIA_UNITS):
        db.add(
            AnalystEvaluationCriteriaUnit(
                exercise_id=ex.id,
                sort_order=idx,
                label=label,
            )
        )
    db.commit()
    return (
        db.query(AnalystEvaluationCriteriaUnit)
        .filter(AnalystEvaluationCriteriaUnit.exercise_id == ex.id)
        .order_by(AnalystEvaluationCriteriaUnit.sort_order, AnalystEvaluationCriteriaUnit.id)
        .all()
    )


def _parse_pct_form_value(raw: str | None) -> float | None:
    s = (raw or "").strip().replace(",", ".")
    if not s:
        return None
    try:
        v = float(s)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(100.0, v))


def _save_analyst_evaluation_criteria_distribution(db, user: User, ex: Exercise) -> None:
    del user  # محفوظ للتوقيع المتسق مع بقية دوال الحفظ.
    existing = {
        int(row.id): row
        for row in (
            db.query(AnalystEvaluationCriteriaUnit)
            .filter(AnalystEvaluationCriteriaUnit.exercise_id == ex.id)
            .all()
        )
    }
    delete_ids = {
        int(x)
        for x in request.form.getlist("delete_unit_ids")
        if (x or "").strip().isdigit()
    }
    ordered_ids = [
        int(x)
        for x in request.form.getlist("unit_ids")
        if (x or "").strip().isdigit()
    ]
    for sort_order, uid in enumerate(ordered_ids):
        row = existing.get(uid)
        if row is None:
            continue
        if uid in delete_ids:
            db.query(AnalystEvaluationCriteriaPhaseItem).filter(
                AnalystEvaluationCriteriaPhaseItem.criteria_unit_id == uid
            ).delete(synchronize_session=False)
            db.delete(row)
            continue
        label = (request.form.get(f"unit_label__{uid}") or "").strip()[:300]
        if label:
            row.label = label
        row.sort_order = sort_order
    for label in request.form.getlist("new_unit_label"):
        clean = (label or "").strip()[:300]
        if not clean:
            continue
        db.add(
            AnalystEvaluationCriteriaUnit(
                exercise_id=ex.id,
                sort_order=len(ordered_ids),
                label=clean,
            )
        )
        ordered_ids.append(-1)
    db.commit()


def _parse_mark_form_value(raw: str | None) -> float | None:
    s = (raw or "").strip().replace(",", ".")
    if not s:
        return None
    try:
        v = float(s)
    except (TypeError, ValueError):
        return None
    return max(0.0, v)


def _criteria_phase_items_for_unit(
    db,
    ex: Exercise,
    unit: AnalystEvaluationCriteriaUnit,
    phase_key: str,
) -> list[dict]:
    rows = (
        db.query(AnalystEvaluationCriteriaPhaseItem)
        .filter(
            AnalystEvaluationCriteriaPhaseItem.exercise_id == ex.id,
            AnalystEvaluationCriteriaPhaseItem.criteria_unit_id == unit.id,
            AnalystEvaluationCriteriaPhaseItem.phase_key == phase_key,
        )
        .order_by(
            AnalystEvaluationCriteriaPhaseItem.sort_order,
            AnalystEvaluationCriteriaPhaseItem.id,
        )
        .all()
    )
    total_mark = sum(float(r.allocated_mark or 0) for r in rows)
    out: list[dict] = []
    for row in rows:
        mark = float(row.allocated_mark) if row.allocated_mark is not None else None
        pct = (mark / total_mark * 100.0) if mark is not None and total_mark > 0 else None
        out.append(
            {
                "criteria_text": row.criteria_text or "",
                "allocated_mark": mark,
                "allocated_pct": pct,
            }
        )
    return out


def _save_criteria_phase_items_for_unit(
    db,
    ex: Exercise,
    unit: AnalystEvaluationCriteriaUnit,
    phase_key: str,
) -> None:
    db.query(AnalystEvaluationCriteriaPhaseItem).filter(
        AnalystEvaluationCriteriaPhaseItem.exercise_id == ex.id,
        AnalystEvaluationCriteriaPhaseItem.criteria_unit_id == unit.id,
        AnalystEvaluationCriteriaPhaseItem.phase_key == phase_key,
    ).delete(synchronize_session=False)
    criteria_texts = request.form.getlist("criteria_text")
    marks = request.form.getlist("allocated_mark")
    n = max(len(criteria_texts), len(marks))
    for idx in range(n):
        text_value = (criteria_texts[idx] if idx < len(criteria_texts) else "").strip()[:1000]
        mark = _parse_mark_form_value(marks[idx] if idx < len(marks) else "")
        if not text_value and mark is None:
            continue
        db.add(
            AnalystEvaluationCriteriaPhaseItem(
                exercise_id=ex.id,
                criteria_unit_id=unit.id,
                phase_key=phase_key,
                sort_order=idx,
                criteria_text=text_value,
                allocated_mark=mark,
            )
        )
    db.commit()


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
    if (u.role_key or "") == RoleKey.CHIEF_JUDGE.value and not next_url:
        return redirect("/chief-judge")
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
    if role_key == RoleKey.CHIEF_JUDGE.value:
        return ("/chief-judge", "فتح مساحة كبير المحكمين", "إبدأ")
    if role_key == RoleKey.STANDARDS_LIBRARY.value:
        return ("/library", "فتح مكتبة المراجع والمعايير", "إبدأ")
    return ("/library", "فتح المكتبة", "إبدأ")


# ترتيب بطاقات الصفحة الرئيسية: المحكمين قبل المحللين ضمن الشبكة
_DASHBOARD_CARD_ORDER: tuple[str, ...] = (
    RoleKey.SYSTEM_ADMIN.value,
    RoleKey.PLANNER.value,
    RoleKey.CONTROL.value,
    RoleKey.JUDGE.value,
    RoleKey.CHIEF_JUDGE.value,
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
    ("incomplete-tasks", "مهام غير مكتملة", "fa-clipboard-list"),
    ("chat-rooms", "غرف محادثة", "fa-comments"),
    ("after-action-review", "إنشاء مراجعة ما بعد العمل", "fa-people-arrows"),
    ("notifications-log", "سجل الإشعارات", "fa-bell"),
    ("exercise-info", "معلومات التمرين", "fa-circle-info"),
    ("visual-documentation", "التوثيق المرئي", "fa-photo-film"),
    ("final-evaluation", "التقييم نهائي", "fa-file-signature"),
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


@bp.route("/analyst/<slug>", methods=["GET", "POST"])
def analyst_hub_section(slug: str):
    user = get_current_user_optional()
    if not user:
        return redirect(f"/login?next=/analyst/{slug}")
    if not can_access_analyst_hub(user):
        abort(403)
    slug_norm = (slug or "").strip().lower()
    if slug_norm == "chat-rooms":
        return redirect(url_for("views.chat_rooms_list", from_analyst=1))
    if slug_norm == "notifications-log":
        return redirect(url_for("views.notifications_log", from_analyst=1))
    if slug_norm == "visual-documentation":
        return redirect(url_for("views.visual_documentation", from_analyst=1))
    title = ANALYST_HUB_SLUGS.get(slug_norm)
    if not title:
        abort(404)
    def _actx(**extra):
        return _ctx(user, **_hub_back_ctx_for_request_path(), **extra)

    if slug_norm == "evaluation-criteria":
        from flask import g

        db = g.db
        dist = _build_analyst_evaluation_criteria_distribution(db, user)
        if not dist.get("has_exercise"):
            return render_template(
                "analyst_evaluation_criteria.html",
                **_actx( section_title=title, has_exercise=False),
            )
        if request.method == "POST":
            _save_analyst_evaluation_criteria_distribution(db, user, dist["exercise"])
            return redirect(url_for("views.analyst_hub_section", slug=slug_norm, ok=1))
        return render_template(
            "analyst_evaluation_criteria.html",
            **_actx(
                section_title=title,
                has_exercise=True,
                exercise=dist["exercise"],
                distribution_rows=dist["distribution_rows"],
                grand_total=dist["grand_total"],
                ok_msg="تم حفظ قائمة وحدات معايير التقييم." if request.args.get("ok") else "",
            ),
        )
    if slug_norm == "positives-negatives":
        from flask import g

        db = g.db
        dash = _build_analyst_evaluation_results_dashboard(db, user)
        if not dash.get("has_exercise"):
            return render_template(
                "analyst_positives_negatives.html",
                **_actx( section_title=title, has_exercise=False),
            )
        return render_template(
            "analyst_positives_negatives.html",
            **_actx(
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
                **_actx( section_title=title, has_exercise=False),
            )
        return render_template(
            "analyst_evaluation_results_dashboard.html",
            **_actx(
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
                **_actx( section_title=title, has_exercise=False),
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
                _exercise_phase_order_expr(EvaluationListPdfItem.exercise_phase),
                _unit_level_order_expr(EvaluationListPdfItem.unit_level_key),
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
                    "phase": _normalized_exercise_phase(getattr(it, "exercise_phase", None)),
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
                        "phase": _normalized_exercise_phase(getattr(it, "exercise_phase", None)),
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
                        "phase": _normalized_exercise_phase(it.get("phase")),
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
            **_actx(
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
    if slug_norm == "final-evaluation":
        from flask import g

        db = g.db
        ex0 = _current_workspace_exercise(db, user)
        if ex0 is None and is_system_admin(user):
            ex0 = db.query(Exercise).order_by(Exercise.id.desc()).first()
        report = _build_analyst_final_evaluation_report(db, user)
        if not report.get("has_exercise"):
            return render_template(
                "analyst_final_evaluation.html",
                **_actx( section_title=title, has_exercise=False),
            )
        return render_template(
            "analyst_final_evaluation.html",
            **_actx(
                section_title=title,
                has_exercise=True,
                exercise=report["exercise"],
                final_rows=report["final_rows"],
                report_summary=report.get("report_summary"),
                all_phase_rows=report["all_phase_rows"],
                detail_rows=report["detail_rows"],
                preparation_detail_rows=report["preparation_detail_rows"],
                opening_detail_rows=report["opening_detail_rows"],
                main_detail_rows=report["main_detail_rows"],
                report_units=report["report_units"],
                n_eval_lists=report["n_eval_lists"],
                n_saved_eval_lists=report["n_saved_eval_lists"],
                n_approved_eval_lists=report["n_approved_eval_lists"],
                n_saved_pending_eval_lists=report["n_saved_pending_eval_lists"],
                final_eval_can_edit=True,
            ),
        )
    return render_template(
        "analyst_section_placeholder.html",
        **_actx( section_title=title, section_slug=slug),
    )


@bp.route("/analyst/final-evaluation/<unit_key>", methods=["GET", "POST"])
def analyst_final_evaluation_unit_detail(unit_key: str):
    user = get_current_user_optional()
    if not user:
        return redirect(f"/login?next=/analyst/final-evaluation/{unit_key}")
    if not can_access_analyst_hub(user):
        abort(403)
    from flask import g

    db = g.db
    unit_key_norm = (unit_key or "").strip()
    ex0 = _current_workspace_exercise(db, user)
    if ex0 is None and is_system_admin(user):
        ex0 = db.query(Exercise).order_by(Exercise.id.desc()).first()
    if request.method == "POST" and ex0 is not None:
        item_ids = [
            int(x)
            for x in request.form.getlist("evaluation_item_id")
            if (x or "").strip().isdigit()
        ]
        _save_final_eval_manual_maxes(
            db,
            exercise_id=int(ex0.id),
            unit_key=unit_key_norm,
            item_ids=item_ids,
        )
        return redirect(
            url_for(
                "views.analyst_final_evaluation_unit_detail",
                unit_key=unit_key_norm,
                saved=1,
            )
        )
    report = _build_analyst_final_evaluation_report(db, user)
    if not report.get("has_exercise"):
        abort(404)
    unit = next(
        (u for u in report.get("report_units", []) if (u.get("unit_key") or "").strip() == unit_key_norm),
        None,
    )
    if unit is None:
        abort(404)
    ok_msg = "تم حفظ علامات القصوى المخصصة." if request.args.get("saved") == "1" else None
    return render_template(
        "analyst_final_evaluation_unit.html",
        **_ctx(
            user,
            section_title=ANALYST_HUB_SLUGS.get("final-evaluation", "التقييم نهائي"),
            exercise=report["exercise"],
            unit=unit,
            n_approved_eval_lists=report["n_approved_eval_lists"],
            n_saved_pending_eval_lists=report["n_saved_pending_eval_lists"],
            final_eval_can_edit=True,
            ok_msg=ok_msg,
            **_hub_back_ctx_for_request_path(),
        ),
    )


@bp.route("/api/analyst/final-evaluation/report-phase-max", methods=["POST"])
def api_analyst_final_eval_report_phase_max():
    """حفظ تلقائي لعلامة القصوى اليدوية (صف وحدة+مرحلة في التقرير النهائي)."""
    user = get_current_user_optional()
    if not user:
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    if not can_access_analyst_hub(user):
        return jsonify({"ok": False, "error": "forbidden"}), 403
    from flask import g

    db = g.db
    try:
        ex0 = _current_workspace_exercise(db, user)
        if ex0 is None and is_system_admin(user):
            ex0 = db.query(Exercise).order_by(Exercise.id.desc()).first()
        if ex0 is None:
            return jsonify({"ok": False, "error": "no_exercise"}), 400

        payload = request.get_json(silent=True) if request.is_json else {}
        if not isinstance(payload, dict):
            payload = {}
        field_name = (request.form.get("field_name") or payload.get("field_name") or "").strip()
        unit_key = (request.form.get("unit_key") or payload.get("unit_key") or "").strip()
        phase_key = request.form.get("phase_key") or payload.get("phase_key")
        if field_name:
            parsed = _parse_report_phase_max_field_name(field_name)
            if parsed:
                unit_key, phase_key = parsed
        mark_raw = request.form.get("max_mark")
        if mark_raw is None:
            mark_raw = payload.get("max_mark")
        if mark_raw is None and field_name:
            mark_raw = request.form.get(field_name)
        unit_key = (unit_key or "").strip()
        phase_key = _normalized_exercise_phase(str(phase_key or ""))
        if not unit_key or not phase_key:
            return jsonify({"ok": False, "error": "invalid_request"}), 400

        saved_mark = _upsert_final_eval_report_phase_max(
            db,
            exercise_id=int(ex0.id),
            unit_key=unit_key,
            phase_key=phase_key,
            mark_raw=None if mark_raw is None else str(mark_raw),
        )
        db.commit()
        metrics = _final_eval_phase_row_metrics(
            db,
            exercise_id=int(ex0.id),
            unit_key=unit_key,
            phase_key=phase_key,
            manual_max=saved_mark,
        )
        return jsonify(
            {
                "ok": True,
                "saved_mark": saved_mark,
                "acquired_mark": metrics["acquired_mark"],
                "phase_pct": metrics["phase_pct"],
                "phase_grade": metrics["phase_grade"],
            }
        )
    except Exception:
        db.rollback()
        return jsonify({"ok": False, "error": "server_error"}), 500


@bp.route("/api/analyst/final-evaluation/item-allocated-max", methods=["POST"])
def api_analyst_final_eval_item_allocated_max():
    """حفظ تلقائي لعلامة القصوى المخصصة لقائمة تقييم في تفاصيل الوحدة."""
    user = get_current_user_optional()
    if not user:
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    if not can_access_analyst_hub(user):
        return jsonify({"ok": False, "error": "forbidden"}), 403
    from flask import g

    db = g.db
    ex0 = _current_workspace_exercise(db, user)
    if ex0 is None and is_system_admin(user):
        ex0 = db.query(Exercise).order_by(Exercise.id.desc()).first()
    if ex0 is None:
        return jsonify({"ok": False, "error": "no_exercise"}), 400

    try:
        payload = request.get_json(silent=True) if request.is_json else {}
        if not isinstance(payload, dict):
            payload = {}
        unit_key = (request.form.get("unit_key") or payload.get("unit_key") or "").strip()
        item_id_raw = request.form.get("item_id") or payload.get("item_id")
        mark_raw = request.form.get("max_mark")
        if mark_raw is None:
            mark_raw = payload.get("max_mark")
        if item_id_raw is None or not str(item_id_raw).strip().isdigit():
            return jsonify({"ok": False, "error": "invalid_item"}), 400
        item_id = int(item_id_raw)
        if mark_raw is None:
            mark_raw = request.form.get(f"allocated_max__{item_id}")

        saved_mark = _upsert_final_eval_item_allocated_max(
            db,
            exercise_id=int(ex0.id),
            unit_key=unit_key,
            item_id=item_id,
            mark_raw=None if mark_raw is None else str(mark_raw),
        )
        db.commit()
        return jsonify({"ok": True, "saved_mark": saved_mark, "item_id": item_id})
    except Exception:
        db.rollback()
        return jsonify({"ok": False, "error": "server_error"}), 500


@bp.route("/analyst/evaluation-criteria/<int:unit_id>/<phase_key>", methods=["GET", "POST"])
def analyst_evaluation_criteria_phase(unit_id: int, phase_key: str):
    user = get_current_user_optional()
    if not user:
        return redirect(f"/login?next=/analyst/evaluation-criteria/{unit_id}/{phase_key}")
    if not can_access_analyst_hub(user):
        abort(403)
    phase_key = (phase_key or "").strip()
    phase_label = ANALYST_EVALUATION_CRITERIA_PHASES.get(phase_key)
    if not phase_label:
        abort(404)
    from flask import g

    db = g.db
    ex0 = _current_workspace_exercise(db, user)
    if ex0 is None:
        return render_template(
            "analyst_evaluation_criteria_phase.html",
            **_ctx(
                user,
                has_exercise=False,
                section_title="معايير التقييم",
                phase_label=phase_label,
                unit=None,
                items=[],
                total_mark=None,
                **_hub_back_ctx_for_request_path(),
            ),
        )
    ex = db.query(Exercise).filter(Exercise.id == ex0.id).first()
    if ex is None:
        abort(404)
    unit = db.get(AnalystEvaluationCriteriaUnit, unit_id)
    if unit is None or unit.exercise_id != ex.id:
        abort(404)
    if request.method == "POST":
        _save_criteria_phase_items_for_unit(db, ex, unit, phase_key)
        return redirect(
            url_for(
                "views.analyst_evaluation_criteria_phase",
                unit_id=unit.id,
                phase_key=phase_key,
                ok=1,
            )
        )
    items = _criteria_phase_items_for_unit(db, ex, unit, phase_key)
    total_mark = sum(
        float(item["allocated_mark"] or 0)
        for item in items
        if item.get("allocated_mark") is not None
    )
    return render_template(
        "analyst_evaluation_criteria_phase.html",
        **_ctx(
            user,
            has_exercise=True,
            section_title="معايير التقييم",
            exercise=ex,
            unit=unit,
            phase_key=phase_key,
            phase_label=phase_label,
            items=items,
            total_mark=total_mark if total_mark > 0 else None,
            ok_msg="تم حفظ جدول المرحلة." if request.args.get("ok") else "",
            **_hub_back_ctx_for_request_path(),
        ),
    )


def _get_or_create_planner_bundle(
    db,
    exercise_id: int,
    phase: str,
    unit_key: str,
    unit_label: str,
) -> ExercisePlannerFlowBundle:
    phase_n = normalize_exercise_phase(phase)
    row = (
        db.query(ExercisePlannerFlowBundle)
        .filter(
            ExercisePlannerFlowBundle.exercise_id == exercise_id,
            ExercisePlannerFlowBundle.exercise_phase == phase_n,
            ExercisePlannerFlowBundle.unit_level_key == unit_key,
        )
        .first()
    )
    if row:
        return row
    row = ExercisePlannerFlowBundle(
        exercise_id=exercise_id,
        exercise_phase=phase_n,
        unit_level_key=unit_key,
        unit_level_label=(unit_label or "")[:200],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


_PLANNER_BUNDLE_MAX_ACTION_SLOTS = 200
_PLANNER_BUNDLE_MAX_EVENT_FLOW_SLOTS = 200


def _planner_upload_display_name(filename: str) -> str:
    base = Path(filename or "").name.strip()
    if not base:
        return ""
    return base[:500]


def _planner_bundle_event_flow_rows(
    db, bundle: ExercisePlannerFlowBundle
) -> list[ExercisePlannerFlowBundleEventFlow]:
    return (
        db.query(ExercisePlannerFlowBundleEventFlow)
        .filter(ExercisePlannerFlowBundleEventFlow.bundle_id == bundle.id)
        .order_by(ExercisePlannerFlowBundleEventFlow.slot_index)
        .all()
    )


def _migrate_legacy_bundle_event_flow(
    db, bundle: ExercisePlannerFlowBundle
) -> list[ExercisePlannerFlowBundleEventFlow]:
    """ينقل المسار القديم الوحيد على الحزمة إلى جدول ملفات المجرى إن لزم."""
    rows = _planner_bundle_event_flow_rows(db, bundle)
    legacy_rel = (bundle.event_flow_file_relpath or "").strip()
    if rows or not legacy_rel:
        return rows
    row = ExercisePlannerFlowBundleEventFlow(
        bundle_id=bundle.id,
        slot_index=1,
        title=(bundle.event_flow_title or "")[:500],
        file_relpath=legacy_rel.replace("\\", "/"),
    )
    db.add(row)
    db.flush()
    for slot_row in bundle.action_eval_slots:
        if slot_row.event_flow_item_id is None:
            slot_row.event_flow_item_id = row.id
    db.commit()
    return _planner_bundle_event_flow_rows(db, bundle)


def _sync_bundle_legacy_event_flow_columns(
    bundle: ExercisePlannerFlowBundle,
    event_rows: list[ExercisePlannerFlowBundleEventFlow],
) -> None:
    """يبقي أعمدة الحزمة القديمة متوافقة مع أول ملف مجرى (واجهة المحكم)."""
    primary = next(
        (r for r in event_rows if (r.file_relpath or "").strip()),
        None,
    )
    if primary is None:
        bundle.event_flow_file_relpath = ""
        bundle.event_flow_title = ""
        return
    bundle.event_flow_file_relpath = (primary.file_relpath or "").replace("\\", "/")
    bundle.event_flow_title = (primary.title or "")[:500]


def _sanitize_planner_bundle_orphan_event_flow_items(
    db, bundle: ExercisePlannerFlowBundle | None
) -> bool:
    if bundle is None:
        return False
    changed = False
    for row in _planner_bundle_event_flow_rows(db, bundle):
        rel = (row.file_relpath or "").strip()
        if rel and _planner_bundle_file_abspath(rel) is None:
            _unlink_planner_bundle_file(rel)
            row.file_relpath = ""
            changed = True
    if changed:
        bundle.linked_at = None
        bundle.updated_at = datetime.utcnow()
        _sync_bundle_legacy_event_flow_columns(
            bundle, _planner_bundle_event_flow_rows(db, bundle)
        )
        db.commit()
    return changed


def _planner_bundle_slot_view(
    *,
    slot_row: ExercisePlannerFlowBundleActionEval,
    bundle: ExercisePlannerFlowBundle,
    event_rows_by_id: dict[int, ExercisePlannerFlowBundleEventFlow],
) -> dict:
    rel = (slot_row.file_relpath or "").strip()
    has_file = bool(rel) and _planner_bundle_file_abspath(rel) is not None
    disp = _planner_blob_display_filename(
        stored_title=slot_row.title or "",
        relpath=rel,
        fallback=f"قائمة {slot_row.slot_index}",
    )
    ef_id = slot_row.event_flow_item_id
    ef_row = event_rows_by_id.get(int(ef_id)) if ef_id else None
    ef_name = ""
    if ef_row is not None:
        ef_name = _planner_blob_display_filename(
            stored_title=ef_row.title or "",
            relpath=ef_row.file_relpath or "",
            fallback=f"مجرى {ef_row.slot_index}",
        )
    linked = bool(bundle.linked_at) and has_file and ef_id is not None
    return {
        "id": int(slot_row.id),
        "slot_index": int(slot_row.slot_index),
        "title": disp,
        "has_file": has_file,
        "insert_label": "تم الإدراج" if has_file else "لم يُدرج",
        "link_label": "مرتبط" if linked else ("جاهز للربط" if has_file else "—"),
        "event_flow_item_id": int(ef_id) if ef_id else None,
        "event_flow_name": ef_name,
    }


def _planner_bundle_event_flow_view(
    *,
    row: ExercisePlannerFlowBundleEventFlow,
    bundle: ExercisePlannerFlowBundle,
) -> dict:
    rel = (row.file_relpath or "").strip()
    has_file = bool(rel) and _planner_bundle_file_abspath(rel) is not None
    disp = _planner_blob_display_filename(
        stored_title=row.title or "",
        relpath=rel,
        fallback=f"مجرى {row.slot_index}",
    )
    linked = bool(bundle.linked_at) and has_file
    return {
        "id": int(row.id),
        "slot_index": int(row.slot_index),
        "title": disp,
        "has_file": has_file,
        "insert_label": "تم الإدراج" if has_file else "لم يُدرج",
        "link_label": "مرتبط" if linked else ("جاهز للربط" if has_file else "—"),
    }


def _planner_bundle_sync_dilemma_count_from_slots(db, bundle: ExercisePlannerFlowBundle) -> None:
    """يُحدّث ``dilemma_count`` من عدد صفوف قوائم تقييم الإجراءات الفعلي."""
    n = (
        db.query(ExercisePlannerFlowBundleActionEval)
        .filter(ExercisePlannerFlowBundleActionEval.bundle_id == bundle.id)
        .count()
    )
    bundle.dilemma_count = int(n)


def _planner_bundle_judge_assignments(db, exercise_id: int, unit_level_key: str):
    return (
        db.query(JudgeTraineeAssignment)
        .filter(
            JudgeTraineeAssignment.exercise_id == exercise_id,
            JudgeTraineeAssignment.unit_level_key == unit_level_key,
        )
        .options(joinedload(JudgeTraineeAssignment.judge_user))
        .order_by(JudgeTraineeAssignment.id)
        .all()
    )


_UI_MSG_PLANNER_BUNDLE = {
    "bad_event_file": "يُقبل ملف PDF أو Word (.doc/.docx) فقط.",
    "bad_xlsx": "يُقبل ملف Excel (.xlsx) فقط.",
    "no_file": "لم يُحدد ملف.",
    "link_count": "أدرِج ملفاً واحداً على الأقل لقائمة تقييم الإجراءات (Excel) قبل الربط.",
    "link_master": "أدرج ملف مجرى الأحداث والمعاضل أولاً.",
    "link_master_disk": "مسار ملف المجرى مسجّل لكن الملف غير موجود على الخادم — أعد إدراج الملف.",
    "link_slots": "يجب إدراج ملف Excel لكل قائمة تقييم إجراءات.",
    "link_slots_disk": "يُشار إلى ملفات تقييم مسجّلة لكن أحدها غير موجود على الخادم — أعد إدراج ملفات Excel.",
    "link_ok": "تم تخصيص الربط بنجاح.",
    "upload_ok": "تم إدراج الملف.",
    "bulk_ok": "تم إدراج ملفات التقييم في الجدول — يمكنك الضغط على «تخصيص وربط» عند اكتمال الإدراج.",
    "bulk_event_ok": "تم إدراج ملف(ات) مجرى الأحداث في الجدول.",
    "bulk_event_limit": "تجاوز الحد الأقصى لعدد ملفات مجرى الأحداث في هذه الحزمة.",
    "delete_event_ok": "تم حذف ملف المجرى.",
    "delete_action_ok": "تم حذف قائمة تقييم الإجراءات.",
    "bulk_limit": "تجاوز الحد الأقصى لعدد قوائم تقييم الإجراءات في هذه الحزمة — احذف قوائم أو أنشئ حزمة أخرى.",
    "assign_ok": "تم ربط الحزمة بالمحكم.",
    "assign_clear_ok": "تمت إزالة ربط الحزمة عن المحكم.",
    "save_err": "تعذر حفظ الملف.",
}


@bp.route("/planner/create-flow", methods=["GET"])
def planner_flow_bundle_workspace():
    user = get_current_user_optional()
    if not user:
        return redirect("/login?next=/planner/create-flow")
    if not can_access_planner_hub(user):
        abort(403)
    from flask import g

    db = g.db
    ex = _current_workspace_exercise(db, user)
    err = (request.args.get("err") or "").strip()
    ok = (request.args.get("ok") or "").strip()
    if ex is None:
        return render_template(
            "planner_flow_bundle.html",
            **_ctx(
                user,
                has_exercise=False,
                bundle=None,
                slots=[],
                phase_key="",
                unit_key="",
                phase_options=EXERCISE_PHASE_OPTIONS,
                unit_levels=UNIT_LEVELS,
                judges=[],
                err_msg="",
                ok_msg="",
                phase_label_display="",
                unit_label_display="",
                planner_event_flow_file_ok=False,
                event_flow_rows=[],
                action_slot_rows=[],
                selected_event_flow_id=None,
                **_hub_back_ctx_for_request_path(),
            ),
        )
    phase_key = normalize_exercise_phase(request.args.get("phase") or DEFAULT_EXERCISE_PHASE)
    unit_param = (request.args.get("unit") or "").strip()
    unit_key = unit_param if unit_param else (UNIT_LEVELS[0]["key"] if UNIT_LEVELS else "")
    unit = next((x for x in UNIT_LEVELS if x["key"] == unit_key), None)
    if unit is None:
        abort(404)
    bundle = _get_or_create_planner_bundle(db, ex.id, phase_key, unit_key, unit["label"])
    _sanitize_planner_bundle_orphan_event_flow(db, bundle)
    _sanitize_planner_bundle_orphan_event_flow_items(db, bundle)
    _migrate_legacy_bundle_event_flow(db, bundle)
    event_db_rows = _planner_bundle_event_flow_rows(db, bundle)
    _sync_bundle_legacy_event_flow_columns(bundle, event_db_rows)
    db.commit()
    slots = (
        db.query(ExercisePlannerFlowBundleActionEval)
        .filter(ExercisePlannerFlowBundleActionEval.bundle_id == bundle.id)
        .order_by(ExercisePlannerFlowBundleActionEval.slot_index)
        .all()
    )
    if int(bundle.dilemma_count or 0) != len(slots):
        bundle.dilemma_count = len(slots)
        bundle.updated_at = datetime.utcnow()
        db.commit()
    judges = _planner_bundle_judge_assignments(db, ex.id, unit_key)
    event_rows_by_id = {int(r.id): r for r in event_db_rows}
    event_flow_rows = [
        _planner_bundle_event_flow_view(row=r, bundle=bundle) for r in event_db_rows
    ]
    action_slot_rows = [
        _planner_bundle_slot_view(
            slot_row=s, bundle=bundle, event_rows_by_id=event_rows_by_id
        )
        for s in slots
    ]
    planner_ef_ok = any(r["has_file"] for r in event_flow_rows)
    sel_raw = (request.args.get("event_flow") or "").strip()
    selected_event_flow_id = int(sel_raw) if sel_raw.isdigit() else None
    if selected_event_flow_id is not None and selected_event_flow_id not in event_rows_by_id:
        selected_event_flow_id = None
    if selected_event_flow_id is None and event_flow_rows:
        selected_event_flow_id = event_flow_rows[0]["id"]
    return render_template(
        "planner_flow_bundle.html",
        **_ctx(
            user,
            has_exercise=True,
            exercise=ex,
            bundle=bundle,
            slots=slots,
            phase_key=phase_key,
            unit_key=unit_key,
            phase_options=EXERCISE_PHASE_OPTIONS,
            unit_levels=UNIT_LEVELS,
            judges=judges,
            err_msg=_UI_MSG_PLANNER_BUNDLE.get(err, "") if err else "",
            ok_msg=_UI_MSG_PLANNER_BUNDLE.get(ok, "") if ok else "",
            phase_label_display=_phase_label_ar(phase_key),
            unit_label_display=unit["label"],
            planner_event_flow_file_ok=planner_ef_ok,
            event_flow_rows=event_flow_rows,
            action_slot_rows=action_slot_rows,
            selected_event_flow_id=selected_event_flow_id,
            can_oversee_judge_planner_flow=can_oversee_judge_planner_flow_materials(
                user
            ),
            **_hub_back_ctx_for_request_path(),
        ),
    )


def _redirect_planner_bundle_workspace(bundle: ExercisePlannerFlowBundle, *, err: str = "", ok: str = ""):
    kw = {"phase": bundle.exercise_phase, "unit": bundle.unit_level_key}
    if err:
        kw["err"] = err
    if ok:
        kw["ok"] = ok
    return redirect(url_for("views.planner_flow_bundle_workspace", **kw))


@bp.route("/planner/create-flow/<int:bundle_id>/upload-event-flow-bulk", methods=["POST"])
def planner_flow_bundle_upload_event_flow_bulk(bundle_id: int):
    user = get_current_user_optional()
    if not user:
        abort(403)
    if not can_access_planner_hub(user):
        abort(403)
    from flask import g

    db = g.db
    ex = _current_workspace_exercise(db, user)
    bundle = db.get(ExercisePlannerFlowBundle, bundle_id)
    if ex is None or bundle is None or bundle.exercise_id != ex.id:
        abort(404)
    raw_files = request.files.getlist("files")
    files = [f for f in raw_files if f and getattr(f, "filename", "").strip()]
    if not files:
        return _redirect_planner_bundle_workspace(bundle, err="no_file")
    rows = _planner_bundle_event_flow_rows(db, bundle)
    empty_count = sum(1 for r in rows if not (r.file_relpath or "").strip())
    need_new = max(0, len(files) - empty_count)
    if len(rows) + need_new > _PLANNER_BUNDLE_MAX_EVENT_FLOW_SLOTS:
        return _redirect_planner_bundle_workspace(bundle, err="bulk_event_limit")
    root = _planner_flow_bundle_root()

    def _assign_event_to_slot(
        slot_row: ExercisePlannerFlowBundleEventFlow, fstor
    ) -> str | None:
        try:
            data = fstor.read()
        except Exception:
            return "save_err"
        ext = _info_bank_event_flow_sniff_ext(data)
        if not ext:
            return "bad_event_file"
        sn = int(slot_row.slot_index)
        rel = f"{bundle.id}/event_flow_{sn}{ext}"
        dest = (root / rel).resolve()
        try:
            dest.relative_to(root)
        except ValueError:
            abort(400)
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            dest.write_bytes(data)
        except OSError:
            return "save_err"
        old_rp = (slot_row.file_relpath or "").strip()
        old_nm = old_rp.replace("\\", "/")
        nw_nm = rel.replace("\\", "/")
        if old_nm and old_nm != nw_nm:
            _unlink_planner_bundle_file(old_rp)
        slot_row.file_relpath = nw_nm
        disp = _planner_upload_display_name(getattr(fstor, "filename", "") or "")
        slot_row.title = disp[:500] or slot_row.title
        return None

    try:
        fi = 0
        for row in rows:
            if fi >= len(files):
                break
            if not (row.file_relpath or "").strip():
                err_k = _assign_event_to_slot(row, files[fi])
                if err_k:
                    db.rollback()
                    return _redirect_planner_bundle_workspace(bundle, err=err_k)
                fi += 1
        mx = max((int(r.slot_index) for r in rows), default=0)
        while fi < len(files):
            mx += 1
            fn = getattr(files[fi], "filename", "") or ""
            title_base = _planner_upload_display_name(fn)
            new_row = ExercisePlannerFlowBundleEventFlow(
                bundle_id=bundle.id,
                slot_index=mx,
                title=title_base or f"مجرى الأحداث — {mx}",
            )
            db.add(new_row)
            db.flush()
            err_k = _assign_event_to_slot(new_row, files[fi])
            if err_k:
                db.rollback()
                return _redirect_planner_bundle_workspace(bundle, err=err_k)
            fi += 1
        bundle.linked_at = None
        bundle.updated_at = datetime.utcnow()
        event_rows = _planner_bundle_event_flow_rows(db, bundle)
        _sync_bundle_legacy_event_flow_columns(bundle, event_rows)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return _redirect_planner_bundle_workspace(bundle, ok="bulk_event_ok")


@bp.route(
    "/planner/create-flow/<int:bundle_id>/delete-event-flow/<int:item_id>",
    methods=["POST"],
)
def planner_flow_bundle_delete_event_flow(bundle_id: int, item_id: int):
    user = get_current_user_optional()
    if not user:
        abort(403)
    if not can_access_planner_hub(user):
        abort(403)
    from flask import g

    db = g.db
    ex = _current_workspace_exercise(db, user)
    bundle = db.get(ExercisePlannerFlowBundle, bundle_id)
    if ex is None or bundle is None or bundle.exercise_id != ex.id:
        abort(404)
    row = (
        db.query(ExercisePlannerFlowBundleEventFlow)
        .filter(
            ExercisePlannerFlowBundleEventFlow.bundle_id == bundle.id,
            ExercisePlannerFlowBundleEventFlow.id == int(item_id),
        )
        .first()
    )
    if row is None:
        abort(404)
    rel = (row.file_relpath or "").strip()
    if rel:
        _unlink_planner_bundle_file(rel)
    for slot_row in (
        db.query(ExercisePlannerFlowBundleActionEval)
        .filter(
            ExercisePlannerFlowBundleActionEval.bundle_id == bundle.id,
            ExercisePlannerFlowBundleActionEval.event_flow_item_id == row.id,
        )
        .all()
    ):
        slot_row.event_flow_item_id = None
    db.delete(row)
    bundle.linked_at = None
    bundle.updated_at = datetime.utcnow()
    event_rows = _planner_bundle_event_flow_rows(db, bundle)
    _sync_bundle_legacy_event_flow_columns(bundle, event_rows)
    db.commit()
    return _redirect_planner_bundle_workspace(bundle, ok="delete_event_ok")


@bp.route("/planner/create-flow/<int:bundle_id>/upload-actions-bulk", methods=["POST"])
def planner_flow_bundle_upload_actions_bulk(bundle_id: int):
    user = get_current_user_optional()
    if not user:
        abort(403)
    if not can_access_planner_hub(user):
        abort(403)
    from flask import g

    db = g.db
    ex = _current_workspace_exercise(db, user)
    bundle = db.get(ExercisePlannerFlowBundle, bundle_id)
    if ex is None or bundle is None or bundle.exercise_id != ex.id:
        abort(404)
    raw_files = request.files.getlist("files")
    files = [f for f in raw_files if f and getattr(f, "filename", "").strip()]
    if not files:
        return _redirect_planner_bundle_workspace(bundle, err="no_file")
    ef_raw = (request.form.get("event_flow_item_id") or "").strip()
    target_ef_id: int | None = int(ef_raw) if ef_raw.isdigit() else None
    if target_ef_id is not None:
        ef_row = (
            db.query(ExercisePlannerFlowBundleEventFlow)
            .filter(
                ExercisePlannerFlowBundleEventFlow.bundle_id == bundle.id,
                ExercisePlannerFlowBundleEventFlow.id == target_ef_id,
            )
            .first()
        )
        if ef_row is None:
            target_ef_id = None
    if target_ef_id is None:
        ef_first = (
            db.query(ExercisePlannerFlowBundleEventFlow)
            .filter(ExercisePlannerFlowBundleEventFlow.bundle_id == bundle.id)
            .order_by(ExercisePlannerFlowBundleEventFlow.slot_index)
            .first()
        )
        target_ef_id = int(ef_first.id) if ef_first else None

    rows = (
        db.query(ExercisePlannerFlowBundleActionEval)
        .filter(ExercisePlannerFlowBundleActionEval.bundle_id == bundle.id)
        .order_by(ExercisePlannerFlowBundleActionEval.slot_index)
        .all()
    )
    empty_count = sum(1 for r in rows if not (r.file_relpath or "").strip())
    need_new = max(0, len(files) - empty_count)
    if len(rows) + need_new > _PLANNER_BUNDLE_MAX_ACTION_SLOTS:
        return _redirect_planner_bundle_workspace(bundle, err="bulk_limit")

    root = _planner_flow_bundle_root()

    def _assign_xlsx_to_slot(slot_row: ExercisePlannerFlowBundleActionEval, fstor) -> str | None:
        """يكتب ملف xlsx على الصف؛ تعيد مفتاح رسالة خطأ أو None."""
        try:
            data = fstor.read()
        except Exception:
            return "save_err"
        if not _is_xlsx_bytes(data):
            return "bad_xlsx"
        sn = int(slot_row.slot_index)
        rel = f"{bundle.id}/action_{sn}.xlsx"
        dest = (root / rel).resolve()
        try:
            dest.relative_to(root)
        except ValueError:
            abort(400)
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            dest.write_bytes(data)
        except OSError:
            return "save_err"
        old_rp = (slot_row.file_relpath or "").strip()
        old_nm = old_rp.replace("\\", "/")
        nw_nm = rel.replace("\\", "/")
        if old_nm and old_nm != nw_nm:
            _unlink_planner_bundle_file(old_rp)
        slot_row.file_relpath = nw_nm
        disp = _planner_upload_display_name(getattr(fstor, "filename", "") or "")
        slot_row.title = disp[:500] or slot_row.title
        if target_ef_id is not None:
            slot_row.event_flow_item_id = target_ef_id
        return None

    try:
        fi = 0
        for row in rows:
            if fi >= len(files):
                break
            if not (row.file_relpath or "").strip():
                err_k = _assign_xlsx_to_slot(row, files[fi])
                if err_k:
                    db.rollback()
                    return _redirect_planner_bundle_workspace(bundle, err=err_k)
                fi += 1

        mx = max((int(r.slot_index) for r in rows), default=0)
        while fi < len(files):
            mx += 1
            fn = getattr(files[fi], "filename", "") or ""
            title_base = _planner_upload_display_name(fn)
            new_row = ExercisePlannerFlowBundleActionEval(
                bundle_id=bundle.id,
                slot_index=mx,
                title=title_base or f"قائمة تقييم الإجراءات — {mx}",
                event_flow_item_id=target_ef_id,
            )
            db.add(new_row)
            db.flush()
            err_k = _assign_xlsx_to_slot(new_row, files[fi])
            if err_k:
                db.rollback()
                return _redirect_planner_bundle_workspace(bundle, err=err_k)
            fi += 1

        bundle.linked_at = None
        bundle.updated_at = datetime.utcnow()
        _planner_bundle_sync_dilemma_count_from_slots(db, bundle)
        db.commit()
    except Exception:
        db.rollback()
        raise

    return _redirect_planner_bundle_workspace(bundle, ok="bulk_ok")


@bp.route(
    "/planner/create-flow/<int:bundle_id>/delete-action/<int:slot_id>",
    methods=["POST"],
)
def planner_flow_bundle_delete_action(bundle_id: int, slot_id: int):
    user = get_current_user_optional()
    if not user:
        abort(403)
    if not can_access_planner_hub(user):
        abort(403)
    from flask import g

    db = g.db
    ex = _current_workspace_exercise(db, user)
    bundle = db.get(ExercisePlannerFlowBundle, bundle_id)
    if ex is None or bundle is None or bundle.exercise_id != ex.id:
        abort(404)
    row = (
        db.query(ExercisePlannerFlowBundleActionEval)
        .filter(
            ExercisePlannerFlowBundleActionEval.bundle_id == bundle.id,
            ExercisePlannerFlowBundleActionEval.id == int(slot_id),
        )
        .first()
    )
    if row is None:
        abort(404)
    rel = (row.file_relpath or "").strip()
    if rel:
        _unlink_planner_bundle_file(rel)
    db.delete(row)
    bundle.linked_at = None
    bundle.updated_at = datetime.utcnow()
    _planner_bundle_sync_dilemma_count_from_slots(db, bundle)
    db.commit()
    return _redirect_planner_bundle_workspace(bundle, ok="delete_action_ok")


@bp.route("/planner/create-flow/<int:bundle_id>/upload-action/<int:slot>", methods=["POST"])
def planner_flow_bundle_upload_action(bundle_id: int, slot: int):
    user = get_current_user_optional()
    if not user:
        abort(403)
    if not can_access_planner_hub(user):
        abort(403)
    from flask import g

    db = g.db
    ex = _current_workspace_exercise(db, user)
    bundle = db.get(ExercisePlannerFlowBundle, bundle_id)
    if ex is None or bundle is None or bundle.exercise_id != ex.id:
        abort(404)
    row = (
        db.query(ExercisePlannerFlowBundleActionEval)
        .filter(
            ExercisePlannerFlowBundleActionEval.bundle_id == bundle.id,
            ExercisePlannerFlowBundleActionEval.slot_index == int(slot),
        )
        .first()
    )
    if row is None:
        abort(404)
    f = request.files.get("file")
    if not f or not getattr(f, "filename", ""):
        return _redirect_planner_bundle_workspace(bundle, err="no_file")
    try:
        data = f.read()
    except Exception:
        return _redirect_planner_bundle_workspace(bundle, err="save_err")
    if not _is_xlsx_bytes(data):
        return _redirect_planner_bundle_workspace(bundle, err="bad_xlsx")
    root = _planner_flow_bundle_root()
    rel = f"{bundle.id}/action_{int(slot)}.xlsx"
    dest = (root / rel).resolve()
    try:
        dest.relative_to(root)
    except ValueError:
        abort(400)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        dest.write_bytes(data)
    except OSError:
        return _redirect_planner_bundle_workspace(bundle, err="save_err")
    old_rp = (row.file_relpath or "").strip()
    old_nm = old_rp.replace("\\", "/")
    nw_nm = rel.replace("\\", "/")
    if old_nm and old_nm != nw_nm:
        _unlink_planner_bundle_file(old_rp)
    row.file_relpath = nw_nm
    disp = _planner_upload_display_name(f.filename or "")
    row.title = disp[:500] or row.title
    bundle.linked_at = None
    bundle.updated_at = datetime.utcnow()
    db.commit()
    return _redirect_planner_bundle_workspace(bundle, ok="upload_ok")


@bp.route("/planner/create-flow/<int:bundle_id>/link", methods=["POST"])
def planner_flow_bundle_link(bundle_id: int):
    user = get_current_user_optional()
    if not user:
        abort(403)
    if not can_access_planner_hub(user):
        abort(403)
    from flask import g

    db = g.db
    ex = _current_workspace_exercise(db, user)
    bundle = db.get(ExercisePlannerFlowBundle, bundle_id)
    if ex is None or bundle is None or bundle.exercise_id != ex.id:
        abort(404)
    event_rows = _migrate_legacy_bundle_event_flow(db, bundle)
    event_with_file = [
        r
        for r in event_rows
        if (r.file_relpath or "").strip()
        and _planner_bundle_file_abspath(r.file_relpath) is not None
    ]
    if not event_with_file:
        return _redirect_planner_bundle_workspace(bundle, err="link_master")
    slots = (
        db.query(ExercisePlannerFlowBundleActionEval)
        .filter(ExercisePlannerFlowBundleActionEval.bundle_id == bundle.id)
        .order_by(ExercisePlannerFlowBundleActionEval.slot_index)
        .all()
    )
    if len(slots) < 1:
        return _redirect_planner_bundle_workspace(bundle, err="link_count")
    for s in slots:
        rel = (s.file_relpath or "").strip()
        if not rel:
            return _redirect_planner_bundle_workspace(bundle, err="link_slots")
        if _planner_bundle_file_abspath(rel) is None:
            return _redirect_planner_bundle_workspace(bundle, err="link_slots_disk")
        if s.event_flow_item_id is None and event_with_file:
            s.event_flow_item_id = int(event_with_file[0].id)
    _sync_bundle_legacy_event_flow_columns(bundle, event_rows)
    bundle.linked_at = datetime.utcnow()
    bundle.updated_at = datetime.utcnow()
    db.commit()
    return _redirect_planner_bundle_workspace(bundle, ok="link_ok")


@bp.route("/planner/create-flow/<int:bundle_id>/assign-judge", methods=["POST"])
def planner_flow_bundle_assign_judge(bundle_id: int):
    user = get_current_user_optional()
    if not user:
        abort(403)
    if not can_access_planner_hub(user):
        abort(403)
    from flask import g

    db = g.db
    ex = _current_workspace_exercise(db, user)
    bundle = db.get(ExercisePlannerFlowBundle, bundle_id)
    if ex is None or bundle is None or bundle.exercise_id != ex.id:
        abort(404)
    raw_j = (request.form.get("judge_user_id") or "").strip()
    if not raw_j.isdigit():
        abort(400)
    judge_uid = int(raw_j)
    clear = (request.form.get("clear") or "").strip() == "1"
    ja = (
        db.query(JudgeTraineeAssignment)
        .filter(
            JudgeTraineeAssignment.exercise_id == ex.id,
            JudgeTraineeAssignment.judge_user_id == judge_uid,
        )
        .first()
    )
    if ja is None or ja.unit_level_key != bundle.unit_level_key:
        abort(400)
    ja.planner_flow_bundle_id = None if clear else bundle.id
    db.commit()
    return _redirect_planner_bundle_workspace(
        bundle,
        ok="assign_clear_ok" if clear else "assign_ok",
    )


def _planner_flow_oversee_judge_id_from_request() -> int | None:
    raw = (request.args.get("judge_user_id") or "").strip()
    return int(raw) if raw.isdigit() else None


def _planner_flow_is_readonly_oversee(
    user: User, *, oversee_judge_id: int | None = None
) -> bool:
    """عرض فقط عند إطلاع إدارة النظام/كبير المحكمين على حزمة محكم آخر (وليس حزمتهم)."""
    if not can_oversee_judge_planner_flow_materials(user):
        return False
    jid = (
        oversee_judge_id
        if oversee_judge_id is not None
        else _planner_flow_oversee_judge_id_from_request()
    )
    if jid is None:
        return True
    return int(jid) != int(getattr(user, "id", 0) or 0)


def _planner_flow_action_lists_editable(user: User) -> bool:
    """المحكم وكبير المحكمين (وإدارة النظام) يقيّمون ويحفظون ويعتمدون قوائم إجراءات الحزمة."""
    return bool(can_save_evaluation_results(user))


def _planner_flow_eval_list_viewer_ctx(user: User, saved) -> dict:
    """سياق واجهة تقييم قائمة إجراءات الحزمة — صلاحية كاملة للمحكم/كبير المحكمين."""
    wf = dict(_eval_list_viewer_ctx(user, saved))
    if _planner_flow_is_readonly_oversee(user):
        wf["eval_can_edit"] = False
        wf["show_eval_approve"] = False
        wf["show_chief_approve"] = False
        wf["show_chief_reopen"] = False
        return wf
    if not _planner_flow_action_lists_editable(user):
        return wf
    return {
        **wf,
        "eval_can_edit": True,
        "show_eval_approve": bool(
            can_approve_evaluation_results(user) and eval_judge_can_approve(saved)
        ),
        "show_chief_approve": bool(
            can_chief_approve_evaluation_results(user) and eval_chief_can_approve(saved)
        ),
        "show_chief_reopen": bool(
            can_chief_reopen_evaluation_for_judge(user) and eval_chief_can_reopen(saved)
        ),
    }


def _planner_flow_materials_query_kwargs(viewer: User) -> dict[str, int]:
    if not can_oversee_judge_planner_flow_materials(viewer):
        return {}
    jid = _planner_flow_oversee_judge_id_from_request()
    if jid is not None:
        return {"judge_user_id": jid}
    return {}


def _planner_flow_oversee_assignment_rows(db, ex: Exercise) -> list[dict]:
    """محكمون لديهم حزمة مجرى مربوطة — لاختيار الإطلاع."""
    rows = (
        db.query(JudgeTraineeAssignment)
        .filter(
            JudgeTraineeAssignment.exercise_id == ex.id,
            JudgeTraineeAssignment.planner_flow_bundle_id.isnot(None),
        )
        .options(joinedload(JudgeTraineeAssignment.judge_user))
        .options(joinedload(JudgeTraineeAssignment.planner_flow_bundle))
        .order_by(JudgeTraineeAssignment.unit_level_key, JudgeTraineeAssignment.id)
        .all()
    )
    out: list[dict] = []
    for ja in rows:
        ju = ja.judge_user
        bundle = ja.planner_flow_bundle
        jlabel = (
            (getattr(ju, "full_name", None) or "").strip()
            or (getattr(ju, "username", None) or "").strip()
            or f"محكم #{ja.judge_user_id}"
        )
        uk = (ja.unit_level_key or "").strip()
        out.append(
            {
                "judge_user_id": int(ja.judge_user_id),
                "judge_label": jlabel,
                "trainee_name": (ja.trainee_name or "").strip() or "—",
                "unit_label": label_for_unit_level_key(uk) or uk or "—",
                "bundle_linked": bool(
                    bundle and getattr(bundle, "linked_at", None)
                ),
                "view_href": url_for(
                    "views.judge_planner_flow_materials",
                    judge_user_id=int(ja.judge_user_id),
                ),
            }
        )
    return out


def _judge_assigned_planner_bundle(
    db,
    user: User,
    ex: Exercise | None,
    *,
    judge_user_id: int | None = None,
) -> ExercisePlannerFlowBundle | None:
    if ex is None:
        return None
    if can_oversee_judge_planner_flow_materials(user):
        jid = (
            judge_user_id
            if judge_user_id is not None
            else _planner_flow_oversee_judge_id_from_request()
        )
        if jid is None:
            return None
        ja = (
            db.query(JudgeTraineeAssignment)
            .filter(
                JudgeTraineeAssignment.exercise_id == ex.id,
                JudgeTraineeAssignment.judge_user_id == int(jid),
            )
            .first()
        )
    else:
        ja = _judge_assignment_for_current_exercise(db, user, ex)
    if ja is None or not ja.planner_flow_bundle_id:
        return None
    b = db.get(ExercisePlannerFlowBundle, ja.planner_flow_bundle_id)
    if b is None or b.exercise_id != ex.id:
        return None
    return b


@bp.route("/judge/planner-flow-materials", methods=["GET"])
def judge_planner_flow_materials():
    user = get_current_user_optional()
    if not user:
        return redirect("/login?next=/judge/planner-flow-materials")
    if not can_access_judge_hub(user):
        abort(403)
    from flask import g

    db = g.db
    ex = _current_workspace_exercise(db, user)
    oversee = can_oversee_judge_planner_flow_materials(user)
    oversee_jid = _planner_flow_oversee_judge_id_from_request() if oversee else None
    if oversee and ex is not None and oversee_jid is None:
        return render_template(
            "judge_planner_flow_materials.html",
            **_ctx(
                user,
                has_exercise=True,
                exercise=ex,
                bundle=None,
                slots=[],
                planner_eval_rows=[],
                planner_flow_unit_label="",
                planner_event_flow_file_ok=False,
                planner_event_flow_display_name="",
                planner_flow_oversee_picker=True,
                planner_flow_oversee_rows=_planner_flow_oversee_assignment_rows(db, ex),
                planner_flow_view_only=True,
                planner_flow_viewing_judge_label="",
                **_hub_back_ctx_for_request_path(),
            ),
        )
    bundle = _judge_assigned_planner_bundle(
        db, user, ex, judge_user_id=oversee_jid
    )
    viewing_judge_label = ""
    if oversee and oversee_jid is not None:
        ja_view = (
            db.query(JudgeTraineeAssignment)
            .filter(
                JudgeTraineeAssignment.exercise_id == ex.id,
                JudgeTraineeAssignment.judge_user_id == int(oversee_jid),
            )
            .options(joinedload(JudgeTraineeAssignment.judge_user))
            .first()
            if ex is not None
            else None
        )
        if ja_view and ja_view.judge_user:
            ju = ja_view.judge_user
            viewing_judge_label = (
                (getattr(ju, "full_name", None) or "").strip()
                or (getattr(ju, "username", None) or "").strip()
                or f"محكم #{oversee_jid}"
            )
        else:
            viewing_judge_label = f"محكم #{oversee_jid}"
    pf_qs = _planner_flow_materials_query_kwargs(user)
    _sanitize_planner_bundle_orphan_event_flow(db, bundle)
    _sanitize_planner_bundle_orphan_event_flow_items(db, bundle)
    slots = []
    planner_eval_rows: list[dict] = []
    unit_label_pf = ""
    planner_event_flow_file_ok = False
    planner_event_flow_display_name = ""
    if bundle:
        _migrate_legacy_bundle_event_flow(db, bundle)
        event_db_rows = _planner_bundle_event_flow_rows(db, bundle)
        _sync_bundle_legacy_event_flow_columns(bundle, event_db_rows)
        db.commit()
        primary_ef = next((r for r in event_db_rows if (r.file_relpath or "").strip()), None)
        if primary_ef is None:
            ev_rel_j = (bundle.event_flow_file_relpath or "").strip()
        else:
            ev_rel_j = (primary_ef.file_relpath or "").strip()
        planner_event_flow_file_ok = bool(
            ev_rel_j and _planner_bundle_file_abspath(ev_rel_j) is not None
        )
        if primary_ef is not None:
            planner_event_flow_display_name = _planner_blob_display_filename(
                stored_title=primary_ef.title or "",
                relpath=ev_rel_j,
                fallback="ملف المجرى",
            )
        else:
            planner_event_flow_display_name = _planner_blob_display_filename(
                stored_title=bundle.event_flow_title or "",
                relpath=ev_rel_j,
                fallback="ملف المجرى",
            )
        slots = (
            db.query(ExercisePlannerFlowBundleActionEval)
            .filter(ExercisePlannerFlowBundleActionEval.bundle_id == bundle.id)
            .order_by(ExercisePlannerFlowBundleActionEval.slot_index)
            .all()
        )
        unit_label_pf = label_for_unit_level_key(bundle.unit_level_key) or (
            bundle.unit_level_label or ""
        ).strip() or bundle.unit_level_key
        if ex is not None:
            for slot_row in slots:
                s_canon = _planner_bundle_eval_canonical_saved(db, ex.id, slot_row.id)
                is_done = bool(
                    s_canon and getattr(s_canon, "is_approved", False)
                )
                has_xlsx = bool((slot_row.file_relpath or "").strip())
                title_s = _planner_blob_display_filename(
                    stored_title=slot_row.title or "",
                    relpath=slot_row.file_relpath or "",
                    fallback=f"قائمة {slot_row.slot_index}",
                )
                planner_eval_rows.append(
                    {
                        "slot_index": int(slot_row.slot_index),
                        "item_title": title_s,
                        "dt": (getattr(s_canon, "updated_at", None) if s_canon else None)
                        or getattr(slot_row, "created_at", None),
                        "exercise_type": (getattr(ex, "exercise_type", "") or "").strip(),
                        "trained_unit": (getattr(ex, "trained_unit", "") or "").strip(),
                        "delivery_dt": (
                            getattr(s_canon, "approved_at", None)
                            if s_canon is not None
                            and bool(getattr(s_canon, "is_approved", False))
                            else None
                        ),
                        "status_label": "ينجز" if is_done else "لم ينجز",
                        "status_done": is_done,
                        "grade_label": (getattr(s_canon, "grade_label", "") or "").strip()
                        if s_canon
                        else "",
                        "open_href": (
                            url_for(
                                "views.judge_planner_flow_materials_action_evaluate",
                                slot=slot_row.slot_index,
                                **pf_qs,
                            )
                            if has_xlsx
                            else ""
                        ),
                    }
                )
    if oversee and ex is not None and oversee_jid is not None and bundle is None:
        abort(404)
    hub_nav_href = url_for("views.judge_planner_flow_materials", **_role_hub_preserve_link_kwargs())
    if not oversee:
        hub_nav_href = ""
    return render_template(
        "judge_planner_flow_materials.html",
        **_ctx(
            user,
            has_exercise=ex is not None,
            exercise=ex,
            bundle=bundle,
            slots=slots,
            planner_eval_rows=planner_eval_rows,
            planner_flow_unit_label=unit_label_pf,
            planner_event_flow_file_ok=planner_event_flow_file_ok,
            planner_event_flow_display_name=planner_event_flow_display_name,
            planner_flow_oversee_picker=False,
            planner_flow_oversee_rows=[],
            planner_flow_view_only=_planner_flow_is_readonly_oversee(user, oversee_judge_id=oversee_jid),
            planner_flow_viewing_judge_label=viewing_judge_label,
            planner_flow_url_kwargs=pf_qs,
            hub_nav_href=hub_nav_href,
            **_hub_back_ctx_for_request_path(),
        ),
    )


@bp.route("/judge/planner-flow-materials/event-flow", methods=["GET"])
def judge_planner_flow_materials_event_flow():
    user = get_current_user_optional()
    if not user:
        abort(403)
    if not can_access_judge_hub(user):
        abort(403)
    from flask import g

    db = g.db
    ex = _current_workspace_exercise(db, user)
    oversee_jid = (
        _planner_flow_oversee_judge_id_from_request()
        if can_oversee_judge_planner_flow_materials(user)
        else None
    )
    bundle = _judge_assigned_planner_bundle(
        db, user, ex, judge_user_id=oversee_jid
    )
    if bundle is None:
        abort(404)
    _migrate_legacy_bundle_event_flow(db, bundle)
    event_rows = _planner_bundle_event_flow_rows(db, bundle)
    primary = next((r for r in event_rows if (r.file_relpath or "").strip()), None)
    rel = (
        (primary.file_relpath or "").strip()
        if primary is not None
        else (bundle.event_flow_file_relpath or "").strip()
    )
    if not rel:
        abort(404)
    path = _planner_bundle_file_abspath(rel)
    if path is None:
        abort(404)
    mt = _mimetype_info_bank_event_flow(path)
    return send_file(path, mimetype=mt, as_attachment=False)


@bp.route("/judge/planner-flow-materials/action/<int:slot>", methods=["GET"])
def judge_planner_flow_materials_action(slot: int):
    user = get_current_user_optional()
    if not user:
        abort(403)
    if not can_access_judge_hub(user):
        abort(403)
    from flask import g

    db = g.db
    ex = _current_workspace_exercise(db, user)
    oversee_jid = (
        _planner_flow_oversee_judge_id_from_request()
        if can_oversee_judge_planner_flow_materials(user)
        else None
    )
    bundle = _judge_assigned_planner_bundle(
        db, user, ex, judge_user_id=oversee_jid
    )
    if bundle is None:
        abort(404)
    row = (
        db.query(ExercisePlannerFlowBundleActionEval)
        .filter(
            ExercisePlannerFlowBundleActionEval.bundle_id == bundle.id,
            ExercisePlannerFlowBundleActionEval.slot_index == int(slot),
        )
        .first()
    )
    if row is None or not (row.file_relpath or "").strip():
        abort(404)
    path = _planner_bundle_file_abspath(row.file_relpath)
    if path is None:
        abort(404)
    return send_file(
        path,
        mimetype=_mimetype_for_eval_list_file(path),
        as_attachment=True,
        download_name=path.name or f"action_eval_{slot}.xlsx",
    )


@bp.route(
    "/judge/planner-flow-materials/action/<int:slot>/evaluate",
    methods=["GET"],
)
def judge_planner_flow_materials_action_evaluate(slot: int):
    """واجهة تقييم تفاعلية لقائمة إجراءات الحزمة (مثل صفحة قوائم التقييم العامة)."""
    user = get_current_user_optional()
    if not user:
        return redirect(
            f"/login?next=/judge/planner-flow-materials/action/{int(slot)}/evaluate"
        )
    if not can_access_judge_hub(user):
        abort(403)
    from flask import g

    db = g.db
    ex = _current_workspace_exercise(db, user)
    pair = _judge_planner_flow_action_bundle_row(db, user, ex, slot)
    if pair is None or ex is None:
        abort(404)
    bundle, action_row = pair
    unit_key = bundle.unit_level_key
    unit = next((x for x in UNIT_LEVELS if x["key"] == unit_key), None)
    unit_label_pf = (
        (unit.get("label") or "").strip()
        if unit
        else (bundle.unit_level_label or "").strip() or unit_key
    )
    path = _planner_bundle_file_abspath(action_row.file_relpath)
    pf_qs = _planner_flow_materials_query_kwargs(user)
    if path is None:
        return redirect(url_for("views.judge_planner_flow_materials", **pf_qs))
    ev = _evaluation_sheet_view_context(path)

    saved_payload = {}
    saved_updated_at = None
    saved_row_id = None
    canon = _planner_bundle_eval_canonical_saved(db, ex.id, action_row.id)

    def _load_payload(sr: PlannerFlowBundleEvalSavedResult | None) -> dict:
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
        saved_row_id = canon.id
    wf = _planner_flow_eval_list_viewer_ctx(user, canon)

    item_title = _planner_blob_display_filename(
        stored_title=action_row.title or "",
        relpath=action_row.file_relpath or "",
        fallback=f"قائمة تقييم إجراءات — {slot}",
    ).strip()
    eval_save_url = url_for(
        "views.judge_planner_flow_materials_action_save_results",
        slot=int(slot),
        **pf_qs,
    )
    eval_approve_url = url_for(
        "views.judge_planner_flow_materials_action_approve",
        slot=int(slot),
        **pf_qs,
    )
    eval_close_href = url_for("views.judge_planner_flow_materials", **pf_qs)

    shown_date = getattr(ex, "planned_start", None) or getattr(ex, "created_at", None)
    commander_name = "—"
    commander_row = (
        db.query(ExerciseRosterRow)
        .filter(
            ExerciseRosterRow.exercise_id == ex.id,
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
            ExerciseRosterRow.exercise_id == ex.id,
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
            item_id=action_row.id,
            evaluation_item_id=action_row.id,
            saved_row_id=saved_row_id,
            item_title=item_title,
            saved_payload=saved_payload,
            saved_updated_at=saved_updated_at,
            **wf,
            eval_close_href=eval_close_href,
            **ev,
            **_eval_crit_media_sheet_ctx(
                db,
                user,
                exercise=ex,
                list_item_id=None,
                bundle_action_eval_id=int(action_row.id),
                eval_can_edit=bool(wf.get("eval_can_edit")),
            ),
            unit_label=unit_label_pf or "—",
            shown_date=shown_date,
            commander_name=commander_name or "—",
            judge_name=judge_name or "—",
            has_saved_rows=bool(saved_payload and (saved_payload.get("rows") or [])),
            eval_save_url=eval_save_url,
            eval_approve_url=eval_approve_url,
            eval_chief_approve_url="",
            eval_chief_reopen_url="",
            eval_approve_incomplete=request.args.get("eval_approve_incomplete", type=int)
            == 1,
        ),
    )


@bp.route(
    "/judge/planner-flow-materials/action/<int:slot>/save-results",
    methods=["POST"],
)
def judge_planner_flow_materials_action_save_results(slot: int):
    user = get_current_user_optional()
    if not user:
        abort(403)
    if _planner_flow_is_readonly_oversee(user):
        abort(403)
    if not can_access_judge_hub(user):
        abort(403)
    from flask import g

    db = g.db
    ex = _current_workspace_exercise(db, user)
    pair = _judge_planner_flow_action_bundle_row(db, user, ex, slot)
    if pair is None or ex is None:
        abort(404)
    bundle, action_row = pair
    raw = (request.form.get("payload_json") or "").strip()
    if not raw:
        return redirect(
            url_for(
                "views.judge_planner_flow_materials_action_evaluate",
                slot=int(slot),
            )
        )
    if len(raw) > 250_000:
        abort(400)
    _planner_bundle_eval_commit_payload_save(
        db,
        user=user,
        action_row=action_row,
        bundle=bundle,
        current_exercise=ex,
        raw=raw,
    )
    return redirect(
        url_for("views.judge_planner_flow_materials_action_evaluate", slot=int(slot))
    )


@bp.route(
    "/judge/planner-flow-materials/action/<int:slot>/approve",
    methods=["POST"],
)
def judge_planner_flow_materials_action_approve(slot: int):
    user = get_current_user_optional()
    if not user:
        abort(403)
    if _planner_flow_is_readonly_oversee(user):
        abort(403)
    if not can_approve_evaluation_results(user):
        abort(403)
    if not can_access_judge_hub(user):
        abort(403)
    from flask import g

    db = g.db
    ex = _current_workspace_exercise(db, user)
    pair = _judge_planner_flow_action_bundle_row(db, user, ex, slot)
    if pair is None or ex is None:
        abort(404)
    _bundle, action_row = pair

    saved = _planner_bundle_eval_canonical_saved(db, ex.id, action_row.id)
    if saved is None or not (saved.payload_json or "").strip():
        abort(400)
    if not eval_judge_can_approve(saved):
        return redirect(
            url_for(
                "views.judge_planner_flow_materials_action_evaluate",
                slot=int(slot),
            )
        )
    rows = _parse_saved_eval_rows(saved.payload_json)
    if _evaluation_payload_has_empty_acquired_for_approve(rows):
        return redirect(
            url_for(
                "views.judge_planner_flow_materials_action_evaluate",
                slot=int(slot),
                eval_approve_incomplete=1,
            )
        )
    apply_judge_approve(saved, getattr(user, "id", None))
    db.commit()
    return redirect(
        url_for("views.judge_planner_flow_materials_action_evaluate", slot=int(slot))
    )


# مساحة التخطيط — عناصر الشريط (المعرّف، العنوان، أيقونة Font Awesome)
PLANNER_HUB_ITEMS: tuple[tuple[str, str, str], ...] = (
    ("new-flow", "المجرى وتقييم الإجراءات", "fa-diagram-project"),
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
    if slug_norm == "new-flow":
        return redirect(url_for("views.planner_flow_bundle_workspace"))
    if slug_norm == "new-evaluation-list":
        return redirect(url_for("views.admin_evaluation_lists_home"))
    if slug_norm == "evaluation-lists":
        return redirect(url_for("views.planner_evaluation_lists_home"))
    if slug_norm == "chat-rooms":
        return redirect(url_for("views.chat_rooms_list", from_planner=1))
    if slug_norm == "notifications-log":
        return redirect(url_for("views.notifications_log", from_planner=1))
    if slug_norm == "visual-documentation":
        return redirect(url_for("views.visual_documentation", from_planner=1))
    title = PLANNER_HUB_SLUGS.get(slug_norm)
    if not title:
        abort(404)
    return render_template(
        "planner_section_placeholder.html",
        **_ctx(
            user,
            section_title=title,
            section_slug=slug,
            **_hub_back_ctx_for_request_path(),
        ),
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
    units = list(UNIT_LEVELS)
    unit_rows = evaluation_unit_home_rows(db, ex, units)
    return render_template(
        "judge_evaluation_lists_home.html",
        **_ctx(
            user,
            has_exercise=ex is not None,
            exercise=ex,
            unit_levels=units,
            unit_rows=unit_rows,
            unit_totals=evaluation_unit_home_totals(unit_rows),
            unit_list_endpoint="views.planner_evaluation_lists",
            **_hub_back_ctx_for_request_path(),
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
        .order_by(
            _exercise_phase_order_expr(EvaluationListPdfItem.exercise_phase),
            EvaluationListPdfItem.sort_order,
            EvaluationListPdfItem.id,
        )
        .all()
    )
    item_ids = [int(it.id) for it in items]
    canonical_by_item = _evaluation_canonical_map_for_items(db, ex.id, item_ids)

    evaluation_lists_rows: list[dict] = []
    for it in items:
        s = canonical_by_item.get(int(it.id))
        evaluation_lists_rows.append(
            build_evaluation_list_row(
                item=it,
                saved=s,
                exercise=ex,
                open_href=url_for(
                    "views.planner_evaluation_list_file_viewer",
                    unit_key=unit_key,
                    item_id=it.id,
                ),
            )
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
            **_hub_back_ctx_for_request_path(),
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

    crit_edit = bool(
        not saved_is_approved and can_save_evaluation_results(user)
    )

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
            **_eval_crit_media_sheet_ctx(
                db,
                user,
                exercise=current_exercise,
                list_item_id=int(row.id),
                bundle_action_eval_id=None,
                eval_can_edit=crit_edit,
            ),
            unit_label=unit_label or "—",
            shown_date=shown_date,
            commander_name=commander_name or "—",
            judge_name=judge_name or "—",
            has_saved_rows=bool(saved_payload and (saved_payload.get("rows") or [])),
            eval_save_url=eval_save_url,
            eval_approve_url=eval_approve_url,
            show_eval_approve=show_eval_approve,
            eval_can_edit=crit_edit,
            eval_approve_incomplete=request.args.get("eval_approve_incomplete", type=int) == 1,
            **_hub_back_ctx_for_request_path(),
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
    ("planner-flow-materials", "المجرى وتقييم الإجراءات", "fa-diagram-project"),
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
    # للمحكم الفردي (غير إدارة النظام): أدوات محددة بترتيب ثابت
    from flask import g

    db = g.db
    ex = _current_workspace_exercise(db, user)
    _ensure_judge_roster_synced(db, user, ex)

    _judge_individual_slugs = (
        "planner-flow-materials",
        "evaluation-lists",
        "incomplete-tasks",
        "chat-rooms",
    )
    _hub_by_slug = {x[0]: x for x in JUDGE_HUB_ITEMS}
    items_src = (
        JUDGE_HUB_ITEMS
        if is_system_admin(user)
        else tuple(_hub_by_slug[s] for s in _judge_individual_slugs if s in _hub_by_slug)
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
    if slug == "planner-flow-materials":
        return redirect(url_for("views.judge_planner_flow_materials"))
    if slug == "chat-rooms":
        return redirect(url_for("views.chat_rooms_list", from_judge=1))
    if slug == "visual-documentation":
        return redirect(url_for("views.visual_documentation", from_judge=1))
    if slug == "notifications-log":
        return redirect(url_for("views.notifications_log", from_judge=1))
    if slug == "incomplete-tasks":
        from flask import g

        db = g.db
        ex = _admin_current_workspace_exercise(db, user)
        if ex is None:
            return render_template(
                "judge_incomplete_tasks.html",
                **_ctx(
                    user,
                    section_title=title,
                    has_exercise=False,
                    tasks=[],
                    **_hub_back_ctx_for_request_path(),
                ),
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

        # تقليص العرض للمحكم إلى وحدته المخصصة (إن وجدت)
        a = _judge_assignment_for_current_exercise(db, user, ex)
        assigned_uk = (getattr(a, "unit_level_key", "") or "").strip() if a else ""

        # overrides المحفوظة
        overrides = (
            db.query(JudgeIncompleteTaskStatus)
            .filter(JudgeIncompleteTaskStatus.exercise_id == ex.id, JudgeIncompleteTaskStatus.judge_id == judge_id)
            .all()
        )
        override_map: dict[tuple[str, str, int], JudgeIncompleteTaskStatus] = {}
        for o in overrides:
            override_map[(o.unit_level_key or "", o.exercise_phase or "", int(o.pair_index or 0))] = o

        eval_q = db.query(EvaluationListPdfItem).filter(EvaluationListPdfItem.exercise_id == ex.id)
        if assigned_uk and not is_system_admin(user):
            eval_q = eval_q.filter(EvaluationListPdfItem.unit_level_key == assigned_uk)
        eval_items = (
            eval_q.order_by(
                _exercise_phase_order_expr(EvaluationListPdfItem.exercise_phase),
                _unit_level_order_expr(EvaluationListPdfItem.unit_level_key),
                EvaluationListPdfItem.sort_order,
                EvaluationListPdfItem.id,
            )
            .all()
        )
        eval_item_ids = [int(it.id) for it in eval_items if getattr(it, "id", None) is not None]
        canonical_by_item = _evaluation_canonical_map_for_items(db, ex.id, eval_item_ids)

        phase_unit_counter: dict[tuple[str, str], int] = {}
        tasks: list[dict] = []
        for it in eval_items:
            eval_item_id = int(it.id)
            uk = (it.unit_level_key or "").strip()
            ph = _normalized_exercise_phase(getattr(it, "exercise_phase", None))
            phase_unit_counter[(uk, ph)] = phase_unit_counter.get((uk, ph), 0) + 1
            item_index = phase_unit_counter[(uk, ph)]
            canon = canonical_by_item.get(eval_item_id)
            is_done = bool(canon and getattr(canon, "is_approved", False))
            done_dt = None
            if canon is not None:
                done_dt = getattr(canon, "approved_at", None) if is_done else getattr(canon, "updated_at", None)
            auto_status = "done" if is_done else "ontime"
            ov = override_map.get((uk, ph, item_index))
            status_key = (ov.status_key if ov else "") or auto_status
            if status_key == "late":
                prio = "high"
            elif status_key == "done":
                prio = "low"
            else:
                prio = "medium"
            tasks.append(
                {
                    "task_name": (it.text or "قائمة تقييم").strip(),
                    "judge_name": judge_name_by_unit.get(uk, fallback_judge_name),
                    "done_dt": done_dt,
                    "priority_key": prio,
                    "status_key": status_key,
                    "unit_key": uk,
                    "unit_label": label_for_unit_level_key(uk) or uk,
                    "phase": ph,
                    "phase_ar": _phase_label_ar(ph),
                    "pair_index": item_index,
                    "dilemma_id": None,
                    "evaluation_item_id": eval_item_id,
                    "open_eval_href": url_for("views.judge_evaluation_list_file_viewer", unit_key=uk, item_id=eval_item_id),
                }
            )

        return render_template(
            "judge_incomplete_tasks.html",
            **_ctx(
                user,
                section_title=title,
                has_exercise=True,
                exercise=ex,
                tasks=tasks,
                **_hub_back_ctx_for_request_path(),
            ),
        )
    return render_template(
        "judge_section_placeholder.html",
        **_ctx(
            user,
            section_title=title,
            section_slug=slug,
            **_hub_back_ctx_for_request_path(),
        ),
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
        **_ctx(
            user,
            has_exercise=ex is not None,
            exercise=ex,
            notifications=rows,
            **_hub_back_ctx_for_request_path(),
            hub_from_form_param=_role_hub_from_form_param(),
        ),
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
        return redirect(url_for("views.notifications_log", **_role_hub_preserve_link_kwargs()))
    row = db.get(ExerciseNotification, nid)
    if (
        row
        and int(row.user_id) == int(user.id)
        and int(row.exercise_id) == int(ex.id)
    ):
        row.is_read = True
        db.add(row)
        db.commit()
    return redirect(url_for("views.notifications_log", **_role_hub_preserve_link_kwargs()))


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
    return redirect(url_for("views.notifications_log", **_role_hub_preserve_link_kwargs()))


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
            **_ctx(
                user,
                has_exercise=False,
                exercise=None,
                unit_levels=[],
                selected_unit_key="",
                docs=[],
                dilemmas=[],
                **_hub_back_ctx_for_request_path(),
                hub_from_form_param=_role_hub_from_form_param(),
            ),
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
            **_hub_back_ctx_for_request_path(),
            hub_from_form_param=_role_hub_from_form_param(),
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
        return redirect(url_for("views.visual_documentation", **_visual_doc_redirect_kwargs()))

    a = _judge_assignment_for_current_exercise(db, user, ex)
    assigned_uk = (getattr(a, "unit_level_key", "") or "").strip() if a else ""
    unit_key = normalize_unit_level_key(request.form.get("unit_key") or "")
    if assigned_uk and not is_system_admin(user):
        unit_key = assigned_uk
    if not unit_key:
        unit_key = assigned_uk

    f = request.files.get("media_file")
    if not f or not (getattr(f, "filename", "") or "").strip():
        return redirect(url_for("views.visual_documentation", **_visual_doc_redirect_kwargs(unit_key=unit_key)))
    raw_name = secure_filename(f.filename)
    suf = Path(raw_name).suffix.lower()
    if suf not in _VISUAL_ALLOWED_SUFFIX:
        return redirect(url_for("views.visual_documentation", **_visual_doc_redirect_kwargs(unit_key=unit_key)))
    data = f.read()
    if not data or len(data) > _VISUAL_MAX_UPLOAD_BYTES:
        return redirect(url_for("views.visual_documentation", **_visual_doc_redirect_kwargs(unit_key=unit_key)))

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

    return redirect(url_for("views.visual_documentation", **_visual_doc_redirect_kwargs(unit_key=unit_key)))


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


def _request_from_control_hub() -> bool:
    raw = (
        request.args.get("from")
        or request.args.get("from_control")
        or request.form.get("from_control")
        or ""
    ).strip().lower()
    return raw in ("1", "true", "yes", "control")


def _control_hub_back_ctx_always() -> dict:
    return {
        "hub_back_href": url_for("views.control_hub"),
        "hub_back_label": "العودة إلى مساحة السيطرة",
    }


def _control_hub_back_ctx() -> dict:
    return _resolve_role_hub_back_ctx()


def _control_hub_link_kwargs() -> dict:
    return _role_hub_preserve_link_kwargs()


def _request_from_judge_hub() -> bool:
    raw = (
        request.args.get("from")
        or request.args.get("from_judge")
        or request.form.get("from_judge")
        or ""
    ).strip().lower()
    return raw in ("1", "true", "yes", "judge")


def _request_from_analyst_hub() -> bool:
    raw = (
        request.args.get("from")
        or request.args.get("from_analyst")
        or request.form.get("from_analyst")
        or ""
    ).strip().lower()
    return raw in ("1", "true", "yes", "analyst")


def _request_from_planner_hub() -> bool:
    raw = (
        request.args.get("from")
        or request.args.get("from_planner")
        or request.form.get("from_planner")
        or ""
    ).strip().lower()
    return raw in ("1", "true", "yes", "planner")


def _request_from_chief_judge_hub() -> bool:
    raw = (
        request.args.get("from")
        or request.args.get("from_chief_judge")
        or request.form.get("from_chief_judge")
        or ""
    ).strip().lower()
    return raw in ("1", "true", "yes", "chief_judge", "chief-judge", "chiefjudge")


def _judge_hub_back_ctx_always() -> dict:
    return {
        "hub_back_href": url_for("views.judge_hub"),
        "hub_back_label": "العودة إلى مساحة المحكمين",
    }


def _analyst_hub_back_ctx_always() -> dict:
    return {
        "hub_back_href": url_for("views.analyst_hub"),
        "hub_back_label": "العودة إلى مساحة المحللين",
    }


def _planner_hub_back_ctx_always() -> dict:
    return {
        "hub_back_href": url_for("views.planner_hub"),
        "hub_back_label": "العودة إلى مساحة التخطيط",
    }


def _chief_judge_hub_back_ctx_always() -> dict:
    return {
        "hub_back_href": url_for("views.chief_judge_hub"),
        "hub_back_label": "العودة إلى مساحة كبير المحكمين",
    }


def _resolve_role_hub_back_ctx() -> dict:
    """سياق العودة عند الدخول من مساحة دور عبر معامل from_* (صفحات مشتركة)."""
    if _request_from_control_hub():
        return _control_hub_back_ctx_always()
    if _request_from_chief_judge_hub():
        return _chief_judge_hub_back_ctx_always()
    if _request_from_judge_hub():
        return _judge_hub_back_ctx_always()
    if _request_from_planner_hub():
        return _planner_hub_back_ctx_always()
    if _request_from_analyst_hub():
        return _analyst_hub_back_ctx_always()
    return {}


def _hub_back_ctx_for_request_path() -> dict:
    """سياق العودة حسب مسار الطلب الحالي أو معامل from_*."""
    p = (request.path or "").lower()
    if p.startswith("/control"):
        return _control_hub_back_ctx_always()
    if p.startswith("/chief-judge"):
        return _chief_judge_hub_back_ctx_always()
    if p.startswith("/judge"):
        return _judge_hub_back_ctx_always()
    if p.startswith("/analyst"):
        return _analyst_hub_back_ctx_always()
    if p.startswith("/planner"):
        return _planner_hub_back_ctx_always()
    return _resolve_role_hub_back_ctx()


def _role_hub_preserve_link_kwargs() -> dict:
    kw: dict = {}
    if _request_from_control_hub():
        kw["from_control"] = 1
    if _request_from_chief_judge_hub():
        kw["from_chief_judge"] = 1
    if _request_from_judge_hub():
        kw["from_judge"] = 1
    if _request_from_planner_hub():
        kw["from_planner"] = 1
    if _request_from_analyst_hub():
        kw["from_analyst"] = 1
    return kw


def _role_hub_from_form_param() -> str | None:
    if _request_from_control_hub():
        return "from_control"
    if _request_from_chief_judge_hub():
        return "from_chief_judge"
    if _request_from_judge_hub():
        return "from_judge"
    if _request_from_planner_hub():
        return "from_planner"
    if _request_from_analyst_hub():
        return "from_analyst"
    return None


def _visual_doc_redirect_kwargs(**extra) -> dict:
    kw = dict(extra)
    kw.update(_role_hub_preserve_link_kwargs())
    return kw


def _build_control_evaluation_lists_status(db, user: User) -> dict:
    """موقف قوائم التقييم مجمّع حسب مراحل التمرين (تبويب لكل مرحلة)."""
    ex0 = _current_workspace_exercise(db, user)
    if ex0 is None:
        return {"has_exercise": False}
    ex = db.query(Exercise).filter(Exercise.id == ex0.id).first()
    if ex is None:
        return {"has_exercise": False}

    items = (
        db.query(EvaluationListPdfItem)
        .filter(EvaluationListPdfItem.exercise_id == ex.id)
        .order_by(
            _unit_level_order_expr(EvaluationListPdfItem.unit_level_key),
            _exercise_phase_order_expr(EvaluationListPdfItem.exercise_phase),
            EvaluationListPdfItem.sort_order,
            EvaluationListPdfItem.id,
        )
        .all()
    )
    item_ids = [int(it.id) for it in items if getattr(it, "id", None) is not None]
    canonical_by_item = (
        _evaluation_canonical_map_for_items(db, int(ex.id), item_ids) if item_ids else {}
    )

    phase_order = {key: idx for idx, key in enumerate(exercise_phase_keys())}
    by_phase: dict[str, list[dict]] = {}

    for it in items:
        uk = (it.unit_level_key or "").strip()
        phase_key = _normalized_exercise_phase(getattr(it, "exercise_phase", None))
        saved = canonical_by_item.get(int(it.id))
        by_phase.setdefault(phase_key, []).append(
            {
                **build_evaluation_list_row(
                    item=it,
                    saved=saved,
                    exercise=ex,
                    open_href=url_for(
                        "views.control_evaluation_list_file_viewer",
                        unit_key=uk,
                        item_id=int(it.id),
                    ),
                ),
                "phase_key": phase_key,
                "phase_label": _phase_label_ar(phase_key),
                "workflow_label": eval_workflow_label_ar(saved),
                "unit_key": uk,
                "unit_label": label_for_unit_level_key(uk) or uk or "—",
            }
        )

    unit_order = {row.get("key"): idx for idx, row in enumerate(UNIT_LEVELS)}
    phase_keys_seen = set(by_phase.keys())
    ordered_phase_keys: list[str] = list(exercise_phase_keys())
    for pk in sorted(phase_keys_seen - set(ordered_phase_keys), key=lambda k: phase_order.get(k, 99)):
        ordered_phase_keys.append(pk)

    phase_tabs: list[dict] = []
    for pk in ordered_phase_keys:
        phase_rows = by_phase.get(pk, [])
        by_unit: dict[str, list[dict]] = {}
        for row in phase_rows:
            uk = (row.get("unit_key") or "").strip()
            by_unit.setdefault(uk, []).append(row)
        unit_tabs: list[dict] = []
        for uk in sorted(
            by_unit.keys(),
            key=lambda k: (unit_order.get(k, len(unit_order)), label_for_unit_level_key(k) or k),
        ):
            unit_rows = by_unit[uk]
            unit_tabs.append(
                {
                    "unit_key": uk,
                    "unit_label": label_for_unit_level_key(uk) or uk or "—",
                    "rows": unit_rows,
                    "total_count": len(unit_rows),
                }
            )
        phase_tabs.append(
            {
                "phase_key": pk,
                "phase_label": _phase_label_ar(pk),
                "unit_tabs": unit_tabs,
                "total_count": len(phase_rows),
            }
        )

    return {
        "has_exercise": True,
        "phase_tabs": phase_tabs,
    }


def _build_control_positives_negatives(db, user: User) -> dict:
    """إيجابيات وسلبيات من الملاحظات الكتابية في قوائم التقييم بعد حفظ واعتماد المحكم."""
    ex0 = _current_workspace_exercise(db, user)
    if ex0 is None:
        return {"has_exercise": False}
    ex = db.query(Exercise).filter(Exercise.id == ex0.id).first()
    if ex is None:
        return {"has_exercise": False}

    items = (
        db.query(EvaluationListPdfItem)
        .filter(EvaluationListPdfItem.exercise_id == ex.id)
        .order_by(
            _unit_level_order_expr(EvaluationListPdfItem.unit_level_key),
            _exercise_phase_order_expr(EvaluationListPdfItem.exercise_phase),
            EvaluationListPdfItem.sort_order,
            EvaluationListPdfItem.id,
        )
        .all()
    )
    item_ids = [int(it.id) for it in items if getattr(it, "id", None) is not None]
    canonical_by_item = (
        _evaluation_canonical_map_for_items(db, int(ex.id), item_ids) if item_ids else {}
    )

    positive_notes: list[dict] = []
    negative_notes: list[dict] = []
    lists_with_notes: set[int] = set()
    n_approved = 0

    for it in items:
        saved = canonical_by_item.get(int(it.id))
        if saved is None or not eval_judge_approved(saved):
            continue
        if not (getattr(saved, "payload_json", "") or "").strip():
            continue
        n_approved += 1
        uk = (it.unit_level_key or "").strip()
        unit_label = label_for_unit_level_key(uk) or uk or "—"
        list_title = (it.text or "قائمة تقييم").strip()
        phase_label = _phase_label_ar(getattr(it, "exercise_phase", None))
        open_href = url_for(
            "views.control_evaluation_list_file_viewer",
            unit_key=uk,
            item_id=int(it.id),
        )
        list_has_note = False
        for row in _parse_saved_eval_rows(saved.payload_json):
            if not isinstance(row, dict):
                continue
            note = (row.get("notes") or "").strip()
            if not note:
                continue
            list_has_note = True
            pct = _eval_row_score_pct(row)
            element = (row.get("element") or "").strip() or "—"
            entry = {
                "list_title": list_title,
                "unit_label": unit_label,
                "phase_label": phase_label,
                "element": element[:200],
                "note": note,
                "pct": pct,
                "grade": grade_label_from_percent(pct) if pct is not None else "—",
                "open_href": open_href,
                "approved_at": getattr(saved, "approved_at", None),
            }
            band = _pct_status_band(pct)
            if band == "high":
                positive_notes.append(entry)
            elif band == "low":
                negative_notes.append(entry)
        if list_has_note:
            lists_with_notes.add(int(it.id))

    positive_notes.sort(
        key=lambda x: (
            -(float(x["pct"]) if x.get("pct") is not None else -1.0),
            x["unit_label"],
            x["list_title"],
        )
    )
    negative_notes.sort(
        key=lambda x: (
            (float(x["pct"]) if x.get("pct") is not None else 101.0),
            x["unit_label"],
            x["list_title"],
        )
    )

    return {
        "has_exercise": True,
        "exercise": ex,
        "positive_notes": positive_notes,
        "negative_notes": negative_notes,
        "n_positive": len(positive_notes),
        "n_negative": len(negative_notes),
        "n_lists_with_notes": len(lists_with_notes),
        "n_eval_lists": len(items),
        "n_approved_eval_lists": n_approved,
    }


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
            "phase_summary": {"phase_summaries": [], "exercise_pct": None, "exercise_grade": "—", "phase_count": 0},
            "donut_conic_gradient": "conic-gradient(var(--tint-200) 0 100%)",
            "unit_detail_rows": [],
            "unit_detail_phase_headers": [lbl for _, lbl in _CONTROL_REPORT_PHASE_COLUMNS],
            "unit_detail_phase_max_dots": _control_phase_max_dot_counts([]),
            "unit_detail_list_number_row": [],
            "grade_legend": _control_report_grade_legend(),
            "n_saved_eval": 0,
            "n_eval_lists_total": 0,
            "radar_series": [],
        }

    ex = db.query(Exercise).filter(Exercise.id == ex0.id).first()
    eval_items = (
        db.query(EvaluationListPdfItem)
        .filter(EvaluationListPdfItem.exercise_id == ex0.id)
        .order_by(
            _exercise_phase_order_expr(EvaluationListPdfItem.exercise_phase),
            _unit_level_order_expr(EvaluationListPdfItem.unit_level_key),
            EvaluationListPdfItem.sort_order,
            EvaluationListPdfItem.id,
        )
        .all()
    )

    item_ids = [int(it.id) for it in eval_items if getattr(it, "id", None) is not None]
    canon_by_item = _evaluation_canonical_map_for_items(db, ex0.id, item_ids) if item_ids else {}
    saved_by_item = {
        iid: sr
        for iid, sr in canon_by_item.items()
        if (getattr(sr, "payload_json", None) or "").strip()
    }
    approved_by_item = {iid: sr for iid, sr in canon_by_item.items() if bool(getattr(sr, "is_approved", False))}

    n_eval_lists = len(eval_items)
    n_saved = len(saved_by_item)
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

    phase_summary = _phase_summary_from_eval_items(eval_items, saved_by_item)
    distribution = _distribution_from_phase_summary(phase_summary)
    donut_conic_gradient = _donut_conic_gradient_from_distribution(distribution)

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

    # ألوان هادئة موحّدة مع تقرير السيطرة (تُطبَّق أيضاً عبر CSS للأعمدة)
    palette = [
        "#6b8cae",
        "#7a9a7e",
        "#9a8bb8",
        "#b89a6e",
        "#5f9a9f",
        "#a67f72",
        "#8a8f7a",
        "#7d8fa8",
    ]
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
    group_scores = []
    for r in unit_avg_rows:
        group_scores.append(
            {
                "label": r["label"],
                "value": r["value"],
                "color": r["color"],
            }
        )

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
        {"label": "قيد التقييم", "value": f"{pending_pct}%", "hint": "من إجمالي التقييم", "icon": "fa-hexagon-nodes", "tone": "violet"},
        {"label": "نسبة الإستكمال", "value": f"{done_pct}%", "hint": "من إجمالي التقييم", "icon": "fa-circle-check", "tone": "purple"},
        {"label": "أقل مجموعة", "value": f"{int(bottom_unit['value']) if bottom_unit else 0}%", "hint": (bottom_unit["label"] if bottom_unit else "—"), "icon": "fa-arrow-down", "tone": "red"},
        {"label": "أعلى مجموعة", "value": f"{int(top_unit['value']) if top_unit else 0}%", "hint": (top_unit["label"] if top_unit else "—"), "icon": "fa-trophy", "tone": "cyan"},
        {"label": "المتوسط العام", "value": f"{overall_avg_i}%", "hint": "أداء التمرين", "icon": "fa-chart-line", "tone": "green"},
        {"label": "معايير التقييم", "value": str(criteria_count), "hint": "إجمالي المعايير", "icon": "fa-list", "tone": "indigo"},
    ]

    unit_detail_rows = _control_build_unit_detail_rows(
        db, ex0.id, eval_items, saved_by_item
    )
    unit_detail_phase_max_dots = _control_phase_max_dot_counts(unit_detail_rows)
    unit_detail_list_number_row = _control_build_list_number_row(unit_detail_phase_max_dots)

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
        "phase_summary": phase_summary,
        "donut_conic_gradient": donut_conic_gradient,
        "table_rows": table_rows,
        "table_headers": table_headers,
        "unit_detail_rows": unit_detail_rows,
        "unit_detail_phase_headers": [lbl for _, lbl in _CONTROL_REPORT_PHASE_COLUMNS],
        "unit_detail_phase_max_dots": unit_detail_phase_max_dots,
        "unit_detail_list_number_row": unit_detail_list_number_row,
        "grade_legend": _control_report_grade_legend(),
        "n_saved_eval": n_saved,
        "n_eval_lists_total": n_eval_lists,
        "radar_series": radar_series,
    }


@bp.route("/control/evaluation-lists/<unit_key>/view/<int:item_id>", methods=["GET"])
def control_evaluation_list_file_viewer(unit_key: str, item_id: int):
    """عرض قائمة تقييم للسيطرة (قراءة فقط) من تقرير النتائج."""
    user = get_current_user_optional()
    if not user:
        return redirect(f"/login?next=/control/evaluation-lists/{unit_key}/view/{item_id}")
    if not can_access_control_hub(user):
        abort(403)
    unit = next((x for x in UNIT_LEVELS if x["key"] == unit_key), None)
    if not unit:
        abort(404)
    from flask import g

    db = g.db
    row = db.get(EvaluationListPdfItem, item_id)
    ex = _current_workspace_exercise(db, user)
    if not row or row.unit_level_key != unit_key:
        abort(404)
    if ex is not None and row.exercise_id not in (None, ex.id):
        abort(404)
    if not (row.pdf_relpath or "").strip():
        abort(404)
    fspath = _evaluation_list_file_abspath(row.pdf_relpath)
    if fspath is None:
        abort(404)

    ev = _evaluation_sheet_view_context(fspath)
    saved_payload = {}
    saved_updated_at = None
    saved_row_id = None
    saved_is_approved = False
    saved_approved_at = None
    if ex is not None:
        saved_row = _evaluation_canonical_map_for_items(db, ex.id, [int(row.id)]).get(int(row.id))
        if saved_row and (saved_row.payload_json or "").strip():
            try:
                saved_payload = json.loads(saved_row.payload_json)
            except Exception:
                saved_payload = {}
            saved_updated_at = saved_row.updated_at
            saved_row_id = saved_row.id
            saved_is_approved = bool(getattr(saved_row, "is_approved", False))
            saved_approved_at = getattr(saved_row, "approved_at", None)

    unit_label = (unit.get("label") or "").strip() if isinstance(unit, dict) else ""
    shown_date = None
    commander_name = "—"
    judge_name = "—"
    if ex is not None:
        shown_date = getattr(ex, "planned_start", None) or getattr(ex, "created_at", None)
        commander_row = (
            db.query(ExerciseRosterRow)
            .filter(
                ExerciseRosterRow.exercise_id == ex.id,
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
                ExerciseRosterRow.exercise_id == ex.id,
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
            close_href=url_for("views.control_hub_section", slug="evaluation-lists-status"),
            close_label="العودة إلى موقف القوائم",
            **_control_hub_back_ctx_always(),
            saved_row_id=saved_row_id,
            saved_payload=saved_payload,
            saved_updated_at=saved_updated_at,
            saved_is_approved=saved_is_approved,
            saved_approved_at=saved_approved_at,
            unit_label=unit_label or "—",
            shown_date=shown_date,
            commander_name=commander_name,
            judge_name=judge_name,
            **ev,
            **_eval_crit_media_sheet_ctx(
                db,
                user,
                exercise=ex,
                list_item_id=int(row.id),
                bundle_action_eval_id=None,
                eval_can_edit=False,
            ),
        ),
    )


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
        return redirect(url_for("views.chat_rooms_list", from_control=1))
    if slug_norm == "notifications-log":
        return redirect(url_for("views.notifications_log", from_control=1))
    if slug_norm in ("visual-doc-status", "visual-documentation"):
        return redirect(url_for("views.visual_documentation", from_control=1))
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
                **_control_hub_back_ctx_always(),
            ),
        )
    if slug_norm == "evaluation-lists-status":
        from flask import g

        status = _build_control_evaluation_lists_status(g.db, user)
        if not status.get("has_exercise"):
            return render_template(
                "control_evaluation_lists_status.html",
                **_ctx(
                    user,
                    section_title=title,
                    has_exercise=False,
                    **_control_hub_back_ctx_always(),
                ),
            )
        return render_template(
            "control_evaluation_lists_status.html",
            **_ctx(
                user,
                section_title=title,
                **_control_hub_back_ctx_always(),
                **status,
            ),
        )
    if slug_norm == "top-positives-negatives":
        from flask import g

        pn = _build_control_positives_negatives(g.db, user)
        if not pn.get("has_exercise"):
            return render_template(
                "control_positives_negatives.html",
                **_ctx(
                    user,
                    section_title=title,
                    has_exercise=False,
                    **_control_hub_back_ctx_always(),
                ),
            )
        return render_template(
            "control_positives_negatives.html",
            **_ctx(
                user,
                section_title=title,
                **_control_hub_back_ctx_always(),
                **pn,
            ),
        )
    return render_template(
        "control_section_placeholder.html",
        **_ctx(
            user,
            section_title=title,
            section_slug=slug,
            **_control_hub_back_ctx_always(),
        ),
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
    add("إدارة النظام", "إدارة تقييمات الوحدات", "/admin/evaluation-lists/saved-results", "إدارة النظام", "نتائج التقييم المحفوظة والمعتمدة.", "عرض، حذف نتيجة محفوظة.", "تطابق الحالة مع اعتماد المحكم.")
    add("إدارة النظام", "الربط المتكامل", "/admin/dilemmas-evaluation-unit-report", "إدارة النظام", "تقرير يربط قائمة الوحدة المتدربة بقائمة المحكمين حسب مستوى الوحدة.", "مراجعة أسماء المتدربين والمحكمين حسب المستوى.", "تطابق مستوى الوحدة بين القائمتين.")
    add("إدارة النظام", "تنظيم المعركة", "/admin/battle-organization", "إدارة النظام", "رموز الوحدات، بيانات المتدربين، بيانات المحكمين، المواقع/التنظيم.", "تعبئة وحفظ تنظيم المعركة.", "انعكاس البيانات في الصورة العامة.")
    add("إدارة النظام", "إدارة المستخدمين", "/admin/users", "إدارة النظام", "المستخدمون، الأدوار، الحالة، كلمة المرور.", "إضافة، تعديل، تعطيل/حذف.", "تطبيق الصلاحيات بعد التعديل.")
    add("إدارة النظام", "غرف المحادثة", "/admin/chat-rooms", "إدارة النظام", "غرف حسب التمرين، النوع، مستوى الوحدة، الأعضاء.", "إنشاء غرفة، إضافة/إزالة أعضاء، أرشفة.", "ظهور الغرفة للأعضاء فقط.")
    add("إدارة النظام", "Checklist محتويات النظام", "/admin/system-checklist", "إدارة النظام", "جدول spreadsheet لمراجعة صفحات ووظائف النظام.", "تحديد المراجعة، البحث، الطباعة/التصدير من المتصفح.", "اكتمال مراجعة جميع الصفوف.")
    add("المحكمين", "مساحة المحكمين", "/judge", "محكم / إدارة النظام", "أوامر المحكمين: المعاضل، التقييم، المحادثات، المهام، التوثيق، الإشعارات.", "فتح أقسام المحكم حسب الصلاحية.", "ظهور الأقسام المطلوبة للمحكم.")
    add("المحكمين", "قوائم المعاضل", "/judge/dilemmas", "محكم", "مستويات الوحدة المتاحة وملفات PDF للمعاضل.", "فتح القوائم وملفات PDF.", "حصر المحكم في وحدته المخصصة.")
    add("المحكمين", "قوائم التقييم", "/judge/evaluation-lists", "محكم", "قوائم Excel، إدخال المكتسبة، النسبة، النتيجة، ملاحظات المحكم.", "حفظ النتيجة واعتمادها.", "ظهور النتيجة المعتمدة في المحللين.")
    add("المحكمين", "مهام غير مكتملة", "/judge/incomplete-tasks", "محكم", "مهام قوائم التقييم حسب مرحلة التمرين ثم مستوى الوحدة، الحالة، الأولوية، المكلف.", "تغيير الحالة وفتح قائمة التقييم.", "تطابق اسم المحكم مع قائمة المحكمين.")
    add("المحكمين", "التوثيق المرئي", "/visual-documentation", "محكم / سيطرة / تخطيط / إدارة", "رفع ملف، تصوير بالكاميرا، تسجيل صوتي، وصف، موقع، ربط بمعضلة.", "رفع صورة/فيديو/صوت وفتح السجل.", "ظهور المادة في سجل التوثيق.")
    add("المحادثات", "غرف المحادثة", "/chat-rooms", "الأعضاء حسب الغرفة", "قائمة غرف المستخدم، آخر نشاط، نوع الغرفة.", "فتح غرفة وإرسال رسائل/ملفات.", "وصول الإشعار للعضو عند رسالة جديدة.")
    add("المحادثات", "تفاصيل غرفة", "/chat-rooms/<id>", "الأعضاء حسب الغرفة", "رسائل نصية، ملفات، قراءات الأعضاء.", "إرسال رسالة، رفع ملف، تنزيل ملف.", "حفظ الرسالة وظهور حالة القراءة.")
    add("المحللين", "مساحة المحللين", "/analyst", "محلل / إدارة النظام", "أدوات التحليل: النتائج، الإيجابيات والسلبيات، تحليل المحكمين، المراجعة.", "فتح أدوات التحليل.", "ظهور الأدوات حسب صلاحية المحلل.")
    add("المحللين", "عرض نتائج التقييم", "/analyst/evaluation-results", "محلل", "مصفوفة نتائج قوائم التقييم المعتمدة حسب مستوى الوحدة والأهداف.", "عرض الحالة والقوائم غير المعبأة.", "عدم إدراج النتائج غير المعتمدة.")
    add("المحللين", "عرض الإيجابيات والسلبيات", "/analyst/positives-negatives", "محلل", "نقاط الاستدامة والتطوير حسب مستوى الوحدة، وملاحظات المحكمين.", "اختيار مستوى الوحدة، عرض الإيجابيات أعلى والسلبيات أسفل.", "ظهور لا يوجد ملاحظات عند عدم وجود ملاحظات.")
    add("المحللين", "تحليل وتقييم المحكمين", "/analyst/judges-eval-analysis", "محلل", "تحليل إنجاز المحكمين، القوائم المعتمدة وغير المعتمدة.", "عرض وفتح تقييمات المحكمين.", "تطابق بيانات الاعتماد مع المحكم.")
    add("التخطيط", "مساحة التخطيط", "/planner", "مخطط / إدارة النظام", "قوائم التقييم، المحادثات، المهام، معلومات التمرين.", "فتح أقسام التخطيط وإدخال نتائج عند السماح.", "التحقق من صلاحيات التخطيط.")
    add("التخطيط", "قوائم المعاضل — إدراج PDF", "/admin/dilemmas", "مخطط / إدارة النظام", "رفع ملفات PDF حسب مستوى الوحدة ومرحلة التمرين.", "رفع، فتح، حذف، تغيير المرحلة، مسح المستوى.", "الدخول من مساحة التخطيط؛ عرض المحكم من مساحة المحكمين.")
    add("التخطيط", "قوائم التقييم — إدراج Excel", "/admin/evaluation-lists", "مخطط / إدارة النظام", "رفع ملفات Excel حسب مستوى الوحدة ومرحلة التمرين.", "رفع، فتح، حذف، تغيير المرحلة، مسح المستوى.", "الدخول من مساحة التخطيط؛ إدخال النتائج للمحكم من مساحة المحكمين.")
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
    custom_rows_raw = (request.form.get("checklist_rows_json") or "").strip()
    rows = _system_checklist_rows()
    if custom_rows_raw:
        try:
            payload = json.loads(custom_rows_raw)
        except Exception:
            payload = []
        if isinstance(payload, list):
            parsed_rows: list[dict] = []
            for item in payload[:500]:
                if not isinstance(item, dict):
                    continue
                parsed_rows.append(
                    {
                        "idx": len(parsed_rows) + 1,
                        "reviewed": bool(item.get("reviewed")),
                        "stage": str(item.get("stage") or "")[:500],
                        "page": str(item.get("page") or "")[:500],
                        "path": str(item.get("path") or "")[:500],
                        "role": str(item.get("role") or "")[:500],
                        "contents": str(item.get("contents") or "")[:2000],
                        "actions": str(item.get("actions") or "")[:2000],
                        "check": str(item.get("check") or "")[:2000],
                    }
                )
            if parsed_rows:
                rows = parsed_rows
    for r in rows:
        r["reviewed"] = bool(r.get("reviewed")) or str(r.get("idx")) in checked
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

    def _render_create_page(*, error: str = "", success: str = ""):
        ex_cur = _admin_current_workspace_exercise(db, user)
        if request.method == "GET":
            form_prefill = _empty_create_form_prefill()
            if ex_cur:
                from_ex = _prefill_create_form_from_exercise(ex_cur)
                for key in (
                    "exercise_type",
                    "exercise_level",
                    "mission",
                    "planned_start",
                    "planned_end",
                ):
                    if from_ex.get(key):
                        form_prefill[key] = from_ex[key]
        else:
            form_prefill = _prefill_create_form_from_request()
        from flask import make_response

        resp = make_response(
            render_template(
                "admin_exercise_create.html",
                **_ctx(
                    user,
                    error=error,
                    success=success,
                    export_dir=str(export_directory()),
                    form_prefill=form_prefill,
                    has_current_exercise=ex_cur is not None,
                    form_build_tag="20260516-create-v2",
                    **_admin_exercise_form_ctx(),
                ),
            )
        )
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        return resp

    if request.method == "GET":
        qerr = (request.args.get("err") or "").strip()
        qok = (request.args.get("ok") or "").strip()
        return _render_create_page(error=qerr, success=qok)

    def _pick(field: str, allowed: list[str]) -> str | None:
        v = (request.form.get(field) or "").strip()
        return v if v in allowed else None

    def _text(field: str, max_len: int) -> str | None:
        v = (request.form.get(field) or "").strip()
        return v[:max_len] if v else None

    def _parse_dt_local(field: str):
        raw = (request.form.get(field) or "").strip()
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except Exception:
            return None

    title = _text("exercise_name", 500)
    et = _pick("exercise_type", ex_opts.EXERCISE_TYPES)
    el = _pick("exercise_level", ex_opts.EXERCISE_LEVELS)
    mission = _pick("mission", ex_opts.MISSIONS)
    unit = _text("trained_unit", 400)
    loc = _text("location_label", 400)
    planned_start = _parse_dt_local("planned_start")
    planned_end = _parse_dt_local("planned_end")

    if planned_start and planned_end and planned_end < planned_start:
        return _render_create_page(error="تاريخ/وقت النهاية يجب أن يكون بعد البداية."), 400

    missing: list[str] = []
    if not title:
        missing.append("اسم التمرين")
    if not et:
        missing.append("نوع التمرين")
    if not el:
        missing.append("مستوى التمرين")
    if not mission:
        missing.append("المهمة")
    if not unit:
        missing.append("اسم الوحدة المتدربة")
    if not loc:
        missing.append("مكان التمرين")
    if missing:
        return (
            _render_create_page(
                error="يرجى تعبئة الحقول التالية: " + "، ".join(missing)
            ),
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


@bp.route("/admin/exercises/finish", methods=["GET", "POST"])
def admin_exercise_finish():
    """إنهاء التمرين الحالي: أرشفة JSON كامل ثم مسح بيانات التمرين (يبقى بنك المعلومات)."""
    user = get_current_user_optional()
    if not user:
        return redirect("/login?next=/admin/exercises/create")
    if not can_manage_users(user):
        abort(403)
    from flask import g
    from urllib.parse import quote

    db = g.db
    ex = _admin_current_workspace_exercise(db, user)
    if ex is None:
        return redirect(
            "/admin/exercises/create?err="
            + quote("لا يوجد تمرين حالي لإنهائه.", safe="")
        )
    pwd = (request.form.get("system_admin_password") or "").strip()
    if not pwd:
        return redirect(
            "/admin/exercises/create?err="
            + quote("يجب إدخال كلمة مرور إدارة النظام لإنهاء التمرين.", safe="")
        )
    if not verify_password(pwd, user.password_hash):
        return redirect(
            "/admin/exercises/create?err="
            + quote("كلمة مرور إدارة النظام غير صحيحة.", safe="")
        )
    try:
        path = archive_and_clear_current_exercise(db, ex.id, finished_by_id=user.id)
        if path is None:
            db.rollback()
            return redirect(
                "/admin/exercises/create?err="
                + quote("تعذر أرشفة التمرين الحالي.", safe="")
            )
        db.commit()
    except Exception:
        db.rollback()
        return redirect(
            "/admin/exercises/create?err="
            + quote("حدث خطأ أثناء إنهاء التمرين.", safe="")
        )
    msg = f"تم إنهاء التمرين وحفظه في: {path}"
    return redirect("/admin/exercises/create?ok=" + quote(msg, safe=""))


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
    _require_planner_hub_catalog_access(user)
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
    admin_crit = bool(not saved_is_approved and can_save_evaluation_results(user))
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
            **_eval_crit_media_sheet_ctx(
                db,
                user,
                exercise=current_exercise,
                list_item_id=int(row.id),
                bundle_action_eval_id=None,
                eval_can_edit=admin_crit,
            ),
            unit_label=unit_label or "—",
            shown_date=shown_date,
            commander_name=commander_name or "—",
            judge_name=judge_name or "—",
            has_saved_rows=bool(saved_payload and (saved_payload.get("rows") or [])),
            eval_can_edit=admin_crit,
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
            **_eval_crit_media_sheet_ctx(
                db,
                user,
                exercise=current_exercise,
                list_item_id=int(row.id),
                bundle_action_eval_id=None,
                eval_can_edit=False,
            ),
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
    _require_planner_hub_catalog_access(user)
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
    _require_planner_hub_catalog_access(user)
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
    _require_planner_hub_catalog_access(user)
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
    _require_planner_hub_catalog_access(user)
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
    units = [u for u in UNIT_LEVELS if not assigned_uk or u.get("key") == assigned_uk]
    unit_rows = evaluation_unit_home_rows(db, ex, units)
    return render_template(
        "judge_evaluation_lists_home.html",
        **_ctx(
            user,
            has_exercise=ex is not None,
            exercise=ex,
            unit_levels=units,
            unit_rows=unit_rows,
            unit_totals=evaluation_unit_home_totals(unit_rows),
            unit_list_endpoint="views.judge_evaluation_lists",
            **_hub_back_ctx_for_request_path(),
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
            **_hub_back_ctx_for_request_path(),
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
        .order_by(
            _exercise_phase_order_expr(DilemmaItem.exercise_phase),
            DilemmaItem.sort_order,
            DilemmaItem.id,
        )
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
        .order_by(
            _exercise_phase_order_expr(EvaluationListPdfItem.exercise_phase),
            EvaluationListPdfItem.sort_order,
            EvaluationListPdfItem.id,
        )
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
        s = canonical_by_item.get(int(it.id))
        evaluation_lists_rows.append(
            build_evaluation_list_row(
                item=it,
                saved=s,
                exercise=ex,
                open_href=url_for(
                    "views.judge_evaluation_list_file_viewer",
                    unit_key=unit_key,
                    item_id=it.id,
                ),
            )
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
            **_hub_back_ctx_for_request_path(),
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
        saved_row_id = canon.id

    eval_save_url = url_for("views.judge_evaluation_list_save_results", unit_key=unit_key, item_id=item_id)
    eval_approve_url = url_for("views.judge_evaluation_list_approve", unit_key=unit_key, item_id=item_id)
    wf = _eval_list_viewer_ctx(user, canon)

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
            **wf,
            **ev,
            **_eval_crit_media_sheet_ctx(
                db,
                user,
                exercise=current_exercise,
                list_item_id=int(row.id),
                bundle_action_eval_id=None,
                eval_can_edit=bool(wf.get("eval_can_edit")),
            ),
            unit_label=unit_label or "—",
            shown_date=shown_date,
            commander_name=commander_name or "—",
            judge_name=judge_name or "—",
            has_saved_rows=bool(saved_payload and (saved_payload.get("rows") or [])),
            eval_save_url=eval_save_url,
            eval_approve_url=eval_approve_url,
            eval_chief_approve_url="",
            eval_chief_reopen_url="",
            eval_approve_incomplete=request.args.get("eval_approve_incomplete", type=int) == 1,
            **_hub_back_ctx_for_request_path(),
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
    if not eval_judge_can_approve(saved):
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
    apply_judge_approve(saved, getattr(user, "id", None))
    db.commit()
    return redirect(url_for("views.judge_evaluation_list_file_viewer", unit_key=unit_key, item_id=item_id))


@bp.route("/eval-criterion-media/<int:media_id>/stream", methods=["GET"])
def eval_criterion_media_stream(media_id: int):
    """تسليم ملف توثيق (صورة أو فيديو) لمستخدم مسموح."""
    user = get_current_user_optional()
    if not user:
        abort(403)
    from flask import g

    db = g.db
    m = db.get(EvaluationCriterionMedia, media_id)
    if m is None or not (m.file_relpath or "").strip():
        abort(404)
    if not _eval_crit_user_can_stream_media(db, user, m):
        abort(403)
    abs_p = criterion_media_absolute_path((m.file_relpath or "").strip())
    if abs_p is None or not abs_p.is_file():
        abort(404)
    dl_name = Path(m.file_relpath or "").name
    mime = ((m.mime_type or "").strip() or mimetypes.guess_type(dl_name)[0] or "").strip()
    return send_file(abs_p, mimetype=mime or None)


@bp.route("/eval-criterion-media/upload", methods=["POST"])
def eval_criterion_media_upload():
    user = get_current_user_optional()
    if not user:
        abort(403)
    from flask import g

    db = g.db
    li_raw = (request.form.get("evaluation_list_item_id") or "").strip()
    ba_raw = (request.form.get("bundle_action_eval_id") or "").strip()
    li_id = int(li_raw) if li_raw.isdigit() else None
    ba_id = int(ba_raw) if ba_raw.isdigit() else None
    if li_id is not None and li_id <= 0:
        li_id = None
    if ba_id is not None and ba_id <= 0:
        ba_id = None
    if li_id is None and ba_id is None:
        return jsonify(ok=False, error="scope_missing"), 400
    if li_id is not None and ba_id is not None:
        return jsonify(ok=False, error="scope_conflict"), 400
    ri_raw = (request.form.get("row_index") or "").strip()
    row_index = int(ri_raw) if ri_raw.isdigit() else -1
    if row_index < 0:
        return jsonify(ok=False, error="row"), 400
    media_kind = (request.form.get("media_kind") or "photo").strip().lower()
    if media_kind not in ("photo", "video"):
        return jsonify(ok=False, error="kind"), 400
    uf = request.files.get("file")
    if uf is None or not (uf.filename or "").strip():
        return jsonify(ok=False, error="file"), 400
    blob = uf.read()
    if not blob:
        return jsonify(ok=False, error="empty"), 400
    ct_in = uf.mimetype or mimetypes.guess_type((uf.filename or "").strip())[0] or ""

    exercise_id = 0
    unit_key = ""
    try:
        if li_id is not None:
            item = db.get(EvaluationListPdfItem, li_id)
            if item is None:
                return jsonify(ok=False, error="item"), 404
            exercise_id = int(item.exercise_id or 0)
            unit_key = (item.unit_level_key or "").strip()
            ba_id = None
        elif ba_id is not None:
            ar = db.get(ExercisePlannerFlowBundleActionEval, int(ba_id))
            if ar is None:
                return jsonify(ok=False, error="action"), 404
            bd = db.get(ExercisePlannerFlowBundle, int(ar.bundle_id))
            if bd is None:
                return jsonify(ok=False, error="bundle"), 404
            exercise_id = int(bd.exercise_id)
            unit_key = (bd.unit_level_key or "").strip()
            li_id = None

        canon = _eval_row_canonical_saved_for_crit_upload(
            db,
            exercise_id=int(exercise_id),
            list_item_id=li_id,
            bundle_action_eval_id=ba_id,
        )
        if not _eval_crit_user_can_upload_media(
            db,
            user,
            exercise_id=int(exercise_id),
            unit_level_key=unit_key,
            list_item_id=li_id,
            bundle_action_eval_id=ba_id,
            canonical_saved=canon,
        ):
            abort(403)
        rec = persist_criterion_medium(
            db,
            exercise_id=int(exercise_id),
            unit_level_key=unit_key,
            list_item_id=li_id,
            bundle_action_eval_id=ba_id,
            row_index=int(row_index),
            media_kind=media_kind,
            mime_type_in=ct_in,
            bin_data=blob,
            uploaded_by_id=getattr(user, "id", None),
        )
        db.commit()
        stream_u = url_for("views.eval_criterion_media_stream", media_id=int(rec.id))
        del_u = url_for("views.eval_criterion_media_delete", media_id=int(rec.id))
        return jsonify(
            ok=True,
            id=int(rec.id),
            media_kind=rec.media_kind,
            stream_url=stream_u,
            delete_url=del_u,
        )
    except ValueError as err:
        db.rollback()
        tag = "".join(str(x) for x in err.args)
        if "mime" in tag:
            return jsonify(ok=False, error="mime"), 415
        if "size" in tag:
            return jsonify(ok=False, error="size"), 413
        return jsonify(ok=False, error="reject"), 400


@bp.route("/eval-criterion-media/<int:media_id>/delete", methods=["POST"])
def eval_criterion_media_delete(media_id: int):
    user = get_current_user_optional()
    if not user:
        abort(403)
    from flask import g

    db = g.db
    m = db.get(EvaluationCriterionMedia, media_id)
    if m is None:
        abort(404)
    li_raw = getattr(m, "evaluation_list_item_id", None)
    ba_raw = getattr(m, "bundle_action_eval_id", None)
    li_pk = int(li_raw) if li_raw is not None else None
    ba_pk = int(ba_raw) if ba_raw is not None else None
    canon = _eval_row_canonical_saved_for_crit_upload(
        db,
        exercise_id=int(m.exercise_id),
        list_item_id=li_pk,
        bundle_action_eval_id=ba_pk,
    )
    if not _eval_crit_user_can_upload_media(
        db,
        user,
        exercise_id=int(m.exercise_id),
        unit_level_key=(getattr(m, "unit_level_key", "") or "").strip(),
        list_item_id=li_pk,
        bundle_action_eval_id=ba_pk,
        canonical_saved=canon,
    ):
        abort(403)
    rel = (m.file_relpath or "").strip()
    abs_p = criterion_media_absolute_path(rel) if rel else None
    db.delete(m)
    db.commit()
    if abs_p is not None and abs_p.is_file():
        try:
            abs_p.unlink()
        except OSError:
            pass
    return jsonify(ok=True)


# ——— مساحة كبير المحكمين ———
CHIEF_JUDGE_ONLY_HUB_ITEMS: tuple[tuple[str, str, str], ...] = (
    ("evaluation-lists-chief", "اعتماد قوائم التقييم (كبير المحكمين)", "fa-stamp"),
)


def _chief_judge_hub_items() -> tuple[tuple[str, str, str], ...]:
    """امتيازات كبير المحكمين الخاصة + جميع أوامر مساحة المحكمين."""
    return CHIEF_JUDGE_ONLY_HUB_ITEMS + JUDGE_HUB_ITEMS


CHIEF_JUDGE_HUB_SLUGS: dict[str, str] = {s: t for s, t, _ in _chief_judge_hub_items()}


@bp.route("/chief-judge")
def chief_judge_hub():
    user = get_current_user_optional()
    if not user:
        return redirect("/login?next=/chief-judge")
    if not can_access_chief_judge_hub(user):
        abort(403)
    from flask import g

    db = g.db
    ex = _current_workspace_exercise(db, user)
    _ensure_judge_roster_synced(db, user, ex)
    hub_items = [
        {"slug": s, "title_ar": t, "icon": ic} for s, t, ic in _chief_judge_hub_items()
    ]
    return render_template("chief_judge_hub.html", **_ctx(user, hub_items=hub_items))


@bp.route("/chief-judge/<slug>")
def chief_judge_hub_section(slug: str):
    user = get_current_user_optional()
    if not user:
        return redirect(f"/login?next=/chief-judge/{slug}")
    if not can_access_chief_judge_hub(user):
        abort(403)
    slug_norm = (slug or "").strip().lower()
    if slug_norm not in CHIEF_JUDGE_HUB_SLUGS:
        abort(404)
    if slug_norm == "evaluation-lists-chief":
        return redirect(url_for("views.chief_judge_evaluation_lists_home"))
    if slug_norm in JUDGE_HUB_SLUGS:
        return judge_hub_section(slug_norm)
    abort(404)


@bp.route("/chief-judge/evaluation-lists", methods=["GET"])
def chief_judge_evaluation_lists_home():
    user = get_current_user_optional()
    if not user:
        return redirect("/login?next=/chief-judge/evaluation-lists")
    if not can_access_chief_judge_hub(user):
        abort(403)
    from flask import g

    db = g.db
    ex = _current_workspace_exercise(db, user)
    units = list(UNIT_LEVELS)
    unit_rows = evaluation_unit_home_rows(db, ex, units)
    return render_template(
        "judge_evaluation_lists_home.html",
        **_ctx(
            user,
            has_exercise=ex is not None,
            exercise=ex,
            unit_levels=units,
            unit_rows=unit_rows,
            unit_totals=evaluation_unit_home_totals(unit_rows),
            unit_list_endpoint="views.chief_judge_evaluation_lists",
            page_title="قوائم التقييم — اعتماد كبير المحكمين",
            **_hub_back_ctx_for_request_path(),
        ),
    )


@bp.route("/chief-judge/evaluation-lists/<unit_key>", methods=["GET"])
def chief_judge_evaluation_lists(unit_key: str):
    user = get_current_user_optional()
    if not user:
        return redirect(f"/login?next=/chief-judge/evaluation-lists/{unit_key}")
    if not can_access_chief_judge_hub(user):
        abort(403)
    unit = next((x for x in UNIT_LEVELS if x["key"] == unit_key), None)
    if not unit:
        abort(404)
    from flask import g

    db = g.db
    ex = _current_workspace_exercise(db, user)
    if ex is None:
        return redirect(url_for("views.chief_judge_evaluation_lists_home"))
    items = (
        db.query(EvaluationListPdfItem)
        .filter(
            EvaluationListPdfItem.exercise_id == ex.id,
            EvaluationListPdfItem.unit_level_key == unit_key,
        )
        .order_by(
            _exercise_phase_order_expr(EvaluationListPdfItem.exercise_phase),
            EvaluationListPdfItem.sort_order,
            EvaluationListPdfItem.id,
        )
        .all()
    )
    item_ids = [int(it.id) for it in items]
    canonical_by_item = _evaluation_canonical_map_for_items(db, ex.id, item_ids)
    evaluation_lists_rows: list[dict] = []
    for it in items:
        s = canonical_by_item.get(int(it.id))
        evaluation_lists_rows.append(
            build_evaluation_list_row(
                item=it,
                saved=s,
                exercise=ex,
                open_href=url_for(
                    "views.chief_judge_evaluation_list_file_viewer",
                    unit_key=unit_key,
                    item_id=it.id,
                ),
                chief_workflow_label=eval_workflow_label_ar(s),
            )
        )
    return render_template(
        "chief_judge_evaluation_lists.html",
        **_ctx(
            user,
            exercise=ex,
            unit=unit,
            unit_key=unit_key,
            evaluation_lists_rows=evaluation_lists_rows,
            eval_lists_parent_href=url_for("views.chief_judge_evaluation_lists_home"),
            **_hub_back_ctx_for_request_path(),
        ),
    )


@bp.route("/chief-judge/evaluation-lists/<unit_key>/view/<int:item_id>", methods=["GET"])
def chief_judge_evaluation_list_file_viewer(unit_key: str, item_id: int):
    user = get_current_user_optional()
    if not user:
        return redirect(f"/login?next=/chief-judge/evaluation-lists/{unit_key}/view/{item_id}")
    if not can_access_chief_judge_hub(user):
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
    list_url = url_for("views.chief_judge_evaluation_lists", unit_key=unit_key)
    if not (row.pdf_relpath or "").strip():
        return redirect(list_url)
    fspath = _evaluation_list_file_abspath(row.pdf_relpath)
    if fspath is None:
        return redirect(list_url)
    ev = _evaluation_sheet_view_context(fspath)
    canon = _evaluation_canonical_saved_row(db, current_exercise.id, row.id)

    def _load_payload(sr: EvaluationListSavedResult | None) -> dict:
        if not sr or not (sr.payload_json or "").strip():
            return {}
        try:
            p = json.loads(sr.payload_json)
        except Exception:
            return {}
        return p if isinstance(p, dict) else {}

    saved_payload = _load_payload(canon)
    saved_updated_at = getattr(canon, "updated_at", None) if canon else None
    saved_row_id = getattr(canon, "id", None) if canon else None
    wf = _eval_list_viewer_ctx(user, canon)
    wf = {
        **wf,
        "eval_can_edit": False,
        "show_eval_approve": False,
    }
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
            **wf,
            **ev,
            **_eval_crit_media_sheet_ctx(
                db,
                user,
                exercise=current_exercise,
                list_item_id=int(row.id),
                bundle_action_eval_id=None,
                eval_can_edit=False,
            ),
            unit_label=unit_label or "—",
            shown_date=shown_date,
            commander_name=commander_name or "—",
            judge_name=judge_name or "—",
            has_saved_rows=bool(saved_payload and (saved_payload.get("rows") or [])),
            eval_save_url="",
            eval_approve_url="",
            eval_chief_approve_url=url_for(
                "views.chief_judge_evaluation_list_chief_approve",
                unit_key=unit_key,
                item_id=item_id,
            ),
            eval_chief_reopen_url=url_for(
                "views.chief_judge_evaluation_list_chief_reopen",
                unit_key=unit_key,
                item_id=item_id,
            ),
            eval_close_href=list_url,
            eval_approve_incomplete=False,
            viewer_readonly_chief=True,
            **_hub_back_ctx_for_request_path(),
        ),
    )


@bp.route(
    "/chief-judge/evaluation-lists/<unit_key>/view/<int:item_id>/chief-approve",
    methods=["POST"],
)
def chief_judge_evaluation_list_chief_approve(unit_key: str, item_id: int):
    user = get_current_user_optional()
    if not user:
        abort(403)
    if not can_chief_approve_evaluation_results(user):
        abort(403)
    if not can_access_chief_judge_hub(user):
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
    saved = _evaluation_canonical_saved_row(db, current_exercise.id, item.id)
    if saved is None or not eval_chief_can_approve(saved):
        abort(400)
    apply_chief_approve(saved, getattr(user, "id", None))
    db.commit()
    return redirect(
        url_for("views.chief_judge_evaluation_list_file_viewer", unit_key=unit_key, item_id=item_id)
    )


@bp.route(
    "/chief-judge/evaluation-lists/<unit_key>/view/<int:item_id>/chief-reopen",
    methods=["POST"],
)
def chief_judge_evaluation_list_chief_reopen(unit_key: str, item_id: int):
    user = get_current_user_optional()
    if not user:
        abort(403)
    if not can_chief_reopen_evaluation_for_judge(user):
        abort(403)
    if not can_access_chief_judge_hub(user):
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
    saved = _evaluation_canonical_saved_row(db, current_exercise.id, item.id)
    if saved is None or not eval_chief_can_reopen(saved):
        abort(400)
    apply_chief_reopen(saved)
    from app.notifications_service import notify_evaluation_reopened_by_chief_judge

    unit_label = label_for_unit_level_key(unit_key) or unit.get("label") or unit_key
    item_title = (getattr(item, "text", None) or "قائمة التقييم").strip()
    notify_evaluation_reopened_by_chief_judge(
        db,
        exercise_id=int(current_exercise.id),
        unit_key=unit_key,
        unit_label=unit_label,
        item_title=item_title,
        item_id=int(item.id),
        saved_by_user_id=getattr(saved, "saved_by_id", None),
        exclude_user_id=getattr(user, "id", None),
    )
    db.commit()
    return redirect(
        url_for("views.chief_judge_evaluation_list_file_viewer", unit_key=unit_key, item_id=item_id)
    )


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
    _require_planner_hub_catalog_access(user)
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
    if not user:
        return redirect(f"/login?next=/admin/evaluation-lists/{unit_key}")
    _require_planner_hub_catalog_access(user)
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
        _exercise_phase_order_expr(EvaluationListPdfItem.exercise_phase),
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
            upload_phase_default=DEFAULT_EXERCISE_PHASE,
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
    _require_planner_hub_catalog_access(user)
    first = UNIT_LEVELS[0]["key"] if UNIT_LEVELS else "brigade_group"
    return redirect(url_for("views.admin_evaluation_lists", unit_key=first))


def _build_dilemma_evaluation_unit_report(
    db,
    exercise_id: int | None = None,
    *,
    exercise_phase: str | None = None,
) -> list[dict]:
    """يعرض ربط مستويات الوحدات بين قائمة الوحدة المتدربة وقائمة المحكمين فقط."""
    phase = _normalized_exercise_phase(exercise_phase)
    out: list[dict] = []
    for unit in UNIT_LEVELS:
        uk = unit["key"]
        ul = unit["label"]

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
                "exercise_phase": phase,
                "n_trainees": len(trainees),
                "n_judges": len(judges),
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
    if not user:
        return redirect("/login?next=/admin/dilemmas")
    _require_planner_hub_catalog_access(user)
    first = UNIT_LEVELS[0]["key"] if UNIT_LEVELS else "brigade_group"
    return redirect(url_for("views.admin_dilemmas", unit_key=first))


@bp.route("/admin/dilemmas/<unit_key>", methods=["GET", "POST"])
def admin_dilemmas(unit_key: str):
    user = get_current_user_optional()
    if not user:
        return redirect(f"/login?next=/admin/dilemmas/{unit_key}")
    _require_planner_hub_catalog_access(user)
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
        _exercise_phase_order_expr(DilemmaItem.exercise_phase),
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
            upload_phase_default=DEFAULT_EXERCISE_PHASE,
            items=existing,
            error=error,
            ok_msg=ok_msg,
        ),
    )


@bp.route("/admin/dilemmas/<unit_key>/view/<int:item_id>", methods=["GET"])
def admin_dilemma_viewer(unit_key: str, item_id: int):
    user = get_current_user_optional()
    _require_planner_hub_catalog_access(user)
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
    _require_planner_hub_catalog_access(user)
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
    _require_planner_hub_catalog_access(user)
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
    _require_planner_hub_catalog_access(user)
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
    _require_planner_hub_catalog_access(user)
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


_INFO_BANK_MAX_PDF = 50 * 1024 * 1024
_INFO_BANK_MAX_XLSX = 30 * 1024 * 1024


def _info_bank_next_sort_order(db, model, phase: str, unit: str) -> int:
    mx = (
        db.query(func.max(model.sort_order))
        .filter(
            model.training_phase_key == phase,
            model.unit_level_key == unit,
        )
        .scalar()
    )
    return (int(mx) if mx is not None else -1) + 1


def _ensure_information_bank_catalog_rows(db) -> None:
    """يجب أن تكون صفوف الكتالوج الافتراضي مطابقة لـ ``TRAINING_PHASES`` و ``INFO_BANK_UNIT_LEVELS``.

    تنشئ أي مفاتيح ناقصة عند أول تشغيل، وتُحدّث التسمية وترتيب العرض عند كل طلب لتظهر تحديثات الكتالوج البرمجي في الواجهة دون تهيئة قاعدة يدوياً.
    """
    changed = False
    for idx, row in enumerate(TRAINING_PHASES):
        r = db.get(InformationBankTrainingPhase, row["key"])
        if r is None:
            db.add(
                InformationBankTrainingPhase(
                    key=row["key"],
                    label=row["label"],
                    sort_order=idx,
                    is_system=True,
                )
            )
            changed = True
        elif r.label != row["label"] or r.sort_order != idx:
            r.label = row["label"]
            r.sort_order = idx
            r.is_system = True
            changed = True
    for idx, row in enumerate(INFO_BANK_UNIT_LEVELS):
        r = db.get(InformationBankUnitLevel, row["key"])
        if r is None:
            db.add(
                InformationBankUnitLevel(
                    key=row["key"],
                    label=row["label"],
                    sort_order=idx,
                    is_system=True,
                )
            )
            changed = True
        elif r.label != row["label"] or r.sort_order != idx:
            r.label = row["label"]
            r.sort_order = idx
            r.is_system = True
            changed = True
    if changed:
        db.commit()


def _information_bank_training_phases(db) -> list[dict[str, str]]:
    _ensure_information_bank_catalog_rows(db)
    rows = (
        db.query(InformationBankTrainingPhase)
        .order_by(InformationBankTrainingPhase.sort_order, InformationBankTrainingPhase.created_at, InformationBankTrainingPhase.key)
        .all()
    )
    return [{"key": r.key, "label": r.label} for r in rows if (r.key or "").strip()]


def _information_bank_unit_levels(db) -> list[dict[str, str]]:
    _ensure_information_bank_catalog_rows(db)
    rows = (
        db.query(InformationBankUnitLevel)
        .order_by(InformationBankUnitLevel.sort_order, InformationBankUnitLevel.created_at, InformationBankUnitLevel.key)
        .all()
    )
    return [{"key": r.key, "label": r.label} for r in rows if (r.key or "").strip()]


def _information_bank_training_phase_label(db, key: str | None) -> str:
    k = (key or "").strip()
    for row in _information_bank_training_phases(db):
        if row["key"] == k:
            return row["label"]
    return training_phase_label(k)


def _information_bank_unit_label(db, key: str | None) -> str:
    k = (key or "").strip()
    for row in _information_bank_unit_levels(db):
        if row["key"] == k:
            return row["label"]
    return info_bank_unit_label(k)


def _is_valid_information_bank_phase(db, key: str | None) -> bool:
    k = (key or "").strip()
    return any(row["key"] == k for row in _information_bank_training_phases(db))


def _is_valid_information_bank_unit(db, key: str | None) -> bool:
    k = (key or "").strip()
    return any(row["key"] == k for row in _information_bank_unit_levels(db))


def _custom_catalog_key(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@bp.route("/admin/information-bank", methods=["GET"])
def admin_information_bank():
    user = get_current_user_optional()
    if not user:
        return redirect("/login?next=/admin/information-bank")
    if not can_view_information_bank(user):
        abort(403)
    from flask import g

    db = g.db
    training_phases = _information_bank_training_phases(db)
    info_bank_units = _information_bank_unit_levels(db)
    phase_notes = {r.phase_key: r.notes for r in db.query(InformationBankPhaseNote).all()}
    unit_notes = {r.unit_level_key: r.notes for r in db.query(InformationBankUnitNote).all()}
    from app.info_bank_tree import build_tree_payload, ensure_all_information_bank_trees

    ensure_all_information_bank_trees(db)
    tree_event_flow = build_tree_payload(db, "event_flow")
    tree_action_eval = build_tree_payload(db, "action_eval")
    tree_dilemma_eval = build_tree_payload(db, "dilemma_eval")
    err = (request.args.get("err") or "").strip()[:2000]
    ok = (request.args.get("ok") or "").strip()[:500]
    active_tab = (request.args.get("tab") or "phases").strip()
    if active_tab not in {"phases", "units", "event-flow", "action-eval", "dilemma-eval"}:
        active_tab = "phases"
    return render_template(
        "admin_information_bank.html",
        **_ctx(
            user,
            training_phases=training_phases,
            info_bank_units=info_bank_units,
            phase_notes=phase_notes,
            unit_notes=unit_notes,
            tree_event_flow=tree_event_flow,
            tree_action_eval=tree_action_eval,
            tree_dilemma_eval=tree_dilemma_eval,
            training_phase_label=lambda key: _information_bank_training_phase_label(db, key),
            info_bank_unit_label=lambda key: _information_bank_unit_label(db, key),
            error=err,
            ok_msg=ok,
            active_tab=active_tab,
            information_bank_can_manage=can_manage_information_bank(user),
        ),
    )


@bp.route("/admin/information-bank/phase-notes", methods=["POST"])
def admin_information_bank_phase_notes():
    user = get_current_user_optional()
    if not user or not can_manage_information_bank(user):
        abort(403)
    from flask import g

    db = g.db
    for p in TRAINING_PHASES:
        key = p["key"]
        raw = request.form.get(f"note_{key}") or ""
        row = db.get(InformationBankPhaseNote, key)
        if row is None:
            row = InformationBankPhaseNote(phase_key=key, notes=raw)
            db.add(row)
        else:
            row.notes = raw
    db.commit()
    return redirect(url_for("views.admin_information_bank", ok="تم حفظ بيانات مراحل التمرين."))


@bp.route("/admin/information-bank/unit-notes", methods=["POST"])
def admin_information_bank_unit_notes():
    user = get_current_user_optional()
    if not user or not can_manage_information_bank(user):
        abort(403)
    from flask import g

    db = g.db
    for u in INFO_BANK_UNIT_LEVELS:
        key = u["key"]
        raw = request.form.get(f"unote_{key}") or ""
        row = db.get(InformationBankUnitNote, key)
        if row is None:
            row = InformationBankUnitNote(unit_level_key=key, notes=raw)
            db.add(row)
        else:
            row.notes = raw
    db.commit()
    return redirect(url_for("views.admin_information_bank", ok="تم حفظ بيانات مستويات الوحدات."))


@bp.route("/admin/information-bank/phases/add", methods=["POST"])
def admin_information_bank_phase_add():
    user = get_current_user_optional()
    if not user or not can_manage_information_bank(user):
        abort(403)
    from flask import g

    label = (request.form.get("phase_label") or "").strip()[:300]
    if not label:
        return redirect(url_for("views.admin_information_bank", tab="phases", err="أدخل اسم المرحلة."))
    db = g.db
    _ensure_information_bank_catalog_rows(db)
    mx = db.query(func.max(InformationBankTrainingPhase.sort_order)).scalar()
    next_order = (int(mx) if mx is not None else -1) + 1
    phase_key = _custom_catalog_key("phase")
    db.add(
        InformationBankTrainingPhase(
            key=phase_key,
            label=label,
            sort_order=next_order,
            is_system=False,
        )
    )
    db.commit()
    from app.info_bank_tree import INFO_BANK_TREE_KINDS, _unit_rows, ensure_information_bank_tree, get_or_create_folder

    for k in INFO_BANK_TREE_KINDS:
        ensure_information_bank_tree(db, k)
        phase_node = get_or_create_folder(
            db,
            kind=k,
            parent_id=None,
            name=label,
            is_system=False,
            catalog_phase_key=phase_key,
        )
        for un in _unit_rows(db):
            get_or_create_folder(
                db,
                kind=k,
                parent_id=int(phase_node.id),
                name=(un.label or un.key)[:500],
                is_system=bool(un.is_system),
                catalog_unit_key=un.key,
            )
    db.commit()
    return redirect(url_for("views.admin_information_bank", tab="phases", ok="تمت إضافة مرحلة التمرين."))


@bp.route("/admin/information-bank/phases/delete", methods=["POST"])
def admin_information_bank_phase_delete():
    user = get_current_user_optional()
    if not user or not can_manage_information_bank(user):
        abort(403)
    from flask import g

    key = (request.form.get("phase_key") or "").strip()
    db = g.db
    row = db.get(InformationBankTrainingPhase, key)
    if row is None:
        return redirect(url_for("views.admin_information_bank", tab="phases", err="اختر مرحلة صالحة للحذف."))
    db.delete(row)
    db.commit()
    return redirect(url_for("views.admin_information_bank", tab="phases", ok="تم حذف مرحلة التمرين."))


@bp.route("/admin/information-bank/units/add", methods=["POST"])
def admin_information_bank_unit_add():
    user = get_current_user_optional()
    if not user or not can_manage_information_bank(user):
        abort(403)
    from flask import g

    label = (request.form.get("unit_label") or "").strip()[:300]
    if not label:
        return redirect(url_for("views.admin_information_bank", tab="units", err="أدخل اسم مستوى الوحدة."))
    db = g.db
    _ensure_information_bank_catalog_rows(db)
    mx = db.query(func.max(InformationBankUnitLevel.sort_order)).scalar()
    next_order = (int(mx) if mx is not None else -1) + 1
    unit_key = _custom_catalog_key("unit")
    db.add(
        InformationBankUnitLevel(
            key=unit_key,
            label=label,
            sort_order=next_order,
            is_system=False,
        )
    )
    db.commit()
    from app.info_bank_tree import INFO_BANK_TREE_KINDS, ensure_information_bank_tree, get_or_create_folder

    for k in INFO_BANK_TREE_KINDS:
        ensure_information_bank_tree(db, k)
        phase_nodes = (
            db.query(InformationBankTreeNode)
            .filter(
                InformationBankTreeNode.kind == k,
                InformationBankTreeNode.parent_id.is_(None),
                InformationBankTreeNode.is_folder.is_(True),
            )
            .all()
        )
        for ph in phase_nodes:
            get_or_create_folder(
                db,
                kind=k,
                parent_id=int(ph.id),
                name=label,
                is_system=False,
                catalog_unit_key=unit_key,
            )
    db.commit()
    return redirect(url_for("views.admin_information_bank", tab="units", ok="تمت إضافة مستوى الوحدة."))


@bp.route("/admin/information-bank/units/delete", methods=["POST"])
def admin_information_bank_unit_delete():
    user = get_current_user_optional()
    if not user or not can_manage_information_bank(user):
        abort(403)
    from flask import g

    key = (request.form.get("unit_key") or "").strip()
    db = g.db
    row = db.get(InformationBankUnitLevel, key)
    if row is None:
        return redirect(url_for("views.admin_information_bank", tab="units", err="اختر مستوى وحدة صالحاً للحذف."))
    db.delete(row)
    db.commit()
    return redirect(url_for("views.admin_information_bank", tab="units", ok="تم حذف مستوى الوحدة."))


@bp.route("/admin/information-bank/tree/folder", methods=["POST"])
def admin_information_bank_tree_folder_add():
    user = get_current_user_optional()
    if not user or not can_manage_information_bank(user):
        abort(403)
    from flask import g

    from app.info_bank_tree import add_custom_folder, ensure_information_bank_tree, kind_tab

    db = g.db
    kind = (request.form.get("kind") or "").strip()
    if kind not in ("event_flow", "action_eval", "dilemma_eval"):
        abort(400)
    parent_raw = (request.form.get("parent_id") or "").strip()
    parent_id = int(parent_raw) if parent_raw.isdigit() else None
    name = (request.form.get("folder_name") or "").strip()
    tab = kind_tab(kind)
    if not name:
        return redirect(url_for("views.admin_information_bank", tab=tab, err="أدخل اسم المجلد."))
    ensure_information_bank_tree(db, kind)
    try:
        add_custom_folder(db, kind=kind, parent_id=parent_id, name=name)
        db.commit()
    except ValueError as exc:
        db.rollback()
        return redirect(url_for("views.admin_information_bank", tab=tab, err=str(exc) or "تعذر إنشاء المجلد."))
    return redirect(url_for("views.admin_information_bank", tab=tab, ok="تم إنشاء المجلد."))


@bp.route("/admin/information-bank/tree/upload", methods=["POST"])
def admin_information_bank_tree_upload():
    user = get_current_user_optional()
    if not user or not can_manage_information_bank(user):
        abort(403)
    from flask import g

    from app.info_bank_tree import (
        ensure_information_bank_tree,
        get_node,
        kind_tab,
        upload_files_to_parent,
    )

    db = g.db
    kind = (request.form.get("kind") or "").strip()
    tab = kind_tab(kind)
    if kind not in ("event_flow", "action_eval", "dilemma_eval"):
        abort(400)
    parent_raw = (request.form.get("parent_id") or "").strip()
    if not parent_raw.isdigit():
        return redirect(
            url_for("views.admin_information_bank", tab=tab, err="حدّد مجلداً مستهدفاً في الشجرة (زر تحديد).")
        )
    parent_id = int(parent_raw)
    ensure_information_bank_tree(db, kind)
    parent = get_node(db, parent_id, kind)
    if parent is None or not parent.is_folder:
        return redirect(url_for("views.admin_information_bank", tab=tab, err="المجلد المستهدف غير صالح."))
    files = [x for x in request.files.getlist("files") if x and getattr(x, "filename", "").strip()]
    if not files:
        return redirect(url_for("views.admin_information_bank", tab=tab, err="اختر ملفاً أو مجلداً للإدراج."))
    added, errors = upload_files_to_parent(db, kind=kind, parent_id=parent_id, file_storages=files)
    if added:
        db.commit()
    else:
        db.rollback()
    err_q = " ".join(errors)[:2000] if errors else ""
    if not added:
        return redirect(url_for("views.admin_information_bank", tab=tab, err=err_q or "لم تُضف أي ملف."))
    ok_msg = f"تم إدراج {added} ملف(ات)."
    if err_q:
        return redirect(
            url_for("views.admin_information_bank", tab=tab, ok=ok_msg, err=f"تجاهل بعض الملفات: {err_q}")
        )
    return redirect(url_for("views.admin_information_bank", tab=tab, ok=ok_msg))


@bp.route("/admin/information-bank/tree/<int:node_id>/delete", methods=["POST"])
def admin_information_bank_tree_delete(node_id: int):
    user = get_current_user_optional()
    if not user or not can_manage_information_bank(user):
        abort(403)
    from flask import g

    from app.info_bank_tree import delete_node, kind_tab

    db = g.db
    row = db.get(InformationBankTreeNode, node_id)
    if row is None:
        abort(404)
    tab = kind_tab(row.kind)
    delete_node(db, row)
    db.commit()
    return redirect(url_for("views.admin_information_bank", tab=tab, ok="تم الحذف."))


@bp.route("/admin/information-bank/tree/move", methods=["POST"])
def admin_information_bank_tree_move():
    user = get_current_user_optional()
    if not user or not can_manage_information_bank(user):
        return jsonify(ok=False, error="غير مسموح."), 403
    from flask import g

    from app.info_bank_tree import move_tree_node

    data = request.get_json(force=True, silent=True) or {}
    kind = (data.get("kind") or "").strip()
    if kind not in ("event_flow", "action_eval", "dilemma_eval"):
        return jsonify(ok=False, error="نوع المرفقات غير صالح."), 400
    try:
        nid = int(data.get("node_id"))
        pid = int(data.get("parent_id"))
    except (TypeError, ValueError):
        return jsonify(ok=False, error="بيانات غير صالحة."), 400
    db = g.db
    try:
        move_tree_node(db, kind=kind, node_id=nid, parent_id=pid)
        db.commit()
    except ValueError as exc:
        db.rollback()
        return jsonify(ok=False, error=str(exc) or "تعذّر النقل."), 400
    return jsonify(ok=True)


@bp.route("/admin/information-bank/tree/<int:node_id>/file", methods=["GET"])
def admin_information_bank_tree_file(node_id: int):
    user = get_current_user_optional()
    if not user or not can_view_information_bank(user):
        abort(403)
    from flask import g

    from app.info_bank_tree import node_file_abspath

    db = g.db
    row = db.get(InformationBankTreeNode, node_id)
    if row is None or row.is_folder or not (row.file_relpath or "").strip():
        abort(404)
    path = node_file_abspath(row.kind, row.file_relpath)
    if path is None:
        abort(404)
    low = path.name.lower()
    if low.endswith(".xlsx"):
        mt = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        mt = _mimetype_info_bank_event_flow(path)
    return send_file(path, mimetype=mt, as_attachment=False, download_name=row.name or path.name)


@bp.route("/admin/information-bank/event-flow/upload", methods=["POST"])
def admin_information_bank_event_flow_upload():
    user = get_current_user_optional()
    if not user or not can_manage_information_bank(user):
        abort(403)
    from flask import g

    db = g.db
    phase = (request.form.get("training_phase_key") or "").strip()
    unit = (request.form.get("unit_level_key") or "").strip()
    if not _is_valid_information_bank_phase(db, phase) or not _is_valid_information_bank_unit(db, unit):
        return redirect(url_for("views.admin_information_bank", tab="event-flow", err="مرحلة أو مستوى وحدة غير صالح."))
    files = [x for x in request.files.getlist("file") if x and getattr(x, "filename", "").strip()]
    if not files:
        return redirect(url_for("views.admin_information_bank", tab="event-flow", err="اختر ملفاً واحداً على الأقل (PDF أو Word)."))
    INFO_BANK_DIR.mkdir(parents=True, exist_ok=True)
    sub = INFO_BANK_DIR / "event_flow"
    sub.mkdir(parents=True, exist_ok=True)
    sort_next = _info_bank_next_sort_order(db, InfoBankEventFlowPdf, phase, unit)
    added = 0
    errors: list[str] = []
    for f in files:
        fn = (getattr(f, "filename", "") or "").strip()
        try:
            data = f.read()
        except Exception:
            errors.append(f"{fn or 'ملف'}: تعذّر القراءة.")
            continue
        ext = _info_bank_event_flow_sniff_ext(data)
        if ext is None:
            errors.append(f"{fn}: يُقبل فقط PDF أو Word صالحاً.")
            continue
        if len(data) > _INFO_BANK_MAX_PDF:
            errors.append(f"{fn}: الملف كبير جداً (الحد 50 ميغابايت).")
            continue
        title = (Path(fn).stem or "مجرى أحداث").strip()[:500]
        rel_name = f"event_flow/{uuid.uuid4().hex}{ext}"
        full = (INFO_BANK_DIR / rel_name).resolve()
        full.write_bytes(data)
        row = InfoBankEventFlowPdf(
            training_phase_key=phase,
            unit_level_key=unit,
            title=title,
            file_relpath=rel_name.replace("\\", "/"),
            sort_order=sort_next,
        )
        sort_next += 1
        db.add(row)
        added += 1
    if added:
        db.commit()
    else:
        db.rollback()
    err_q = " ".join(errors)[:2000] if errors else ""
    if not added:
        return redirect(url_for("views.admin_information_bank", tab="event-flow", err=err_q or "لم تُضف أي ملف."))
    ok_msg = f"تمت إضافة {added} ملف(ات) لمجرى الأحداث والمعاضل."
    if err_q:
        return redirect(url_for("views.admin_information_bank", tab="event-flow", ok=ok_msg, err=f"تجاهل أو فشل بعض الملفات: {err_q}"))
    return redirect(url_for("views.admin_information_bank", tab="event-flow", ok=ok_msg))


@bp.route("/admin/information-bank/event-flow/<int:item_id>/delete", methods=["POST"])
def admin_information_bank_event_flow_delete(item_id: int):
    user = get_current_user_optional()
    if not user or not can_manage_information_bank(user):
        abort(403)
    from flask import g

    db = g.db
    row = db.get(InfoBankEventFlowPdf, item_id)
    if not row:
        abort(404)
    if row.file_relpath:
        _unlink_info_bank_file("event_flow", row.file_relpath)
    db.delete(row)
    db.commit()
    return redirect(url_for("views.admin_information_bank", tab="event-flow", ok="تم حذف ملف مجرى الأحداث."))


@bp.route("/admin/information-bank/action-eval/upload", methods=["POST"])
def admin_information_bank_action_eval_upload():
    user = get_current_user_optional()
    if not user or not can_manage_information_bank(user):
        abort(403)
    from flask import g

    db = g.db
    phase = (request.form.get("training_phase_key") or "").strip()
    unit = (request.form.get("unit_level_key") or "").strip()
    if not _is_valid_information_bank_phase(db, phase) or not _is_valid_information_bank_unit(db, unit):
        return redirect(url_for("views.admin_information_bank", tab="action-eval", err="مرحلة أو مستوى وحدة غير صالح."))
    files = [x for x in request.files.getlist("file") if x and getattr(x, "filename", "").strip()]
    if not files:
        return redirect(url_for("views.admin_information_bank", tab="action-eval", err="اختر ملفاً واحداً على الأقل (.xlsx)."))
    sort_next = _info_bank_next_sort_order(db, InfoBankActionEvalXlsx, phase, unit)
    added = 0
    errors: list[str] = []
    for f in files:
        fn = (getattr(f, "filename", "") or "").strip()
        try:
            data = f.read()
        except Exception:
            errors.append(f"{fn or 'ملف'}: تعذّر القراءة.")
            continue
        if not fn.lower().endswith(".xlsx") or not _is_xlsx_bytes(data):
            errors.append(f"{fn}: يُقبل فقط ملف .xlsx صالحاً.")
            continue
        if len(data) > _INFO_BANK_MAX_XLSX:
            errors.append(f"{fn}: ملف Excel كبير جداً (الحد 30 ميغابايت).")
            continue
        title = (Path(fn).stem or "قائمة تقييم إجراءات").strip()[:500]
        rel_name = f"action_eval/{uuid.uuid4().hex}.xlsx"
        full = (INFO_BANK_DIR / rel_name).resolve()
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(data)
        row = InfoBankActionEvalXlsx(
            training_phase_key=phase,
            unit_level_key=unit,
            title=title,
            file_relpath=rel_name.replace("\\", "/"),
            sort_order=sort_next,
        )
        sort_next += 1
        db.add(row)
        added += 1
    if added:
        db.commit()
    else:
        db.rollback()
    err_q = " ".join(errors)[:2000] if errors else ""
    if not added:
        return redirect(url_for("views.admin_information_bank", tab="action-eval", err=err_q or "لم تُضف أي ملف."))
    ok_msg = f"تمت إضافة {added} ملف(ات) لتقييم الإجراءات."
    if err_q:
        return redirect(url_for("views.admin_information_bank", tab="action-eval", ok=ok_msg, err=f"تجاهل أو فشل بعض الملفات: {err_q}"))
    return redirect(url_for("views.admin_information_bank", tab="action-eval", ok=ok_msg))


@bp.route("/admin/information-bank/action-eval/<int:item_id>/delete", methods=["POST"])
def admin_information_bank_action_eval_delete(item_id: int):
    user = get_current_user_optional()
    if not user or not can_manage_information_bank(user):
        abort(403)
    from flask import g

    db = g.db
    row = db.get(InfoBankActionEvalXlsx, item_id)
    if not row:
        abort(404)
    if row.file_relpath:
        _unlink_info_bank_file("action_eval", row.file_relpath)
    db.delete(row)
    db.commit()
    return redirect(url_for("views.admin_information_bank", tab="action-eval", ok="تم حذف قائمة تقييم الإجراءات."))


@bp.route("/admin/information-bank/dilemma-eval/upload", methods=["POST"])
def admin_information_bank_dilemma_eval_upload():
    user = get_current_user_optional()
    if not user or not can_manage_information_bank(user):
        abort(403)
    from flask import g

    db = g.db
    phase = (request.form.get("training_phase_key") or "").strip()
    unit = (request.form.get("unit_level_key") or "").strip()
    if not _is_valid_information_bank_phase(db, phase) or not _is_valid_information_bank_unit(db, unit):
        return redirect(url_for("views.admin_information_bank", tab="dilemma-eval", err="مرحلة أو مستوى وحدة غير صالح."))
    files = [x for x in request.files.getlist("file") if x and getattr(x, "filename", "").strip()]
    if not files:
        return redirect(url_for("views.admin_information_bank", tab="dilemma-eval", err="اختر ملفاً واحداً على الأقل (.xlsx)."))
    sort_next = _info_bank_next_sort_order(db, InfoBankDilemmaEvalXlsx, phase, unit)
    added = 0
    errors: list[str] = []
    for f in files:
        fn = (getattr(f, "filename", "") or "").strip()
        try:
            data = f.read()
        except Exception:
            errors.append(f"{fn or 'ملف'}: تعذّر القراءة.")
            continue
        if not fn.lower().endswith(".xlsx") or not _is_xlsx_bytes(data):
            errors.append(f"{fn}: يُقبل فقط ملف .xlsx صالحاً.")
            continue
        if len(data) > _INFO_BANK_MAX_XLSX:
            errors.append(f"{fn}: ملف Excel كبير جداً (الحد 30 ميغابايت).")
            continue
        title = (Path(fn).stem or "قائمة تقييم معضلة").strip()[:500]
        rel_name = f"dilemma_eval/{uuid.uuid4().hex}.xlsx"
        full = (INFO_BANK_DIR / rel_name).resolve()
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(data)
        row = InfoBankDilemmaEvalXlsx(
            training_phase_key=phase,
            unit_level_key=unit,
            title=title,
            file_relpath=rel_name.replace("\\", "/"),
            sort_order=sort_next,
        )
        sort_next += 1
        db.add(row)
        added += 1
    if added:
        db.commit()
    else:
        db.rollback()
    err_q = " ".join(errors)[:2000] if errors else ""
    if not added:
        return redirect(url_for("views.admin_information_bank", tab="dilemma-eval", err=err_q or "لم تُضف أي ملف."))
    ok_msg = f"تمت إضافة {added} ملف(ات) لتقييم المعاضل."
    if err_q:
        return redirect(url_for("views.admin_information_bank", tab="dilemma-eval", ok=ok_msg, err=f"تجاهل أو فشل بعض الملفات: {err_q}"))
    return redirect(url_for("views.admin_information_bank", tab="dilemma-eval", ok=ok_msg))


@bp.route("/admin/information-bank/dilemma-eval/<int:item_id>/delete", methods=["POST"])
def admin_information_bank_dilemma_eval_delete(item_id: int):
    user = get_current_user_optional()
    if not user or not can_manage_information_bank(user):
        abort(403)
    from flask import g

    db = g.db
    row = db.get(InfoBankDilemmaEvalXlsx, item_id)
    if not row:
        abort(404)
    if row.file_relpath:
        _unlink_info_bank_file("dilemma_eval", row.file_relpath)
    db.delete(row)
    db.commit()
    return redirect(url_for("views.admin_information_bank", tab="dilemma-eval", ok="تم حذف قائمة تقييم المعاضل."))


@bp.route("/admin/information-bank/file/event-flow/<int:item_id>", methods=["GET"])
def admin_information_bank_event_flow_file(item_id: int):
    user = get_current_user_optional()
    if not user or not can_view_information_bank(user):
        abort(403)
    from flask import g

    db = g.db
    row = db.get(InfoBankEventFlowPdf, item_id)
    if not row or not (row.file_relpath or "").strip():
        abort(404)
    path = _info_bank_file_abspath("event_flow", row.file_relpath)
    if path is None:
        abort(404)
    mt = _mimetype_info_bank_event_flow(path)
    return send_file(path, mimetype=mt, as_attachment=False)


@bp.route("/admin/information-bank/file/action-eval/<int:item_id>", methods=["GET"])
def admin_information_bank_action_eval_file(item_id: int):
    user = get_current_user_optional()
    if not user or not can_view_information_bank(user):
        abort(403)
    from flask import g

    db = g.db
    row = db.get(InfoBankActionEvalXlsx, item_id)
    if not row or not (row.file_relpath or "").strip():
        abort(404)
    path = _info_bank_file_abspath("action_eval", row.file_relpath)
    if path is None:
        abort(404)
    return send_file(
        path,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=False,
    )


@bp.route("/admin/information-bank/file/dilemma-eval/<int:item_id>", methods=["GET"])
def admin_information_bank_dilemma_eval_file(item_id: int):
    user = get_current_user_optional()
    if not user or not can_view_information_bank(user):
        abort(403)
    from flask import g

    db = g.db
    row = db.get(InfoBankDilemmaEvalXlsx, item_id)
    if not row or not (row.file_relpath or "").strip():
        abort(404)
    path = _info_bank_file_abspath("dilemma_eval", row.file_relpath)
    if path is None:
        abort(404)
    return send_file(
        path,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=False,
    )


@bp.route("/admin/information-bank/manifest.json", methods=["GET"])
def admin_information_bank_manifest_json():
    """قائمة موحّدة للمرفقات (لصفحات أخرى تستهلك السحب والإفلات لاحقاً)."""
    user = get_current_user_optional()
    if not user or not can_view_information_bank(user):
        abort(403)
    from flask import g

    db = g.db
    items: list[dict] = []
    for row in db.query(InfoBankEventFlowPdf).order_by(InfoBankEventFlowPdf.id).all():
        if not (row.file_relpath or "").strip():
            continue
        p = _info_bank_file_abspath("event_flow", row.file_relpath)
        if p is None:
            continue
        items.append(
            {
                "kind": "event_flow_document",
                "id": row.id,
                "title": row.title or "",
                "file_ext": p.suffix.lower().lstrip("."),
                "training_phase_key": row.training_phase_key,
                "training_phase_label": training_phase_label(row.training_phase_key),
                "unit_level_key": row.unit_level_key,
                "unit_label": info_bank_unit_label(row.unit_level_key),
                "url": url_for("views.admin_information_bank_event_flow_file", item_id=row.id),
            }
        )
    for row in db.query(InfoBankActionEvalXlsx).order_by(InfoBankActionEvalXlsx.id).all():
        if not (row.file_relpath or "").strip():
            continue
        if _info_bank_file_abspath("action_eval", row.file_relpath) is None:
            continue
        items.append(
            {
                "kind": "action_eval_xlsx",
                "id": row.id,
                "title": row.title or "",
                "training_phase_key": row.training_phase_key,
                "training_phase_label": training_phase_label(row.training_phase_key),
                "unit_level_key": row.unit_level_key,
                "unit_label": info_bank_unit_label(row.unit_level_key),
                "url": url_for("views.admin_information_bank_action_eval_file", item_id=row.id),
            }
        )
    for row in db.query(InfoBankDilemmaEvalXlsx).order_by(InfoBankDilemmaEvalXlsx.id).all():
        if not (row.file_relpath or "").strip():
            continue
        if _info_bank_file_abspath("dilemma_eval", row.file_relpath) is None:
            continue
        items.append(
            {
                "kind": "dilemma_eval_xlsx",
                "id": row.id,
                "title": row.title or "",
                "training_phase_key": row.training_phase_key,
                "training_phase_label": training_phase_label(row.training_phase_key),
                "unit_level_key": row.unit_level_key,
                "unit_label": info_bank_unit_label(row.unit_level_key),
                "url": url_for("views.admin_information_bank_dilemma_eval_file", item_id=row.id),
            }
        )
    return jsonify({"version": 1, "items": items})


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
            **_hub_back_ctx_for_request_path(),
            control_link_kwargs=_role_hub_preserve_link_kwargs(),
            hub_from_form_param=_role_hub_from_form_param(),
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
            **_hub_back_ctx_for_request_path(),
            control_link_kwargs=_role_hub_preserve_link_kwargs(),
            hub_from_form_param=_role_hub_from_form_param(),
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
        return redirect(url_for("views.chat_room_detail", room_id=room_id, **_role_hub_preserve_link_kwargs()))
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
    return redirect(url_for("views.chat_room_detail", room_id=room_id, **_control_hub_link_kwargs()))


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
        return redirect(url_for("views.chat_room_detail", room_id=room_id, **_role_hub_preserve_link_kwargs()))
    raw_name = secure_filename(f.filename)
    suf = Path(raw_name).suffix.lower()
    if suf not in _CHAT_ALLOWED_SUFFIX:
        return redirect(url_for("views.chat_room_detail", room_id=room_id, **_role_hub_preserve_link_kwargs()))
    data = f.read()
    if len(data) > _CHAT_MAX_UPLOAD_BYTES:
        return redirect(url_for("views.chat_room_detail", room_id=room_id, **_role_hub_preserve_link_kwargs()))
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
    return redirect(url_for("views.chat_room_detail", room_id=room_id, **_control_hub_link_kwargs()))


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
