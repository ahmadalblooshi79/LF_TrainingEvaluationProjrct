"""بنك المعلومات — بنية شجرية للمرفقات (مجرى الأحداث، تقييم الإجراءات، تقييم المعاضل)."""

from __future__ import annotations

import re
import sys
import uuid
from collections import defaultdict
from pathlib import Path, PurePosixPath

# عند تشغيل الملف مباشرة (Run Python File) يُضاف جذر المشروع لمسار الاستيراد
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import INFO_BANK_DIR
from app.information_bank_catalog import INFO_BANK_UNIT_LEVELS, TRAINING_PHASES
from app.models.domain import (
    InformationBankTrainingPhase,
    InformationBankTreeNode,
    InformationBankUnitLevel,
    InfoBankActionEvalXlsx,
    InfoBankDilemmaEvalXlsx,
    InfoBankEventFlowPdf,
)

INFO_BANK_TREE_KINDS = ("event_flow", "action_eval", "dilemma_eval")

# المراحل الرئيسية الثلاث المطلوبة في الشجرة
PRIMARY_PHASE_KEYS = ("preparation", "opening", "battle_exposure")

ALLOWED_FILE_EXTENSIONS = (".pdf", ".doc", ".docx", ".xlsx")

_LEGACY_MODEL_BY_KIND = {
    "event_flow": InfoBankEventFlowPdf,
    "action_eval": InfoBankActionEvalXlsx,
    "dilemma_eval": InfoBankDilemmaEvalXlsx,
}

_INVALID_PATH_PART = re.compile(r'[<>:"|?*\x00-\x1f]')


def kind_tab(kind: str) -> str:
    return {
        "event_flow": "event-flow",
        "action_eval": "action-eval",
        "dilemma_eval": "dilemma-eval",
    }.get(kind, "event-flow")


def _sanitize_path_parts(relative: str) -> str:
    """يحافظ على أسماء الملفات/المجلدات مع منع اجتياز المسار فقط."""
    rel = (relative or "").replace("\\", "/").strip().lstrip("/")
    if not rel:
        return ""
    parts: list[str] = []
    for part in PurePosixPath(rel).parts:
        p = part.strip()
        if not p or p in (".", ".."):
            continue
        p = _INVALID_PATH_PART.sub("_", p)
        if p:
            parts.append(p)
    return "/".join(parts)


def is_allowed_tree_filename(name: str) -> bool:
    low = (name or "").lower()
    return any(low.endswith(ext) for ext in ALLOWED_FILE_EXTENSIONS)


def _is_xlsx_bytes(data: bytes) -> bool:
    import io
    import zipfile

    if not data or len(data) < 4:
        return False
    if data[:2] != b"PK":
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            return "[Content_Types].xml" in z.namelist()
    except zipfile.BadZipFile:
        return False


def _sniff_pdf_doc_ext(data: bytes) -> str | None:
    if data[:5] == b"%PDF-":
        return ".pdf"
    if data[:4] == b"PK\x03\x04":
        return ".docx"
    if len(data) >= 8 and data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return ".doc"
    return None


def sniff_allowed_ext(data: bytes, filename: str) -> str | None:
    low = (filename or "").lower()
    if low.endswith(".xlsx") and _is_xlsx_bytes(data):
        return ".xlsx"
    ext = _sniff_pdf_doc_ext(data)
    if ext:
        return ext
    return None


def tree_storage_root(kind: str) -> Path:
    root = (INFO_BANK_DIR / kind / "tree").resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def node_file_abspath(kind: str, relpath: str | None) -> Path | None:
    if not relpath or kind not in INFO_BANK_TREE_KINDS:
        return None
    norm = relpath.replace("\\", "/").strip()
    if not norm or any(part == ".." for part in norm.split("/")):
        return None
    base = INFO_BANK_DIR.resolve()
    out = (base / norm).resolve()
    try:
        out.relative_to(base)
    except ValueError:
        return None
    return out if out.is_file() else None


