"""مزامنة قوائم التقييم في التخطيط من تبويب «قوائم التقييم» في بنك المعلومات (dilemma_eval)."""
from __future__ import annotations

import hashlib
import re
import shutil
from collections import defaultdict
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import EVALUATION_LIST_XLSX_DIR, INFO_BANK_DIR
from app.exercise_phase_catalog import (
    exercise_phase_keys,
    exercise_phase_label,
    normalize_exercise_phase,
)
from app.info_bank_tree import (
    _backfill_unit_eval_folder_catalog,
    _is_phase_root_folder,
    _match_phase_key_by_folder_name,
    _normalize_tree_label,
    _phase_key_for_node,
    _unit_key_for_node,
    ensure_information_bank_tree,
    migrate_legacy_flat_files,
    node_file_abspath,
)
from app.models import (
    EvaluationListPdfItem,
    ExerciseRosterKind,
    ExerciseRosterRow,
    InformationBankTreeNode,
)
from app.unit_levels_catalog import (
    label_for_unit_level_key,
    normalize_unit_level_key,
    planning_included_unit_keys,
)
from app.ibank_ui import unit_level_row_is_removed_brigade

# تبويب «قوائم التقييم» في بنك المعلومات — ليس action_eval (قوائم تقييم الإجراءات).
INFO_BANK_EVAL_LIST_KIND = "dilemma_eval"
_IBANK_REL_RE = re.compile(r"^(.+)/ibn_(\d+)\.xlsx$", re.IGNORECASE)


def ibank_eval_storage_relpath(unit_key: str, node_id: int) -> str:
    uk = (unit_key or "").strip()
    return f"{uk}/ibn_{int(node_id)}.xlsx"


def parse_ibank_eval_storage_relpath(relpath: str | None) -> int | None:
    norm = (relpath or "").replace("\\", "/").strip()
    m = _IBANK_REL_RE.match(norm)
    if not m:
        return None
    try:
        return int(m.group(2))
    except (TypeError, ValueError):
        return None


def _resolve_unit_key(raw: str | None, db: Session) -> str:
    """مفتاح مستوى الوحدة — كتالوج التخطيط ثم بنك المعلومات (مفتاح أو تسمية)."""
    uk = normalize_unit_level_key(raw)
    if uk:
        return uk
    v = (raw or "").strip()
    if not v or unit_level_row_is_removed_brigade(key=v):
        return ""
    from app.models import InformationBankUnitLevel

    row = db.get(InformationBankUnitLevel, v)
    if row is not None:
        return v
    by_label = (
        db.query(InformationBankUnitLevel)
        .filter(InformationBankUnitLevel.label == v)
        .first()
    )
    if by_label is not None and (by_label.key or "").strip():
        return (by_label.key or "").strip()
    norm_v = _normalize_tree_label(v)
    if norm_v:
        for r in db.query(InformationBankUnitLevel).all():
            lbl = (r.label or "").strip()
            key = (r.key or "").strip()
            if not key:
                continue
            if _normalize_tree_label(lbl) == norm_v:
                return key
    from app.information_bank_catalog import INFO_BANK_UNIT_LEVEL_TEMPLATES

    for u in INFO_BANK_UNIT_LEVEL_TEMPLATES:
        key = (u.get("key") or "").strip()
        label = (u.get("label") or "").strip()
        if v == key or v == label:
            return key
        if norm_v and _normalize_tree_label(label) == norm_v:
            return key
    return ""


def _resolve_phase_key(raw: str | None, db: Session) -> str:
    """مفتاح مرحلة التمرين — كتالوج التخطيط ثم مرادفات legacy ثم بنك المعلومات."""
    pk = normalize_exercise_phase(raw)
    if pk:
        return pk
    v = (raw or "").strip()
    if not v:
        return ""
    from app.exercise_phase_catalog import _LEGACY_TO_CATALOG, _STATIC_PHASE_LABELS
    from app.models import InformationBankTrainingPhase

    if v in _STATIC_PHASE_LABELS:
        return v
    catalog = _LEGACY_TO_CATALOG.get(v)
    if catalog:
        return catalog
    row = db.get(InformationBankTrainingPhase, v)
    if row is not None:
        return v
    by_label = (
        db.query(InformationBankTrainingPhase)
        .filter(InformationBankTrainingPhase.label == v)
        .first()
    )
    if by_label is not None and (by_label.key or "").strip():
        return (by_label.key or "").strip()
    norm_v = _normalize_tree_label(v)
    if norm_v:
        for r in db.query(InformationBankTrainingPhase).all():
            lbl = (r.label or "").strip()
            key = (r.key or "").strip()
            if key and _normalize_tree_label(lbl) == norm_v:
                return key
    from app.information_bank_catalog import TRAINING_PHASES

    for p in TRAINING_PHASES:
        key = (p.get("key") or "").strip()
        label = (p.get("label") or "").strip()
        if v == key or v == label:
            return key
        if norm_v and _normalize_tree_label(label) == norm_v:
            return key
    return ""


def _match_unit_key_by_folder_name(db: Session, folder_name: str) -> str:
    """ربط اسم مجلد فرعي بمستوى وحدة (مثل «1. قيادة مجموعة اللواء»)."""
    nm = (folder_name or "").strip()
    if not nm:
        return ""
    norm_nm = _normalize_tree_label(nm)
    norm_short = re.sub(r"^[\d\s.\-]+", "", norm_nm).strip()
    from app.models import InformationBankUnitLevel

    for row in db.query(InformationBankUnitLevel).all():
        key = (row.key or "").strip()
        label = (row.label or "").strip()
        if not key:
            continue
        if nm == label or nm == key:
            return key
        norm_label = _normalize_tree_label(label)
        if not norm_label:
            continue
        if norm_nm == norm_label or norm_short == norm_label:
            return key
        if norm_label in norm_nm or norm_nm in norm_label:
            return key
        if norm_short and (norm_label in norm_short or norm_short in norm_label):
            return key
    from app.information_bank_catalog import INFO_BANK_UNIT_LEVEL_TEMPLATES

    for u in INFO_BANK_UNIT_LEVEL_TEMPLATES:
        key = (u.get("key") or "").strip()
        label = (u.get("label") or "").strip()
        if not key:
            continue
        norm_label = _normalize_tree_label(label)
        if norm_nm == norm_label or norm_short == norm_label:
            return key
        if norm_label and (norm_label in norm_nm or norm_nm in norm_label):
            return key
    cm = re.match(r"^(?:ال)?سر(?:ية|يه)\s*(\d+)\s*$", norm_nm)
    if cm:
        from app.information_bank_catalog import INFO_BANK_UNIT_LEVEL_TEMPLATES

        num = cm.group(1)
        for u in INFO_BANK_UNIT_LEVEL_TEMPLATES:
            key = (u.get("key") or "").strip()
            label = _normalize_tree_label(u.get("label") or "")
            if not key or not label:
                continue
            if re.search(rf"سر(?:ية|يه)[/\s]*{num}(?:\s|$)", label):
                return key
    return ""


