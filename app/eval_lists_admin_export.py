"""تصدير قوائم التقييم وقوائم المعاضل من أوامر عمل إدارة النظام."""
from __future__ import annotations

import io
import shutil
import zipfile
from pathlib import Path
from typing import Any, Iterable

from app.eval_criterion_media import (
    criterion_media_absolute_path,
    ext_for_mime,
)
from app.evaluation_list_export import (
    eval_export_list_folder_relpath,
    export_download_filename,
    zip_safe_segment,
)
from app.evaluation_workflow import (
    ADMIN_EXPORT_STATUS_LABELS,
    eval_admin_export_status_key,
)
from app.exercise_phase_catalog import (
    exercise_phase_keys,
    exercise_phase_label,
    normalize_exercise_phase,
)
from app.models import (
    EvaluationCriterionMedia,
    EvaluationListPdfItem,
    EvaluationListSavedResult,
    ExercisePlannerFlowBundle,
    ExercisePlannerFlowBundleActionEval,
    PlannerFlowBundleEvalSavedResult,
)

EXPORT_KIND_EVAL = "eval"
EXPORT_KIND_ACTION = "action"

EXPORT_KIND_LABELS = {
    EXPORT_KIND_EVAL: "قوائم تقييم الإجراءات",
    EXPORT_KIND_ACTION: "قوائم تقييم المعاضل",
}

PHASE_UNSET = "__none__"
PHASE_UNSET_LABEL = "بدون مرحلة"


def parse_export_form_filters(src) -> dict[str, set[str]]:
    """units / phases / list keys / statuses من form أو args."""
    def _vals(name: str, alt: str) -> list[str]:
        getter = getattr(src, "getlist", None)
        if callable(getter):
            raw = list(getter(name) or []) + list(getter(alt) or [])
        else:
            v = src.get(name) if hasattr(src, "get") else None
            raw = v if isinstance(v, list) else ([v] if v else [])
        return [str(x).strip() for x in raw if str(x).strip()]

    units = set(_vals("unit", "units"))
    phases = set(_vals("phase", "phases"))
    lists = set(_vals("list", "lists"))
    statuses = {s for s in _vals("status", "statuses") if s in ADMIN_EXPORT_STATUS_LABELS}
    kinds = {k for k in _vals("kind", "kinds") if k in EXPORT_KIND_LABELS}
    return {
        "units": units,
        "phases": phases,
        "list_keys": lists,
        "statuses": statuses,
        "kinds": kinds,
    }


def entry_key(kind: str, item_id: int) -> str:
    return f"{kind}:{int(item_id)}"


def _phase_export_label(phase_fn, pk: str, pk_n: str) -> str:
    if not (pk_n or "").strip():
        return PHASE_UNSET_LABEL
    return phase_fn(pk) or pk_n or "مرحلة"


def _canonical_eval_map(db, exercise_id: int) -> dict[int, EvaluationListSavedResult]:
    rows = (
        db.query(EvaluationListSavedResult)
        .filter(EvaluationListSavedResult.exercise_id == int(exercise_id))
        .order_by(
            EvaluationListSavedResult.updated_at.desc(),
            EvaluationListSavedResult.id.desc(),
        )
        .all()
    )
    out: dict[int, EvaluationListSavedResult] = {}
    for row in rows:
        iid = int(row.evaluation_item_id)
        if iid not in out:
            out[iid] = row
    return out


def _canonical_action_map(db, exercise_id: int) -> dict[int, PlannerFlowBundleEvalSavedResult]:
    rows = (
        db.query(PlannerFlowBundleEvalSavedResult)
        .filter(PlannerFlowBundleEvalSavedResult.exercise_id == int(exercise_id))
        .order_by(
            PlannerFlowBundleEvalSavedResult.updated_at.desc(),
            PlannerFlowBundleEvalSavedResult.id.desc(),
        )
        .all()
    )
    out: dict[int, PlannerFlowBundleEvalSavedResult] = {}
    for row in rows:
        iid = int(row.bundle_action_eval_id)
        if iid not in out:
            out[iid] = row
    return out


