"""المكتبة — بنية شجرية للمرفقات (عقائد، معايير) بنفس آلية بنك المعلومات."""

from __future__ import annotations

from pathlib import PurePosixPath

from sqlalchemy.orm import Session

from app.config import LIBRARY_DIR
from collections import defaultdict

from app.info_bank_tree import (
    ALLOWED_FILE_EXTENSIONS,
    InformationBankTreeNode,
    _ensure_folder_path,
    _natural_sort_key,
    _next_sort,
    _resort_siblings_by_natural_name,
    _resort_touched_parents,
    _sanitize_path_parts,
    _sort_file_storages_by_path,
    _write_file_bytes,
    add_custom_folder,
    delete_node,
    get_node,
    get_or_create_folder,
    is_allowed_tree_filename,
    move_tree_node,
    node_file_abspath as _node_file_abspath_ibank,
    sniff_allowed_ext,
    upload_files_to_parent,
)
from app.models.domain import InformationBankTreeNode as _Node

LIBRARY_TREE_KINDS: tuple[str, ...] = (
    "land_forces",
    "other_branches",
    "training_standards",
)

LIBRARY_TAB_SPECS: tuple[tuple[str, str, str], ...] = (
    ("land-forces", "land_forces", "عقائد القوات البرية"),
    ("other-branches", "other_branches", "عقائد الصنوف الأخرى"),
    ("training-standards", "training_standards", "معايير التدريب"),
)

_LIBRARY_KIND_BY_TAB = {tab: kind for tab, kind, _ in LIBRARY_TAB_SPECS}
_LIBRARY_TAB_BY_KIND = {kind: tab for tab, kind, _ in LIBRARY_TAB_SPECS}
_LIBRARY_TITLE_BY_KIND = {kind: title for _, kind, title in LIBRARY_TAB_SPECS}


def is_library_tree_kind(kind: str) -> bool:
    return (kind or "").strip() in LIBRARY_TREE_KINDS


def library_kind_tab(kind: str) -> str:
    return _LIBRARY_TAB_BY_KIND.get(kind, "land-forces")


def library_tab_kind(tab: str) -> str:
    t = (tab or "").strip()
    if t in _LIBRARY_KIND_BY_TAB:
        return _LIBRARY_KIND_BY_TAB[t]
    if t in _LIBRARY_TAB_BY_KIND:
        return t
    return LIBRARY_TREE_KINDS[0]


def library_active_tab_from_request(tab_arg: str | None) -> str:
    """يُرجع معرّف التبويب (land-forces) وليس kind."""
    t = (tab_arg or "").strip()
    if t in _LIBRARY_KIND_BY_TAB:
        return t
    if t in _LIBRARY_TAB_BY_KIND:
        return _LIBRARY_TAB_BY_KIND[t]
    return LIBRARY_TAB_SPECS[0][0]


def library_kind_title(kind: str) -> str:
    return _LIBRARY_TITLE_BY_KIND.get(kind, "المكتبة")


def node_file_abspath(kind: str, relpath: str | None):
    if not is_library_tree_kind(kind):
        return _node_file_abspath_ibank(kind, relpath)
    if not relpath:
        return None
    norm = relpath.replace("\\", "/").strip()
    if not norm or ".." in norm.split("/"):
        return None
    base = LIBRARY_DIR.resolve()
    out = (base / norm).resolve()
    try:
        out.relative_to(base)
    except ValueError:
        return None
    return out if out.is_file() else None


def ensure_library_tree(db: Session, kind: str) -> None:
    """شجرة المكتبة بسيطة — بدون مجلدات نظام للمراحل."""
    if not is_library_tree_kind(kind):
        return


def build_tree_payload(db: Session, kind: str) -> list[dict]:
    ensure_library_tree(db, kind)
    rows = (
        db.query(_Node)
        .filter(_Node.kind == kind)
        .order_by(_Node.sort_order, _Node.id)
        .all()
    )
    by_parent: dict[int | None, list[_Node]] = defaultdict(list)
    for r in rows:
        by_parent[r.parent_id].append(r)
    for pid, siblings in by_parent.items():
        if pid is not None:
            siblings.sort(key=lambda n: (_natural_sort_key(n.name or ""), int(n.id)))

    def node_dict(n: _Node) -> dict:
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


