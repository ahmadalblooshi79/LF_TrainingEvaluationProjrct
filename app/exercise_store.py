"""تصدير التمرين كاملًا إلى JSON في مجلد خارجي وقراءة الملف للعودة إلى صفحة التمرين."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session, joinedload

from app import exercise_options as ex_opts
from app.config import EXERCISE_EXPORT_DIR
from app.unit_levels_catalog import label_for_unit_level_key, normalize_unit_level_key
from app.models import (
    Checklist,
    ChecklistItem,
    DilemmaItem,
    EvaluationListPdfItem,
    EvaluationNote,
    EventFlow,
    EventFlowType,
    Exercise,
    ExerciseObjective,
    ExerciseRosterRow,
    ExerciseRefLink,
    ExerciseTimelineItem,
    ExerciseStatus,
    Problem,
    ProblemStatus,
    Reference,
    User,
)

EXPORT_SCHEMA_VERSION = 2


def export_directory() -> Path:
    p = Path(EXERCISE_EXPORT_DIR)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat()


def _sanitize_filename_stem(name: str, fallback: str) -> str:
    s = (name or "").strip() or fallback
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s)
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > 180:
        s = s[:180].rstrip()
    return s or fallback


def _export_path_for_exercise(directory: Path, title: str, code: str, exercise_id: int) -> Path:
    stem = _sanitize_filename_stem(title, code or "exercise")
    primary = directory / f"{stem}.json"
    if not primary.exists():
        return primary
    try:
        data = json.loads(primary.read_text(encoding="utf-8"))
        ex = data.get("exercise") if isinstance(data, dict) else None
        if isinstance(ex, dict) and ex.get("id") == exercise_id:
            return primary
    except Exception:
        pass
    alt = _sanitize_filename_stem(f"{stem}_{code}", code or str(exercise_id))
    return directory / f"{alt}.json"


def load_exercise_for_export(db: Session, exercise_id: int) -> Exercise | None:
    return (
        db.query(Exercise)
        .options(
            joinedload(Exercise.objectives),
            joinedload(Exercise.roster_rows),
            joinedload(Exercise.events),
            joinedload(Exercise.problems),
            joinedload(Exercise.checklists).joinedload(Checklist.items),
            joinedload(Exercise.eval_notes),
        )
        .filter(Exercise.id == exercise_id)
        .first()
    )


def exercise_to_export_dict(ex: Exercise, db: Session) -> dict[str, Any]:
    ref_rows = (
        db.query(ExerciseRefLink)
        .filter(ExerciseRefLink.exercise_id == ex.id)
        .all()
    )
    objectives = sorted(ex.objectives or [], key=lambda o: o.sort_order)
    roster_all = sorted(ex.roster_rows or [], key=lambda r: (r.roster_kind, r.sort_order, r.id))
    roster_trainee = [r for r in roster_all if (r.roster_kind or "") == "trainee"]
    roster_judge = [r for r in roster_all if (r.roster_kind or "") == "judge"]
    events = sorted(ex.events or [], key=lambda e: e.order_index)
    problems = list(ex.problems or [])
    checklists = list(ex.checklists or [])
    notes = list(ex.eval_notes or [])
    dilemma_rows = (
        db.query(DilemmaItem)
        .filter(DilemmaItem.exercise_id == ex.id)
        .order_by(DilemmaItem.unit_level_key, DilemmaItem.sort_order, DilemmaItem.id)
        .all()
    )
    evaluation_list_rows = (
        db.query(EvaluationListPdfItem)
        .filter(EvaluationListPdfItem.exercise_id == ex.id)
        .order_by(EvaluationListPdfItem.unit_level_key, EvaluationListPdfItem.sort_order, EvaluationListPdfItem.id)
        .all()
    )

    return {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "exported_at": _iso(datetime.utcnow()),
        "exercise": {
            "id": ex.id,
            "code": ex.code,
            "title": ex.title,
            "description": ex.description or "",
            "exercise_type": ex.exercise_type or "",
            "exercise_level": ex.exercise_level or "",
            "mission_label": ex.mission_label or "",
            "trained_unit": ex.trained_unit or "",
            "location_label": ex.location_label or "",
            "status": ex.status or "",
            "owner_id": ex.owner_id,
            "planned_start": _iso(ex.planned_start),
            "planned_end": _iso(ex.planned_end),
            "control_approved": bool(ex.control_approved),
            "created_at": _iso(ex.created_at),
            "updated_at": _iso(ex.updated_at),
        },
        "objectives": [
            {
                "id": o.id,
                "sort_order": o.sort_order,
                "text": o.text,
                "created_at": _iso(o.created_at),
            }
            for o in objectives
        ],
        "trainee_unit_roster": [
            {
                "sort_order": r.sort_order,
                "military_number": r.military_number or "",
                "rank_ar": r.rank_ar or "",
                "full_name": r.full_name or "",
                "unit_level_key": getattr(r, "unit_level_key", None) or "",
                "position_ar": r.position_ar or "",
                "created_at": _iso(r.created_at),
            }
            for r in roster_trainee
        ],
        "judge_unit_roster": [
            {
                "sort_order": r.sort_order,
                "military_number": r.military_number or "",
                "rank_ar": r.rank_ar or "",
                "full_name": r.full_name or "",
                "unit_level_key": getattr(r, "unit_level_key", None) or "",
                "position_ar": r.position_ar or "",
                "created_at": _iso(r.created_at),
            }
            for r in roster_judge
        ],
        "event_flows": [
            {
                "id": ev.id,
                "order_index": ev.order_index,
                "title": ev.title,
                "description": ev.description or "",
                "scheduled_at": _iso(ev.scheduled_at),
                "event_type": ev.event_type or "",
                "created_at": _iso(ev.created_at),
            }
            for ev in events
        ],
        "problems": [
            {
                "id": p.id,
                "title": p.title,
                "description": p.description or "",
                "severity": p.severity,
                "status": p.status or "",
                "reported_by_id": p.reported_by_id,
                "created_at": _iso(p.created_at),
                "updated_at": _iso(p.updated_at),
            }
            for p in problems
        ],
        "checklists": [
            {
                "id": cl.id,
                "title": cl.title,
                "created_by_id": cl.created_by_id,
                "created_at": _iso(cl.created_at),
                "items": [
                    {
                        "id": it.id,
                        "sort_order": it.sort_order,
                        "text": it.text,
                        "weight": float(it.weight),
                        "is_done": bool(it.is_done),
                        "judge_note": it.judge_note or "",
                    }
                    for it in sorted(cl.items or [], key=lambda x: x.sort_order)
                ],
            }
            for cl in checklists
        ],
        "evaluation_notes": [
            {
                "id": n.id,
                "user_id": n.user_id,
                "body": n.body or "",
                "created_at": _iso(n.created_at),
            }
            for n in notes
        ],
        "exercise_ref_links": [
            {"id": r.id, "reference_id": r.reference_id} for r in ref_rows
        ],
        "dilemma_items": [
            {
                "unit_level_key": d.unit_level_key,
                "unit_level_label": d.unit_level_label or "",
                "exercise_phase": getattr(d, "exercise_phase", None) or "main",
                "sort_order": d.sort_order,
                "text": d.text,
                "pdf_relpath": d.pdf_relpath or "",
            }
            for d in dilemma_rows
        ],
        "evaluation_list_items": [
            {
                "unit_level_key": e.unit_level_key,
                "unit_level_label": e.unit_level_label or "",
                "exercise_phase": getattr(e, "exercise_phase", None) or "main",
                "sort_order": e.sort_order,
                "text": e.text,
                "pdf_relpath": e.pdf_relpath or "",
            }
            for e in evaluation_list_rows
        ],
    }


def write_exercise_json_file(db: Session, exercise_id: int) -> Path | None:
    ex = load_exercise_for_export(db, exercise_id)
    if not ex:
        return None
    payload = exercise_to_export_dict(ex, db)
    directory = export_directory()
    path = _export_path_for_exercise(directory, ex.title, ex.code, ex.id)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def list_export_json_files() -> list[tuple[str, float]]:
    """أسماء الملفات (.json) ووقت التعديل."""
    d = export_directory()
    out: list[tuple[str, float]] = []
    for p in sorted(d.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        if p.is_file():
            out.append((p.name, p.stat().st_mtime))
    return out


def read_exercise_id_from_json_path(path: Path) -> int | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    ex = data.get("exercise")
    if isinstance(ex, dict) and ex.get("id") is not None:
        try:
            return int(ex["id"])
        except (TypeError, ValueError):
            return None
    return None


def _iso_to_datetime_local_value(s: Any) -> str | None:
    """تحويل قيمة ISO من JSON إلى صيغة input datetime-local."""
    if s is None or s == "":
        return None
    if not isinstance(s, str):
        return None
    t = s.strip().replace(" ", "T")
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    if not t:
        return None
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M")


def extract_create_form_prefill_from_export_json(
    data: dict[str, Any],
) -> tuple[dict[str, str | None], list[str]]:
    """
    يقرأ نفس مخطط تصدير التمرين ويُرجع قيماً تطابق قوائم نموذج الإنشاء (أو None).
    المفتاح الثاني: تحذيرات عربية للقيم غير المعتمدة في القوائم الثابتة.
    """
    warnings: list[str] = []

    def _pick(val: Any, allowed: list[str], label_ar: str) -> str | None:
        if val is None:
            return None
        s = str(val).strip()
        if not s:
            return None
        if s in allowed:
            return s
        snippet = s if len(s) <= 100 else s[:97] + "…"
        warnings.append(f"قيمة غير معتمدة في القائمة ({label_ar})، وتُركت: {snippet}")
        return None

    if not isinstance(data, dict):
        return {}, ["ملف JSON غير صالح (الجذر ليس كائناً)."]
    ex = data.get("exercise")
    if not isinstance(ex, dict):
        return {}, ["الملف لا يحتوي على كائن «exercise» كما في ملفات التصدير."]

    fields: dict[str, str | None] = {
        "exercise_name": _pick(ex.get("title"), ex_opts.EXERCISE_NAMES, "اسم التمرين"),
        "exercise_type": _pick(ex.get("exercise_type"), ex_opts.EXERCISE_TYPES, "نوع التمرين"),
        "exercise_level": _pick(ex.get("exercise_level"), ex_opts.EXERCISE_LEVELS, "مستوى التمرين"),
        "mission": _pick(ex.get("mission_label"), ex_opts.MISSIONS, "المهمة"),
        "trained_unit": _pick(ex.get("trained_unit"), ex_opts.TRAINED_UNITS, "اسم الوحدة المتدربة"),
        "location_label": _pick(ex.get("location_label"), ex_opts.EXERCISE_LOCATIONS, "مكان التمرين"),
        "planned_start": _iso_to_datetime_local_value(ex.get("planned_start")),
        "planned_end": _iso_to_datetime_local_value(ex.get("planned_end")),
    }
    return fields, warnings


def read_exercise_id_from_json_bytes(raw: bytes) -> int | None:
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    ex = data.get("exercise")
    if isinstance(ex, dict) and ex.get("id") is not None:
        try:
            return int(ex["id"])
        except (TypeError, ValueError):
            return None
    return None


def open_export_directory_in_os() -> tuple[bool, str]:
    """يفتح مجلد التصدير في مدير الملفات على الجهاز الذي يشغّل تطبيق Flask (محلياً = جهازك)."""
    d = export_directory()
    d.mkdir(parents=True, exist_ok=True)
    path = str(d.resolve())
    try:
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path], close_fds=True)
        else:
            subprocess.Popen(["xdg-open", path], close_fds=True)
        return True, ""
    except OSError as e:
        return False, str(e)


def purge_all_exercises_and_dilemmas(db: Session) -> None:
    """حذف جميع التمارين وما يتبعها من قاعدة البيانات، وجميع عناصر المعاضل (دون commit)."""
    import shutil

    from app.config import DILEMMA_PDF_DIR, EVALUATION_LIST_XLSX_DIR

    db.execute(delete(DilemmaItem))
    db.execute(delete(EvaluationListPdfItem))
    db.execute(delete(Exercise))
    if DILEMMA_PDF_DIR.exists():
        shutil.rmtree(DILEMMA_PDF_DIR, ignore_errors=True)
    if EVALUATION_LIST_XLSX_DIR.exists():
        shutil.rmtree(EVALUATION_LIST_XLSX_DIR, ignore_errors=True)


def _parse_dt(val: Any) -> datetime | None:
    if val is None or val == "":
        return None
    if isinstance(val, datetime):
        return val
    if not isinstance(val, str):
        return None
    s = val.strip().replace(" ", "T")
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _uid_or(db: Session, uid: Any, fallback: int) -> int:
    try:
        i = int(uid)
    except (TypeError, ValueError):
        return fallback
    return i if db.get(User, i) is not None else fallback


def import_exercise_bundle_from_dict(db: Session, data: dict[str, Any], owner_id: int) -> int | None:
    """
    يستورد تمريناً كاملاً من قاموس JSON بنفس مخطط التصدير (نسخة 1 أو 2).
    يُفترض أن قاعدة البيانات خالية من التمارين مسبقاً.
    """
    if not isinstance(data, dict):
        return None
    exj = data.get("exercise")
    if not isinstance(exj, dict):
        return None

    code = str(exj.get("code") or "").strip() or f"EX-{uuid.uuid4().hex[:8].upper()}"
    if db.query(Exercise).filter(Exercise.code == code).first():
        code = f"EX-{uuid.uuid4().hex[:8].upper()}"

    title = str(exj.get("title") or "").strip() or "تمرين"
    status = str(exj.get("status") or ExerciseStatus.DRAFT.value)[:32]
    ex = Exercise(
        code=code,
        title=title,
        description=str(exj.get("description") or ""),
        exercise_type=str(exj.get("exercise_type") or "")[:200],
        exercise_level=str(exj.get("exercise_level") or "")[:200],
        mission_label=str(exj.get("mission_label") or "")[:400],
        trained_unit=str(exj.get("trained_unit") or "")[:400],
        location_label=str(exj.get("location_label") or "")[:400],
        status=status,
        owner_id=owner_id,
        planned_start=_parse_dt(exj.get("planned_start")),
        planned_end=_parse_dt(exj.get("planned_end")),
        control_approved=bool(exj.get("control_approved")),
        created_at=_parse_dt(exj.get("created_at")) or datetime.utcnow(),
        updated_at=_parse_dt(exj.get("updated_at")) or datetime.utcnow(),
    )
    db.add(ex)
    db.flush()

    objectives = data.get("objectives") or []
    if isinstance(objectives, list):
        for i, row in enumerate(objectives):
            if not isinstance(row, dict):
                continue
            txt = str(row.get("text") or "").strip()[:2000]
            if not txt:
                continue
            so = row.get("sort_order")
            try:
                sort_order = int(so) if so is not None else i
            except (TypeError, ValueError):
                sort_order = i
            db.add(
                ExerciseObjective(
                    exercise_id=ex.id,
                    sort_order=sort_order,
                    text=txt,
                    created_at=_parse_dt(row.get("created_at")) or datetime.utcnow(),
                )
            )

    def _import_roster_block(key: str, kind: str) -> None:
        block = data.get(key) or []
        if not isinstance(block, list):
            return
        for i, row in enumerate(block):
            if not isinstance(row, dict):
                continue
            mil = str(row.get("military_number") or "").strip()[:128]
            rk = str(row.get("rank_ar") or "").strip()[:256]
            nm = str(row.get("full_name") or "").strip()[:256]
            pos = str(row.get("position_ar") or "").strip()[:512]
            uk = normalize_unit_level_key(str(row.get("unit_level_key") or "").strip())
            if not uk:
                uk = normalize_unit_level_key(pos)
            if uk and not pos:
                pos = label_for_unit_level_key(uk)
            if not (mil or rk or nm or uk or pos):
                continue
            so = row.get("sort_order")
            try:
                sort_order = int(so) if so is not None else i
            except (TypeError, ValueError):
                sort_order = i
            db.add(
                ExerciseRosterRow(
                    exercise_id=ex.id,
                    roster_kind=kind,
                    sort_order=sort_order,
                    military_number=mil,
                    rank_ar=rk,
                    full_name=nm,
                    unit_level_key=(uk or "")[:64],
                    position_ar=pos,
                    created_at=_parse_dt(row.get("created_at")) or datetime.utcnow(),
                )
            )

    _import_roster_block("trainee_unit_roster", "trainee")
    _import_roster_block("judge_unit_roster", "judge")

    events = data.get("event_flows") or []
    if isinstance(events, list):
        for i, row in enumerate(events):
            if not isinstance(row, dict):
                continue
            et = str(row.get("event_type") or EventFlowType.STAGE.value)[:32]
            db.add(
                EventFlow(
                    exercise_id=ex.id,
                    order_index=int(row.get("order_index") or i),
                    title=str(row.get("title") or "")[:500],
                    description=str(row.get("description") or ""),
                    scheduled_at=_parse_dt(row.get("scheduled_at")),
                    event_type=et,
                    created_at=_parse_dt(row.get("created_at")) or datetime.utcnow(),
                )
            )


    timeline = data.get("timeline_items") or []
    if isinstance(timeline, list):
        old_to_new: dict[int, int] = {}
        pending_parent: list[tuple[ExerciseTimelineItem, int]] = []
        for i, row in enumerate(timeline):
            if not isinstance(row, dict):
                continue
            try:
                so = int(row.get("sort_order") or i)
            except (TypeError, ValueError):
                so = i
            try:
                old_id = int(row.get("id")) if row.get("id") is not None else 0
            except (TypeError, ValueError):
                old_id = 0
            try:
                old_parent = int(row.get("parent_id")) if row.get("parent_id") is not None else 0
            except (TypeError, ValueError):
                old_parent = 0
            try:
                seq = int(row.get("sequence_no") or 0)
            except (TypeError, ValueError):
                seq = 0
            try:
                child_seq = int(row.get("child_sequence_no") or 0)
            except (TypeError, ValueError):
                child_seq = 0
            kind = str(row.get("row_kind") or "detail")[:32]
            if kind not in ("event", "dilemma", "detail"):
                kind = "detail"
            item = ExerciseTimelineItem(
                exercise_id=ex.id,
                sort_order=so,
                row_kind=kind,
                sequence_no=seq,
                child_sequence_no=child_seq,
                title=str(row.get("title") or "")[:500],
                time_from=str(row.get("time_from") or "")[:64],
                time_to=str(row.get("time_to") or "")[:64],
                reporting_systems=str(row.get("reporting_systems") or "")[:1000],
                description=str(row.get("description") or ""),
                expected_reaction=str(row.get("expected_reaction") or ""),
                training_objective=str(row.get("training_objective") or ""),
                notes=str(row.get("notes") or ""),
                created_at=_parse_dt(row.get("created_at")) or datetime.utcnow(),
                updated_at=_parse_dt(row.get("updated_at")) or datetime.utcnow(),
            )
            db.add(item)
            db.flush()
            if old_id:
                old_to_new[old_id] = item.id
            if old_parent:
                pending_parent.append((item, old_parent))
        for item, old_parent in pending_parent:
            new_parent = old_to_new.get(old_parent)
            if new_parent:
                item.parent_id = new_parent

    problems = data.get("problems") or []
    if isinstance(problems, list):
        for row in problems:
            if not isinstance(row, dict):
                continue
            rid = _uid_or(db, row.get("reported_by_id"), owner_id)
            try:
                sev = int(row.get("severity") or 1)
            except (TypeError, ValueError):
                sev = 1
            sev = max(1, min(5, sev))
            st = str(row.get("status") or ProblemStatus.OPEN.value)[:32]
            db.add(
                Problem(
                    exercise_id=ex.id,
                    title=str(row.get("title") or "")[:500],
                    description=str(row.get("description") or ""),
                    severity=sev,
                    status=st,
                    reported_by_id=rid,
                    created_at=_parse_dt(row.get("created_at")) or datetime.utcnow(),
                    updated_at=_parse_dt(row.get("updated_at")) or datetime.utcnow(),
                )
            )

    checklists = data.get("checklists") or []
    if isinstance(checklists, list):
        for cl in checklists:
            if not isinstance(cl, dict):
                continue
            cid = _uid_or(db, cl.get("created_by_id"), owner_id)
            c = Checklist(
                exercise_id=ex.id,
                title=str(cl.get("title") or "")[:500],
                created_by_id=cid,
                created_at=_parse_dt(cl.get("created_at")) or datetime.utcnow(),
            )
            db.add(c)
            db.flush()
            items = cl.get("items") or []
            if isinstance(items, list):
                for j, it in enumerate(items):
                    if not isinstance(it, dict):
                        continue
                    try:
                        w = float(it.get("weight") or 1.0)
                    except (TypeError, ValueError):
                        w = 1.0
                    try:
                        so = int(it.get("sort_order") or j)
                    except (TypeError, ValueError):
                        so = j
                    db.add(
                        ChecklistItem(
                            checklist_id=c.id,
                            sort_order=so,
                            text=str(it.get("text") or "")[:2000],
                            weight=w,
                            is_done=bool(it.get("is_done")),
                            judge_note=str(it.get("judge_note") or "")[:2000],
                        )
                    )

    notes = data.get("evaluation_notes") or []
    if isinstance(notes, list):
        for row in notes:
            if not isinstance(row, dict):
                continue
            uid = _uid_or(db, row.get("user_id"), owner_id)
            db.add(
                EvaluationNote(
                    exercise_id=ex.id,
                    user_id=uid,
                    body=str(row.get("body") or ""),
                    created_at=_parse_dt(row.get("created_at")) or datetime.utcnow(),
                )
            )

    links = data.get("exercise_ref_links") or []
    if isinstance(links, list):
        for row in links:
            if not isinstance(row, dict):
                continue
            try:
                ref_id = int(row.get("reference_id"))
            except (TypeError, ValueError):
                continue
            if db.get(Reference, ref_id) is None:
                continue
            db.add(ExerciseRefLink(exercise_id=ex.id, reference_id=ref_id))

    dilemmas = data.get("dilemma_items")
    if isinstance(dilemmas, list) and dilemmas:
        db.execute(delete(DilemmaItem))
        for row in dilemmas:
            if not isinstance(row, dict):
                continue
            uk = str(row.get("unit_level_key") or "").strip()[:64]
            if not uk:
                continue
            try:
                so = int(row.get("sort_order") or 0)
            except (TypeError, ValueError):
                so = 0
            ep_raw = str(row.get("exercise_phase") or "main").strip()[:32]
            exercise_phase = ep_raw if ep_raw == "reorg" else "main"
            db.add(
                DilemmaItem(
                    exercise_id=ex.id,
                    exercise_phase=exercise_phase,
                    unit_level_key=uk,
                    unit_level_label=str(row.get("unit_level_label") or "")[:200],
                    sort_order=so,
                    text=str(row.get("text") or "")[:2000],
                    pdf_relpath=str(row.get("pdf_relpath") or "")[:500],
                    created_at=_parse_dt(row.get("created_at")) or datetime.utcnow(),
                )
            )


    evaluation_lists = data.get("evaluation_list_items") or data.get("evaluation_lists")
    if isinstance(evaluation_lists, list) and evaluation_lists:
        db.execute(delete(EvaluationListPdfItem).where(EvaluationListPdfItem.exercise_id == ex.id))
        for row in evaluation_lists:
            if not isinstance(row, dict):
                continue
            uk = str(row.get("unit_level_key") or "").strip()[:64]
            if not uk:
                continue
            try:
                so = int(row.get("sort_order") or 0)
            except (TypeError, ValueError):
                so = 0
            ep_raw = str(row.get("exercise_phase") or "main").strip()[:32]
            exercise_phase = ep_raw if ep_raw == "reorg" else "main"
            db.add(
                EvaluationListPdfItem(
                    exercise_id=ex.id,
                    exercise_phase=exercise_phase,
                    unit_level_key=uk,
                    unit_level_label=str(row.get("unit_level_label") or "")[:200],
                    sort_order=so,
                    text=str(row.get("text") or "")[:2000],
                    pdf_relpath=str(row.get("pdf_relpath") or "")[:500],
                    created_at=_parse_dt(row.get("created_at")) or datetime.utcnow(),
                )
            )

    db.flush()
    db.refresh(ex)
    write_exercise_json_file(db, ex.id)
    return ex.id