def collect_admin_eval_export_catalog(
    db,
    exercise,
    *,
    unit_label_fn,
    phase_label_fn=None,
) -> list[dict[str, Any]]:
    """كل قوائم التقييم وقوائم المعاضل ذات نتيجة محفوظة في التمرين."""
    if exercise is None:
        return []
    eid = int(exercise.id)
    phase_fn = phase_label_fn or exercise_phase_label
    eval_saved = _canonical_eval_map(db, eid)
    action_saved = _canonical_action_map(db, eid)
    entries: list[dict[str, Any]] = []

    items = (
        db.query(EvaluationListPdfItem)
        .filter(EvaluationListPdfItem.exercise_id == eid)
        .order_by(EvaluationListPdfItem.sort_order, EvaluationListPdfItem.id)
        .all()
    )
    for it in items:
        saved = eval_saved.get(int(it.id))
        status = eval_admin_export_status_key(saved)
        if status is None:
            continue
        uk = (it.unit_level_key or "").strip()
        pk = (it.exercise_phase or "").strip()
        pk_n = normalize_exercise_phase(pk) or pk
        title = (it.text or "").strip() or f"قائمة تقييم {it.id}"
        entries.append(
            {
                "key": entry_key(EXPORT_KIND_EVAL, int(it.id)),
                "kind": EXPORT_KIND_EVAL,
                "item_id": int(it.id),
                "slot_index": None,
                "title": title,
                "unit_key": uk,
                "unit_label": unit_label_fn(uk) or uk,
                "phase_key": pk_n,
                "phase_label": _phase_export_label(phase_fn, pk, pk_n),
                "status": status,
                "status_label": ADMIN_EXPORT_STATUS_LABELS[status],
                "kind_label": EXPORT_KIND_LABELS[EXPORT_KIND_EVAL],
            }
        )

    pairs = (
        db.query(ExercisePlannerFlowBundleActionEval, ExercisePlannerFlowBundle)
        .join(
            ExercisePlannerFlowBundle,
            ExercisePlannerFlowBundleActionEval.bundle_id == ExercisePlannerFlowBundle.id,
        )
        .filter(ExercisePlannerFlowBundle.exercise_id == eid)
        .order_by(
            ExercisePlannerFlowBundleActionEval.slot_index,
            ExercisePlannerFlowBundleActionEval.id,
        )
        .all()
    )
    for action_row, bundle in pairs:
        if not (action_row.file_relpath or "").strip():
            continue
        saved = action_saved.get(int(action_row.id))
        status = eval_admin_export_status_key(saved)
        if status is None:
            continue
        uk = (bundle.unit_level_key or "").strip()
        pk = (bundle.exercise_phase or "").strip()
        pk_n = normalize_exercise_phase(pk) or pk
        title = (action_row.title or "").strip() or f"قائمة معاضل {action_row.id}"
        entries.append(
            {
                "key": entry_key(EXPORT_KIND_ACTION, int(action_row.id)),
                "kind": EXPORT_KIND_ACTION,
                "item_id": int(action_row.id),
                "slot_index": int(action_row.slot_index or 0),
                "title": title,
                "unit_key": uk,
                "unit_label": unit_label_fn(uk) or uk,
                "phase_key": pk_n,
                "phase_label": _phase_export_label(phase_fn, pk, pk_n),
                "status": status,
                "status_label": ADMIN_EXPORT_STATUS_LABELS[status],
                "kind_label": EXPORT_KIND_LABELS[EXPORT_KIND_ACTION],
            }
        )
    return entries


