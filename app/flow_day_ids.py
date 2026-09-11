"""معرّفات أيام المجرى: نفس اليوم المنطقي قد يملك أكثر من id (تخطيط ≠ بنك المعلومات)."""
from __future__ import annotations

import json
import re

from sqlalchemy.orm import Session

_DAY_LABEL_RE = re.compile(r"اليوم\s*[/\\-]?\s*(\d+)", re.IGNORECASE)
_SHORT_DAY_ID_RE = re.compile(r"^day-(\d{1,2})$", re.IGNORECASE)
_SOURCE_RANK = {"ibank": 0, "planner": 1, "folder": 2}


def flow_day_ordinal(day_id: str, label: str = "") -> int | None:
    """رقم اليوم المنطقي: day-1..day-99 من المعرّف، وإلا من تسمية «اليوم/N».

    معرّفات الزمن (day-1788…) ليست رقماً لليوم.
    """
    did = (day_id or "").strip()
    m = _SHORT_DAY_ID_RE.match(did)
    if m:
        n = int(m.group(1))
        if n > 0:
            return n
    m2 = _DAY_LABEL_RE.search((label or "").strip())
    if m2:
        n = int(m2.group(1))
        if n > 0:
            return n
    return None


def _parse_days_meta(raw: str) -> list[dict[str, str]]:
    if not (raw or "").strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(data, list):
        return [{"id": "day-1", "label": "اليوم/1", "phase_key": ""}]
    if not (isinstance(data, dict) and isinstance(data.get("days"), list)):
        return []
    out: list[dict[str, str]] = []
    for idx, item in enumerate(data["days"]):
        if not isinstance(item, dict):
            continue
        day_id = str(item.get("id") or "").strip() or f"day-{idx + 1}"
        label = str(item.get("label") or "").strip() or f"اليوم/{idx + 1}"
        out.append(
            {
                "id": day_id[:64],
                "label": label[:200],
                "phase_key": str(item.get("phase_key") or "").strip()[:64],
            }
        )
    return out


def _iter_flow_day_pairs(db: Session) -> list[tuple[str, str, str]]:
    """(id, label, source) من بنك المعلومات ثم حزم التخطيط ثم مجلدات تقييم الإجراءات."""
    from app.models.domain import (
        ExercisePlannerFlowBundle,
        InformationBankEventFlowTable,
        InformationBankTreeNode,
    )
    from app.info_bank_tree import parse_flow_day_catalog_key

    pairs: list[tuple[str, str, str]] = []
    row = (
        db.query(InformationBankEventFlowTable)
        .order_by(InformationBankEventFlowTable.id)
        .first()
    )
    raw = (getattr(row, "flow_table_json", None) or "").strip() if row else ""
    for d in _parse_days_meta(raw):
        did = (d.get("id") or "").strip()
        if did:
            pairs.append((did, d.get("label") or "", "ibank"))

    for bundle in db.query(ExercisePlannerFlowBundle).all():
        braw = (getattr(bundle, "flow_table_json", None) or "").strip()
        if not braw:
            continue
        for d in _parse_days_meta(braw):
            did = (d.get("id") or "").strip()
            if did:
                pairs.append((did, d.get("label") or "", "planner"))

    roots = (
        db.query(InformationBankTreeNode)
        .filter(
            InformationBankTreeNode.kind == "action_eval",
            InformationBankTreeNode.parent_id.is_(None),
            InformationBankTreeNode.is_folder.is_(True),
        )
        .all()
    )
    for node in roots:
        did = parse_flow_day_catalog_key((node.catalog_phase_key or "").strip())
        if did:
            pairs.append((did, node.name or "", "folder"))
    return pairs