def _effective_unit_key_for_node(db: Session, node: InformationBankTreeNode) -> str:
    raw = _unit_key_for_node(db, node)
    uk = _resolve_unit_key(raw, db)
    if uk:
        return uk
    if node.is_folder:
        return _match_unit_key_by_folder_name(db, node.name)
    return ""


def _effective_phase_key_for_node(db: Session, node: InformationBankTreeNode) -> str:
    raw = _phase_key_for_node(db, node)
    pk = _resolve_phase_key(raw, db)
    if pk:
        return pk
    if node.is_folder and _is_phase_root_folder(node):
        return _resolve_phase_key(_match_phase_key_by_folder_name(db, node.name), db)
    return ""


def _phase_root_nodes_for_key(db: Session, phase_key: str) -> list[InformationBankTreeNode]:
    """مجلدات جذر «مرحلة التمرين» في تبويب قوائم التقييم."""
    pk = _resolve_phase_key(phase_key, db)
    if not pk:
        return []
    match_keys = _phase_match_keys(pk)
    roots = (
        db.query(InformationBankTreeNode)
        .filter(
            InformationBankTreeNode.kind == INFO_BANK_EVAL_LIST_KIND,
            InformationBankTreeNode.parent_id.is_(None),
            InformationBankTreeNode.is_folder.is_(True),
        )
        .order_by(InformationBankTreeNode.sort_order, InformationBankTreeNode.id)
        .all()
    )
    out: list[InformationBankTreeNode] = []
    for root in roots:
        rpk = _effective_phase_key_for_node(db, root)
        if rpk in match_keys:
            out.append(root)
    return out


def _collect_subtree_xlsx_nodes(
    db: Session, root_id: int
) -> list[InformationBankTreeNode]:
    """كل ملفات Excel (بأي عمق) تحت عقدة جذر — مجلد أو ملف."""
    root = db.get(InformationBankTreeNode, int(root_id))
    if root is None:
        return []
    out: list[InformationBankTreeNode] = []
    queue = [int(root.id)]
    seen: set[int] = set()
    while queue:
        nid = queue.pop(0)
        if nid in seen:
            continue
        seen.add(nid)
        node = db.get(InformationBankTreeNode, nid)
        if node is None or node.kind != INFO_BANK_EVAL_LIST_KIND:
            continue
        if not node.is_folder and _is_xlsx_tree_file(node):
            out.append(node)
        children = (
            db.query(InformationBankTreeNode)
            .filter(InformationBankTreeNode.parent_id == nid)
            .order_by(
                InformationBankTreeNode.sort_order,
                InformationBankTreeNode.id,
            )
            .all()
        )
        for ch in children:
            queue.append(int(ch.id))
    return out


def _file_node_to_source(db: Session, row: InformationBankTreeNode) -> dict | None:
    src_rel = (row.file_relpath or "").strip()
    if not src_rel:
        return None
    src_path = node_file_abspath(INFO_BANK_EVAL_LIST_KIND, src_rel)
    if src_path is None or not src_path.is_file():
        alt = (Path(INFO_BANK_DIR) / src_rel.replace("\\", "/")).resolve()
        if alt.is_file():
            src_path = alt
        else:
            return None
    title = (row.name or src_path.name or "قائمة تقييم").strip()[:2000]
    return {
        "node_id": int(row.id),
        "title": title or "قائمة تقييم",
        "src_relpath": src_rel,
        "src_path": src_path,
        "sort_order": int(row.sort_order or 0),
    }


def _file_belongs_to_phase_unit(
    db: Session,
    file_node: InformationBankTreeNode,
    *,
    phase_key: str,
    unit_key: str,
) -> bool:
    """هل ينتمي ملف Excel فعلياً إلى مرحلة × مستوى وحدة (وليس لوحدة فرعية أخرى)؟"""
    f_pk, f_uk = _ibank_context_for_file_node(db, file_node)
    if not f_uk or f_uk != unit_key:
        return False
    phase_match = _phase_match_keys(phase_key) or {phase_key}
    return bool(f_pk and f_pk in phase_match)


def resolve_ibank_eval_publish_unit_key(
    db: Session,
    *,
    node_id: int,
    fallback_unit_key: str,
) -> str:
    """مستوى الوحدة الصحيح للنشر حسب سياق ملف البنك."""
    node = db.get(InformationBankTreeNode, int(node_id))
    if node is not None:
        _, uk = _ibank_context_for_file_node(db, node)
        resolved = _resolve_unit_key(uk, db)
        if resolved:
            return resolved
    return _resolve_unit_key(fallback_unit_key, db) or fallback_unit_key


def remap_publish_selections_by_ibank_context(
    db: Session,
    *,
    phase_key: str,
    selections_by_unit: dict[str, set[int]],
) -> dict[str, set[int]]:
    """إعادة توزيع الاختيارات على مستوى الوحدة الفعلي لكل ملف."""
    from collections import defaultdict

    pk = _resolve_phase_key(phase_key, db) or normalize_exercise_phase(phase_key)
    out: dict[str, set[int]] = defaultdict(set)
    for form_uk, node_ids in selections_by_unit.items():
        for nid in node_ids:
            resolved_uk = resolve_ibank_eval_publish_unit_key(
                db, node_id=int(nid), fallback_unit_key=form_uk
            )
            if resolved_uk:
                out[resolved_uk].add(int(nid))
    if pk:
        return dict(out)
    return dict(selections_by_unit)


def _published_ibank_items_by_node_for_phase(
    db: Session,
    *,
    exercise_id: int,
    phase_db_keys: set[str],
) -> dict[int, object]:
    """كل القوائم المنشورة في المرحلة مفهرسة بمعرّف عقدة البنك."""
    out: dict[int, object] = {}
    rows = (
        db.query(EvaluationListPdfItem)
        .filter(
            EvaluationListPdfItem.exercise_id == int(exercise_id),
            EvaluationListPdfItem.exercise_phase.in_(phase_db_keys),
        )
        .all()
    )
    for item in rows:
        nid = parse_ibank_eval_storage_relpath(getattr(item, "pdf_relpath", None))
        if nid is not None and nid not in out:
            out[int(nid)] = item
    return out


def _published_ibank_items_by_node_for_unit_group(
    db: Session,
    *,
    exercise_id: int,
    phase_key: str,
    phase_db_keys: set[str],
    unit_key: str,
    eval_items: list,
) -> dict[int, object]:
    """قوائم منشورة لمجموعة عرض واحدة (مرحلة × مستوى وحدة) دون تسرب من وحدات أخرى."""
    uk = _resolve_unit_key(unit_key, db) or unit_key
    out: dict[int, object] = {}
    for item in eval_items:
        nid = parse_ibank_eval_storage_relpath(getattr(item, "pdf_relpath", None))
        if nid is not None:
            out[int(nid)] = item
    for item in (
        db.query(EvaluationListPdfItem)
        .filter(
            EvaluationListPdfItem.exercise_id == int(exercise_id),
            EvaluationListPdfItem.exercise_phase.in_(phase_db_keys),
        )
        .all()
    ):
        nid = parse_ibank_eval_storage_relpath(getattr(item, "pdf_relpath", None))
        if nid is None or int(nid) in out:
            continue
        node = db.get(InformationBankTreeNode, int(nid))
        if node is None:
            continue
        if _file_belongs_to_phase_unit(db, node, phase_key=phase_key, unit_key=uk):
            out[int(nid)] = item
    return out


