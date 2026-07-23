# -*- coding: utf-8 -*-
"""ربط مجلدات التقييم الخارجية (يN - مN) بمعاضل مجرى الأحداث في بنك المعلومات."""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import INFO_BANK_DIR
from app.info_bank_tree import (
    _next_sort,
    _sanitize_path_parts,
    ensure_information_bank_kind,
    flow_day_catalog_key,
    get_or_create_folder,
    get_node,
    ibank_event_flow_days,
)
from app.models.domain import InformationBankEventFlowTable, InformationBankTreeNode

DILEMMA_FOLDER_UNIT_PREFIX = "fdlm:"
IMPORT_FILE_EXTENSIONS = (".xlsx", ".docx", ".doc", ".pdf", ".png", ".jpg", ".jpeg")

_DAY_DIR_RE = re.compile(r"اليوم\s*[/\\-]?\s*(\d+)", re.IGNORECASE)
_Y_M_RE = re.compile(
    r"ي\s*(\d+)\s*[-–—]?\s*م\s*(\d+)",
    re.IGNORECASE,
)
_MUADALA_RE = re.compile(r"معضل[ةه]\s*[/\\-]?\s*(\d+)", re.IGNORECASE)
_DILEMMA_TEXT_NO_RE = re.compile(r"المعضل[ةه]\s*/\s*(\d+)", re.IGNORECASE)


def dilemma_folder_unit_key(day_id: str, dilemma_no: int) -> str:
    day_id = (day_id or "day-1").strip()[:48]
    return f"{DILEMMA_FOLDER_UNIT_PREFIX}{day_id}:{int(dilemma_no)}"


def parse_dilemma_folder_unit_key(unit_key: str) -> tuple[str, int] | None:
    uk = (unit_key or "").strip()
    if not uk.startswith(DILEMMA_FOLDER_UNIT_PREFIX):
        return None
    rest = uk[len(DILEMMA_FOLDER_UNIT_PREFIX) :]
    if ":" not in rest:
        return None
    day_id, _, num_s = rest.partition(":")
    try:
        return day_id.strip(), int(num_s.strip())
    except ValueError:
        return None


def is_dilemma_folder_unit_key(unit_key: str) -> bool:
    return parse_dilemma_folder_unit_key(unit_key) is not None


def parse_dilemma_no_from_text(text: str) -> int | None:
    m = _DILEMMA_TEXT_NO_RE.search(text or "")
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def day_id_for_number(day_no: int) -> str:
    return f"day-{int(day_no)}"


def parse_day_no_from_dirname(name: str) -> int | None:
    m = _DAY_DIR_RE.search(name or "")
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def parse_dilemma_folder_codes(
    folder_name: str, *, parent_day_no: int | None = None
) -> tuple[int, int] | None:
    """استخراج (رقم اليوم، رقم المعضلة) من اسم المجلد."""
    name = (folder_name or "").strip()
    m = _Y_M_RE.search(name)
    if m:
        try:
            return int(m.group(1)), int(m.group(2))
        except ValueError:
            return None
    m2 = _MUADALA_RE.search(name)
    if m2 and parent_day_no:
        try:
            return int(parent_day_no), int(m2.group(1))
        except ValueError:
            return None
    return None