def flow_day_alias_groups(db: Session) -> dict[int, list[str]]:
    """ordinal → معرّفات اليوم المنطقي (المعرّف المعياري أولاً)."""
    cache = None
    try:
        from flask import g, has_app_context

        if has_app_context():
            hit = getattr(g, "_flow_day_alias_groups", None)
            if hit is not None:
                return hit
            cache = g
    except Exception:
        cache = None

    grouped: dict[int, list[tuple[int, str, str]]] = {}
    seen: dict[int, set[str]] = {}
    for day_id, label, source in _iter_flow_day_pairs(db):
        ordinal = flow_day_ordinal(day_id, label)
        if ordinal is None:
            continue
        if day_id in seen.setdefault(ordinal, set()):
            continue
        seen[ordinal].add(day_id)
        rank = _SOURCE_RANK.get(source, 9)
        if _SHORT_DAY_ID_RE.match(day_id):
            rank = -1
        grouped.setdefault(ordinal, []).append((rank, day_id, source))

    out: dict[int, list[str]] = {}
    for ordinal, items in grouped.items():
        items.sort(key=lambda t: (t[0], t[1]))
        out[ordinal] = [day_id for _rank, day_id, _src in items]
    if cache is not None:
        cache._flow_day_alias_groups = out
    return out


def flow_day_alias_ids(db: Session, day_id: str, label: str = "") -> set[str]:
    want = (day_id or "").strip()
    if not want:
        return set()
    groups = flow_day_alias_groups(db)
    for ids in groups.values():
        if want in ids:
            return set(ids)
    ordinal = flow_day_ordinal(want, label)
    if ordinal is not None and ordinal in groups:
        return set(groups[ordinal]) | {want}
    return {want}


def flow_days_equivalent(
    db: Session,
    a: str,
    b: str,
    *,
    label_a: str = "",
    label_b: str = "",
) -> bool:
    sa = (a or "").strip()
    sb = (b or "").strip()
    if not sa or not sb:
        return False
    if sa == sb:
        return True
    groups = flow_day_alias_groups(db)
    for ids in groups.values():
        idset = set(ids)
        if sa in idset and sb in idset:
            return True
    oa = flow_day_ordinal(sa, label_a)
    ob = flow_day_ordinal(sb, label_b)
    return oa is not None and oa == ob


def canonical_flow_day_id(db: Session, day_id: str, label: str = "") -> str:
    want = (day_id or "").strip()
    ids = list(flow_day_alias_ids(db, want, label))
    if not ids:
        return want
    groups = flow_day_alias_groups(db)
    for gids in groups.values():
        if want in gids or set(gids) & set(ids):
            return gids[0]
    return want


def flow_day_alias_fingerprint(db: Session) -> tuple:
    groups = flow_day_alias_groups(db)
    return tuple((ordinal, tuple(ids)) for ordinal, ids in sorted(groups.items()))


def expand_flow_day_keyed_lists(
    db: Session, mapping: dict[str, list]
) -> dict[str, list]:
    """انسخ قوائم اليوم إلى كل المعرّفات المرادفة."""
    groups = flow_day_alias_groups(db)
    extra: dict[str, list] = {}
    for ids in groups.values():
        src = None
        for i in ids:
            rows = mapping.get(i)
            if rows:
                src = rows
                break
        if src is None:
            for i in ids:
                if i in mapping:
                    src = mapping[i]
                    break
        if src is None:
            continue
        for i in ids:
            extra[i] = src
    out = dict(mapping)
    out.update(extra)
    return out


def merge_flow_day_file_buckets(
    db: Session, mapping: dict[str, dict[int, list]]
) -> dict[str, dict[int, list]]:
    """ادمج ملفات نفس اليوم المنطقي ثم انشرها على كل المعرّفات المرادفة."""
    groups = flow_day_alias_groups(db)
    id_to_ord: dict[str, int] = {}
    for ordinal, ids in groups.items():
        for i in ids:
            id_to_ord[i] = ordinal

    by_ord: dict[int, dict[int, list]] = {}
    for key, bucket in (mapping or {}).items():
        ordinal = id_to_ord.get(key)
        if ordinal is None:
            continue
        dest = by_ord.setdefault(ordinal, {})
        for dno, files in (bucket or {}).items():
            dest.setdefault(int(dno), [])
            seen = {int(f.get("node_id") or 0) for f in dest[int(dno)]}
            for meta in files or []:
                nid = int(meta.get("node_id") or 0)
                if nid and nid not in seen:
                    dest[int(dno)].append(meta)
                    seen.add(nid)

    out = dict(mapping or {})
    for ordinal, bucket in by_ord.items():
        for i in groups.get(ordinal) or []:
            out[i] = bucket
    return out
