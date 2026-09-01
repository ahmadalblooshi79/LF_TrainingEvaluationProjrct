"""المكتبة — بنية شجرية للمرفقات (عقائد، معايير) بنفس آلية بنك المعلومات."""

from __future__ import annotations

import shutil
from pathlib import Path, PurePosixPath

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

EXERCISE_PAPERS_KIND_PREFIX = "ex_p_"
EXERCISE_PAPERS_TITLE = "أوراق التمرين"


def exercise_papers_kind(exercise_id: int) -> str:
    return f"{EXERCISE_PAPERS_KIND_PREFIX}{int(exercise_id)}"


def parse_exercise_papers_eid(kind: str) -> int | None:
    k = (kind or "").strip()
    if not k.startswith(EXERCISE_PAPERS_KIND_PREFIX):
        return None
    rest = k[len(EXERCISE_PAPERS_KIND_PREFIX) :]
    return int(rest) if rest.isdigit() else None


def is_exercise_papers_kind(kind: str) -> bool:
    return parse_exercise_papers_eid(kind) is not None


def is_library_tree_kind(kind: str) -> bool:
    k = (kind or "").strip()
    return k in LIBRARY_TREE_KINDS or is_exercise_papers_kind(k)


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
    if is_exercise_papers_kind(kind):
        return EXERCISE_PAPERS_TITLE
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
    if out.is_file():
        return out
    name = Path(norm).name
    if not name:
        return None
    tree = (base / kind / "tree").resolve()
    try:
        tree.relative_to(base)
    except ValueError:
        return None
    if not tree.is_dir():
        return None
    found = [p for p in tree.rglob(name) if p.is_file()]
    if len(found) == 1:
        try:
            found[0].resolve().relative_to(base)
        except ValueError:
            return None
        return found[0]
    return None


def ensure_library_tree(db: Session, kind: str) -> None:
    """شجرة المكتبة بسيطة — بدون مجلدات نظام للمراحل."""
    if not is_library_tree_kind(kind):
        return


def get_library_node(db: Session, node_id: int) -> _Node | None:
    """قراءة عقدة مكتبة بلا عزل قسم بنك المعلومات."""
    from app.ibank_section_ctx import ibank_section_bypass

    with ibank_section_bypass():
        return db.get(_Node, int(node_id))


def build_tree_payload(
    db: Session, kind: str, *, only_existing_files: bool = False
) -> list[dict]:
    ensure_library_tree(db, kind)
    from app.ibank_section_ctx import ibank_section_bypass

    with ibank_section_bypass():
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

    def node_dict(n: _Node) -> dict | None:
        children = [
            c
            for c in (node_dict(ch) for ch in by_parent.get(int(n.id), []))
            if c is not None
        ]
        if n.is_folder:
            if only_existing_files and not children:
                return None
            return {
                "id": int(n.id),
                "name": n.name,
                "is_folder": True,
                "is_system": bool(n.is_system),
                "children": children,
            }
        rel = (n.file_relpath or "").strip()
        exists = bool(rel) and node_file_abspath(n.kind, rel) is not None
        if only_existing_files and not exists:
            return None
        d: dict = {
            "id": int(n.id),
            "name": n.name,
            "is_folder": False,
            "is_system": bool(n.is_system),
            "children": children,
        }
        if exists:
            d["file_url"] = True
        return d

    return [n for n in (node_dict(r) for r in by_parent.get(None, [])) if n is not None]


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
    from app.ibank_section_ctx import ibank_section_bypass

    added = 0
    errors: list[str] = []
    touched_parents: set[int | None] = {parent_id}
    with ibank_section_bypass():
        return _upload_files_to_tree_inner(
            db,
            kind=kind,
            parent_id=parent_id,
            file_storages=file_storages,
            added=added,
            errors=errors,
            touched_parents=touched_parents,
        )


def _upload_files_to_tree_inner(
    db: Session,
    *,
    kind: str,
    parent_id: int | None,
    file_storages: list,
    added: int,
    errors: list[str],
    touched_parents: set[int | None],
) -> tuple[int, list[str]]:
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
            # صيغ غير مدعومة تُتجاهل بصمت عند إرفاق مجلد
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
    from app.ibank_section_ctx import ibank_section_bypass
    from app.info_bank_tree import _collect_descendants_post_order

    with ibank_section_bypass():
        descendants = _collect_descendants_post_order(db, int(node.id))
        for ch in descendants:
            if not ch.is_folder and ch.file_relpath:
                unlink_library_file(ch.kind, ch.file_relpath)
            db.delete(ch)
        if not node.is_folder and node.file_relpath:
            unlink_library_file(node.kind, node.file_relpath)
        db.delete(node)


def purge_library_tree(db: Session, kind: str) -> int:
    """حذف كل مجلدات وملفات تبويب المكتبة مع الملفات على القرص."""
    if not is_library_tree_kind(kind):
        raise ValueError("نوع غير صالح.")
    from app.ibank_section_ctx import ibank_section_bypass

    with ibank_section_bypass():
        rows = db.query(_Node).filter(_Node.kind == kind).all()
        count = len(rows)
        for row in rows:
            if not row.is_folder and row.file_relpath:
                unlink_library_file(row.kind, row.file_relpath)
            db.delete(row)
        db.flush()
    tree_dir = LIBRARY_DIR / kind / "tree"
    if tree_dir.is_dir():
        shutil.rmtree(tree_dir, ignore_errors=True)
    return count


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
    "EXERCISE_PAPERS_TITLE",
    "LIBRARY_TAB_SPECS",
    "LIBRARY_TREE_KINDS",
    "add_custom_folder",
    "build_tree_payload",
    "delete_library_node",
    "ensure_library_tree",
    "exercise_papers_kind",
    "get_library_node",
    "get_node",
    "is_exercise_papers_kind",
    "is_library_tree_kind",
    "library_kind_tab",
    "library_kind_title",
    "library_tab_kind",
    "move_tree_node",
    "node_file_abspath",
    "parse_exercise_papers_eid",
    "purge_library_tree",
    "upload_files_to_tree",
]