def unlink_node_file(kind: str, relpath: str | None) -> None:
    p = node_file_abspath(kind, relpath)
    if p is None:
        return
    try:
        p.unlink()
    except OSError:
        pass


def _next_sort(db: Session, kind: str, parent_id: int | None) -> int:
    mx = (
        db.query(func.max(InformationBankTreeNode.sort_order))
        .filter(
            InformationBankTreeNode.kind == kind,
            InformationBankTreeNode.parent_id == parent_id,
        )
        .scalar()
    )
    return (int(mx) if mx is not None else -1) + 1


def _phase_rows(db: Session) -> list[InformationBankTrainingPhase]:
    rows = (
        db.query(InformationBankTrainingPhase)
        .order_by(
            InformationBankTrainingPhase.sort_order,
            InformationBankTrainingPhase.created_at,
        )
        .all()
    )
    if rows:
        return rows
    out: list[InformationBankTrainingPhase] = []
    for idx, p in enumerate(TRAINING_PHASES):
        out.append(
            InformationBankTrainingPhase(
                key=p["key"],
                label=p["label"],
                sort_order=idx,
                is_system=True,
            )
        )
    return out


def _unit_rows(db: Session) -> list[InformationBankUnitLevel]:
    rows = (
        db.query(InformationBankUnitLevel)
        .order_by(
            InformationBankUnitLevel.sort_order,
            InformationBankUnitLevel.created_at,
        )
        .all()
    )
    if rows:
        return rows
    out: list[InformationBankUnitLevel] = []
    for idx, u in enumerate(INFO_BANK_UNIT_LEVELS):
        out.append(
            InformationBankUnitLevel(
                key=u["key"],
                label=u["label"],
                sort_order=idx,
                is_system=True,
            )
        )
    return out


def _find_phase_folder(
    db: Session, kind: str, phase_key: str
) -> InformationBankTreeNode | None:
    return (
        db.query(InformationBankTreeNode)
        .filter(
            InformationBankTreeNode.kind == kind,
            InformationBankTreeNode.parent_id.is_(None),
            InformationBankTreeNode.is_folder.is_(True),
            InformationBankTreeNode.catalog_phase_key == phase_key,
        )
        .first()
    )


def _find_unit_folder(
    db: Session, kind: str, phase_folder_id: int, unit_key: str
) -> InformationBankTreeNode | None:
    return (
        db.query(InformationBankTreeNode)
        .filter(
            InformationBankTreeNode.kind == kind,
            InformationBankTreeNode.parent_id == phase_folder_id,
            InformationBankTreeNode.is_folder.is_(True),
            InformationBankTreeNode.catalog_unit_key == unit_key,
        )
        .first()
    )


def ensure_information_bank_tree(db: Session, kind: str) -> None:
    """تهيئة مجلدات المراحل والوحدات الفرعية لنوع مرفقات معيّن."""
    if kind not in INFO_BANK_TREE_KINDS:
        return
    changed = False
    phases = _phase_rows(db)
    units = _unit_rows(db)
    primary_keys = set(PRIMARY_PHASE_KEYS)
    for ph in phases:
        if ph.is_system and ph.key not in primary_keys and ph.key in {
            p["key"] for p in TRAINING_PHASES if p["key"] not in PRIMARY_PHASE_KEYS
        }:
            # مراحل نظام إضافية (مثل مسارات التقييم) — تُنشأ عند وجودها في الكتالوج
            pass
        phase_node = _find_phase_folder(db, kind, ph.key)
        if phase_node is None:
            phase_node = InformationBankTreeNode(
                kind=kind,
                parent_id=None,
                name=(ph.label or ph.key)[:500],
                is_folder=True,
                catalog_phase_key=ph.key,
                catalog_unit_key="",
                sort_order=ph.sort_order,
                is_system=True,
            )
            db.add(phase_node)
            db.flush()
            changed = True
        elif phase_node.name != (ph.label or "")[:500]:
            phase_node.name = (ph.label or ph.key)[:500]
            phase_node.sort_order = ph.sort_order
            changed = True
        for un in units:
            unit_node = _find_unit_folder(db, kind, int(phase_node.id), un.key)
            if unit_node is None:
                db.add(
                    InformationBankTreeNode(
                        kind=kind,
                        parent_id=int(phase_node.id),
                        name=(un.label or un.key)[:500],
                        is_folder=True,
                        catalog_phase_key="",
                        catalog_unit_key=un.key,
                        sort_order=un.sort_order,
                        is_system=True,
                    )
                )
                changed = True
            elif unit_node.name != (un.label or "")[:500]:
                unit_node.name = (un.label or un.key)[:500]
                unit_node.sort_order = un.sort_order
                changed = True
    if changed:
        db.commit()


