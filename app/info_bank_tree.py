"""بنك المعلومات — بنية شجرية للمرفقات (مجرى الأحداث، تقييم الإجراءات، تقييم المعاضل)."""

from __future__ import annotations

import re
import sys
import unicodedata
import uuid
from collections import defaultdict
from pathlib import Path, PurePosixPath

# عند تشغيل الملف مباشرة (Run Python File) يُضاف جذر المشروع لمسار الاستيراد
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.config import INFO_BANK_DIR
from app.information_bank_catalog import INFO_BANK_UNIT_LEVEL_TEMPLATES, TRAINING_PHASES
from app.models.domain import (
    ExerciseRosterKind,
    ExerciseRosterRow,
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
    for idx, u in enumerate(INFO_BANK_UNIT_LEVEL_TEMPLATES):
        out.append(
            InformationBankUnitLevel(
                key=u["key"],
                label=u["label"],
                sort_order=idx,
                is_system=True,
            )
        )
    return out


def _normalize_tree_label(text: str) -> str:
    """تطبيع أسماء المجلدات للمقارنة (همزات، تاء مربوطة، مسافات)."""
    s = (text or "").strip()
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
    return re.sub(r"\s+", " ", s).strip().casefold()


# تسميات شائعة في المجلدات المرفقة (قد تختلف عن كتالوج المراحل)
_PHASE_FOLDER_NAME_HINTS: tuple[tuple[str, str], ...] = (
    ("preparation", "التحضير"),
    ("opening", "الانفتاح"),
    ("battle_exposure", "التعرضية"),
    ("battle_exposure", "العمليات التعرضية"),
    ("battle_exposure", "المعركة التعرضية"),
)


def _match_phase_key_by_folder_name(db: Session, folder_name: str) -> str:
    """ربط مجلد جذر بلا مفتاح كتالوج بمرحلة تمرين عبر اسم المجلد."""
    nm = (folder_name or "").strip()
    if not nm:
        return ""
    norm_nm = _normalize_tree_label(nm)
    for ph in _phase_rows(db):
        label = (ph.label or "").strip()
        key = (ph.key or "").strip()
        if nm == label or nm == key:
            return key
        norm_label = _normalize_tree_label(label)
        if norm_nm and norm_label and norm_nm == norm_label:
            return key
    for phase_key, hint in _PHASE_FOLDER_NAME_HINTS:
        if hint in nm or _normalize_tree_label(hint) in norm_nm:
            return phase_key
    return ""


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


def _record_tree_suppression(
    db: Session,
    *,
    kind: str,
    catalog_phase_key: str = "",
    catalog_unit_key: str = "",
) -> None:
    """تسجيل حذف يدوي لمجلد مرحلة/وحدة حتى لا يُعاد إنشاؤه تلقائياً."""
    from app.database import ensure_information_bank_tree_suppressions_table

    ensure_information_bank_tree_suppressions_table()
    pk = (catalog_phase_key or "").strip()
    uk = (catalog_unit_key or "").strip()
    if not pk and not uk:
        return
    db.execute(
        text(
            """
            INSERT OR IGNORE INTO information_bank_tree_suppressions
                (kind, catalog_phase_key, catalog_unit_key)
            VALUES (:kind, :pk, :uk)
            """
        ),
        {"kind": kind, "pk": pk, "uk": uk},
    )


def _is_tree_suppressed(
    db: Session,
    *,
    kind: str,
    catalog_phase_key: str = "",
    catalog_unit_key: str = "",
) -> bool:
    pk = (catalog_phase_key or "").strip()
    uk = (catalog_unit_key or "").strip()
    row = db.execute(
        text(
            """
            SELECT 1 FROM information_bank_tree_suppressions
            WHERE kind = :kind
              AND catalog_phase_key = :pk
              AND catalog_unit_key = :uk
            LIMIT 1
            """
        ),
        {"kind": kind, "pk": pk, "uk": uk},
    ).first()
    return row is not None


def _is_phase_root_folder(node: InformationBankTreeNode) -> bool:
    return bool(
        node.is_folder
        and node.parent_id is None
        and (node.catalog_phase_key or "").strip()
    )


def _is_folder_directly_under_phase(
    db: Session, node: InformationBankTreeNode
) -> bool:
    if not node.is_folder or node.parent_id is None:
        return False
    parent = db.get(InformationBankTreeNode, int(node.parent_id))
    return parent is not None and _is_phase_root_folder(parent)


def upload_includes_subdirectory_paths(file_storages: list) -> bool:
    """هل الرفع يتضمن مسارات فرعية (إرفاق مجلد وليس ملفات جذرية فقط)."""
    for f in file_storages:
        raw = (getattr(f, "filename", "") or "").strip()
        rel = _sanitize_path_parts(raw.replace("\\", "/"))
        if rel and len(PurePosixPath(rel).parts) > 1:
            return True
    return False


def _unit_key_for_node(db: Session, node: InformationBankTreeNode) -> str:
    cur: InformationBankTreeNode | None = node
    hops = 0
    while cur is not None and hops < 50:
        uk = (cur.catalog_unit_key or "").strip()
        if uk:
            return uk
        if cur.parent_id is None:
            break
        cur = db.get(InformationBankTreeNode, int(cur.parent_id))
        hops += 1
    return ""


def _apply_catalog_keys_from_parent(
    db: Session, row: InformationBankTreeNode, parent: InformationBankTreeNode | None
) -> None:
    if parent is None:
        return
    if _is_phase_root_folder(parent):
        row.catalog_phase_key = (parent.catalog_phase_key or "").strip()[:64]
        row.catalog_unit_key = (row.catalog_unit_key or "").strip()[:128]
        return
    pk = _phase_key_for_node(db, parent)
    uk = _unit_key_for_node(db, parent)
    if pk:
        row.catalog_phase_key = pk[:64]
    if uk:
        row.catalog_unit_key = uk[:128]


def _propagate_catalog_to_subtree(
    db: Session, root_id: int, *, phase_key: str, unit_key: str
) -> None:
    pk = (phase_key or "").strip()
    uk = (unit_key or "").strip()
    queue = [int(root_id)]
    seen: set[int] = set()
    while queue:
        nid = queue.pop(0)
        if nid in seen:
            continue
        seen.add(nid)
        children = (
            db.query(InformationBankTreeNode)
            .filter(InformationBankTreeNode.parent_id == nid)
            .order_by(InformationBankTreeNode.sort_order, InformationBankTreeNode.id)
            .all()
        )
        for ch in children:
            if ch.is_folder:
                if not _is_phase_root_folder(ch):
                    ch.catalog_unit_key = uk[:128]
                ch.catalog_phase_key = ""
            else:
                ch.catalog_unit_key = uk[:128]
                ch.catalog_phase_key = pk[:64]
            queue.append(int(ch.id))


def _action_eval_show_unit_select(db: Session, node: InformationBankTreeNode) -> bool:
    if node.kind != "action_eval" or _is_phase_root_folder(node):
        return False
    return bool(_phase_key_for_node(db, node))


def set_folder_unit_level(
    db: Session, *, kind: str, node_id: int, unit_key: str
) -> None:
    """تعيين مستوى الوحدة لعنصر داخل مرحلة (مجلد يُطبَّق على محتوياته، ملف يُحفظ له وحده)."""
    if kind != "action_eval":
        raise ValueError("unsupported kind")
    row = get_node(db, node_id, kind)
    if row is None:
        raise ValueError("العنصر غير موجود")
    if _is_phase_root_folder(row):
        raise ValueError("لا يُعيَّن مستوى الوحدة على مجلد المرحلة نفسه")
    phase_key = _phase_key_for_node(db, row)
    if not phase_key:
        raise ValueError("العنصر يجب أن يكون داخل مرحلة تمرين")
    uk = (unit_key or "").strip()
    if not uk:
        raise ValueError("اختر مستوى وحدة")
    valid = (
        db.query(InformationBankUnitLevel.key)
        .filter(InformationBankUnitLevel.key == uk)
        .first()
    )
    if not valid:
        raise ValueError("مستوى وحدة غير صالح")
    if row.is_folder:
        row.catalog_unit_key = uk[:128]
        row.catalog_phase_key = ""
        _propagate_catalog_to_subtree(db, int(row.id), phase_key=phase_key, unit_key=uk)
    else:
        row.catalog_unit_key = uk[:128]
        row.catalog_phase_key = phase_key[:64]


def _phase_key_for_node(db: Session, node: InformationBankTreeNode) -> str:
    pk = (node.catalog_phase_key or "").strip()
    if pk:
        return pk
    pid = node.parent_id
    hops = 0
    while pid is not None and hops < 50:
        parent = db.get(InformationBankTreeNode, int(pid))
        if parent is None:
            break
        pk = (parent.catalog_phase_key or "").strip()
        if pk:
            return pk
        if parent.parent_id is None and parent.is_folder:
            guessed = _match_phase_key_by_folder_name(db, parent.name)
            if guessed:
                return guessed
        pid = parent.parent_id
        hops += 1
    if node.parent_id is None and node.is_folder:
        return _match_phase_key_by_folder_name(db, node.name)
    return ""


def _record_suppression_for_node(db: Session, node: InformationBankTreeNode) -> None:
    pk = (node.catalog_phase_key or "").strip()
    uk = (node.catalog_unit_key or "").strip()
    if pk and not uk:
        _record_tree_suppression(db, kind=node.kind, catalog_phase_key=pk)
    elif uk:
        phase_key = _phase_key_for_node(db, node)
        _record_tree_suppression(
            db,
            kind=node.kind,
            catalog_phase_key=phase_key,
            catalog_unit_key=uk,
        )


def _clear_catalog_keys_subtree(db: Session, root_id: int) -> None:
    """فك ربط مجلدات النظام بالكتالوج بعد النقل اليدوي."""
    queue = [int(root_id)]
    seen: set[int] = set()
    while queue:
        nid = queue.pop(0)
        if nid in seen:
            continue
        seen.add(nid)
        row = db.get(InformationBankTreeNode, nid)
        if row is None:
            continue
        row.catalog_phase_key = ""
        row.catalog_unit_key = ""
        children = (
            db.query(InformationBankTreeNode.id)
            .filter(InformationBankTreeNode.parent_id == nid)
            .all()
        )
        for (cid,) in children:
            queue.append(int(cid))


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


def _canonical_phase_root_by_key(
    db: Session, kind: str
) -> dict[str, InformationBankTreeNode]:
    """أفضل مجلد جذر لكل مرحلة (يفضّل العقدة ذات catalog_phase_key أو is_system)."""
    roots = (
        db.query(InformationBankTreeNode)
        .filter(
            InformationBankTreeNode.kind == kind,
            InformationBankTreeNode.parent_id.is_(None),
            InformationBankTreeNode.is_folder.is_(True),
        )
        .all()
    )
    out: dict[str, InformationBankTreeNode] = {}

    def _prefer(a: InformationBankTreeNode, b: InformationBankTreeNode) -> InformationBankTreeNode:
        a_pk = bool((a.catalog_phase_key or "").strip())
        b_pk = bool((b.catalog_phase_key or "").strip())
        if a_pk and not b_pk:
            return a
        if b_pk and not a_pk:
            return b
        if a.is_system and not b.is_system:
            return a
        if b.is_system and not a.is_system:
            return b
        return a if int(a.id) <= int(b.id) else b

    for root in roots:
        pk = (root.catalog_phase_key or "").strip() or _match_phase_key_by_folder_name(
            db, root.name
        )
        if not pk:
            continue
        prev = out.get(pk)
        out[pk] = root if prev is None else _prefer(prev, root)
    return out


def _merge_duplicate_phase_root_folders(db: Session, kind: str) -> bool:
    """دمج مجلدات مرحلة مكررة (بدون مفتاح كتالوج) في المجلد الرسمي للمرحلة."""
    changed = False
    canonical = _canonical_phase_root_by_key(db, kind)
    if not canonical:
        return False
    roots = (
        db.query(InformationBankTreeNode)
        .filter(
            InformationBankTreeNode.kind == kind,
            InformationBankTreeNode.parent_id.is_(None),
            InformationBankTreeNode.is_folder.is_(True),
        )
        .all()
    )
    for root in roots:
        if int(root.id) in {int(c.id) for c in canonical.values()}:
            continue
        pk = _match_phase_key_by_folder_name(db, root.name)
        if not pk or pk not in canonical:
            continue
        canon = canonical[pk]
        if int(root.id) == int(canon.id):
            continue
        children = (
            db.query(InformationBankTreeNode)
            .filter(InformationBankTreeNode.parent_id == int(root.id))
            .all()
        )
        for ch in children:
            ch.parent_id = int(canon.id)
            if kind == "action_eval":
                _apply_catalog_keys_from_parent(db, ch, canon)
        db.delete(root)
        changed = True
    return changed


def _backfill_action_eval_folder_catalog(db: Session) -> bool:
    """تعزيز سياق المرحلة/الوحدة على المجلدات الفرعية القديمة."""
    changed = False
    phase_roots = (
        db.query(InformationBankTreeNode)
        .filter(
            InformationBankTreeNode.kind == "action_eval",
            InformationBankTreeNode.parent_id.is_(None),
            InformationBankTreeNode.is_folder.is_(True),
        )
        .all()
    )
    queue: list[tuple[InformationBankTreeNode, InformationBankTreeNode | None]] = []
    for pr in phase_roots:
        pk = (pr.catalog_phase_key or "").strip() or _match_phase_key_by_folder_name(
            db, pr.name
        )
        if pk and not (pr.catalog_phase_key or "").strip():
            pr.catalog_phase_key = pk[:64]
            pr.is_system = True
            changed = True
        queue.append((pr, None))
    seen: set[int] = set()
    while queue:
        node, parent = queue.pop(0)
        nid = int(node.id)
        if nid in seen:
            continue
        seen.add(nid)
        if parent is not None and not _is_phase_root_folder(node):
            before_pk = (node.catalog_phase_key or "").strip()
            before_uk = (node.catalog_unit_key or "").strip()
            _apply_catalog_keys_from_parent(db, node, parent)
            if (node.catalog_phase_key or "").strip() != before_pk or (
                node.catalog_unit_key or ""
            ).strip() != before_uk:
                changed = True
        children = (
            db.query(InformationBankTreeNode)
            .filter(InformationBankTreeNode.parent_id == nid)
            .order_by(InformationBankTreeNode.sort_order, InformationBankTreeNode.id)
            .all()
        )
        for ch in children:
            queue.append((ch, node))
    return changed


def _link_orphan_phase_root_folders(db: Session, kind: str) -> bool:
    """ربط مجلدات مرحلة قديمة (parent_id=NULL وبدون catalog_phase_key) بالكتالوج."""
    changed = False
    orphans = (
        db.query(InformationBankTreeNode)
        .filter(
            InformationBankTreeNode.kind == kind,
            InformationBankTreeNode.parent_id.is_(None),
            InformationBankTreeNode.is_folder.is_(True),
            InformationBankTreeNode.catalog_phase_key == "",
        )
        .all()
    )
    for root in orphans:
        guessed = _match_phase_key_by_folder_name(db, root.name)
        if not guessed:
            continue
        if _find_phase_folder(db, kind, guessed) is not None:
            continue
        root.catalog_phase_key = guessed[:64]
        root.is_system = True
        changed = True
    return changed


def _hoist_children_from_unit_folder(
    db: Session,
    *,
    kind: str,
    phase_folder_id: int,
    unit_folder: InformationBankTreeNode,
    phase_key: str,
) -> None:
    from app.ibank_ui import is_removed_brigade_unit_catalog_key

    uk = (unit_folder.catalog_unit_key or "").strip()
    if uk and is_removed_brigade_unit_catalog_key(uk):
        uk = ""
    pk = (phase_key or "").strip()
    children = (
        db.query(InformationBankTreeNode)
        .filter(InformationBankTreeNode.parent_id == int(unit_folder.id))
        .order_by(InformationBankTreeNode.sort_order, InformationBankTreeNode.id)
        .all()
    )
    for ch in children:
        ch.parent_id = phase_folder_id
        if ch.is_folder:
            if uk:
                ch.catalog_unit_key = uk[:128]
            ch.catalog_phase_key = ""
        else:
            ch.catalog_unit_key = uk[:128] if uk else ""
            ch.catalog_phase_key = pk[:64] if uk else ""


def repair_action_eval_tree(db: Session) -> None:
    """إصلاح شجرة تقييم الإجراءات: ربط مجلدات المراحل القديمة وتسطيح مجلدات الوحدات."""
    kind = "action_eval"
    changed = _link_orphan_phase_root_folders(db, kind)
    if _merge_duplicate_phase_root_folders(db, kind):
        changed = True
    if _backfill_action_eval_folder_catalog(db):
        changed = True
    phase_roots = (
        db.query(InformationBankTreeNode)
        .filter(
            InformationBankTreeNode.kind == kind,
            InformationBankTreeNode.parent_id.is_(None),
            InformationBankTreeNode.is_folder.is_(True),
        )
        .all()
    )
    for phase_root in phase_roots:
        phase_key = (phase_root.catalog_phase_key or "").strip()
        if not phase_key:
            phase_key = _match_phase_key_by_folder_name(db, phase_root.name)
            if phase_key:
                phase_root.catalog_phase_key = phase_key[:64]
                phase_root.is_system = True
                changed = True
        if not phase_key:
            continue
        unit_folders = (
            db.query(InformationBankTreeNode)
            .filter(
                InformationBankTreeNode.kind == kind,
                InformationBankTreeNode.parent_id == int(phase_root.id),
                InformationBankTreeNode.is_folder.is_(True),
                InformationBankTreeNode.is_system.is_(True),
                InformationBankTreeNode.catalog_unit_key != "",
            )
            .all()
        )
        for uf in unit_folders:
            _hoist_children_from_unit_folder(
                db,
                kind=kind,
                phase_folder_id=int(phase_root.id),
                unit_folder=uf,
                phase_key=phase_key,
            )
            db.delete(uf)
            changed = True
    if changed:
        db.commit()


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
        if _is_tree_suppressed(db, kind=kind, catalog_phase_key=ph.key):
            continue
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
            if kind == "action_eval":
                continue
            if _is_tree_suppressed(
                db,
                kind=kind,
                catalog_phase_key=ph.key,
                catalog_unit_key=un.key,
            ):
                continue
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
    if kind == "action_eval":
        if _link_orphan_phase_root_folders(db, kind):
            db.commit()


def ensure_all_information_bank_trees(db: Session) -> None:
    for k in INFO_BANK_TREE_KINDS:
        ensure_information_bank_tree(db, k)
        migrate_legacy_flat_files(db, k)
    repair_action_eval_tree(db)


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
        if kind == "action_eval" and parent_id is not None:
            parent = get_node(db, parent_id, kind)
            if parent is not None:
                _apply_catalog_keys_from_parent(db, existing, parent)
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
    parent = get_node(db, parent_id, kind) if parent_id else None
    if kind == "action_eval" and parent is not None:
        if not (catalog_unit_key or "").strip():
            _apply_catalog_keys_from_parent(db, row, parent)
    db.add(row)
    db.flush()
    return row


def apply_unit_key_to_action_eval_folder(
    db: Session, *, node_id: int, unit_key: str
) -> None:
    """تعيين مستوى الوحدة لمجلد داخل مرحلة (وليس مجلد مرحلة التمرين الجذر)."""
    set_folder_unit_level(db, kind="action_eval", node_id=node_id, unit_key=unit_key)


def add_custom_folder(
    db: Session,
    *,
    kind: str,
    parent_id: int | None,
    name: str,
    unit_key: str | None = None,
) -> InformationBankTreeNode:
    parent = get_node(db, parent_id, kind) if parent_id else None
    if parent_id is not None and (parent is None or not parent.is_folder):
        raise ValueError("invalid parent")
    inherit_uk = _unit_key_for_node(db, parent) if parent else ""
    inherit_pk = (
        (parent.catalog_phase_key or "").strip()[:64]
        if parent and _is_phase_root_folder(parent)
        else (_phase_key_for_node(db, parent) if parent else "")
    )
    pending_uk = (unit_key or "").strip()
    effective_uk = pending_uk or inherit_uk
    row = get_or_create_folder(
        db,
        kind=kind,
        parent_id=parent_id,
        name=name,
        catalog_phase_key=inherit_pk if inherit_pk and not effective_uk else "",
        catalog_unit_key=effective_uk,
    )
    if kind == "action_eval" and effective_uk:
        phase_key = _phase_key_for_node(db, row) or inherit_pk
        if phase_key and not _is_phase_root_folder(row):
            row.catalog_unit_key = effective_uk[:128]
            row.catalog_phase_key = ""
            _propagate_catalog_to_subtree(
                db, int(row.id), phase_key=phase_key, unit_key=effective_uk
            )
    return row


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
        if ch.is_folder:
            _record_suppression_for_node(db, ch)
        if not ch.is_folder and ch.file_relpath:
            unlink_node_file(ch.kind, ch.file_relpath)
        db.delete(ch)
    if not node.is_folder and node.file_relpath:
        unlink_node_file(node.kind, node.file_relpath)
    if node.is_folder:
        _record_suppression_for_node(db, node)
    db.delete(node)


def move_tree_node(
    db: Session, *, kind: str, node_id: int, parent_id: int | None
) -> None:
    """نقل مجلد أو ملف إلى مجلد أب (أو إلى جذر الشجرة عند parent_id فارغ)."""
    row = get_node(db, node_id, kind)
    if row is None:
        raise ValueError("العنصر غير موجود.")
    new_parent_id: int | None
    if parent_id is None or int(parent_id) < 1:
        new_parent_id = None
    else:
        new_parent_id = int(parent_id)
        dest = get_node(db, new_parent_id, kind)
        if dest is None or not dest.is_folder:
            raise ValueError("المجلد المستهدف غير صالح.")
        if int(row.id) == new_parent_id:
            raise ValueError("لا يمكن نقل العنصر إلى نفس المجلد.")
        if row.is_folder and _node_is_descendant_or_self(
            db, int(row.id), new_parent_id
        ):
            raise ValueError(
                "لا يمكن نقل مجلد داخل نفسه أو داخل مجلد فرعي منه."
            )
    row.parent_id = new_parent_id
    db.flush()
    row.sort_order = _next_sort(db, kind, new_parent_id)
    dest_parent = get_node(db, new_parent_id, kind) if new_parent_id else None
    if row.is_folder:
        if kind == "action_eval" and dest_parent is not None:
            _apply_catalog_keys_from_parent(db, row, dest_parent)
            uk = _unit_key_for_node(db, row)
            pk = _phase_key_for_node(db, row)
            if uk:
                _propagate_catalog_to_subtree(
                    db, int(row.id), phase_key=pk, unit_key=uk
                )
        else:
            _clear_catalog_keys_subtree(db, int(row.id))
    else:
        if kind == "action_eval" and dest_parent is not None:
            _apply_catalog_keys_from_parent(db, row, dest_parent)
        else:
            row.catalog_phase_key = ""
            row.catalog_unit_key = ""


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
    if kind == "action_eval":
        _apply_catalog_keys_from_parent(db, row, parent)
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


def exercise_judge_names_by_unit(db: Session, exercise_id: int | None) -> dict[str, str]:
    """أسماء المحكمين من قائمة المحكمين حسب مفتاح مستوى الوحدة (التمرين الحالي)."""
    if not exercise_id:
        return {}
    out: dict[str, str] = {}
    rows = (
        db.query(ExerciseRosterRow)
        .filter(
            ExerciseRosterRow.exercise_id == int(exercise_id),
            ExerciseRosterRow.roster_kind == ExerciseRosterKind.JUDGE.value,
        )
        .order_by(ExerciseRosterRow.sort_order, ExerciseRosterRow.id)
        .all()
    )
    for jr in rows:
        uk = (jr.unit_level_key or "").strip()
        if not uk or uk in out:
            continue
        out[uk] = (jr.full_name or "").strip()
    return out


def build_tree_payload(
    db: Session,
    kind: str,
    *,
    unit_label_by_key: dict[str, str] | None = None,
    judge_name_by_unit: dict[str, str] | None = None,
) -> list[dict]:
    ensure_information_bank_tree(db, kind)
    labels = dict(unit_label_by_key or {})
    if not labels:
        for r in _unit_rows(db):
            k = (r.key or "").strip()
            if k:
                labels[k] = (r.label or k).strip()
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
    judge_map = dict(judge_name_by_unit or {})

    def node_dict(n: InformationBankTreeNode) -> dict:
        children = [node_dict(c) for c in by_parent.get(int(n.id), [])]
        eff_uk = _unit_key_for_node(db, n)
        is_phase_root = _is_phase_root_folder(n)
        d: dict = {
            "id": int(n.id),
            "name": n.name,
            "is_folder": bool(n.is_folder),
            "is_system": bool(n.is_system),
            "is_phase_root": is_phase_root,
            "children": children,
            "catalog_unit_key": (n.catalog_unit_key or "").strip(),
            "effective_unit_key": eff_uk,
            "unit_level_label": labels.get(eff_uk, "") if eff_uk else "",
            "judge_name": judge_map.get(eff_uk, "") if eff_uk else "",
            "show_unit_select": _action_eval_show_unit_select(db, n)
            if kind == "action_eval"
            else False,
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