def collect_ibank_eval_files_for_phase_unit(
    db: Session,
    *,
    phase_key: str,
    unit_key: str,
) -> list[dict]:
    """جمع ملفات Excel من بنك المعلومات: مجلد المرحلة × مستوى الوحدة (مع المجلدات الفرعية).

    القاعدة:
    - مرحلة التمرين في البنك = مرحلة التمرين في التخطيط
    - مستوى الوحدة (مجلد أو تعيين) = مستوى وحدة المحكم في قائمة المحكمين
    - تُنسخ كل الملفات تحت المجلدات المطابقة بأي عمق
    """
    prepare_dilemma_eval_ibank_tree(db)
    uk = _resolve_unit_key(unit_key, db)
    pk = _resolve_phase_key(phase_key, db)
    if not uk or not pk:
        return []

    seen: set[int] = set()
    sources: list[dict] = []

    def _add_node(row: InformationBankTreeNode) -> None:
        nid = int(row.id)
        if nid in seen:
            return
        src = _file_node_to_source(db, row)
        if src is None:
            return
        seen.add(nid)
        sources.append(src)

    for phase_root in _phase_root_nodes_for_key(db, pk):
        # 1) مجلدات مستوى الوحدة مباشرة تحت مرحلة التمرين → نسخ الشجرة كاملة
        direct_children = (
            db.query(InformationBankTreeNode)
            .filter(InformationBankTreeNode.parent_id == int(phase_root.id))
            .order_by(
                InformationBankTreeNode.sort_order,
                InformationBankTreeNode.id,
            )
            .all()
        )
        for child in direct_children:
            child_uk = _effective_unit_key_for_node(db, child)
            if child_uk != uk:
                continue
            if child.is_folder:
                for f in _collect_subtree_xlsx_nodes(db, int(child.id)):
                    if _file_belongs_to_phase_unit(db, f, phase_key=pk, unit_key=uk):
                        _add_node(f)
            elif _is_xlsx_tree_file(child) and _file_belongs_to_phase_unit(
                db, child, phase_key=pk, unit_key=uk
            ):
                _add_node(child)

        # 2) أي ملف Excel تحت مرحلة التمرين يحمل سياق (مرحلة، وحدة) مطابقاً
        for f in _collect_subtree_xlsx_nodes(db, int(phase_root.id)):
            if _file_belongs_to_phase_unit(db, f, phase_key=pk, unit_key=uk):
                _add_node(f)

    sources.sort(key=lambda s: (int(s.get("sort_order", 0)), int(s["node_id"])))
    return sources


def _node_ancestor_chain(
    db: Session, node: InformationBankTreeNode
) -> list[InformationBankTreeNode]:
    """سلسلة العقد من الملف/المجلد إلى الجذر (الأقرب أولاً)."""
    chain: list[InformationBankTreeNode] = []
    cur: InformationBankTreeNode | None = node
    hops = 0
    while cur is not None and hops < 50:
        chain.append(cur)
        if cur.parent_id is None:
            break
        cur = db.get(InformationBankTreeNode, int(cur.parent_id))
        hops += 1
    return chain


def _deepest_unit_key_for_file_node(db: Session, node: InformationBankTreeNode) -> str:
    """أقرب مستوى وحدة للملف — كتالوج أو اسم مجلد قبل مستوى أعلى."""
    for cur in _node_ancestor_chain(db, node):
        uk = (cur.catalog_unit_key or "").strip()
        if uk:
            resolved = _resolve_unit_key(uk, db)
            if resolved:
                return resolved
        if cur.is_folder:
            guessed = _match_unit_key_by_folder_name(db, cur.name)
            if guessed:
                resolved = _resolve_unit_key(guessed, db)
                if resolved:
                    return resolved
    return ""


def _deepest_phase_key_for_file_node(db: Session, node: InformationBankTreeNode) -> str:
    """أقرب مرحلة تمرين لملف Excel في الشجرة."""
    for cur in _node_ancestor_chain(db, node):
        pk = (cur.catalog_phase_key or "").strip()
        if pk:
            resolved = _resolve_phase_key(pk, db)
            if resolved:
                return resolved
        if cur.parent_id is None and cur.is_folder:
            guessed = _match_phase_key_by_folder_name(db, cur.name)
            if guessed:
                resolved = _resolve_phase_key(guessed, db)
                if resolved:
                    return resolved
    return ""


def _ibank_context_for_file_node(
    db: Session, node: InformationBankTreeNode
) -> tuple[str, str]:
    """استنتاج (مرحلة، وحدة) لملف Excel — من أقرب مجلد سياق في الشجرة."""
    pk = _deepest_phase_key_for_file_node(db, node)
    uk = _deepest_unit_key_for_file_node(db, node)
    return pk, uk


def _ibank_sources_for_phase_unit(
    index: dict[tuple[str, str], list[dict]],
    *,
    phase_key: str,
    unit_key: str,
) -> list[dict]:
    """جمع مصادر بنك المعلومات مع مراعاة مرادفات مرحلة التمرين."""
    uk = unit_key
    seen: set[int] = set()
    out: list[dict] = []
    for mpk in _phase_match_keys(phase_key) or {phase_key}:
        for src in index.get((mpk, uk), []):
            nid = int(src["node_id"])
            if nid in seen:
                continue
            seen.add(nid)
            out.append(src)
    out.sort(key=lambda s: (int(s.get("sort_order", 0)), int(s["node_id"])))
    return out


def _phase_match_keys(phase_key: str) -> set[str]:
    """كل مفاتيح المرحلة المكافئة (كتالوج + legacy) للتصفية في قاعدة البيانات."""
    pk = normalize_exercise_phase(phase_key) or (phase_key or "").strip()
    if not pk:
        return set()
    keys = {pk}
    from app.exercise_phase_catalog import _CATALOG_TO_LEGACY, _PHASE_ALIASES, _LEGACY_TO_CATALOG

    if pk in _PHASE_ALIASES:
        keys.add(_PHASE_ALIASES[pk])
    if pk in _CATALOG_TO_LEGACY:
        keys.add(_CATALOG_TO_LEGACY[pk])
    if pk in _LEGACY_TO_CATALOG:
        keys.add(_LEGACY_TO_CATALOG[pk])
    aliased = _PHASE_ALIASES.get(pk)
    if aliased and aliased in _LEGACY_TO_CATALOG:
        keys.add(_LEGACY_TO_CATALOG[aliased])
    return {k for k in keys if k}