def ensure_all_information_bank_trees(db: Session) -> None:
    for k in INFO_BANK_TREE_KINDS:
        ensure_information_bank_tree(db, k)
        migrate_legacy_flat_files(db, k)


def get_node(db: Session, node_id: int, kind: str | None = None) -> InformationBankTreeNode | None:
    row = db.get(InformationBankTreeNode, node_id)
    if row is None:
        return None
    if kind and row.kind != kind:
        return None
    return row


def get_or_create_folder(
    db: Session,
    *,
    kind: str,
    parent_id: int | None,
    name: str,
    is_system: bool = False,
    catalog_phase_key: str = "",
    catalog_unit_key: str = "",
) -> InformationBankTreeNode:
    nm = (name or "").strip()[:500]
    if not nm:
        raise ValueError("empty folder name")
    q = db.query(InformationBankTreeNode).filter(
        InformationBankTreeNode.kind == kind,
        InformationBankTreeNode.parent_id == parent_id,
        InformationBankTreeNode.is_folder.is_(True),
        InformationBankTreeNode.name == nm,
    )
    if catalog_phase_key:
        q = q.filter(InformationBankTreeNode.catalog_phase_key == catalog_phase_key)
    elif catalog_unit_key:
        q = q.filter(InformationBankTreeNode.catalog_unit_key == catalog_unit_key)
    existing = q.first()
    if existing:
        return existing
    row = InformationBankTreeNode(
        kind=kind,
        parent_id=parent_id,
        name=nm,
        is_folder=True,
        catalog_phase_key=(catalog_phase_key or "")[:64],
        catalog_unit_key=(catalog_unit_key or "")[:128],
        sort_order=_next_sort(db, kind, parent_id),
        is_system=is_system,
    )
    db.add(row)
    db.flush()
    return row


def add_custom_folder(
    db: Session, *, kind: str, parent_id: int | None, name: str
) -> InformationBankTreeNode:
    parent = get_node(db, parent_id, kind) if parent_id else None
    if parent_id is not None and (parent is None or not parent.is_folder):
        raise ValueError("invalid parent")
    return get_or_create_folder(db, kind=kind, parent_id=parent_id, name=name)


def _collect_descendants_post_order(db: Session, parent_node_id: int) -> list[InformationBankTreeNode]:
    """جميع أبناء parent_node_id بعمق، بترتيب آمن للحذف (الأوراق والأطفال قبل الآباء)."""
    out: list[InformationBankTreeNode] = []
    children = (
        db.query(InformationBankTreeNode)
        .filter(InformationBankTreeNode.parent_id == parent_node_id)
        .order_by(InformationBankTreeNode.sort_order, InformationBankTreeNode.id)
        .all()
    )
    for ch in children:
        out.extend(_collect_descendants_post_order(db, int(ch.id)))
        out.append(ch)
    return out


