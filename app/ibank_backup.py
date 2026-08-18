"""نسخ احتياطي واستعادة كاملة لبنك المعلومات (جداول + ملفات + دلالات)."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import DateTime, text
from sqlalchemy.orm import Session

from app.config import INFO_BANK_DIR
from app.ibank_section_ctx import ibank_section_bypass
from app.info_bank_tree import INFO_BANK_TREE_KINDS, invalidate_information_bank_kind_cache
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
    UnitDesignation,
    UnitDesignationAlias,
)
from app.paths import data_dir
from app.unit_designations import _DATA_XLSX, _REPO_XLSX, reload_unit_designation_cache

BACKUP_FORMAT = "information_bank_full_v1"
MANIFEST_NAME = "manifest.json"
DATA_NAME = "data.json"
FILES_PREFIX = "files/"
SOURCES_PREFIX = "sources/"

_ORM_TABLE_SPECS: tuple[tuple[str, type, str | None], ...] = (
    ("information_bank_training_phases", InformationBankTrainingPhase, None),
    ("information_bank_unit_levels", InformationBankUnitLevel, None),
    ("information_bank_phase_notes", InformationBankPhaseNote, None),
    ("information_bank_unit_notes", InformationBankUnitNote, None),
    ("information_bank_tree_nodes", InformationBankTreeNode, "ibank_kinds"),
    ("information_bank_dilemma_list_units", InformationBankDilemmaListUnit, None),
    ("information_bank_event_flow_table", InformationBankEventFlowTable, None),
    ("info_bank_event_flow_pdfs", InfoBankEventFlowPdf, None),
    ("info_bank_action_eval_xlsx", InfoBankActionEvalXlsx, None),
    ("info_bank_dilemma_eval_xlsx", InfoBankDilemmaEvalXlsx, None),
    ("unit_designations", UnitDesignation, None),
    ("unit_designation_aliases", UnitDesignationAlias, None),
)


def _ibank_backups_dir() -> Path:
    d = Path(data_dir()) / "backups" / "information_bank"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _serialize_value(val: Any) -> Any:
    if isinstance(val, datetime):
        return val.isoformat()
    return val


def _row_to_dict(obj: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for col in type(obj).__mapper__.columns:
        out[col.key] = _serialize_value(getattr(obj, col.key))
    return out


def _parse_datetime(raw: Any) -> datetime | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return raw
    s = str(raw).strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _is_datetime_column(col) -> bool:
    try:
        return isinstance(col.type, DateTime)
    except Exception:
        return False


def _apply_row(model: type, data: dict[str, Any]) -> Any:
    kwargs: dict[str, Any] = {}
    for col in model.__mapper__.columns:
        if col.key not in data:
            continue
        val = data[col.key]
        if _is_datetime_column(col):
            val = _parse_datetime(val)
        elif isinstance(val, str):
            try:
                if getattr(col.type, "python_type", None) is bool:
                    val = val.strip().lower() in ("1", "true", "yes", "on")
            except Exception:
                pass
        kwargs[col.key] = val
    if "ibank_section" in model.__mapper__.columns and not str(
        kwargs.get("ibank_section") or ""
    ).strip():
        kwargs["ibank_section"] = "mission-readiness"
    return model(**kwargs)


def _topo_sort_tree_nodes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {int(r["id"]): r for r in rows if r.get("id") is not None}
    ordered: list[dict[str, Any]] = []
    seen: set[int] = set()

    def visit(nid: int) -> None:
        if nid in seen or nid not in by_id:
            return
        row = by_id[nid]
        pid = row.get("parent_id")
        if pid is not None:
            try:
                visit(int(pid))
            except (TypeError, ValueError):
                pass
        if nid in seen:
            return
        seen.add(nid)
        ordered.append(row)

    for nid in sorted(by_id.keys()):
        visit(nid)
    return ordered


def _export_suppressions(db: Session) -> list[dict[str, str]]:
    try:
        rows = (
            db.execute(
                text(
                    "SELECT ibank_section, kind, catalog_phase_key, catalog_unit_key "
                    "FROM information_bank_tree_suppressions"
                )
            )
            .mappings()
            .all()
        )
    except Exception:
        try:
            rows = (
                db.execute(
                    text(
                        "SELECT kind, catalog_phase_key, catalog_unit_key "
                        "FROM information_bank_tree_suppressions"
                    )
                )
                .mappings()
                .all()
            )
        except Exception:
            return []
        return [
            {
                "ibank_section": "mission-readiness",
                "kind": str(r["kind"] or ""),
                "catalog_phase_key": str(r["catalog_phase_key"] or ""),
                "catalog_unit_key": str(r["catalog_unit_key"] or ""),
            }
            for r in rows
        ]
    return [
        {
            "ibank_section": str(r.get("ibank_section") or "mission-readiness"),
            "kind": str(r["kind"] or ""),
            "catalog_phase_key": str(r["catalog_phase_key"] or ""),
            "catalog_unit_key": str(r["catalog_unit_key"] or ""),
        }
        for r in rows
    ]


def _collect_table_payload(db: Session) -> dict[str, Any]:
    with ibank_section_bypass():
        payload: dict[str, Any] = {}
        kinds = set(INFO_BANK_TREE_KINDS)
        for name, model, filt in _ORM_TABLE_SPECS:
            q = db.query(model)
            if filt == "ibank_kinds":
                q = q.filter(InformationBankTreeNode.kind.in_(tuple(kinds)))
            rows = [_row_to_dict(r) for r in q.all()]
            if name == "information_bank_tree_nodes":
                rows = _topo_sort_tree_nodes(rows)
            payload[name] = rows
        payload["information_bank_tree_suppressions"] = _export_suppressions(db)
        return payload


def _iter_info_bank_files() -> list[tuple[Path, str]]:
    root = INFO_BANK_DIR.resolve()
    if not root.is_dir():
        return []
    out: list[tuple[Path, str]] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            continue
        if not rel or ".." in PurePosixPath(rel).parts:
            continue
        out.append((path, rel))
    return out


def _source_xlsx_candidates() -> list[Path]:
    out: list[Path] = []
    for p in (_REPO_XLSX, _DATA_XLSX):
        if p.is_file() and p not in out:
            out.append(p)
    return out


def build_information_bank_backup_zip(db: Session, dest: Path | None = None) -> Path:
    """يبني أرشيف zip يضم كل بيانات ومرفقات بنك المعلومات."""
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    if dest is None:
        dest = _ibank_backups_dir() / f"ibank-backup-{stamp}.zip"
    else:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)

    tables = _collect_table_payload(db)
    file_entries = _iter_info_bank_files()
    sources = _source_xlsx_candidates()
    counts = {k: len(v) if isinstance(v, list) else 0 for k, v in tables.items()}
    manifest = {
        "format": BACKUP_FORMAT,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "info_bank_tree_kinds": list(INFO_BANK_TREE_KINDS),
        "counts": counts,
        "file_count": len(file_entries),
        "source_files": [p.name for p in sources],
        "notes_ar": "نسخة كاملة لبنك المعلومات: الجداول والمرفقات وكشف المسميات والدلالات.",
    }

    tmp_path = dest.with_suffix(".zip.partial")
    if tmp_path.exists():
        tmp_path.unlink()
    try:
        with zipfile.ZipFile(
            tmp_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
        ) as zf:
            zf.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2))
            zf.writestr(DATA_NAME, json.dumps(tables, ensure_ascii=False, indent=2))
            for src, rel in file_entries:
                zf.write(src, arcname=f"{FILES_PREFIX}{rel}")
            for src in sources:
                zf.write(src, arcname=f"{SOURCES_PREFIX}{src.name}")
        if dest.exists():
            dest.unlink()
        tmp_path.replace(dest)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise
    return dest


def _read_zip_json(zf: zipfile.ZipFile, name: str) -> Any:
    with zf.open(name) as fh:
        return json.loads(fh.read().decode("utf-8"))


def validate_information_bank_backup_zip(zip_path: Path) -> dict[str, Any]:
    path = Path(zip_path)
    if not path.is_file():
        raise ValueError("ملف النسخة غير موجود")
    with zipfile.ZipFile(path, "r") as zf:
        names = set(zf.namelist())
        if MANIFEST_NAME not in names or DATA_NAME not in names:
            raise ValueError("الأرشيف لا يحتوي على بيانات بنك المعلومات الكاملة")
        manifest = _read_zip_json(zf, MANIFEST_NAME)
        if (manifest.get("format") or "").strip() != BACKUP_FORMAT:
            raise ValueError("صيغة النسخة الاحتياطية غير مدعومة")
        data = _read_zip_json(zf, DATA_NAME)
        if not isinstance(data, dict):
            raise ValueError("ملف البيانات تالف")
        for key, _, _ in _ORM_TABLE_SPECS:
            if key not in data:
                raise ValueError(f"الجدول الناقص في النسخة: {key}")
        if "information_bank_tree_suppressions" not in data:
            raise ValueError("الجدول الناقص في النسخة: information_bank_tree_suppressions")
    return manifest


def _clear_ibank_files_dir() -> None:
    root = INFO_BANK_DIR.resolve()
    root.mkdir(parents=True, exist_ok=True)
    for child in list(root.iterdir()):
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            try:
                child.unlink()
            except OSError:
                pass


def _extract_files_from_zip(zf: zipfile.ZipFile) -> int:
    root = INFO_BANK_DIR.resolve()
    root.mkdir(parents=True, exist_ok=True)
    count = 0
    for info in zf.infolist():
        name = (info.filename or "").replace("\\", "/")
        if info.is_dir() or not name.startswith(FILES_PREFIX):
            continue
        rel = name[len(FILES_PREFIX) :].lstrip("/")
        if not rel or ".." in PurePosixPath(rel).parts:
            continue
        dest = (root / rel).resolve()
        if not str(dest).startswith(str(root)):
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info, "r") as src, open(dest, "wb") as out:
            shutil.copyfileobj(src, out)
        count += 1
    return count


def _extract_sources_from_zip(zf: zipfile.ZipFile) -> list[str]:
    restored: list[str] = []
    data_xlsx = Path(__file__).resolve().parent / "data" / "unit_designations.xlsx"
    for info in zf.infolist():
        name = (info.filename or "").replace("\\", "/")
        if info.is_dir() or not name.startswith(SOURCES_PREFIX):
            continue
        base = Path(name).name
        if not base.lower().endswith((".xlsx", ".xls")):
            continue
        if "unit_designations" in base.lower() or "المسميات" in base:
            dest = data_xlsx
        else:
            dest = Path(data_dir()) / "backups" / "information_bank" / "sources" / base
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info, "r") as src, open(dest, "wb") as out:
            shutil.copyfileobj(src, out)
        restored.append(str(dest))
    return restored


def _delete_ibank_tree_nodes(db: Session) -> None:
    kinds = tuple(INFO_BANK_TREE_KINDS)
    for _ in range(64):
        ids = [
            int(r[0])
            for r in db.query(InformationBankTreeNode.id)
            .filter(InformationBankTreeNode.kind.in_(kinds))
            .all()
        ]
        if not ids:
            break
        child_count = (
            db.query(InformationBankTreeNode)
            .filter(
                InformationBankTreeNode.kind.in_(kinds),
                InformationBankTreeNode.parent_id.in_(ids),
            )
            .count()
        )
        if child_count:
            (
                db.query(InformationBankTreeNode)
                .filter(
                    InformationBankTreeNode.kind.in_(kinds),
                    InformationBankTreeNode.parent_id.in_(ids),
                )
                .delete(synchronize_session=False)
            )
            db.flush()
            continue
        (
            db.query(InformationBankTreeNode)
            .filter(InformationBankTreeNode.kind.in_(kinds))
            .delete(synchronize_session=False)
        )
        db.flush()
        break


def _wipe_ibank_tables(db: Session) -> None:
    with ibank_section_bypass():
        db.query(InformationBankDilemmaListUnit).delete(synchronize_session=False)
        _delete_ibank_tree_nodes(db)
        db.query(InformationBankEventFlowTable).delete(synchronize_session=False)
        db.query(InfoBankEventFlowPdf).delete(synchronize_session=False)
        db.query(InfoBankActionEvalXlsx).delete(synchronize_session=False)
        db.query(InfoBankDilemmaEvalXlsx).delete(synchronize_session=False)
        db.query(InformationBankPhaseNote).delete(synchronize_session=False)
        db.query(InformationBankUnitNote).delete(synchronize_session=False)
        db.query(InformationBankTrainingPhase).delete(synchronize_session=False)
        db.query(InformationBankUnitLevel).delete(synchronize_session=False)
        db.query(UnitDesignationAlias).delete(synchronize_session=False)
        db.query(UnitDesignation).delete(synchronize_session=False)
        try:
            db.execute(text("DELETE FROM information_bank_tree_suppressions"))
        except Exception:
            pass
        db.flush()


def _insert_suppressions(db: Session, rows: list[dict[str, Any]]) -> int:
    n = 0
    for r in rows or []:
        kind = str(r.get("kind") or "").strip()
        if not kind:
            continue
        db.execute(
            text(
                "INSERT OR REPLACE INTO information_bank_tree_suppressions "
                "(ibank_section, kind, catalog_phase_key, catalog_unit_key) "
                "VALUES (:sec, :kind, :pk, :uk)"
            ),
            {
                "sec": str(r.get("ibank_section") or "mission-readiness")[:32],
                "kind": kind[:32],
                "pk": str(r.get("catalog_phase_key") or "")[:64],
                "uk": str(r.get("catalog_unit_key") or "")[:128],
            },
        )
        n += 1
    return n


def _restore_sqlite_identity(db: Session, table: str) -> None:
    try:
        mx = db.execute(text(f"SELECT MAX(id) FROM [{table}]")).scalar()
        if mx is None:
            return
        exists = db.execute(
            text("SELECT 1 FROM sqlite_sequence WHERE name=:n"), {"n": table}
        ).scalar()
        if exists:
            db.execute(
                text("UPDATE sqlite_sequence SET seq=:s WHERE name=:n"),
                {"n": table, "s": int(mx)},
            )
        else:
            db.execute(
                text("INSERT INTO sqlite_sequence(name, seq) VALUES (:n, :s)"),
                {"n": table, "s": int(mx)},
            )
    except Exception:
        pass


def restore_information_bank_from_zip(
    db: Session,
    zip_path: Path,
    *,
    safety_backup: bool = True,
) -> dict[str, Any]:
    """استعادة كاملة لبنك المعلومات من أرشيف zip (مع نسخة أمان قبل الاستبدال)."""
    zip_path = Path(zip_path)
    manifest = validate_information_bank_backup_zip(zip_path)

    safety_path = None
    if safety_backup:
        stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        safety_path = _ibank_backups_dir() / f"ibank-pre-restore-{stamp}.zip"
        build_information_bank_backup_zip(db, safety_path)

    file_count = 0
    with zipfile.ZipFile(zip_path, "r") as zf:
        data = _read_zip_json(zf, DATA_NAME)
        bind = db.get_bind()
        is_sqlite = bind is not None and bind.dialect.name == "sqlite"
        if is_sqlite:
            db.execute(text("PRAGMA foreign_keys=OFF"))
        try:
            with ibank_section_bypass():
                _wipe_ibank_tables(db)
                _clear_ibank_files_dir()

                for name, model, _filt in _ORM_TABLE_SPECS:
                    rows = data.get(name) or []
                    if name == "information_bank_tree_nodes":
                        rows = _topo_sort_tree_nodes(
                            [
                                r
                                for r in rows
                                if (r.get("kind") or "") in INFO_BANK_TREE_KINDS
                            ]
                        )
                    for row in rows:
                        if name == "information_bank_tree_nodes":
                            if (row.get("kind") or "").strip() not in INFO_BANK_TREE_KINDS:
                                continue
                        db.add(_apply_row(model, row))
                    db.flush()

                _insert_suppressions(db, data.get("information_bank_tree_suppressions") or [])
                db.flush()

                if is_sqlite:
                    for tbl in (
                        "information_bank_tree_nodes",
                        "information_bank_dilemma_list_units",
                        "information_bank_event_flow_table",
                        "info_bank_event_flow_pdfs",
                        "info_bank_action_eval_xlsx",
                        "info_bank_dilemma_eval_xlsx",
                    ):
                        _restore_sqlite_identity(db, tbl)

                file_count = _extract_files_from_zip(zf)
                _extract_sources_from_zip(zf)
                db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            if is_sqlite:
                try:
                    db.execute(text("PRAGMA foreign_keys=ON"))
                except Exception:
                    pass

    invalidate_information_bank_kind_cache()
    try:
        from app.ibank_action_eval_dilemma_tree import (
            invalidate_action_eval_dilemma_tree_cache,
        )

        invalidate_action_eval_dilemma_tree_cache()
    except Exception:
        pass
    reload_unit_designation_cache(db)

    return {
        "ok": True,
        "manifest": manifest,
        "safety_backup": str(safety_path) if safety_path else "",
        "file_count": file_count,
    }


def save_uploaded_backup_to_temp(file_storage) -> Path:
    filename = (getattr(file_storage, "filename", "") or "upload.zip").strip()
    if not filename.lower().endswith(".zip"):
        raise ValueError("يجب أن يكون الملف بصيغة ZIP")
    fd, name = tempfile.mkstemp(prefix="ibank-restore-", suffix=".zip")
    tmp_path = Path(name)
    try:
        os.close(fd)
        file_storage.save(str(tmp_path))
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    return tmp_path