def prepare_dilemma_eval_ibank_tree(db: Session) -> None:
    """تهيئة شجرة تبويب «قوائم التقييم» وترحيل أي ملفات مسطحة قديمة."""
    ensure_information_bank_tree(db, INFO_BANK_EVAL_LIST_KIND)
    migrate_legacy_flat_files(db, INFO_BANK_EVAL_LIST_KIND)
    if _backfill_unit_eval_folder_catalog(db, INFO_BANK_EVAL_LIST_KIND):
        db.commit()


def _legacy_dilemma_eval_xlsx_count(db: Session) -> int:
    from app.models import InfoBankDilemmaEvalXlsx

    return int(db.query(InfoBankDilemmaEvalXlsx).count())


def _is_xlsx_tree_file(node: InformationBankTreeNode) -> bool:
    if node.is_folder:
        return False
    rel = (node.file_relpath or "").strip()
    if not rel:
        return False
    name = (node.name or Path(rel).name or "").lower()
    return name.endswith(".xlsx") or rel.lower().endswith(".xlsx")


def count_dilemma_eval_ibank_xlsx_nodes(db: Session) -> int:
    """عدد ملفات Excel في تبويب «قوائم التقييم» (شجرة بأي عمق + جدول legacy)."""
    prepare_dilemma_eval_ibank_tree(db)
    tree_count = (
        db.query(InformationBankTreeNode)
        .filter(
            InformationBankTreeNode.kind == INFO_BANK_EVAL_LIST_KIND,
            InformationBankTreeNode.is_folder.is_(False),
            InformationBankTreeNode.file_relpath != "",
        )
        .count()
    )
    return int(tree_count) + _legacy_dilemma_eval_xlsx_count(db)


def _unlink_eval_list_copy(relpath: str | None) -> None:
    norm = (relpath or "").replace("\\", "/").strip()
    if not norm or any(part == ".." for part in norm.split("/")):
        return
    root = EVALUATION_LIST_XLSX_DIR.resolve()
    out = (root / norm).resolve()
    try:
        out.relative_to(root)
    except ValueError:
        return
    if not out.is_file():
        return
    try:
        out.unlink()
    except OSError:
        pass


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def exercise_roster_labels_by_unit(
    db: Session, exercise_id: int | None
) -> tuple[dict[str, str], dict[str, str]]:
    """أسماء المحكم والضابط المتدرب حسب مستوى الوحدة من قائمة المحكمين."""
    if not exercise_id:
        return {}, {}

    def _label(row: ExerciseRosterRow | None) -> str:
        if row is None:
            return "—"
        display = (getattr(row, "full_name", None) or "").strip()
        rank = (getattr(row, "rank_ar", None) or "").strip()
        if rank and display:
            return f"{rank} {display}"
        if display:
            return display
        mil = (getattr(row, "military_number", None) or "").strip()
        return mil or "—"

    judge_by_unit: dict[str, str] = {}
    trainee_by_unit: dict[str, str] = {}
    for rr in (
        db.query(ExerciseRosterRow)
        .filter(ExerciseRosterRow.exercise_id == int(exercise_id))
        .order_by(ExerciseRosterRow.sort_order, ExerciseRosterRow.id)
        .all()
    ):
        uk = _resolve_unit_key(getattr(rr, "unit_level_key", None) or "", db)
        if not uk:
            continue
        kind = (getattr(rr, "roster_kind", None) or "").strip()
        if kind == ExerciseRosterKind.JUDGE.value and uk not in judge_by_unit:
            judge_by_unit[uk] = _label(rr)
        elif kind == ExerciseRosterKind.TRAINEE.value and uk not in trainee_by_unit:
            trainee_by_unit[uk] = _label(rr)
    return judge_by_unit, trainee_by_unit


def roster_judge_unit_keys(db: Session, exercise_id: int) -> set[str]:
    """مفاتيح مستويات الوحدة المعيّنة لمحكمين في قائمة المحكمين."""
    out: set[str] = set()
    for jr in (
        db.query(ExerciseRosterRow)
        .filter(
            ExerciseRosterRow.exercise_id == int(exercise_id),
            ExerciseRosterRow.roster_kind == ExerciseRosterKind.JUDGE.value,
        )
        .order_by(ExerciseRosterRow.sort_order, ExerciseRosterRow.id)
        .all()
    ):
        uk = _resolve_unit_key(jr.unit_level_key or "", db)
        if not uk:
            uk = _resolve_unit_key(getattr(jr, "position_ar", None) or "", db)
        if uk:
            out.add(uk)
    return out


def _roster_row_unit_key(row: ExerciseRosterRow, db: Session) -> str:
    uk = _resolve_unit_key(row.unit_level_key or "", db)
    if not uk:
        uk = _resolve_unit_key(getattr(row, "position_ar", None) or "", db)
    return uk


def roster_eval_display_unit_keys(db: Session, exercise_id: int) -> set[str]:
    """مستويات الوحدة لعرض/نشر القوائم: محكمين أولاً، ثم متدربين إن لزم."""
    units = roster_judge_unit_keys(db, int(exercise_id))
    if units:
        return units
    out: set[str] = set()
    for tr in (
        db.query(ExerciseRosterRow)
        .filter(
            ExerciseRosterRow.exercise_id == int(exercise_id),
            ExerciseRosterRow.roster_kind == ExerciseRosterKind.TRAINEE.value,
        )
        .order_by(ExerciseRosterRow.sort_order, ExerciseRosterRow.id)
        .all()
    ):
        uk = _roster_row_unit_key(tr, db)
        if uk:
            out.add(uk)
    return out


def summarize_judge_roster_for_eval_lists(
    db: Session, exercise_id: int
) -> dict[str, object]:
    """تشخيص قائمة المحكمين — من لديه مستوى وحدة ومن لا."""
    total = 0
    with_unit = 0
    without_names: list[str] = []
    for jr in (
        db.query(ExerciseRosterRow)
        .filter(
            ExerciseRosterRow.exercise_id == int(exercise_id),
            ExerciseRosterRow.roster_kind == ExerciseRosterKind.JUDGE.value,
        )
        .order_by(ExerciseRosterRow.sort_order, ExerciseRosterRow.id)
        .all()
    ):
        mil = (jr.military_number or "").strip()
        nm = (jr.full_name or "").strip()
        if not mil and not nm:
            continue
        total += 1
        if _roster_row_unit_key(jr, db):
            with_unit += 1
        else:
            without_names.append(nm or mil)
    return {
        "total": total,
        "with_unit": with_unit,
        "without_names": without_names,
    }