def filter_admin_eval_export_entries(
    entries: Iterable[dict[str, Any]],
    *,
    units: set[str] | None = None,
    phases: set[str] | None = None,
    list_keys: set[str] | None = None,
    statuses: set[str] | None = None,
    kinds: set[str] | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for e in entries:
        uk = (e.get("unit_key") or "").strip()
        pk = (e.get("phase_key") or "").strip() or PHASE_UNSET
        if units is not None and uk not in units:
            continue
        if phases is not None and pk not in phases:
            continue
        if list_keys is not None and (e.get("key") or "") not in list_keys:
            continue
        st = (e.get("status") or "").strip()
        if statuses is not None and st not in statuses:
            continue
        if kinds is not None and (e.get("kind") or "") not in kinds:
            continue
        out.append(e)
    return out


def catalog_filter_options(entries: list[dict[str, Any]]) -> dict[str, list[dict[str, str]]]:
    units: dict[str, str] = {}
    phases: dict[str, str] = {}
    for e in entries:
        uk = (e.get("unit_key") or "").strip()
        if uk and uk not in units:
            units[uk] = (e.get("unit_label") or uk).strip() or uk
        pk = (e.get("phase_key") or "").strip() or PHASE_UNSET
        if pk not in phases:
            if pk == PHASE_UNSET:
                phases[pk] = PHASE_UNSET_LABEL
            else:
                phases[pk] = (e.get("phase_label") or pk).strip() or pk
    phase_order = {k: i for i, k in enumerate(exercise_phase_keys())}
    return {
        "units": [{"key": k, "label": v} for k, v in units.items()],
        "phases": sorted(
            [{"key": k, "label": v} for k, v in phases.items()],
            key=lambda r: (phase_order.get(r["key"], 99), r["label"]),
        ),
        "statuses": [
            {"key": k, "label": lab} for k, lab in ADMIN_EXPORT_STATUS_LABELS.items()
        ],
        "kinds": [
            {"key": k, "label": EXPORT_KIND_LABELS[k]}
            for k in (EXPORT_KIND_EVAL, EXPORT_KIND_ACTION)
        ],
    }


def media_rows_for_list(
    db,
    exercise_id: int,
    *,
    kind: str,
    item_id: int,
) -> list[EvaluationCriterionMedia]:
    q = db.query(EvaluationCriterionMedia).filter(
        EvaluationCriterionMedia.exercise_id == int(exercise_id)
    )
    if kind == EXPORT_KIND_EVAL:
        q = q.filter(
            EvaluationCriterionMedia.evaluation_list_item_id == int(item_id),
            EvaluationCriterionMedia.bundle_action_eval_id.is_(None),
        )
    else:
        q = q.filter(
            EvaluationCriterionMedia.bundle_action_eval_id == int(item_id),
            EvaluationCriterionMedia.evaluation_list_item_id.is_(None),
        )
    return q.order_by(EvaluationCriterionMedia.row_index, EvaluationCriterionMedia.id).all()


def media_export_filename(row: EvaluationCriterionMedia, used: set[str]) -> str:
    kind = "فيديو" if (row.media_kind or "").strip().lower() == "video" else "صورة"
    src = criterion_media_absolute_path(row.file_relpath or "")
    ext = ""
    if src is not None:
        ext = src.suffix or ""
    if not ext:
        mk = "video" if kind == "فيديو" else "photo"
        ext = ext_for_mime(row.mime_type, mk)
    if ext and not ext.startswith("."):
        ext = f".{ext}"
    base = zip_safe_segment(f"{kind}_بند_{int(row.row_index)}_{int(row.id)}", "وسيط")
    name = f"{base}{ext}"
    n = 2
    while name in used:
        name = f"{base}_{n}{ext}"
        n += 1
    used.add(name)
    return name


def media_file_bytes(row: EvaluationCriterionMedia) -> tuple[str, bytes] | None:
    path = criterion_media_absolute_path(row.file_relpath or "")
    if path is None or not path.is_file():
        return None
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if not data:
        return None
    return (path.name, data)


def iter_existing_media_exports(
    rows: Iterable[EvaluationCriterionMedia],
) -> list[tuple[EvaluationCriterionMedia, str, Path]]:
    """أسماء التصدير للوسائط الموجودة على القرص دون قراءة محتواها."""
    used: set[str] = set()
    out: list[tuple[EvaluationCriterionMedia, str, Path]] = []
    for row in rows:
        path = criterion_media_absolute_path(row.file_relpath or "")
        if path is None or not path.is_file():
            continue
        try:
            if path.stat().st_size <= 0:
                continue
        except OSError:
            continue
        out.append((row, media_export_filename(row, used), path))
    return out


def folder_for_export_entry(entry: dict[str, Any], used: set[str]) -> str:
    kind = (entry.get("kind") or "").strip()
    root = EXPORT_KIND_LABELS.get(kind, "")
    return eval_export_list_folder_relpath(
        phase_label=entry.get("phase_label") or "مرحلة",
        unit_label=entry.get("unit_label") or "وحدة",
        list_title=entry.get("title") or (entry.get("key") or "قائمة"),
        item_id=int(entry.get("item_id") or 0),
        used=used,
        root_label=root,
    )


def layout_admin_export_files(
    selected: list[dict[str, Any]],
    media_names_by_key: dict[str, list[str]],
) -> dict[str, dict[str, Any]]:
    """مسارات الأرشيف مفصولة بنوع القائمة، دون بناء Excel."""
    used_dirs: set[str] = set()
    out: dict[str, dict[str, Any]] = {}
    for entry in selected:
        key = entry.get("key") or ""
        if not key:
            continue
        folder = folder_for_export_entry(entry, used_dirs)
        xlsx_name = export_download_filename(entry.get("title") or "قائمة")
        media = [
            {"name": name, "relpath": f"{folder}/{name}"}
            for name in (media_names_by_key.get(key) or [])
        ]
        out[key] = {
            "kind": entry.get("kind") or "",
            "item_id": int(entry.get("item_id") or 0),
            "folder": folder,
            "xlsx_name": xlsx_name,
            "xlsx_relpath": f"{folder}/{xlsx_name}",
            "media": media,
        }
    return out


def admin_export_zip_filename(selected: Iterable[dict[str, Any]]) -> str:
    kinds = {(e.get("kind") or "").strip() for e in selected}
    kinds.discard("")
    if kinds == {EXPORT_KIND_EVAL}:
        return "قوائم_تقييم_الإجراءات.zip"
    if kinds == {EXPORT_KIND_ACTION}:
        return "قوائم_تقييم_المعاضل.zip"
    return "قوائم_تقييم_الإجراءات_والمعاضل.zip"


def zip_entries_for_selected(
    selected: list[dict[str, Any]],
    *,
    xlsx_by_key: dict[str, bytes],
    media_by_key: dict[str, list[tuple[str, bytes]]],
) -> list[tuple[str, bytes]]:
    """يبني شجرة المرحلة/الوحدة/القائمة مع ملف Excel والوسائط."""
    used_dirs: set[str] = set()
    entries: list[tuple[str, bytes]] = []
    for e in selected:
        key = e.get("key") or ""
        data = xlsx_by_key.get(key)
        if not data:
            continue
        folder = folder_for_export_entry(e, used_dirs)
        xlsx_name = export_download_filename(e.get("title") or "قائمة")
        entries.append((f"{folder}/{xlsx_name}", data))
        used_media: set[str] = set()
        for media_name, media_bytes in media_by_key.get(key) or []:
            fname = zip_safe_segment(Path(media_name).stem, "وسيط") + Path(media_name).suffix
            n = 2
            out_name = fname
            while out_name in used_media:
                stem = Path(fname).stem
                out_name = f"{stem}_{n}{Path(fname).suffix}"
                n += 1
            used_media.add(out_name)
            entries.append((f"{folder}/{out_name}", media_bytes))
    return entries


def _stored_zip_info(relpath: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo((relpath or "").replace("\\", "/"))
    info.compress_type = zipfile.ZIP_STORED
    info.flag_bits |= 0x800
    return info


def stored_zip_add_bytes(zf: zipfile.ZipFile, relpath: str, data: bytes) -> None:
    zf.writestr(_stored_zip_info(relpath), data)


def stored_zip_add_file(
    zf: zipfile.ZipFile,
    relpath: str,
    path: Path,
    on_bytes=None,
) -> None:
    """نسخ الملف كما هو دون إعادة ضغط — أسرع للصور والفيديو."""
    info = _stored_zip_info(relpath)
    size = path.stat().st_size
    copied = 0
    with zf.open(info, "w", force_zip64=size > 0xFFFFFFFF) as dest, path.open("rb") as src:
        while True:
            chunk = src.read(1024 * 1024)
            if not chunk:
                break
            dest.write(chunk)
            copied += len(chunk)
            if on_bytes is not None:
                on_bytes(copied, size)


def pack_admin_eval_export_zip(entries: list[tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
        for rel, data in entries:
            stored_zip_add_bytes(zf, rel, data)
    return buf.getvalue()