def _node_is_descendant_or_self(db: Session, ancestor_id: int, node_id: int) -> bool:
    """يُعاد True إذا node_id هي ancestor_id أو تابعة له في الشجرة (عبر سلسلة parent_id)."""
    if node_id == ancestor_id:
        return True
    hops = 0
    cur = db.get(InformationBankTreeNode, node_id)
    while cur and cur.parent_id is not None and hops < 10_000:
        if int(cur.parent_id) == ancestor_id:
            return True
        cur = db.get(InformationBankTreeNode, int(cur.parent_id))
        hops += 1
    return False


def delete_node(db: Session, node: InformationBankTreeNode) -> None:
    descendants = _collect_descendants_post_order(db, int(node.id))
    for ch in descendants:
        if not ch.is_folder and ch.file_relpath:
            unlink_node_file(ch.kind, ch.file_relpath)
        db.delete(ch)
    if not node.is_folder and node.file_relpath:
        unlink_node_file(node.kind, node.file_relpath)
    db.delete(node)


def move_tree_node(db: Session, *, kind: str, node_id: int, parent_id: int) -> None:
    """نقل مجلد أو ملف أسفل مجلد أب محدّد (نفس kind). لا يُسمح بتعيين parent_id فارغًا هنا."""
    if parent_id is None or int(parent_id) < 1:
        raise ValueError("المجلد الأب غير صالح.")
    row = get_node(db, node_id, kind)
    if row is None:
        raise ValueError("العنصر غير موجود.")
    dest = get_node(db, parent_id, kind)
    if dest is None or not dest.is_folder:
        raise ValueError("المجلد المستهدف غير صالح.")
    if int(row.id) == int(parent_id):
        raise ValueError("لا يمكن نقل العنصر إلى نفس المجلد.")
    if row.is_folder and _node_is_descendant_or_self(db, int(row.id), int(parent_id)):
        raise ValueError("لا يمكن نقل مجلد داخل نفسه أو داخل مجلد فرعي منه.")
    row.parent_id = parent_id
    db.flush()
    row.sort_order = _next_sort(db, kind, parent_id)


def _write_file_bytes(
    db: Session,
    *,
    kind: str,
    parent_id: int,
    display_name: str,
    data: bytes,
    ext: str,
) -> InformationBankTreeNode:
    parent = get_node(db, parent_id, kind)
    if parent is None or not parent.is_folder:
        raise ValueError("invalid parent")
    base_name = (display_name or "ملف").strip()
    if not base_name.lower().endswith(ext):
        base_name = f"{Path(base_name).stem}{ext}"
    base_name = base_name[:500]
    rel_storage = f"{kind}/tree/n{uuid.uuid4().hex}/{_sanitize_path_parts(base_name)}"
    dest = (INFO_BANK_DIR / rel_storage).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    row = InformationBankTreeNode(
        kind=kind,
        parent_id=parent_id,
        name=base_name,
        is_folder=False,
        file_relpath=rel_storage.replace("\\", "/"),
        sort_order=_next_sort(db, kind, parent_id),
        is_system=False,
    )
    db.add(row)
    return row


def _ensure_folder_path(
    db: Session, *, kind: str, root_parent_id: int, relative_dir: str
) -> int:
    parent_id = root_parent_id
    rel = _sanitize_path_parts(relative_dir)
    if not rel:
        return parent_id
    for part in PurePosixPath(rel).parts:
        folder = get_or_create_folder(db, kind=kind, parent_id=parent_id, name=part)
        parent_id = int(folder.id)
    return parent_id