def index_dilemma_eval_ibank_files(
    db: Session,
) -> dict[tuple[str, str], list[dict]]:
    """فهرس (مرحلة، وحدة) → ملفات Excel — عبر نسخ مباشر من مجلدات المراحل."""
    prepare_dilemma_eval_ibank_tree(db)
    out: dict[tuple[str, str], list[dict]] = defaultdict(list)
    unit_keys: set[str] = set()

    phase_roots = (
        db.query(InformationBankTreeNode)
        .filter(
            InformationBankTreeNode.kind == INFO_BANK_EVAL_LIST_KIND,
            InformationBankTreeNode.parent_id.is_(None),
            InformationBankTreeNode.is_folder.is_(True),
        )
        .all()
    )
    for pr in phase_roots:
        for child in (
            db.query(InformationBankTreeNode)
            .filter(InformationBankTreeNode.parent_id == int(pr.id))
            .all()
        ):
            uk = _effective_unit_key_for_node(db, child)
            if uk:
                unit_keys.add(uk)
        for f in _collect_subtree_xlsx_nodes(db, int(pr.id)):
            _, fuk = _ibank_context_for_file_node(db, f)
            if fuk:
                unit_keys.add(fuk)

    for pr in phase_roots:
        pk = _effective_phase_key_for_node(db, pr)
        if not pk:
            continue
        for uk in sorted(unit_keys):
            files = collect_ibank_eval_files_for_phase_unit(
                db, phase_key=pk, unit_key=uk
            )
            if files:
                out[(pk, uk)] = files

    if not out:
        from app.models import InfoBankDilemmaEvalXlsx

        _LEGACY_NODE_ID_OFFSET = 1_000_000_000
        for leg in db.query(InfoBankDilemmaEvalXlsx).order_by(
            InfoBankDilemmaEvalXlsx.sort_order, InfoBankDilemmaEvalXlsx.id
        ):
            uk = _resolve_unit_key(leg.unit_level_key or "", db)
            pk = _resolve_phase_key(leg.training_phase_key or "", db)
            if not uk or not pk:
                continue
            src_rel = (leg.file_relpath or "").strip()
            src_path = node_file_abspath(INFO_BANK_EVAL_LIST_KIND, src_rel)
            if src_path is None:
                continue
            title = (leg.title or src_path.name or "قائمة تقييم").strip()[:2000]
            out[(pk, uk)].append(
                {
                    "node_id": _LEGACY_NODE_ID_OFFSET + int(leg.id),
                    "title": title or "قائمة تقييم",
                    "src_relpath": src_rel,
                    "src_path": src_path,
                    "sort_order": int(leg.sort_order or 0),
                }
            )
    return dict(out)


def effective_eval_list_phase_keys(
    db: Session, *, roster_units: set[str]
) -> list[str]:
    """مراحل التمرين المستخدمة في المزامنة: كتالوج التخطيط + ما وُجد في بنك المعلومات."""
    catalog = list(exercise_phase_keys())
    if catalog:
        return catalog
    index = index_dilemma_eval_ibank_files(db)
    ibank_phases = sorted({pk for (pk, uk) in index.keys() if uk in roster_units})
    if ibank_phases:
        return ibank_phases
    from app.info_bank_tree import PRIMARY_PHASE_KEYS

    return list(PRIMARY_PHASE_KEYS)


def ibank_eval_list_sources(
    db: Session,
    *,
    phase_key: str,
    unit_key: str,
    allowed_unit_keys: set[str] | None = None,
    ibank_index: dict[tuple[str, str], list[dict]] | None = None,
) -> list[dict]:
    """ملفات Excel من بنك المعلومات لمرحلة × مستوى وحدة (نسخ مباشر من شجرة المرحلة)."""
    phase_norm = _resolve_phase_key(phase_key, db) or normalize_exercise_phase(phase_key)
    uk = _resolve_unit_key(unit_key, db) or normalize_unit_level_key(unit_key)
    if not phase_norm or not uk:
        return []
    if allowed_unit_keys is not None and uk not in allowed_unit_keys:
        return []
    if ibank_index is not None:
        cached = _ibank_sources_for_phase_unit(
            ibank_index, phase_key=phase_norm, unit_key=uk
        )
        if cached:
            return cached
    return collect_ibank_eval_files_for_phase_unit(
        db, phase_key=phase_norm, unit_key=uk
    )


def sync_evaluation_lists_from_ibank(
    db: Session,
    *,
    exercise_id: int,
    phase_key: str,
    unit_key: str,
    unit_label: str,
    allowed_unit_keys: set[str] | None = None,
    ibank_index: dict[tuple[str, str], list[dict]] | None = None,
    sources: list[dict] | None = None,
) -> dict[str, int]:
    """نسخ ملفات Excel من بنك المعلومات (مجلد المرحلة × مستوى الوحدة) إلى التمرين."""
    phase_norm = _resolve_phase_key(phase_key, db) or normalize_exercise_phase(phase_key)
    uk = _resolve_unit_key(unit_key, db) or normalize_unit_level_key(unit_key)
    if not phase_norm or not uk:
        return {"added": 0, "updated": 0, "removed": 0, "sources": 0}

    if sources is None:
        sources = ibank_eval_list_sources(
            db,
            phase_key=phase_norm,
            unit_key=uk,
            allowed_unit_keys=allowed_unit_keys,
            ibank_index=ibank_index,
        )
    source_ids = {int(s["node_id"]) for s in sources}
    phase_keys = _phase_match_keys(phase_norm)

    existing = (
        db.query(EvaluationListPdfItem)
        .filter(
            EvaluationListPdfItem.exercise_id == int(exercise_id),
            EvaluationListPdfItem.unit_level_key == uk,
            EvaluationListPdfItem.exercise_phase.in_(phase_keys),
        )
        .order_by(EvaluationListPdfItem.sort_order, EvaluationListPdfItem.id)
        .all()
    )
    by_node_id: dict[int, EvaluationListPdfItem] = {}
    for item in existing:
        nid = parse_ibank_eval_storage_relpath(item.pdf_relpath)
        if nid is not None:
            by_node_id[nid] = item

    EVALUATION_LIST_XLSX_DIR.mkdir(parents=True, exist_ok=True)
    added = updated = removed = 0

    for idx, src in enumerate(sources):
        node_id = int(src["node_id"])
        rel = ibank_eval_storage_relpath(uk, node_id)
        dest = (EVALUATION_LIST_XLSX_DIR / rel).resolve()
        try:
            dest.relative_to(EVALUATION_LIST_XLSX_DIR.resolve())
        except ValueError:
            continue
        src_path: Path = src["src_path"]
        if not src_path.is_file():
            alt = node_file_abspath(INFO_BANK_EVAL_LIST_KIND, src.get("src_relpath"))
            if alt is not None and alt.is_file():
                src_path = alt
            else:
                continue
        need_copy = True
        if dest.is_file():
            try:
                need_copy = _file_sha256(dest) != _file_sha256(src_path)
            except OSError:
                need_copy = True
        if need_copy:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dest)

        item = by_node_id.get(node_id)
        if item is None:
            db.add(
                EvaluationListPdfItem(
                    exercise_id=int(exercise_id),
                    exercise_phase=phase_norm,
                    unit_level_key=uk,
                    unit_level_label=(unit_label or uk)[:200],
                    sort_order=idx,
                    text=str(src["title"]),
                    pdf_relpath=rel.replace("\\", "/"),
                )
            )
            added += 1
        else:
            changed = False
            if item.exercise_phase != phase_norm:
                item.exercise_phase = phase_norm
                changed = True
            if (item.text or "").strip() != str(src["title"]).strip():
                item.text = str(src["title"])[:2000]
                changed = True
            if int(item.sort_order or 0) != idx:
                item.sort_order = idx
                changed = True
            if (item.pdf_relpath or "").replace("\\", "/") != rel.replace("\\", "/"):
                item.pdf_relpath = rel.replace("\\", "/")
                changed = True
            if need_copy or changed:
                updated += 1

    for item in existing:
        nid = parse_ibank_eval_storage_relpath(item.pdf_relpath)
        if nid is None or nid in source_ids:
            continue
        if item.pdf_relpath:
            _unlink_eval_list_copy(item.pdf_relpath)
        db.delete(item)
        removed += 1

    if added or updated or removed:
        db.flush()

    return {
        "added": added,
        "updated": updated,
        "removed": removed,
        "sources": len(sources),
    }


