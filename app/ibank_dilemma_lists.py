"""تبويب «قوائم تقييم المعاضل» — رفع القوائم وفرضها على وحدات تنظيم المعركة."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from sqlalchemy.orm import Session

from app.ibank_ui import unit_level_row_is_removed_brigade
from app.models.domain import (
    InformationBankDilemmaListUnit,
    InformationBankTreeNode,
    InformationBankUnitLevel,
)

DILEMMA_LISTS_KIND = "dilemma_lists"
DILEMMA_LISTS_TAB = "dilemma-lists"
DILEMMA_LISTS_ROOT_NAME = "قوائم تقييم المعاضل"
DILEMMA_LISTS_ROOT_CATALOG_KEY = "dilemma_lists_root"


def normalize_list_basename(name: str) -> str:
    """تطبيع اسم ملف القائمة للمطابقة مع قوائم تقييم الإجراءات."""
    s = Path((name or "").strip()).name
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = s.translate(
        str.maketrans(
            {
                "أ": "ا",
                "إ": "ا",
                "آ": "ا",
                "ٱ": "ا",
                "ى": "ي",
                "ئ": "ي",
                "ؤ": "و",
                "ة": "ه",
                "ـ": "",
            }
        )
    )
    stem = Path(s).stem
    stem = re.sub(r"\s+", " ", stem).strip().casefold()
    return stem


def ensure_dilemma_lists_root(db: Session) -> InformationBankTreeNode:
    """جذر نظام واحد لاستقبال الملفات/المجلدات المرفقة."""
    existing = (
        db.query(InformationBankTreeNode)
        .filter(
            InformationBankTreeNode.kind == DILEMMA_LISTS_KIND,
            InformationBankTreeNode.parent_id.is_(None),
            InformationBankTreeNode.is_folder.is_(True),
            InformationBankTreeNode.catalog_phase_key == DILEMMA_LISTS_ROOT_CATALOG_KEY,
        )
        .order_by(InformationBankTreeNode.id)
        .first()
    )
    if existing is not None:
        if (existing.name or "").strip() != DILEMMA_LISTS_ROOT_NAME:
            existing.name = DILEMMA_LISTS_ROOT_NAME
        existing.is_system = True
        return existing
    # توافق: جذر قديم بلا catalog_phase_key
    legacy = (
        db.query(InformationBankTreeNode)
        .filter(
            InformationBankTreeNode.kind == DILEMMA_LISTS_KIND,
            InformationBankTreeNode.parent_id.is_(None),
            InformationBankTreeNode.is_folder.is_(True),
        )
        .order_by(InformationBankTreeNode.id)
        .first()
    )
    if legacy is not None:
        legacy.catalog_phase_key = DILEMMA_LISTS_ROOT_CATALOG_KEY
        legacy.is_system = True
        legacy.name = DILEMMA_LISTS_ROOT_NAME
        return legacy
    root = InformationBankTreeNode(
        kind=DILEMMA_LISTS_KIND,
        parent_id=None,
        name=DILEMMA_LISTS_ROOT_NAME,
        is_folder=True,
        catalog_phase_key=DILEMMA_LISTS_ROOT_CATALOG_KEY,
        catalog_unit_key="",
        sort_order=0,
        is_system=True,
    )
    db.add(root)
    db.flush()
    return root


def _collect_file_nodes(
    db: Session, parent_id: int | None, out: list[InformationBankTreeNode]
) -> None:
    rows = (
        db.query(InformationBankTreeNode)
        .filter(
            InformationBankTreeNode.kind == DILEMMA_LISTS_KIND,
            InformationBankTreeNode.parent_id == parent_id,
        )
        .order_by(
            InformationBankTreeNode.sort_order,
            InformationBankTreeNode.id,
        )
        .all()
    )
    for row in rows:
        if row.is_folder:
            _collect_file_nodes(db, int(row.id), out)
        else:
            out.append(row)


def list_dilemma_eval_list_files(db: Session) -> list[InformationBankTreeNode]:
    ensure_dilemma_lists_root(db)
    files: list[InformationBankTreeNode] = []
    roots = (
        db.query(InformationBankTreeNode)
        .filter(
            InformationBankTreeNode.kind == DILEMMA_LISTS_KIND,
            InformationBankTreeNode.parent_id.is_(None),
        )
        .order_by(InformationBankTreeNode.sort_order, InformationBankTreeNode.id)
        .all()
    )
    for root in roots:
        if root.is_folder:
            _collect_file_nodes(db, int(root.id), files)
        else:
            files.append(root)
    return files


def org_units_for_assignment(db: Session) -> list[dict[str, str]]:
    """وحدات تنظيم المعركة المدرجة في التمرين (لـ checkbox)."""
    rows = (
        db.query(InformationBankUnitLevel)
        .filter(InformationBankUnitLevel.included_in_exercise.is_(True))
        .order_by(
            InformationBankUnitLevel.brigade_group,
            InformationBankUnitLevel.sort_order,
            InformationBankUnitLevel.created_at,
        )
        .all()
    )
    out: list[dict[str, str]] = []
    for r in rows:
        key = (r.key or "").strip()
        if not key:
            continue
        if unit_level_row_is_removed_brigade(key=key, brigade_group=r.brigade_group):
            continue
        out.append(
            {
                "key": key,
                "label": (r.label or key).strip() or key,
                "brigade_group": str(r.brigade_group or "1").strip() or "1",
            }
        )
    return out


def assignments_map(db: Session) -> dict[int, set[str]]:
    rows = db.query(InformationBankDilemmaListUnit).all()
    out: dict[int, set[str]] = {}
    for row in rows:
        nid = int(row.list_node_id)
        uk = (row.unit_key or "").strip()
        if not uk:
            continue
        out.setdefault(nid, set()).add(uk)
    return out


def set_list_unit_assignments(
    db: Session, *, list_node_id: int, unit_keys: set[str]
) -> None:
    node = db.get(InformationBankTreeNode, int(list_node_id))
    if (
        node is None
        or node.kind != DILEMMA_LISTS_KIND
        or bool(node.is_folder)
    ):
        raise ValueError("قائمة التقييم غير صالحة.")
    valid_keys = {u["key"] for u in org_units_for_assignment(db)}
    wanted = {k for k in unit_keys if k in valid_keys}
    existing = (
        db.query(InformationBankDilemmaListUnit)
        .filter(InformationBankDilemmaListUnit.list_node_id == int(list_node_id))
        .all()
    )
    have = {(r.unit_key or "").strip() for r in existing}
    for row in existing:
        uk = (row.unit_key or "").strip()
        if uk not in wanted:
            db.delete(row)
    for uk in sorted(wanted - have):
        db.add(
            InformationBankDilemmaListUnit(
                list_node_id=int(list_node_id),
                unit_key=uk,
            )
        )
    db.flush()


def assignments_by_basename(db: Session) -> dict[str, set[str]]:
    """اسم القائمة المطبّع → وحدات مفروضة."""
    amap = assignments_map(db)
    out: dict[str, set[str]] = {}
    for node in list_dilemma_eval_list_files(db):
        base = normalize_list_basename(node.name or "")
        if not base:
            continue
        keys = amap.get(int(node.id), set())
        if not keys:
            continue
        out.setdefault(base, set()).update(keys)
    return out


def assigned_units_for_action_eval_name(db: Session, name: str) -> set[str]:
    """الوحدات المفروضة على قائمة إجراءات حسب مطابقة اسم الملف مع قوائم المعاضل."""
    base = normalize_list_basename(name or "")
    if not base:
        return set()
    return set(assignments_by_basename(db).get(base) or set())


def apply_dilemma_list_units_to_action_eval(db: Session) -> int:
    """تعبئة مستوى الوحدة تلقائياً في قوائم تقييم الإجراءات حسب اختيارات هذه الصفحة.

    - قائمة بوحدة واحدة: تُعبَّأ فوراً إن كان الحقل فارغاً.
    - قائمة بعدة وحدات: تُعبَّأ إن تطابق مستوى الوحدة الموروث/الحالي مع إحدى الوحدات المفروضة،
      أو تُترك فارغة للنقاش لاحقاً إن لم يتضح السياق.
    """
    by_base = assignments_by_basename(db)
    if not by_base:
        return 0
    from app.info_bank_tree import _unit_key_for_node

    rows = (
        db.query(InformationBankTreeNode)
        .filter(
            InformationBankTreeNode.kind == "action_eval",
            InformationBankTreeNode.is_folder.is_(False),
        )
        .all()
    )
    updated = 0
    for row in rows:
        base = normalize_list_basename(row.name or "")
        if not base or base not in by_base:
            continue
        assigned = by_base[base]
        if not assigned:
            continue
        current = (row.catalog_unit_key or "").strip()
        if current and current in assigned:
            continue
        if len(assigned) == 1:
            only = next(iter(assigned))
            if current != only:
                row.catalog_unit_key = only
                updated += 1
            continue
        # وحدات متعددة: إن وُجد سياق وحدة موروث ضمن المفروضات نستخدمه
        if current:
            continue
        inherited = (_unit_key_for_node(db, row) or "").strip()
        if inherited and inherited in assigned:
            row.catalog_unit_key = inherited
            updated += 1
    if updated:
        db.flush()
    return updated


def build_dilemma_lists_page_payload(db: Session) -> dict:
    """بيانات عرض تبويب قوائم تقييم المعاضل."""
    root = ensure_dilemma_lists_root(db)
    files = list_dilemma_eval_list_files(db)
    amap = assignments_map(db)
    units = org_units_for_assignment(db)
    lists: list[dict] = []
    for idx, node in enumerate(files, start=1):
        selected = sorted(amap.get(int(node.id), set()))
        lists.append(
            {
                "seq": idx,
                "id": int(node.id),
                "name": (node.name or "").strip() or f"قائمة {idx}",
                "selected_unit_keys": selected,
                "selected_count": len(selected),
            }
        )
    return {
        "root_id": int(root.id),
        "lists": lists,
        "org_units": units,
    }
