"""استنساخ لمرة واحدة: جاهزية المهمة → لعبات الحرب (ملفات وجداول مستقلة)."""

from __future__ import annotations

import shutil
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import INFO_BANK_DIR
from app.ibank_section_ctx import (
    IBANK_SECTION_MISSION,
    IBANK_SECTION_WARGAMES,
    ibank_section_bypass,
)
from app.models.domain import (
    InfoBankActionEvalXlsx,
    InfoBankDilemmaEvalXlsx,
    InfoBankEventFlowPdf,
    InformationBankDilemmaListUnit,
    InformationBankEventFlowTable,
    InformationBankPhaseNote,
    InformationBankTrainingPhase,
    InformationBankTreeNode,
    InformationBankUnitLevel,
    InformationBankUnitNote,
)


def _copy_file_rel(relpath: str) -> str:
    rel = (relpath or "").replace("\\", "/").strip().lstrip("/")
    if not rel:
        return ""
    if rel.startswith(f"{IBANK_SECTION_WARGAMES}/"):
        return rel
    src = (INFO_BANK_DIR / rel).resolve()
    dest_rel = f"{IBANK_SECTION_WARGAMES}/{rel}"
    dest = (INFO_BANK_DIR / dest_rel).resolve()
    try:
        dest.relative_to(INFO_BANK_DIR.resolve())
    except ValueError:
        return dest_rel
    if src.is_file():
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            shutil.copy2(src, dest)
    return dest_rel