def sync_evaluation_lists_for_unit_all_phases(
    db: Session,
    *,
    exercise_id: int,
    unit_key: str,
    unit_label: str,
    phase_keys: list[str],
    allowed_unit_keys: set[str] | None = None,
    ibank_index: dict[tuple[str, str], list[dict]] | None = None,
) -> dict[str, int]:
    totals = {"added": 0, "updated": 0, "removed": 0, "sources": 0}
    for pk in phase_keys:
        stats = sync_evaluation_lists_from_ibank(
            db,
            exercise_id=int(exercise_id),
            phase_key=pk,
            unit_key=unit_key,
            unit_label=unit_label,
            allowed_unit_keys=allowed_unit_keys,
            ibank_index=ibank_index,
        )
        for k in totals:
            totals[k] += int(stats.get(k, 0))
    return totals


def prune_ibank_evaluation_lists_not_in_roster(
    db: Session, *, exercise_id: int, active_unit_keys: set[str]
) -> int:
    removed = 0
    rows = (
        db.query(EvaluationListPdfItem)
        .filter(EvaluationListPdfItem.exercise_id == int(exercise_id))
        .all()
    )
    for item in rows:
        uk = _resolve_unit_key(item.unit_level_key or "", db)
        if uk in active_unit_keys:
            continue
        if parse_ibank_eval_storage_relpath(item.pdf_relpath) is None:
            continue
        if item.pdf_relpath:
            _unlink_eval_list_copy(item.pdf_relpath)
        db.delete(item)
        removed += 1
    if removed:
        db.flush()
    return removed


def sync_evaluation_lists_for_exercise_roster(
    db: Session,
    *,
    exercise_id: int,
    phase_keys: list[str] | None = None,
    ibank_index: dict[tuple[str, str], list[dict]] | None = None,
) -> dict[str, int]:
    """نسخ تلقائي من بنك المعلومات عند حفظ المحكمين: مرحلة × مستوى وحدة → قوائم التقييم."""
    active_units = roster_judge_unit_keys(db, int(exercise_id))
    phases = list(phase_keys or effective_eval_list_phase_keys(db, roster_units=active_units))
    totals = {
        "added": 0,
        "updated": 0,
        "removed": 0,
        "sources": 0,
        "units": len(active_units),
        "ibank_files": 0,
    }
    for uk in sorted(active_units):
        label = label_for_unit_level_key(uk, db=db) or uk
        for pk in phases:
            file_sources = collect_ibank_eval_files_for_phase_unit(
                db, phase_key=pk, unit_key=uk
            )
            totals["ibank_files"] += len(file_sources)
            stats = sync_evaluation_lists_from_ibank(
                db,
                exercise_id=int(exercise_id),
                phase_key=pk,
                unit_key=uk,
                unit_label=label,
                allowed_unit_keys=active_units,
                sources=file_sources,
            )
            for k in ("added", "updated", "removed", "sources"):
                totals[k] += int(stats.get(k, 0))
    totals["removed"] += prune_ibank_evaluation_lists_not_in_roster(
        db, exercise_id=int(exercise_id), active_unit_keys=active_units
    )
    return totals


def publish_evaluation_lists_from_ibank(
    db: Session,
    *,
    exercise_id: int,
    phase_key: str,
    unit_key: str,
    selected_node_ids: set[int] | None = None,
) -> dict[str, int]:
    """نشر صريح: نسخ قوائم Excel من بنك المعلومات → التمرين (مرحلة × مستوى وحدة)."""
    uk = _resolve_unit_key(unit_key, db)
    pk = _resolve_phase_key(phase_key, db)
    if not uk or not pk:
        return {"added": 0, "updated": 0, "removed": 0, "sources": 0, "sources_available": 0}

    label = label_for_unit_level_key(uk, db=db) or uk
    sources = collect_ibank_eval_files_for_phase_unit(
        db, phase_key=pk, unit_key=uk
    )
    avail = len(sources)
    if selected_node_ids is not None:
        sources = [s for s in sources if int(s["node_id"]) in selected_node_ids]
    stats = sync_evaluation_lists_from_ibank(
        db,
        exercise_id=int(exercise_id),
        phase_key=pk,
        unit_key=uk,
        unit_label=label,
        sources=sources,
    )
    stats["sources_available"] = avail
    return stats


def published_ibank_node_ids_for_unit_phase(
    db: Session,
    *,
    exercise_id: int,
    phase_key: str,
    unit_key: str,
) -> set[int]:
    """معرّفات عقد بنك المعلومات المنشورة حالياً لمرحلة × وحدة."""
    uk = _resolve_unit_key(unit_key, db)
    pk = _resolve_phase_key(phase_key, db)
    if not uk or not pk:
        return set()
    phase_keys = _phase_match_keys(pk)
    out: set[int] = set()
    rows = (
        db.query(EvaluationListPdfItem)
        .filter(
            EvaluationListPdfItem.exercise_id == int(exercise_id),
            EvaluationListPdfItem.unit_level_key == uk,
            EvaluationListPdfItem.exercise_phase.in_(phase_keys),
        )
        .all()
    )
    for item in rows:
        nid = parse_ibank_eval_storage_relpath(getattr(item, "pdf_relpath", None))
        if nid is not None:
            out.add(int(nid))
    return out