def upload_files_to_parent(
    db: Session,
    *,
    kind: str,
    parent_id: int,
    file_storages: list,
) -> tuple[int, list[str]]:
    """يرفع ملفات و/أو شجرة مجلد (عبر webkitRelativePath) تحت parent."""
    added = 0
    errors: list[str] = []
    for f in file_storages:
        raw_name = (getattr(f, "filename", "") or "").strip()
        if not raw_name:
            continue
        rel = _sanitize_path_parts(raw_name.replace("\\", "/"))
        if not rel:
            errors.append("مسار ملف غير صالح.")
            continue
        parts = PurePosixPath(rel).parts
        file_name = parts[-1]
        dir_parts = parts[:-1]
        if not is_allowed_tree_filename(file_name):
            errors.append(f"{file_name}: صيغة غير مدعومة (PDF أو Word أو Excel).")
            continue
        try:
            data = f.read()
        except Exception:
            errors.append(f"{file_name}: تعذّر القراءة.")
            continue
        ext = sniff_allowed_ext(data, file_name)
        if not ext:
            errors.append(f"{file_name}: الملف غير صالح.")
            continue
        max_sz = 50 * 1024 * 1024 if ext in (".pdf", ".doc", ".docx") else 30 * 1024 * 1024
        if len(data) > max_sz:
            errors.append(f"{file_name}: حجم الملف يتجاوز الحد.")
            continue
        target_parent = _ensure_folder_path(
            db,
            kind=kind,
            root_parent_id=parent_id,
            relative_dir="/".join(dir_parts),
        )
        _write_file_bytes(
            db,
            kind=kind,
            parent_id=target_parent,
            display_name=file_name,
            data=data,
            ext=ext,
        )
        added += 1
    return added, errors


def build_tree_payload(db: Session, kind: str) -> list[dict]:
    ensure_information_bank_tree(db, kind)
    rows = (
        db.query(InformationBankTreeNode)
        .filter(InformationBankTreeNode.kind == kind)
        .order_by(
            InformationBankTreeNode.sort_order,
            InformationBankTreeNode.id,
        )
        .all()
    )
    by_parent: dict[int | None, list[InformationBankTreeNode]] = defaultdict(list)
    for r in rows:
        by_parent[r.parent_id].append(r)

    def node_dict(n: InformationBankTreeNode) -> dict:
        children = [node_dict(c) for c in by_parent.get(int(n.id), [])]
        d: dict = {
            "id": int(n.id),
            "name": n.name,
            "is_folder": bool(n.is_folder),
            "is_system": bool(n.is_system),
            "children": children,
        }
        if not n.is_folder and n.file_relpath:
            d["file_url"] = True
        return d

    return [node_dict(n) for n in by_parent.get(None, [])]


def migrate_legacy_flat_files(db: Session, kind: str) -> None:
    model = _LEGACY_MODEL_BY_KIND.get(kind)
    if model is None:
        return
    legacy_count = db.query(model).count()
    if legacy_count < 1:
        return
    migrated = (
        db.query(InformationBankTreeNode)
        .filter(
            InformationBankTreeNode.kind == kind,
            InformationBankTreeNode.is_folder.is_(False),
            InformationBankTreeNode.is_system.is_(False),
        )
        .count()
    )
    if migrated >= legacy_count:
        return
    for row in db.query(model).all():
        phase_key = (row.training_phase_key or "").strip()
        unit_key = (row.unit_level_key or "").strip()
        phase_folder = _find_phase_folder(db, kind, phase_key)
        if phase_folder is None:
            continue
        unit_folder = _find_unit_folder(db, kind, int(phase_folder.id), unit_key)
        if unit_folder is None:
            continue
        title = (row.title or Path(row.file_relpath or "").name or "ملف")[:500]
        rel = (row.file_relpath or "").strip()
        if not rel:
            continue
        db.add(
            InformationBankTreeNode(
                kind=kind,
                parent_id=int(unit_folder.id),
                name=title,
                is_folder=False,
                file_relpath=rel.replace("\\", "/"),
                sort_order=int(row.sort_order or 0),
                is_system=False,
            )
        )
    db.commit()


if __name__ == "__main__":
    print(
        "info_bank_tree.py وحدة داخلية — لا تُشغَّل وحدها.\n"
        "لتشغيل الموقع من مجلد المشروع:\n"
        "  run.bat\n"
        "  أو: .venv\\Scripts\\python.exe run.py\n"
        "ثم افتح: http://127.0.0.1:8005/",
        file=sys.stderr,
    )
    sys.exit(0)
