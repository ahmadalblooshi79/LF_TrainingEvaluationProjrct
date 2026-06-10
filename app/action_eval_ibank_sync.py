"""مزامنة قوائم تقييم الإجراءات من بنك المعلومات (action_eval) إلى حزم المجرى."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections import defaultdict
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import PLANNER_FLOW_BUNDLE_DIR
from app.evaluation_list_ibank_sync import (
    _deepest_unit_key_for_file_node,
    _file_sha256,
    _ibank_context_for_file_node,
    _is_xlsx_tree_file,
    _phase_match_keys,
    _resolve_phase_key,
    _resolve_unit_key,
    effective_eval_list_phase_keys,
    exercise_roster_labels_by_unit,
    remap_publish_selections_by_ibank_context,
    resolve_ibank_eval_publish_unit_key,
    roster_eval_display_unit_keys,
    roster_judge_unit_keys,
)
from app.exercise_phase_catalog import exercise_phase_label, normalize_exercise_phase
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
    ExercisePlannerFlowBundle,
    ExercisePlannerFlowBundleActionEval,
    InformationBankTreeNode,
)
from app.unit_levels_catalog import label_for_unit_level_key, normalize_unit_level_key

INFO_BANK_ACTION_EVAL_KIND = "action_eval"
_IBANK_REL_RE = re.compile(r"^(\d+)/ibn_(\d+)\.xlsx$", re.IGNORECASE)


def action_eval_storage_relpath(bundle_id: int, node_id: int) -> str:
    return f"{int(bundle_id)}/ibn_{int(node_id)}.xlsx"


def parse_action_eval_storage_relpath(relpath: str | None) -> int | None:
    norm = (relpath or "").replace("\\", "/").strip()
    m = _IBANK_REL_RE.match(norm)
    if not m:
        return None
    try:
        return int(m.group(2))
    except (TypeError, ValueError):
        return None


def prepare_action_eval_ibank_tree(db: Session) -> None:
    ensure_information_bank_tree(db, INFO_BANK_ACTION_EVAL_KIND)
    migrate_legacy_flat_files(db, INFO_BANK_ACTION_EVAL_KIND)
    if _backfill_unit_eval_folder_catalog(db, INFO_BANK_ACTION_EVAL_KIND):
        db.commit()


def _effective_unit_key_for_node(db: Session, node: InformationBankTreeNode) -> str:
    raw = _unit_key_for_node(db, node)
    uk = _resolve_unit_key(raw, db)
    if uk:
        return uk
    if node.is_folder:
        from app.evaluation_list_ibank_sync import _match_unit_key_by_folder_name

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
    pk = _resolve_phase_key(phase_key, db)
    if not pk:
        return []
    match_keys = _phase_match_keys(pk)
    roots = (
        db.query(InformationBankTreeNode)
        .filter(
            InformationBankTreeNode.kind == INFO_BANK_ACTION_EVAL_KIND,
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


def _collect_subtree_xlsx_nodes(db: Session, root_id: int) -> list[InformationBankTreeNode]:
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
        if node is None or node.kind != INFO_BANK_ACTION_EVAL_KIND:
            continue
        if not node.is_folder and _is_xlsx_tree_file(node):
            out.append(node)
        children = (
            db.query(InformationBankTreeNode)
            .filter(InformationBankTreeNode.parent_id == nid)
            .order_by(InformationBankTreeNode.sort_order, InformationBankTreeNode.id)
            .all()
        )
        for ch in children:
            queue.append(int(ch.id))
    return out


def _file_node_to_source(db: Session, row: InformationBankTreeNode) -> dict | None:
    src_rel = (row.file_relpath or "").strip()
    if not src_rel:
        return None
    src_path = node_file_abspath(INFO_BANK_ACTION_EVAL_KIND, src_rel)
    if src_path is None or not src_path.is_file():
        return None
    title = (row.name or src_path.name or "قائمة تقييم إجراءات").strip()[:2000]
    return {
        "node_id": int(row.id),
        "title": title or "قائمة تقييم إجراءات",
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
    f_pk, f_uk = _ibank_context_for_file_node(db, file_node)
    if not f_uk or f_uk != unit_key:
        return False
    phase_match = _phase_match_keys(phase_key) or {phase_key}
    return bool(f_pk and f_pk in phase_match)


def collect_ibank_action_eval_files_for_phase_unit(
    db: Session,
    *,
    phase_key: str,
    unit_key: str,
) -> list[dict]:
    prepare_action_eval_ibank_tree(db)
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
        direct_children = (
            db.query(InformationBankTreeNode)
            .filter(InformationBankTreeNode.parent_id == int(phase_root.id))
            .order_by(InformationBankTreeNode.sort_order, InformationBankTreeNode.id)
            .all()
        )
        for child in direct_children:
            if child.is_folder:
                child_uk = _effective_unit_key_for_node(db, child)
                if child_uk == uk:
                    for xn in _collect_subtree_xlsx_nodes(db, int(child.id)):
                        _add_node(xn)
            elif _is_xlsx_tree_file(child):
                ctx_uk = _deepest_unit_key_for_file_node(db, child) or _effective_unit_key_for_node(
                    db, child
                )
                if ctx_uk == uk:
                    _add_node(child)

    sources.sort(key=lambda s: (int(s.get("sort_order", 0)), int(s["node_id"])))
    return sources


def _get_or_create_bundle(
    db: Session,
    *,
    exercise_id: int,
    phase_key: str,
    unit_key: str,
    unit_label: str,
) -> ExercisePlannerFlowBundle:
    phase_n = normalize_exercise_phase(phase_key)
    row = (
        db.query(ExercisePlannerFlowBundle)
        .filter(
            ExercisePlannerFlowBundle.exercise_id == int(exercise_id),
            ExercisePlannerFlowBundle.exercise_phase == phase_n,
            ExercisePlannerFlowBundle.unit_level_key == unit_key,
        )
        .first()
    )
    if row:
        return row
    row = ExercisePlannerFlowBundle(
        exercise_id=int(exercise_id),
        exercise_phase=phase_n,
        unit_level_key=unit_key,
        unit_level_label=(unit_label or "")[:200],
    )
    db.add(row)
    db.flush()
    return row


def _unlink_bundle_action_file(relpath: str | None) -> None:
    norm = (relpath or "").replace("\\", "/").strip()
    if not norm or any(part == ".." for part in norm.split("/")):
        return
    root = PLANNER_FLOW_BUNDLE_DIR.resolve()
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


def _normalize_flow_rows(raw_rows) -> list[dict]:
    if not isinstance(raw_rows, list):
        return []
    out: list[dict] = []
    for item in raw_rows:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "row").strip().lower()
        if kind not in ("event", "dilemma", "row"):
            kind = "row"
        if kind in ("event", "dilemma"):
            out.append({"kind": kind, "text": str(item.get("text") or "")[:4000]})
        else:
            out.append(
                {
                    "kind": "row",
                    "time": str(item.get("time") or "")[:500],
                    "description": str(item.get("description") or "")[:4000],
                    "assignee": str(item.get("assignee") or "")[:500],
                    "method": str(item.get("method") or "")[:500],
                    "reaction": str(item.get("reaction") or "")[:500],
                }
            )
    return out


def _parse_flow_table_days(raw: str) -> list[dict]:
    if not (raw or "").strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(data, list):
        return [{"id": "day-1", "label": "اليوم/1", "rows": _normalize_flow_rows(data)}]
    if isinstance(data, dict) and isinstance(data.get("days"), list):
        out: list[dict] = []
        for idx, item in enumerate(data["days"]):
            if not isinstance(item, dict):
                continue
            out.append(
                {
                    "id": str(item.get("id") or f"day-{idx + 1}"),
                    "label": str(item.get("label") or f"اليوم/{idx + 1}"),
                    "rows": _normalize_flow_rows(item.get("rows")),
                }
            )
        return out
    return []


def extract_assignee_judge_labels_from_bundle(
    bundle: ExercisePlannerFlowBundle | None,
) -> list[str]:
    """أصناف المحكمين من عمود المكلف بالإجراء والمتابعة في جدول المجرى."""
    from app.planner_flow_judge_labels import parse_assignee_cell_lines

    if bundle is None:
        return []
    raw = (getattr(bundle, "flow_table_json", None) or "").strip()
    if not raw:
        return []
    labels: list[str] = []
    seen: set[str] = set()
    for day in _parse_flow_table_days(raw):
        for row in day.get("rows") or []:
            if (row.get("kind") or "row").strip().lower() != "row":
                continue
            for lbl in parse_assignee_cell_lines(row.get("assignee")):
                n = _normalize_tree_label(lbl)
                if n and n not in seen:
                    seen.add(n)
                    labels.append(lbl)
    return labels


def collect_flow_assignee_units_for_phase(
    db: Session,
    *,
    exercise_id: int,
    phase_key: str,
) -> dict[str, list[str]]:
    """مستوى الوحدة ← أصناف المحكمين المستخرجة من عمود المكلف في المجرى."""
    from app.planner_flow_judge_labels import unit_key_for_assignee_label

    pk = normalize_exercise_phase(phase_key)
    phase_db_keys = _phase_match_keys(pk)
    bundles = (
        db.query(ExercisePlannerFlowBundle)
        .filter(
            ExercisePlannerFlowBundle.exercise_id == int(exercise_id),
            ExercisePlannerFlowBundle.exercise_phase.in_(phase_db_keys),
        )
        .all()
    )
    out: dict[str, list[str]] = defaultdict(list)
    seen_per_unit: dict[str, set[str]] = defaultdict(set)
    for bundle in bundles:
        for lbl in extract_assignee_judge_labels_from_bundle(bundle):
            uk = unit_key_for_assignee_label(lbl, db=db)
            if not uk:
                continue
            norm_lbl = _normalize_tree_label(lbl)
            if norm_lbl in seen_per_unit[uk]:
                continue
            seen_per_unit[uk].add(norm_lbl)
            out[uk].append(lbl)
    return dict(out)


def extract_flow_dilemmas_from_bundle(bundle: ExercisePlannerFlowBundle | None) -> list[dict]:
    """معاضل جدول المجرى عبر كل الأيام — للربط مع قوائم التقييم."""
    if bundle is None:
        return []
    raw = (getattr(bundle, "flow_table_json", None) or "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    days: list[dict] = []
    if isinstance(data, list):
        days = [{"id": "day-1", "label": "اليوم/1", "rows": _normalize_flow_rows(data)}]
    elif isinstance(data, dict) and isinstance(data.get("days"), list):
        for idx, item in enumerate(data["days"]):
            if not isinstance(item, dict):
                continue
            days.append(
                {
                    "id": str(item.get("id") or f"day-{idx + 1}"),
                    "label": str(item.get("label") or f"اليوم/{idx + 1}"),
                    "rows": _normalize_flow_rows(item.get("rows")),
                }
            )
    dilemmas: list[dict] = []
    idx = 0
    for day in days:
        day_label = (day.get("label") or "").strip()
        for row in day.get("rows") or []:
            if (row.get("kind") or "").strip().lower() != "dilemma":
                continue
            text = (row.get("text") or "").strip()
            if not text:
                continue
            idx += 1
            dilemmas.append(
                {
                    "index": idx,
                    "day_label": day_label,
                    "text": text,
                    "short_label": text[:120] + ("…" if len(text) > 120 else ""),
                }
            )
    return dilemmas


def _published_slots_by_node(
    db: Session, bundle: ExercisePlannerFlowBundle
) -> dict[int, ExercisePlannerFlowBundleActionEval]:
    out: dict[int, ExercisePlannerFlowBundleActionEval] = {}
    rows = (
        db.query(ExercisePlannerFlowBundleActionEval)
        .filter(ExercisePlannerFlowBundleActionEval.bundle_id == bundle.id)
        .all()
    )
    for slot in rows:
        nid = parse_action_eval_storage_relpath(slot.file_relpath)
        if nid is not None:
            out[int(nid)] = slot
    return out


def published_action_eval_node_ids_for_bundle(
    db: Session, bundle: ExercisePlannerFlowBundle
) -> set[int]:
    return set(_published_slots_by_node(db, bundle).keys())


def _slot_title_with_dilemma(base_title: str, dilemma: dict | None) -> str:
    title = (base_title or "قائمة تقييم إجراءات").strip()[:400]
    if dilemma is None:
        return title
    dtxt = (dilemma.get("short_label") or dilemma.get("text") or "").strip()
    if not dtxt:
        return title
    return f"{title} — معضلة {int(dilemma['index'])}: {dtxt}"[:500]


def publish_action_eval_lists_from_ibank(
    db: Session,
    *,
    exercise_id: int,
    phase_key: str,
    unit_key: str,
    selected_node_ids: set[int],
    dilemma_by_node: dict[int, int] | None = None,
) -> dict[str, int]:
    """نشر قوائم مختارة إلى حزمة المجرى (مرحلة × مستوى وحدة)."""
    uk = _resolve_unit_key(unit_key, db) or normalize_unit_level_key(unit_key)
    pk = _resolve_phase_key(phase_key, db) or normalize_exercise_phase(phase_key)
    if not uk or not pk:
        return {"added": 0, "updated": 0, "removed": 0, "sources": 0}

    ul = label_for_unit_level_key(uk, db=db) or uk
    bundle = _get_or_create_bundle(
        db, exercise_id=int(exercise_id), phase_key=pk, unit_key=uk, unit_label=ul
    )
    sources = collect_ibank_action_eval_files_for_phase_unit(db, phase_key=pk, unit_key=uk)
    source_by_id = {int(s["node_id"]): s for s in sources}
    dilemmas = extract_flow_dilemmas_from_bundle(bundle)
    dilemma_by_idx = {int(d["index"]): d for d in dilemmas}
    by_node = _published_slots_by_node(db, bundle)
    root = PLANNER_FLOW_BUNDLE_DIR.resolve()
    root.mkdir(parents=True, exist_ok=True)
    added = updated = removed = 0
    dilemma_map = dilemma_by_node or {}

    for nid, slot in list(by_node.items()):
        if int(nid) not in selected_node_ids:
            _unlink_bundle_action_file(slot.file_relpath)
            db.delete(slot)
            removed += 1
    db.flush()
    by_node = _published_slots_by_node(db, bundle)

    for sort_i, nid in enumerate(sorted(selected_node_ids)):
        src = source_by_id.get(int(nid))
        if src is None:
            continue
        src_path: Path = src["src_path"]
        if not src_path.is_file():
            alt = node_file_abspath(INFO_BANK_ACTION_EVAL_KIND, src.get("src_relpath"))
            if alt is not None and alt.is_file():
                src_path = alt
            else:
                continue
        rel = action_eval_storage_relpath(int(bundle.id), int(nid))
        dest = (root / rel).resolve()
        try:
            dest.relative_to(root)
        except ValueError:
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

        d_idx = int(dilemma_map.get(int(nid), 0) or 0)
        dilemma = dilemma_by_idx.get(d_idx) if d_idx > 0 else None
        title = _slot_title_with_dilemma(str(src["title"]), dilemma)
        slot_index = d_idx if d_idx > 0 else (sort_i + 1)

        slot = by_node.get(int(nid))
        if slot is None:
            existing_at = (
                db.query(ExercisePlannerFlowBundleActionEval)
                .filter(
                    ExercisePlannerFlowBundleActionEval.bundle_id == bundle.id,
                    ExercisePlannerFlowBundleActionEval.slot_index == slot_index,
                )
                .first()
            )
            if existing_at is not None and parse_action_eval_storage_relpath(
                existing_at.file_relpath
            ) != int(nid):
                mx = (
                    db.query(func.max(ExercisePlannerFlowBundleActionEval.slot_index))
                    .filter(ExercisePlannerFlowBundleActionEval.bundle_id == bundle.id)
                    .scalar()
                )
                slot_index = int(mx or 0) + 1
            slot = ExercisePlannerFlowBundleActionEval(
                bundle_id=int(bundle.id),
                slot_index=int(slot_index),
                title=title,
            )
            db.add(slot)
            added += 1
        else:
            updated += 1
        old_rel = (slot.file_relpath or "").strip()
        if old_rel and old_rel.replace("\\", "/") != rel:
            _unlink_bundle_action_file(old_rel)
        slot.file_relpath = rel.replace("\\", "/")
        slot.title = title
        if d_idx > 0:
            slot.slot_index = int(d_idx)

    bundle.linked_at = None
    bundle.dilemma_count = (
        db.query(ExercisePlannerFlowBundleActionEval)
        .filter(ExercisePlannerFlowBundleActionEval.bundle_id == bundle.id)
        .count()
    )
    bundle.updated_at = __import__("datetime").datetime.utcnow()
    return {
        "added": added,
        "updated": updated,
        "removed": removed,
        "sources": len(sources),
        "sources_available": len(source_by_id),
    }


def publish_single_action_eval_from_ibank(
    db: Session,
    *,
    exercise_id: int,
    phase_key: str,
    unit_key: str,
    node_id: int,
    dilemma_index: int = 0,
) -> dict[str, int]:
    uk = resolve_ibank_eval_publish_unit_key(
        db, node_id=int(node_id), fallback_unit_key=unit_key
    )
    bundle = _get_or_create_bundle(
        db,
        exercise_id=int(exercise_id),
        phase_key=phase_key,
        unit_key=uk,
        unit_label=label_for_unit_level_key(uk, db=db) or uk,
    )
    selected = published_action_eval_node_ids_for_bundle(db, bundle)
    selected.add(int(node_id))
    dmap = {int(node_id): int(dilemma_index)} if dilemma_index > 0 else None
    return publish_action_eval_lists_from_ibank(
        db,
        exercise_id=int(exercise_id),
        phase_key=phase_key,
        unit_key=uk,
        selected_node_ids=selected,
        dilemma_by_node=dmap,
    )


def withdraw_single_action_eval_from_ibank(
    db: Session,
    *,
    exercise_id: int,
    phase_key: str,
    unit_key: str,
    node_id: int,
) -> dict[str, int]:
    uk = resolve_ibank_eval_publish_unit_key(
        db, node_id=int(node_id), fallback_unit_key=unit_key
    )
    bundle = (
        db.query(ExercisePlannerFlowBundle)
        .filter(
            ExercisePlannerFlowBundle.exercise_id == int(exercise_id),
            ExercisePlannerFlowBundle.exercise_phase
            == normalize_exercise_phase(phase_key),
            ExercisePlannerFlowBundle.unit_level_key == uk,
        )
        .first()
    )
    if bundle is None:
        return {"added": 0, "updated": 0, "removed": 0, "sources": 0}
    selected = published_action_eval_node_ids_for_bundle(db, bundle)
    selected.discard(int(node_id))
    return publish_action_eval_lists_from_ibank(
        db,
        exercise_id=int(exercise_id),
        phase_key=phase_key,
        unit_key=uk,
        selected_node_ids=selected,
    )


def publish_phase_action_eval_lists_from_ibank(
    db: Session,
    *,
    exercise_id: int,
    phase_key: str,
    selections_by_unit: dict[str, set[int]],
    dilemma_by_unit_node: dict[tuple[str, int], int] | None = None,
) -> dict[str, int]:
    pk = _resolve_phase_key(phase_key, db) or normalize_exercise_phase(phase_key)
    if not pk:
        return {"added": 0, "updated": 0, "removed": 0, "sources": 0, "units": 0}
    totals = {"added": 0, "updated": 0, "removed": 0, "sources": 0, "units": 0}
    remapped = remap_publish_selections_by_ibank_context(
        db, phase_key=pk, selections_by_unit=selections_by_unit
    )
    dmap_all = dilemma_by_unit_node or {}
    for uk in sorted(remapped.keys()):
        d_for_unit: dict[int, int] = {}
        for (form_uk, nid), d_idx in dmap_all.items():
            if form_uk == uk and d_idx > 0:
                d_for_unit[int(nid)] = int(d_idx)
        stats = publish_action_eval_lists_from_ibank(
            db,
            exercise_id=int(exercise_id),
            phase_key=pk,
            unit_key=uk,
            selected_node_ids=remapped.get(uk, set()),
            dilemma_by_node=d_for_unit or None,
        )
        totals["units"] += 1
        for k in ("added", "updated", "removed", "sources"):
            totals[k] += int(stats.get(k, 0))
    return totals


def sync_all_action_eval_from_ibank(db: Session, *, exercise_id: int) -> dict[str, int]:
    """تحديث الفهرس من البنك وسحب كل المنشور (بدون نسخ)."""
    prepare_action_eval_ibank_tree(db)
    active_units = roster_eval_display_unit_keys(db, int(exercise_id))
    phases = effective_eval_list_phase_keys(db, roster_units=active_units)
    totals = {"added": 0, "updated": 0, "removed": 0, "units": 0}
    for pk in phases:
        for uk in sorted(active_units):
            stats = publish_action_eval_lists_from_ibank(
                db,
                exercise_id=int(exercise_id),
                phase_key=pk,
                unit_key=uk,
                selected_node_ids=set(),
            )
            totals["units"] += 1
            totals["removed"] += int(stats.get("removed", 0))
    return totals


def _unit_folder_ids_for_phase_unit(db: Session, *, phase_key: str, unit_key: str) -> set[int]:
    prepare_action_eval_ibank_tree(db)
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


def build_action_eval_rows_for_group(
    *,
    ibank_sources: list[dict],
    published_by_node: dict[int, ExercisePlannerFlowBundleActionEval],
) -> list[dict]:
    rows: list[dict] = []
    for src in ibank_sources:
        nid = int(src["node_id"])
        slot = published_by_node.get(nid)
        rows.append(
            {
                "node_id": nid,
                "title": str(src.get("title") or "قائمة تقييم إجراءات"),
                "published": slot is not None,
                "selected": False,
                "slot_id": int(slot.id) if slot is not None else None,
            }
        )
    for nid, slot in published_by_node.items():
        if any(r["node_id"] == nid for r in rows):
            continue
        rows.append(
            {
                "node_id": int(nid),
                "title": (slot.title or "قائمة منشورة").strip(),
                "published": True,
                "selected": False,
                "slot_id": int(slot.id),
            }
        )
    return rows


def build_action_eval_folder_groups(
    db: Session,
    *,
    phase_key: str,
    unit_key: str,
    ibank_sources: list[dict],
    published_by_node: dict[int, ExercisePlannerFlowBundleActionEval],
) -> list[dict]:
    rows = build_action_eval_rows_for_group(
        ibank_sources=ibank_sources,
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
            if not _file_belongs_to_phase_unit(db, node, phase_key=phase_key, unit_key=uk):
                continue
            fk, fn, fs = _folder_group_for_file_node(db, node, unit_folder_ids)
        else:
            fk, fn, fs = ("orphan", "منشور سابقاً", 99998)
        bucket = grouped.setdefault(
            fk,
            {"folder_key": fk, "folder_name": fn, "sort_order": fs, "rows": []},
        )
        bucket["rows"].append(row)
    return sorted(
        grouped.values(),
        key=lambda g: (int(g.get("sort_order", 0)), str(g.get("folder_name") or "")),
    )


def build_action_eval_display_groups(
    db: Session,
    *,
    exercise_id: int,
    phase_key: str | None = None,
) -> tuple[list[dict], dict[str, int]]:
    roster_units = roster_eval_display_unit_keys(db, int(exercise_id))
    judge_units = roster_judge_unit_keys(db, int(exercise_id))
    judge_by_unit, trainee_by_unit = exercise_roster_labels_by_unit(db, int(exercise_id))
    phase_keys = (
        effective_eval_list_phase_keys(db, roster_units=roster_units)
        if roster_units
        else []
    )
    if not phase_keys:
        bundle_phases = (
            db.query(ExercisePlannerFlowBundle.exercise_phase)
            .filter(ExercisePlannerFlowBundle.exercise_id == int(exercise_id))
            .distinct()
            .all()
        )
        phase_keys = sorted(
            {
                normalize_exercise_phase(p[0])
                for p in bundle_phases
                if (p[0] or "").strip()
            }
        )
    if not phase_keys and phase_key:
        pk_resolved = _resolve_phase_key(phase_key, db) or normalize_exercise_phase(phase_key)
        if pk_resolved:
            phase_keys = [pk_resolved]
    if phase_key:
        pk_resolved = _resolve_phase_key(phase_key, db) or normalize_exercise_phase(phase_key)
        if pk_resolved:
            match = set(_phase_match_keys(pk_resolved))
            filtered = [pk for pk in phase_keys if pk in match]
            phase_keys = filtered if filtered else [pk_resolved]

    from app.unit_levels_catalog import UNIT_LEVELS

    unit_order = {row["key"]: idx for idx, row in enumerate(UNIT_LEVELS)}
    groups: list[dict] = []
    flow_unit_total = 0

    for pk in phase_keys:
        pl = exercise_phase_label(pk) or pk
        flow_units = collect_flow_assignee_units_for_phase(
            db, exercise_id=int(exercise_id), phase_key=pk
        )
        flow_unit_total += len(flow_units)
        for uk in sorted(flow_units.keys(), key=lambda k: unit_order.get(k, 9999)):
            ul = label_for_unit_level_key(uk, db=db) or uk
            ibank_sources = collect_ibank_action_eval_files_for_phase_unit(
                db, phase_key=pk, unit_key=uk
            )
            bundle = (
                db.query(ExercisePlannerFlowBundle)
                .filter(
                    ExercisePlannerFlowBundle.exercise_id == int(exercise_id),
                    ExercisePlannerFlowBundle.exercise_phase == normalize_exercise_phase(pk),
                    ExercisePlannerFlowBundle.unit_level_key == uk,
                )
                .first()
            )
            published_by_node = (
                _published_slots_by_node(db, bundle) if bundle is not None else {}
            )
            groups.append(
                {
                    "phase_key": pk,
                    "phase_label": pl,
                    "unit_key": uk,
                    "unit_label": ul,
                    "judge_name": judge_by_unit.get(uk, "—"),
                    "trainee_name": trainee_by_unit.get(uk, "—"),
                    "assignee_labels": flow_units.get(uk, []),
                    "ibank_sources": ibank_sources,
                    "ibank_source_count": len(ibank_sources),
                    "bundle_id": int(bundle.id) if bundle is not None else None,
                    "list_folder_groups": build_action_eval_folder_groups(
                        db,
                        phase_key=pk,
                        unit_key=uk,
                        ibank_sources=ibank_sources,
                        published_by_node=published_by_node,
                    ),
                }
            )

    meta = {
        "roster_units": len(roster_units),
        "judge_units": len(judge_units),
        "flow_units": flow_unit_total,
        "phases": len(phase_keys),
    }
    return groups, meta


def withdraw_action_eval_for_units_removed_from_flow(
    db: Session,
    *,
    exercise_id: int,
    phase_key: str,
) -> int:
    """سحب نشر القوائم لمستويات لم تعد موجودة في عمود المكلف بالمجرى."""
    flow_units = collect_flow_assignee_units_for_phase(
        db, exercise_id=int(exercise_id), phase_key=phase_key
    )
    active_uk = set(flow_units.keys())
    pk = normalize_exercise_phase(phase_key)
    phase_db_keys = _phase_match_keys(pk)
    withdrawn = 0
    bundles = (
        db.query(ExercisePlannerFlowBundle)
        .filter(
            ExercisePlannerFlowBundle.exercise_id == int(exercise_id),
            ExercisePlannerFlowBundle.exercise_phase.in_(phase_db_keys),
        )
        .all()
    )
    for bundle in bundles:
        uk = (bundle.unit_level_key or "").strip()
        if not uk or uk in active_uk:
            continue
        if not published_action_eval_node_ids_for_bundle(db, bundle):
            continue
        publish_action_eval_lists_from_ibank(
            db,
            exercise_id=int(exercise_id),
            phase_key=pk,
            unit_key=uk,
            selected_node_ids=set(),
        )
        withdrawn += 1
    return withdrawn


def sync_action_eval_units_from_flow(
    db: Session,
    *,
    exercise_id: int,
    phase_key: str,
) -> dict[str, int]:
    """مزامنة أصناف المحكمين من عمود المكلف — دون نشر (النشر يدوي من المستخدم)."""
    flow_units = collect_flow_assignee_units_for_phase(
        db, exercise_id=int(exercise_id), phase_key=phase_key
    )
    withdrawn = withdraw_action_eval_for_units_removed_from_flow(
        db, exercise_id=int(exercise_id), phase_key=phase_key
    )
    label_count = sum(len(labels) for labels in flow_units.values())
    return {
        "units": len(flow_units),
        "labels": label_count,
        "withdrawn_units": withdrawn,
    }