def enrich_dilemma_names(by_day: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """أضف dilemma_no من نص المعضلة (المعضلة/N) مع الإبقاء على الترقيم التسلسلي."""
    out: dict[str, list[dict]] = {}
    for day_id, rows in (by_day or {}).items():
        enriched: list[dict] = []
        for row in rows:
            item = dict(row)
            text = str(item.get("text") or "")
            dno = parse_dilemma_no_from_text(text)
            if dno is None:
                dno = int(item.get("num") or 0) or None
            item["dilemma_no"] = dno
            enriched.append(item)
        out[day_id] = enriched
    return out


def _find_day_root(db: Session, day_id: str) -> InformationBankTreeNode | None:
    ck = flow_day_catalog_key(day_id)
    if not ck:
        return None
    return (
        db.query(InformationBankTreeNode)
        .filter(
            InformationBankTreeNode.kind == "action_eval",
            InformationBankTreeNode.parent_id.is_(None),
            InformationBankTreeNode.is_folder.is_(True),
            InformationBankTreeNode.catalog_phase_key == ck,
        )
        .first()
    )


def _ensure_flow_day_exists(db: Session, day_no: int) -> str:
    """ضمان وجود اليوم في JSON المجرى وجذر الشجرة."""
    day_id = day_id_for_number(day_no)
    label = f"اليوم/{day_no}"
    row = (
        db.query(InformationBankEventFlowTable)
        .order_by(InformationBankEventFlowTable.id)
        .first()
    )
    if row is None:
        row = InformationBankEventFlowTable(flow_table_json="")
        db.add(row)
        db.flush()

    raw = (row.flow_table_json or "").strip()
    data: dict
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            data = {
                "version": 2,
                "active_day_id": "day-1",
                "days": [{"id": "day-1", "label": "اليوم/1", "note": "", "rows": parsed}],
            }
        elif isinstance(parsed, dict):
            data = parsed
        else:
            data = {"version": 2, "active_day_id": "day-1", "days": []}
    else:
        data = {"version": 2, "active_day_id": "day-1", "days": []}

    days = data.get("days")
    if not isinstance(days, list):
        days = []
        data["days"] = days
    found = False
    for item in days:
        if isinstance(item, dict) and str(item.get("id") or "") == day_id:
            found = True
            break
    if not found:
        days.append({"id": day_id, "label": label, "note": "", "rows": []})
        data["days"] = days
        if not data.get("active_day_id"):
            data["active_day_id"] = day_id
        row.flow_table_json = json.dumps(data, ensure_ascii=False)
        db.flush()

    ensure_information_bank_kind(db, "action_eval")
    root = _find_day_root(db, day_id)
    if root is None:
        root = InformationBankTreeNode(
            kind="action_eval",
            parent_id=None,
            name=label[:500],
            is_folder=True,
            catalog_phase_key=flow_day_catalog_key(day_id),
            catalog_unit_key="",
            sort_order=day_no,
            is_system=True,
        )
        db.add(root)
        db.flush()
    return day_id


def _short_title_from_folder(folder_name: str) -> str:
    name = (folder_name or "").strip()
    m = _Y_M_RE.search(name)
    if m:
        return name[m.end() :].lstrip(" -–—\t").strip() or name
    m2 = _MUADALA_RE.search(name)
    if m2:
        return name[m2.end() :].lstrip(" -–—\t").strip() or name
    return name


def scan_external_dilemma_folders(root_path: str | Path) -> list[dict]:
    """مسح المجلد الخارجي وإرجاع حزم المعاضل مع مسارات الملفات."""
    root = Path(root_path)
    if not root.is_dir():
        raise ValueError(f"المسار غير موجود أو ليس مجلداً: {root}")

    packs: list[dict] = []
    day_dirs = [p for p in root.iterdir() if p.is_dir() and parse_day_no_from_dirname(p.name)]
    # إن لم توجد مجلدات أيام، اعتبر الجذر نفسه يحوي مجلدات يN-مN
    if not day_dirs:
        day_dirs = [root]

    for day_dir in sorted(day_dirs, key=lambda p: parse_day_no_from_dirname(p.name) or 0):
        parent_day = parse_day_no_from_dirname(day_dir.name)
        candidates = [p for p in day_dir.iterdir() if p.is_dir()]
        for folder in sorted(candidates, key=lambda p: p.name):
            codes = parse_dilemma_folder_codes(folder.name, parent_day_no=parent_day)
            if not codes:
                continue
            day_no, dilemma_no = codes
            files: list[Path] = []
            for f in sorted(folder.rglob("*")):
                if not f.is_file():
                    continue
                if f.suffix.lower() not in IMPORT_FILE_EXTENSIONS:
                    continue
                files.append(f)
            packs.append(
                {
                    "day_no": day_no,
                    "dilemma_no": dilemma_no,
                    "folder_name": folder.name,
                    "folder_path": str(folder),
                    "title": _short_title_from_folder(folder.name),
                    "files": files,
                }
            )
    return packs


def _find_dilemma_folder(
    db: Session, *, day_id: str, dilemma_no: int
) -> InformationBankTreeNode | None:
    uk = dilemma_folder_unit_key(day_id, dilemma_no)
    day_root = _find_day_root(db, day_id)
    if day_root is None:
        return None
    return (
        db.query(InformationBankTreeNode)
        .filter(
            InformationBankTreeNode.kind == "action_eval",
            InformationBankTreeNode.parent_id == int(day_root.id),
            InformationBankTreeNode.is_folder.is_(True),
            InformationBankTreeNode.catalog_unit_key == uk,
        )
        .first()
    )


def _write_imported_file(
    db: Session,
    *,
    parent_id: int,
    src: Path,
) -> InformationBankTreeNode | None:
    parent = get_node(db, parent_id, "action_eval")
    if parent is None or not parent.is_folder:
        return None
    display_name = src.name[:500]
    # تجنب التكرار بنفس الاسم تحت نفس المجلد
    existing = (
        db.query(InformationBankTreeNode)
        .filter(
            InformationBankTreeNode.kind == "action_eval",
            InformationBankTreeNode.parent_id == parent_id,
            InformationBankTreeNode.is_folder.is_(False),
            InformationBankTreeNode.name == display_name,
        )
        .first()
    )
    if existing is not None:
        return existing
    data = src.read_bytes()
    ext = src.suffix.lower()
    rel_storage = f"action_eval/tree/n{uuid.uuid4().hex}/{_sanitize_path_parts(display_name)}"
    dest = (INFO_BANK_DIR / rel_storage).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    row = InformationBankTreeNode(
        kind="action_eval",
        parent_id=parent_id,
        name=display_name,
        is_folder=False,
        file_relpath=rel_storage.replace("\\", "/"),
        catalog_phase_key=(parent.catalog_phase_key or "")[:64],
        catalog_unit_key=(parent.catalog_unit_key or "")[:128],
        sort_order=_next_sort(db, "action_eval", parent_id),
        is_system=False,
    )
    db.add(row)
    db.flush()
    return row


def import_dilemma_folders_from_path(
    db: Session,
    *,
    root_path: str | Path,
) -> dict:
    """استيراد ملفات التقييم من مجلدات يN-مN وربطها بالمعاضل."""
    packs = scan_external_dilemma_folders(root_path)
    ensure_information_bank_kind(db, "action_eval")

    folders_touched = 0
    files_added = 0
    files_skipped = 0
    unmatched: list[str] = []
    matched_keys: set[tuple[str, int]] = set()

    for pack in packs:
        day_no = int(pack["day_no"])
        dilemma_no = int(pack["dilemma_no"])
        day_id = _ensure_flow_day_exists(db, day_no)
        day_root = _find_day_root(db, day_id)
        if day_root is None:
            unmatched.append(pack["folder_name"])
            continue

        title = (pack.get("title") or "").strip() or f"معضلة {dilemma_no}"
        folder_label = f"م{dilemma_no} — {title}"[:500]
        uk = dilemma_folder_unit_key(day_id, dilemma_no)
        dfolder = _find_dilemma_folder(db, day_id=day_id, dilemma_no=dilemma_no)
        if dfolder is None:
            dfolder = get_or_create_folder(
                db,
                kind="action_eval",
                parent_id=int(day_root.id),
                name=folder_label,
                catalog_unit_key=uk,
            )
            dfolder.catalog_unit_key = uk[:128]
            dfolder.name = folder_label
            folders_touched += 1
        else:
            # حدّث الاسم إن تغيّر العنوان
            if (dfolder.name or "") != folder_label:
                dfolder.name = folder_label
            dfolder.catalog_unit_key = uk[:128]

        matched_keys.add((day_id, dilemma_no))
        for src in pack["files"]:
            before = (
                db.query(InformationBankTreeNode)
                .filter(
                    InformationBankTreeNode.parent_id == int(dfolder.id),
                    InformationBankTreeNode.name == src.name[:500],
                    InformationBankTreeNode.is_folder.is_(False),
                )
                .first()
            )
            if before is not None:
                files_skipped += 1
                continue
            row = _write_imported_file(db, parent_id=int(dfolder.id), src=src)
            if row is not None:
                files_added += 1

    try:
        from app.ibank_action_eval_dilemma_tree import invalidate_action_eval_dilemma_tree_cache
        from app.info_bank_tree import invalidate_information_bank_kind_cache

        invalidate_action_eval_dilemma_tree_cache()
        invalidate_information_bank_kind_cache("action_eval")
    except Exception:
        pass

    return {
        "packs": len(packs),
        "folders": folders_touched,
        "files_added": files_added,
        "files_skipped": files_skipped,
        "matched": len(matched_keys),
        "unmatched": unmatched,
    }


def collect_linked_files_by_dilemma(db: Session) -> dict[str, dict[int, list[dict]]]:
    """day_id -> dilemma_no -> [{id, name, open_url_path}]."""
    out: dict[str, dict[int, list[dict]]] = {}
    folders = (
        db.query(InformationBankTreeNode)
        .filter(
            InformationBankTreeNode.kind == "action_eval",
            InformationBankTreeNode.is_folder.is_(True),
            InformationBankTreeNode.catalog_unit_key.like(f"{DILEMMA_FOLDER_UNIT_PREFIX}%"),
        )
        .all()
    )
    for folder in folders:
        parsed = parse_dilemma_folder_unit_key(folder.catalog_unit_key or "")
        if not parsed:
            continue
        day_id, dilemma_no = parsed
        files = (
            db.query(InformationBankTreeNode)
            .filter(
                InformationBankTreeNode.parent_id == int(folder.id),
                InformationBankTreeNode.is_folder.is_(False),
            )
            .order_by(InformationBankTreeNode.sort_order, InformationBankTreeNode.id)
            .all()
        )
        bucket = out.setdefault(day_id, {})
        bucket[dilemma_no] = [
            {
                "id": int(f.id),
                "name": f.name,
                "node_id": int(f.id),
            }
            for f in files
        ]
    return out


def attach_files_to_dilemma_names(
    by_day: dict[str, list[dict]],
    linked: dict[str, dict[int, list[dict]]],
) -> dict[str, list[dict]]:
    enriched = enrich_dilemma_names(by_day)
    for day_id, rows in enriched.items():
        day_files = linked.get(day_id) or {}
        for row in rows:
            dno = row.get("dilemma_no")
            row["files"] = list(day_files.get(int(dno), [])) if dno else []
    return enriched