def clone_mission_ibank_to_wargames(db: Session) -> bool:
    """ينسخ محتوى جاهزية المهمة إلى لعبات الحرب إن لم يكن قسم الحرب موجوداً بعد."""
    with ibank_section_bypass():
        exists = (
            db.query(InformationBankTrainingPhase)
            .filter(InformationBankTrainingPhase.ibank_section == IBANK_SECTION_WARGAMES)
            .first()
        )
        if exists is not None:
            return False

        now = datetime.utcnow()
        for row in (
            db.query(InformationBankTrainingPhase)
            .filter(InformationBankTrainingPhase.ibank_section == IBANK_SECTION_MISSION)
            .all()
        ):
            db.add(
                InformationBankTrainingPhase(
                    ibank_section=IBANK_SECTION_WARGAMES,
                    key=row.key,
                    label=row.label,
                    sort_order=row.sort_order,
                    included_in_exercise=row.included_in_exercise,
                    is_system=row.is_system,
                    created_at=row.created_at or now,
                    updated_at=row.updated_at or now,
                )
            )
        for row in (
            db.query(InformationBankUnitLevel)
            .filter(InformationBankUnitLevel.ibank_section == IBANK_SECTION_MISSION)
            .all()
        ):
            db.add(
                InformationBankUnitLevel(
                    ibank_section=IBANK_SECTION_WARGAMES,
                    key=row.key,
                    label=row.label,
                    brigade_group=row.brigade_group,
                    sort_order=row.sort_order,
                    included_in_exercise=row.included_in_exercise,
                    is_system=row.is_system,
                    created_at=row.created_at or now,
                    updated_at=row.updated_at or now,
                )
            )
        for row in (
            db.query(InformationBankPhaseNote)
            .filter(InformationBankPhaseNote.ibank_section == IBANK_SECTION_MISSION)
            .all()
        ):
            db.add(
                InformationBankPhaseNote(
                    ibank_section=IBANK_SECTION_WARGAMES,
                    phase_key=row.phase_key,
                    notes=row.notes,
                    updated_at=row.updated_at or now,
                )
            )
        for row in (
            db.query(InformationBankUnitNote)
            .filter(InformationBankUnitNote.ibank_section == IBANK_SECTION_MISSION)
            .all()
        ):
            db.add(
                InformationBankUnitNote(
                    ibank_section=IBANK_SECTION_WARGAMES,
                    unit_level_key=row.unit_level_key,
                    notes=row.notes,
                    updated_at=row.updated_at or now,
                )
            )
        db.flush()

        for model in (
            InfoBankEventFlowPdf,
            InfoBankActionEvalXlsx,
            InfoBankDilemmaEvalXlsx,
        ):
            for row in (
                db.query(model)
                .filter(model.ibank_section == IBANK_SECTION_MISSION)
                .all()
            ):
                db.add(
                    model(
                        ibank_section=IBANK_SECTION_WARGAMES,
                        training_phase_key=row.training_phase_key,
                        unit_level_key=row.unit_level_key,
                        title=row.title,
                        file_relpath=_copy_file_rel(row.file_relpath),
                        sort_order=row.sort_order,
                        created_at=row.created_at or now,
                    )
                )

        for row in (
            db.query(InformationBankEventFlowTable)
            .filter(InformationBankEventFlowTable.ibank_section == IBANK_SECTION_MISSION)
            .all()
        ):
            db.add(
                InformationBankEventFlowTable(
                    ibank_section=IBANK_SECTION_WARGAMES,
                    flow_table_json=row.flow_table_json or "",
                    updated_at=row.updated_at or now,
                )
            )
        db.flush()

        id_map: dict[int, int] = {}
        mission_nodes = (
            db.query(InformationBankTreeNode)
            .filter(InformationBankTreeNode.ibank_section == IBANK_SECTION_MISSION)
            .order_by(InformationBankTreeNode.id.asc())
            .all()
        )
        pending = list(mission_nodes)
        # آباء قبل الأبناء؛ إن تعذّر الترتيب نمرّ بعدة دورات
        while pending:
            progressed = False
            still: list[InformationBankTreeNode] = []
            for row in pending:
                old_parent = row.parent_id
                if old_parent is not None and int(old_parent) not in id_map:
                    still.append(row)
                    continue
                new_parent = (
                    None if old_parent is None else id_map.get(int(old_parent))
                )
                clone = InformationBankTreeNode(
                    ibank_section=IBANK_SECTION_WARGAMES,
                    kind=row.kind,
                    parent_id=new_parent,
                    name=row.name,
                    is_folder=row.is_folder,
                    file_relpath=(
                        "" if row.is_folder else _copy_file_rel(row.file_relpath)
                    ),
                    catalog_phase_key=row.catalog_phase_key,
                    catalog_unit_key=row.catalog_unit_key,
                    sort_order=row.sort_order,
                    is_system=row.is_system,
                    created_at=row.created_at or now,
                )
                db.add(clone)
                db.flush()
                id_map[int(row.id)] = int(clone.id)
                progressed = True
            if not progressed:
                for row in still:
                    clone = InformationBankTreeNode(
                        ibank_section=IBANK_SECTION_WARGAMES,
                        kind=row.kind,
                        parent_id=None,
                        name=row.name,
                        is_folder=row.is_folder,
                        file_relpath=(
                            "" if row.is_folder else _copy_file_rel(row.file_relpath)
                        ),
                        catalog_phase_key=row.catalog_phase_key,
                        catalog_unit_key=row.catalog_unit_key,
                        sort_order=row.sort_order,
                        is_system=row.is_system,
                        created_at=row.created_at or now,
                    )
                    db.add(clone)
                    db.flush()
                    id_map[int(row.id)] = int(clone.id)
                break
            pending = still

        for row in (
            db.query(InformationBankDilemmaListUnit)
            .filter(InformationBankDilemmaListUnit.ibank_section == IBANK_SECTION_MISSION)
            .all()
        ):
            new_list_id = id_map.get(int(row.list_node_id))
            if new_list_id is None:
                continue
            db.add(
                InformationBankDilemmaListUnit(
                    ibank_section=IBANK_SECTION_WARGAMES,
                    list_node_id=new_list_id,
                    unit_key=row.unit_key,
                    created_at=row.created_at or now,
                )
            )

        try:
            rows = db.execute(
                text(
                    """
                    SELECT kind, catalog_phase_key, catalog_unit_key
                    FROM information_bank_tree_suppressions
                    WHERE ibank_section = :sec
                    """
                ),
                {"sec": IBANK_SECTION_MISSION},
            ).fetchall()
            for kind, pk, uk in rows:
                db.execute(
                    text(
                        """
                        INSERT OR IGNORE INTO information_bank_tree_suppressions
                            (ibank_section, kind, catalog_phase_key, catalog_unit_key)
                        VALUES (:sec, :kind, :pk, :uk)
                        """
                    ),
                    {
                        "sec": IBANK_SECTION_WARGAMES,
                        "kind": kind,
                        "pk": pk or "",
                        "uk": uk or "",
                    },
                )
        except Exception:
            pass

        db.commit()
        return True


def ensure_wargames_ibank_clone() -> None:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        clone_mission_ibank_to_wargames(db)
    finally:
        db.close()