def publish_single_eval_list_from_ibank(
    db: Session,
    *,
    exercise_id: int,
    phase_key: str,
    unit_key: str,
    node_id: int,
) -> dict[str, int]:
    """نشر قائمة واحدة مع الإبقاء على المنشور سابقاً."""
    uk = resolve_ibank_eval_publish_unit_key(
        db, node_id=int(node_id), fallback_unit_key=unit_key
    )
    selected = published_ibank_node_ids_for_unit_phase(
        db,
        exercise_id=int(exercise_id),
        phase_key=phase_key,
        unit_key=uk,
    )
    selected.add(int(node_id))
    return publish_evaluation_lists_from_ibank(
        db,
        exercise_id=int(exercise_id),
        phase_key=phase_key,
        unit_key=uk,
        selected_node_ids=selected,
    )


def withdraw_single_eval_list_from_ibank(
    db: Session,
    *,
    exercise_id: int,
    phase_key: str,
    unit_key: str,
    node_id: int,
) -> dict[str, int]:
    """سحب نشر قائمة واحدة (إزالتها من التمرين)."""
    uk = resolve_ibank_eval_publish_unit_key(
        db, node_id=int(node_id), fallback_unit_key=unit_key
    )
    selected = published_ibank_node_ids_for_unit_phase(
        db,
        exercise_id=int(exercise_id),
        phase_key=phase_key,
        unit_key=uk,
    )
    selected.discard(int(node_id))
    return publish_evaluation_lists_from_ibank(
        db,
        exercise_id=int(exercise_id),
        phase_key=phase_key,
        unit_key=uk,
        selected_node_ids=selected,
    )


def publish_phase_evaluation_lists_from_ibank(
    db: Session,
    *,
    exercise_id: int,
    phase_key: str,
    selections_by_unit: dict[str, set[int]],
) -> dict[str, int]:
    """نشر مرحلة: قوائم مختارة فقط لكل مستوى وحدة في المرحلة."""
    pk = _resolve_phase_key(phase_key, db) or normalize_exercise_phase(phase_key)
    if not pk:
        return {"added": 0, "updated": 0, "removed": 0, "sources": 0, "sources_available": 0, "units": 0}

    totals = {
        "added": 0,
        "updated": 0,
        "removed": 0,
        "sources": 0,
        "sources_available": 0,
        "units": 0,
    }
    remapped = remap_publish_selections_by_ibank_context(
        db,
        phase_key=pk,
        selections_by_unit=selections_by_unit,
    )
    for uk in sorted(remapped.keys()):
        stats = publish_evaluation_lists_from_ibank(
            db,
            exercise_id=int(exercise_id),
            phase_key=pk,
            unit_key=uk,
            selected_node_ids=remapped.get(uk, set()),
        )
        totals["units"] += 1
        for k in ("added", "updated", "removed", "sources", "sources_available"):
            totals[k] += int(stats.get(k, 0))
    return totals


def publish_all_evaluation_lists_from_ibank(
    db: Session,
    *,
    exercise_id: int,
) -> dict[str, int]:
    """نسخ الكل من البنك: تحديث الفهرس وإلغاء نشر جميع القوائم (بدون نسخ للتمرين).

    النشر الفعلي يتم لاحقاً عبر «نشر القوائم» بعد تحديد الـ checkbox.
    """
    prepare_dilemma_eval_ibank_tree(db)
    active_units = roster_eval_display_unit_keys(db, int(exercise_id))
    phases = effective_eval_list_phase_keys(db, roster_units=active_units)
    totals = {
        "added": 0,
        "updated": 0,
        "removed": 0,
        "sources": 0,
        "sources_available": 0,
        "groups": 0,
    }
    for uk in sorted(active_units):
        for pk in phases:
            stats = publish_evaluation_lists_from_ibank(
                db,
                exercise_id=int(exercise_id),
                phase_key=pk,
                unit_key=uk,
                selected_node_ids=set(),
            )
            totals["groups"] += 1
            for k in ("added", "updated", "removed", "sources", "sources_available"):
                totals[k] += int(stats.get(k, 0))
    totals["removed"] += prune_ibank_evaluation_lists_not_in_roster(
        db, exercise_id=int(exercise_id), active_unit_keys=active_units
    )
    return totals


def _unit_folder_ids_for_phase_unit(
    db: Session, *, phase_key: str, unit_key: str
) -> set[int]:
    """معرّفات مجلدات مستوى الوحدة تحت مرحلة التمرين (بأي عمق)."""
    prepare_dilemma_eval_ibank_tree(db)
    uk = _resolve_unit_key(unit_key, db)
    pk = _resolve_phase_key(phase_key, db)
    if not uk or not pk:
        return set()
    out: set[int] = set()
    for phase_root in _phase_root_nodes_for_key(db, pk):
        queue = [int(phase_root.id)]
        seen: set[int] = set()
        while queue:
            nid = queue.pop(0)
            if nid in seen:
                continue
            seen.add(nid)
            children = (
                db.query(InformationBankTreeNode)
                .filter(InformationBankTreeNode.parent_id == nid)
                .all()
            )
            for child in children:
                cid = int(child.id)
                queue.append(cid)
                if not child.is_folder:
                    continue
                child_uk = _effective_unit_key_for_node(db, child)
                if child_uk == uk:
                    out.add(cid)
    return out


def _folder_group_for_file_node(
    db: Session,
    file_node: InformationBankTreeNode,
    unit_folder_ids: set[int],
) -> tuple[str, str, int]:
    """مجلد العرض الذي تنتمي إليه القائمة (تحت مستوى الوحدة)."""
    if file_node.parent_id is None:
        return ("misc", "غير مصنّف", 99999)
    cur = db.get(InformationBankTreeNode, int(file_node.parent_id))
    if cur is None:
        return ("misc", "غير مصنّف", 99999)
    if int(cur.id) in unit_folder_ids:
        return ("direct", "قوائم مباشرة", 0)
    subfolders: list[InformationBankTreeNode] = []
    while cur is not None and int(cur.id) not in unit_folder_ids:
        if cur.is_folder:
            subfolders.append(cur)
        if cur.parent_id is None:
            break
        cur = db.get(InformationBankTreeNode, int(cur.parent_id))
    if subfolders:
        top = subfolders[-1]
        return (
            str(int(top.id)),
            (top.name or "").strip() or "مجلد",
            int(top.sort_order or 0),
        )
    return (
        str(int(cur.id)) if cur else "misc",
        ((cur.name or "").strip() if cur else "") or "مجلد",
        int(getattr(cur, "sort_order", 0) or 0),
    )