def _write_file_bytes_library(
    db: Session,
    *,
    kind: str,
    parent_id: int | None,
    display_name: str,
    data: bytes,
    ext: str,
) -> _Node:
    import uuid
    from pathlib import Path

    base_name = (display_name or "ملف").strip()
    if not base_name.lower().endswith(ext):
        base_name = f"{Path(base_name).stem}{ext}"
    base_name = base_name[:500]
    rel_storage = f"{kind}/tree/n{uuid.uuid4().hex}/{_sanitize_path_parts(base_name)}"
    dest = (LIBRARY_DIR / rel_storage).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    row = _Node(
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


def upload_files_to_tree(
    db: Session,
    *,
    kind: str,
    parent_id: int | None,
    file_storages: list,
) -> tuple[int, list[str]]:
    """رفع ملفات/مجلدات تحت مجلد مستهدف أو جذر الشجرة."""
    if not is_library_tree_kind(kind):
        if parent_id is None:
            raise ValueError("invalid parent")
        return upload_files_to_parent(
            db, kind=kind, parent_id=int(parent_id), file_storages=file_storages
        )
    added = 0
    errors: list[str] = []
    touched_parents: set[int | None] = {parent_id}
    for f in _sort_file_storages_by_path(file_storages):
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
        if parent_id is not None:
            target_parent = _ensure_folder_path(
                db,
                kind=kind,
                root_parent_id=int(parent_id),
                relative_dir="/".join(dir_parts),
                touched_parents=touched_parents,
            )
        elif dir_parts:
            target_parent = _ensure_folder_path_library_root(
                db,
                kind=kind,
                relative_dir="/".join(dir_parts),
                touched_parents=touched_parents,
            )
        else:
            target_parent = None
        if target_parent is not None:
            _write_file_bytes_library(
                db,
                kind=kind,
                parent_id=target_parent,
                display_name=file_name,
                data=data,
                ext=ext,
            )
            touched_parents.add(int(target_parent))
            db.flush()
            _resort_siblings_by_natural_name(db, kind=kind, parent_id=int(target_parent))
        else:
            _write_file_bytes_library(
                db,
                kind=kind,
                parent_id=None,
                display_name=file_name,
                data=data,
                ext=ext,
            )
        added += 1
    if added:
        db.flush()
    return added, errors


def _ensure_folder_path_library_root(
    db: Session,
    *,
    kind: str,
    relative_dir: str,
    touched_parents: set[int | None] | None = None,
) -> int:
    parent_id: int | None = None
    if touched_parents is not None:
        touched_parents.add(None)
    rel = _sanitize_path_parts(relative_dir)
    if not rel:
        raise ValueError("empty path")
    for part in PurePosixPath(rel).parts:
        folder = get_or_create_folder(db, kind=kind, parent_id=parent_id, name=part)
        parent_id = int(folder.id)
        if touched_parents is not None:
            touched_parents.add(parent_id)
    if parent_id is None:
        raise ValueError("empty path")
    return parent_id


def delete_library_node(db: Session, node: _Node) -> None:
    if not is_library_tree_kind(node.kind):
        delete_node(db, node)
        return
    from app.info_bank_tree import _collect_descendants_post_order

    descendants = _collect_descendants_post_order(db, int(node.id))
    for ch in descendants:
        if not ch.is_folder and ch.file_relpath:
            unlink_library_file(ch.kind, ch.file_relpath)
        db.delete(ch)
    if not node.is_folder and node.file_relpath:
        unlink_library_file(node.kind, node.file_relpath)
    db.delete(node)


def unlink_library_file(kind: str, relpath: str | None) -> None:
    p = node_file_abspath(kind, relpath)
    if p is None:
        return
    try:
        p.unlink()
    except OSError:
        pass


__all__ = [
    "ALLOWED_FILE_EXTENSIONS",
    "LIBRARY_TAB_SPECS",
    "LIBRARY_TREE_KINDS",
    "add_custom_folder",
    "build_tree_payload",
    "delete_library_node",
    "ensure_library_tree",
    "get_node",
    "is_library_tree_kind",
    "library_kind_tab",
    "library_kind_title",
    "library_tab_kind",
    "move_tree_node",
    "node_file_abspath",
    "upload_files_to_tree",
]