def build_eval_list_rows_for_group(
    *,
    ibank_sources: list[dict],
    eval_items: list,
    published_by_node: dict[int, object] | None = None,
) -> list[dict]:
    """صفوف العرض: ملفات البنك + المنشورة (للاختيار بالـ checkbox)."""
    published_by_nid: dict[int, object] = dict(published_by_node or {})
    for item in eval_items:
        nid = parse_ibank_eval_storage_relpath(getattr(item, "pdf_relpath", None))
        if nid is not None:
            published_by_nid[int(nid)] = item

    rows: list[dict] = []
    seen: set[int] = set()
    for src in ibank_sources:
        nid = int(src["node_id"])
        seen.add(nid)
        item = published_by_nid.get(nid)
        rows.append(
            {
                "node_id": nid,
                "title": str(src.get("title") or "قائمة تقييم"),
                "published": item is not None,
                "selected": False,
                "item_id": int(item.id) if item is not None else None,
                "item_unit_key": (getattr(item, "unit_level_key", None) or "").strip()
                if item is not None
                else None,
                "pdf_relpath": getattr(item, "pdf_relpath", None) if item else None,
            }
        )
    for nid, item in published_by_nid.items():
        if nid in seen:
            continue
        rows.append(
            {
                "node_id": nid,
                "title": (getattr(item, "text", None) or "قائمة تقييم").strip(),
                "published": True,
                "selected": False,
                "item_id": int(item.id),
                "item_unit_key": (getattr(item, "unit_level_key", None) or "").strip(),
                "pdf_relpath": getattr(item, "pdf_relpath", None),
            }
        )
    return rows


def build_eval_list_folder_groups(
    db: Session,
    *,
    phase_key: str,
    unit_key: str,
    ibank_sources: list[dict],
    eval_items: list,
    published_by_node: dict[int, object] | None = None,
) -> list[dict]:
    """تجميع صفوف القوائم حسب مجلدات بنك المعلومات (قابلة للطي في الواجهة)."""
    rows = build_eval_list_rows_for_group(
        ibank_sources=ibank_sources,
        eval_items=eval_items,
        published_by_node=published_by_node,
    )
    unit_folder_ids = _unit_folder_ids_for_phase_unit(
        db, phase_key=phase_key, unit_key=unit_key
    )
    uk = _resolve_unit_key(unit_key, db) or unit_key
    grouped: dict[str, dict] = {}
    for row in rows:
        node = db.get(InformationBankTreeNode, int(row["node_id"]))
        if node is not None:
            if not _file_belongs_to_phase_unit(
                db, node, phase_key=phase_key, unit_key=uk
            ):
                continue
            fk, fn, fs = _folder_group_for_file_node(db, node, unit_folder_ids)
        else:
            fk, fn, fs = ("orphan", "منشور سابقاً", 99998)
        bucket = grouped.setdefault(
            fk,
            {
                "folder_key": fk,
                "folder_name": fn,
                "sort_order": fs,
                "rows": [],
            },
        )
        bucket["rows"].append(row)
    return sorted(
        grouped.values(),
        key=lambda g: (int(g.get("sort_order", 0)), str(g.get("folder_name") or "")),
    )


def unit_eval_group_visible_for_phase(
    *,
    ibank_sources: list[dict],
    eval_items: list,
) -> bool:
    """هل يُعرض مستوى الوحدة في هذه المرحلة؟ (مدرج في البنك أو منشور سابقاً فقط)."""
    return bool(ibank_sources or eval_items)


def build_eval_list_display_groups(
    db: Session,
    *,
    exercise_id: int,
    phase_key: str | None = None,
) -> tuple[list[dict], dict[str, int]]:
    """مجموعات العرض: مرحلة × مستوى وحدة المدرجين في بنك المعلومات لتلك المرحلة."""
    roster_units = roster_eval_display_unit_keys(db, int(exercise_id))
    judge_units = roster_judge_unit_keys(db, int(exercise_id))
    raw_ibank_files = count_dilemma_eval_ibank_xlsx_nodes(db)
    ibank_index = index_dilemma_eval_ibank_files(db)
    if not roster_units and ibank_index:
        roster_units = {uk for (_pk, uk) in ibank_index.keys() if uk}
    if not roster_units:
        return [], {
            "ibank_files": sum(len(v) for v in ibank_index.values()),
            "raw_ibank_files": raw_ibank_files,
            "roster_units": 0,
            "judge_units": len(judge_units),
        }

    judge_by_unit, trainee_by_unit = exercise_roster_labels_by_unit(db, int(exercise_id))
    phase_keys = effective_eval_list_phase_keys(db, roster_units=roster_units)
    if not phase_keys:
        phase_keys = sorted({pk for (pk, _uk) in ibank_index.keys()})
    if phase_key:
        pk_resolved = _resolve_phase_key(phase_key, db) or normalize_exercise_phase(phase_key)
        if pk_resolved:
            match = set(_phase_match_keys(pk_resolved))
            filtered = [pk for pk in phase_keys if pk in match]
            phase_keys = filtered if filtered else [pk_resolved]

    from app.unit_levels_catalog import UNIT_LEVELS

    unit_order = {row["key"]: idx for idx, row in enumerate(UNIT_LEVELS)}
    groups: list[dict] = []

    for pk in phase_keys:
        pl = exercise_phase_label(pk) or pk
        phase_db_keys = _phase_match_keys(pk)
        for uk in sorted(roster_units, key=lambda k: unit_order.get(k, 9999)):
            ul = label_for_unit_level_key(uk, db=db) or uk
            ibank_sources = collect_ibank_eval_files_for_phase_unit(
                db, phase_key=pk, unit_key=uk
            )
            eval_items = (
                db.query(EvaluationListPdfItem)
                .filter(
                    EvaluationListPdfItem.exercise_id == int(exercise_id),
                    EvaluationListPdfItem.unit_level_key == uk,
                    EvaluationListPdfItem.exercise_phase.in_(phase_db_keys),
                )
                .order_by(EvaluationListPdfItem.sort_order, EvaluationListPdfItem.id)
                .all()
            )
            if not unit_eval_group_visible_for_phase(
                ibank_sources=ibank_sources,
                eval_items=eval_items,
            ):
                continue
            unit_published_by_node = _published_ibank_items_by_node_for_unit_group(
                db,
                exercise_id=int(exercise_id),
                phase_key=pk,
                phase_db_keys=phase_db_keys,
                unit_key=uk,
                eval_items=eval_items,
            )
            groups.append(
                {
                    "phase_key": pk,
                    "phase_label": pl,
                    "unit_key": uk,
                    "unit_label": ul,
                    "judge_name": judge_by_unit.get(uk, "—"),
                    "trainee_name": trainee_by_unit.get(uk, "—"),
                    "eval_items": eval_items,
                    "ibank_sources": ibank_sources,
                    "ibank_source_count": len(ibank_sources),
                    "list_rows": build_eval_list_rows_for_group(
                        ibank_sources=ibank_sources,
                        eval_items=eval_items,
                        published_by_node=unit_published_by_node,
                    ),
                    "list_folder_groups": build_eval_list_folder_groups(
                        db,
                        phase_key=pk,
                        unit_key=uk,
                        ibank_sources=ibank_sources,
                        eval_items=eval_items,
                        published_by_node=unit_published_by_node,
                    ),
                }
            )

    meta = {
        "ibank_files": sum(len(v) for v in ibank_index.values()),
        "raw_ibank_files": raw_ibank_files,
        "roster_units": len(roster_units),
        "judge_units": len(judge_units),
        "phases": len(phase_keys),
    }
    return groups, meta
