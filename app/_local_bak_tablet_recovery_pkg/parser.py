# -*- coding: utf-8 -*-
"""تحليل حزمة استعادة التابلت — قراءة فقط."""
from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


class RecoveryPackageError(ValueError):
    """حزمة غير صالحة أو غير آمنة."""


MAX_ZIP_UNCOMPRESSED = 2 * 1024 * 1024 * 1024
MAX_ZIP_MEMBERS = 20000


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def validate_zip_members(zf: zipfile.ZipFile) -> list[str]:
    names: list[str] = []
    total_uncomp = 0
    infos = zf.infolist()
    if len(infos) > MAX_ZIP_MEMBERS:
        raise RecoveryPackageError("عدد ملفات الحزمة كبير جداً")
    for info in infos:
        name = (info.filename or "").replace("\\", "/")
        if not name or name.endswith("/"):
            continue
        if name.startswith("/") or name.startswith("\\") or (len(name) > 2 and name[1] == ":"):
            raise RecoveryPackageError(f"مسار غير مسموح: {name}")
        parts = name.split("/")
        if any(p == ".." for p in parts):
            raise RecoveryPackageError(f"مسار غير مسموح: {name}")
        lower = name.lower()
        if lower.endswith((".exe", ".bat", ".cmd", ".ps1", ".sh", ".dll", ".so")):
            raise RecoveryPackageError(f"نوع ملف غير مسموح: {name}")
        total_uncomp += int(info.file_size or 0)
        if total_uncomp > MAX_ZIP_UNCOMPRESSED:
            raise RecoveryPackageError("حجم فك الضغط يتجاوز الحد المسموح")
        names.append(name)
    return names


def extract_save_rows(body: dict | None) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        return []
    payload = body.get("payload")
    raw = None
    if isinstance(payload, dict):
        raw = payload.get("rows")
    if raw is None:
        raw = body.get("rows")
    if not isinstance(raw, list):
        return []
    return [dict(r) for r in raw if isinstance(r, dict)]


def count_scored(rows: list[dict[str, Any]]) -> int:
    return sum(1 for r in rows if str(r.get("acquired") or "").strip())


def count_notes(rows: list[dict[str, Any]]) -> int:
    return sum(1 for r in rows if str(r.get("notes") or "").strip())


def rows_fingerprint(rows: list[dict[str, Any]]) -> str:
    parts = []
    for r in rows:
        parts.append(
            "|".join(
                [
                    str(r.get("row_kind") or "").strip(),
                    str(r.get("element") or "").strip(),
                    str(r.get("max_val") or "").strip(),
                    str(r.get("acquired") or "").strip(),
                    str(r.get("notes") or "").strip(),
                ]
            )
        )
    return "\n".join(parts)


def parse_body_raw(raw: str | None) -> tuple[dict[str, Any] | None, bool]:
    if raw is None:
        return {}, True
    text = str(raw)
    if not text.strip():
        return {}, True
    try:
        decoded = json.loads(text)
        if isinstance(decoded, dict):
            return dict(decoded), True
        return None, False
    except Exception:
        return None, False


def eval_id_from_cache_key(cache_key: str) -> int | None:
    parts = (cache_key or "").split(":")
    try:
        i = parts.index("evaluation_list_detail")
        if i + 2 < len(parts):
            return int(parts[i + 2])
    except (ValueError, IndexError):
        pass
    try:
        i = parts.index("action_eval_detail")
        if i + 1 < len(parts):
            return int(parts[i + 1])
    except (ValueError, IndexError):
        pass
    try:
        return int(parts[-1])
    except Exception:
        return None


def unit_key_from_cache_key(cache_key: str) -> str | None:
    parts = (cache_key or "").split(":")
    try:
        i = parts.index("evaluation_list_detail")
        if i + 1 < len(parts):
            return parts[i + 1]
    except ValueError:
        return None
    return None


def extract_cache_saved_rows(body: dict[str, Any]) -> list[dict[str, Any]]:
    from_payload = extract_save_rows(
        {"payload": body.get("saved_payload"), "rows": body.get("saved_rows")}
    )
    if from_payload:
        return from_payload
    saved = body.get("saved_rows")
    if isinstance(saved, list):
        return [dict(r) for r in saved if isinstance(r, dict)]
    return []


@dataclass
class PendingOpRecord:
    id: str
    method: str
    path: str
    kind: str
    op_type: str
    created_at: str
    attempts: int
    last_error: str | None
    sync_status: str
    judge_id: int | None
    user_id: int | None
    exercise_id: int | None
    list_id: str | None
    eval_item_id: int | None
    media_local_path: str | None
    body_raw: str
    body_parse_ok: bool
    body: dict[str, Any] | None
    client_op_id: str | None
    save_rows: list[dict[str, Any]] = field(default_factory=list)

    @property
    def is_save_results(self) -> bool:
        return (self.op_type or "") == "save_results"

    @property
    def scored_count(self) -> int:
        return count_scored(self.save_rows)

    @property
    def notes_count(self) -> int:
        return count_notes(self.save_rows)


@dataclass
class CacheEvalRecord:
    cache_key: str
    sync_status: str
    updated_at: str
    body: dict[str, Any] | None
    body_parse_ok: bool
    saved_rows: list[dict[str, Any]]
    eval_item_id: int | None
    unit_key: str | None
    locally_modified: bool
    json_body_raw: str


@dataclass
class MediaRecord:
    raw: dict[str, Any]
    id: str
    client_uuid: str | None
    evaluation_list_item_id: int | None
    bundle_action_eval_id: int | None
    row_index: int
    media_kind: str
    local_path: str
    local_filename: str | None
    original_filename: str | None
    mime_type: str | None
    file_size: int
    checksum: str | None
    export_relative_path: str | None
    file_exists_in_manifest: bool
    physical_path: Path | None = None


@dataclass
class RecoveryPackage:
    manifest: dict[str, Any]
    pending_ops: list[PendingOpRecord]
    cache_evals: list[CacheEvalRecord]
    media: list[MediaRecord]
    approvals: list[dict[str, Any]]
    member_names: list[str]
    staging_dir: Path
    has_excel: bool
    parse_warnings: list[str] = field(default_factory=list)


def _as_int(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except Exception:
        return None


def _map_pending(entry: dict[str, Any]) -> PendingOpRecord:
    body_raw = entry.get("body_raw")
    if body_raw is None and isinstance(entry.get("body"), (dict, list)):
        body_raw = json.dumps(entry.get("body"), ensure_ascii=False)
    elif body_raw is None:
        body_raw = str(entry.get("body") or "")
    body_raw = str(body_raw)
    parsed, ok = parse_body_raw(body_raw)
    if not ok and isinstance(entry.get("body"), dict):
        parsed = dict(entry["body"])
        ok = True
    client_op = None
    if isinstance(parsed, dict):
        client_op = str(parsed.get("client_op_id") or "").strip() or None
    if not client_op:
        client_op = str(entry.get("client_op_id") or entry.get("id") or "").strip() or None
    rows = extract_save_rows(parsed) if ok else []
    return PendingOpRecord(
        id=str(entry.get("id") or ""),
        method=str(entry.get("method") or ""),
        path=str(entry.get("path") or ""),
        kind=str(entry.get("kind") or ""),
        op_type=str(entry.get("op_type") or ""),
        created_at=str(entry.get("created_at") or ""),
        attempts=int(entry.get("attempts") or 0),
        last_error=(str(entry["last_error"]) if entry.get("last_error") is not None else None),
        sync_status=str(entry.get("sync_status") or ""),
        judge_id=_as_int(entry.get("judge_id")),
        user_id=_as_int(entry.get("user_id")),
        exercise_id=_as_int(entry.get("exercise_id")),
        list_id=(str(entry["list_id"]) if entry.get("list_id") is not None else None),
        eval_item_id=_as_int(entry.get("eval_item_id")),
        media_local_path=(
            str(entry["media_local_path"]) if entry.get("media_local_path") is not None else None
        ),
        body_raw=body_raw,
        body_parse_ok=ok,
        body=parsed,
        client_op_id=client_op,
        save_rows=rows,
    )


def _map_cache(entry: dict[str, Any]) -> CacheEvalRecord:
    key = str(entry.get("cache_key") or "")
    raw = entry.get("json_body_raw")
    if raw is None and isinstance(entry.get("body"), dict):
        raw = json.dumps(entry["body"], ensure_ascii=False)
    else:
        raw = str(raw or "")
    parsed, ok = parse_body_raw(raw)
    if not ok and isinstance(entry.get("body"), dict):
        parsed = dict(entry["body"])
        ok = True
    body = parsed if isinstance(parsed, dict) else {}
    return CacheEvalRecord(
        cache_key=key,
        sync_status=str(entry.get("sync_status") or ""),
        updated_at=str(entry.get("updated_at") or ""),
        body=body if ok else None,
        body_parse_ok=ok,
        saved_rows=extract_cache_saved_rows(body) if ok else [],
        eval_item_id=_as_int(entry.get("eval_item_id")) or eval_id_from_cache_key(key),
        unit_key=(
            str(entry["unit_key"])
            if entry.get("unit_key") is not None
            else unit_key_from_cache_key(key)
        ),
        locally_modified=bool(body.get("locally_modified")) if ok else False,
        json_body_raw=raw,
    )


def _truthy_flag(value: Any, default: bool = True) -> bool:
    """يقبل YES/NO والنصوص الشائعة من تصدير التابلت."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("", "0", "false", "no", "n", "missing", "absent"):
        return False
    if text in ("1", "true", "yes", "y", "ok"):
        return True
    return bool(value)


def _map_media(entry: dict[str, Any]) -> MediaRecord:
    # الحزم الحقيقية تستخدم exported_path؛ بعض النسخ قد تستخدم export_relative_path
    export_rel = (
        entry.get("export_relative_path")
        if entry.get("export_relative_path") is not None
        else entry.get("exported_path")
    )
    return MediaRecord(
        raw=dict(entry),
        id=str(entry.get("id") or ""),
        client_uuid=(str(entry["client_uuid"]) if entry.get("client_uuid") is not None else None),
        evaluation_list_item_id=_as_int(
            entry.get("evaluation_list_item_id")
            if entry.get("evaluation_list_item_id") is not None
            else entry.get("eval_item_id")
        ),
        bundle_action_eval_id=_as_int(entry.get("bundle_action_eval_id")),
        row_index=int(entry.get("row_index") or 0),
        media_kind=str(entry.get("media_kind") or "photo"),
        local_path=str(entry.get("local_path") or ""),
        local_filename=(
            str(entry["local_filename"]) if entry.get("local_filename") is not None else None
        ),
        original_filename=(
            str(entry["original_filename"])
            if entry.get("original_filename") is not None
            else None
        ),
        mime_type=(str(entry["mime_type"]) if entry.get("mime_type") is not None else None),
        file_size=int(entry.get("file_size") or entry.get("actual_file_size") or 0),
        checksum=(str(entry["checksum"]) if entry.get("checksum") is not None else None),
        export_relative_path=(str(export_rel).replace("\\", "/") if export_rel else None),
        file_exists_in_manifest=_truthy_flag(entry.get("file_exists"), True),
    )


def _resolve_media_physical(staging: Path, media: MediaRecord) -> Path | None:
    candidates: list[Path] = []
    if media.export_relative_path:
        rel = media.export_relative_path.replace("\\", "/").lstrip("/")
        candidates.append(staging / rel)
    name = media.local_filename or (Path(media.local_path).name if media.local_path else "")
    mid = (media.id or "").strip()
    cuid = (media.client_uuid or "").strip()
    names: list[str] = []
    for n in (name, media.original_filename or ""):
        n = Path(str(n)).name.strip()
        if n and n not in names:
            names.append(n)
    if mid and name and f"{mid}_{name}" not in names:
        names.append(f"{mid}_{name}")
    if cuid and name and f"{cuid}_{name}" not in names:
        names.append(f"{cuid}_{name}")
    for folder in ("images", "videos", "files", "signatures"):
        for n in names:
            candidates.append(staging / folder / n)
        # مطابقة بالبادئة: media-xxx_* داخل المجلد
        for key in (mid, cuid):
            if not key:
                continue
            folder_path = staging / folder
            if folder_path.is_dir():
                try:
                    for p in folder_path.iterdir():
                        if p.is_file() and p.name.startswith(f"{key}_"):
                            candidates.append(p)
                except OSError:
                    pass
    seen: set[str] = set()
    for c in candidates:
        try:
            key = str(c.resolve()) if c.exists() else str(c)
            if key in seen:
                continue
            seen.add(key)
            if c.is_file():
                return c
        except OSError:
            continue
    return None


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_recovery_zip(zip_path: Path, staging_dir: Path) -> RecoveryPackage:
    if not zip_path.is_file():
        raise RecoveryPackageError("ملف ZIP غير موجود")
    warnings: list[str] = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = validate_zip_members(zf)
        if "manifest.json" not in names:
            raise RecoveryPackageError("manifest.json مفقود")
        for name in names:
            dest = (staging_dir / name).resolve()
            try:
                dest.relative_to(staging_dir.resolve())
            except ValueError as exc:
                raise RecoveryPackageError(f"مسار غير مسموح: {name}") from exc
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(name) as src, dest.open("wb") as out:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)

    try:
        manifest = _load_json(staging_dir / "manifest.json")
    except Exception as exc:
        raise RecoveryPackageError("manifest.json تالف") from exc
    if not isinstance(manifest, dict):
        raise RecoveryPackageError("manifest.json غير صالح")

    pending_path = staging_dir / "data" / "pending_ops.json"
    if not pending_path.is_file():
        raise RecoveryPackageError("data/pending_ops.json مفقود")
    try:
        pending_raw = _load_json(pending_path)
    except Exception as exc:
        raise RecoveryPackageError("data/pending_ops.json تالف") from exc

    cache_raw = None
    cache_path = staging_dir / "data" / "cache_evaluations.json"
    if cache_path.is_file():
        try:
            cache_raw = _load_json(cache_path)
        except Exception as exc:
            raise RecoveryPackageError("data/cache_evaluations.json تالف") from exc

    media_raw = None
    media_path = staging_dir / "data" / "media_manifest.json"
    if media_path.is_file():
        try:
            media_raw = _load_json(media_path)
        except Exception as exc:
            raise RecoveryPackageError("data/media_manifest.json تالف") from exc

    approvals_raw = None
    approvals_path = staging_dir / "data" / "approvals.json"
    if approvals_path.is_file():
        try:
            approvals_raw = _load_json(approvals_path)
        except Exception:
            warnings.append("approvals.json تالف — تم تجاهله")

    if isinstance(pending_raw, dict):
        ops_list = pending_raw.get("operations") or pending_raw.get("pending_ops") or []
    elif isinstance(pending_raw, list):
        ops_list = pending_raw
    else:
        raise RecoveryPackageError("بنية pending_ops غير معروفة")

    pending_ops: list[PendingOpRecord] = []
    for e in ops_list:
        if not isinstance(e, dict):
            warnings.append("سجل pending_ops غير قاموس — تم تجاهله")
            continue
        try:
            pending_ops.append(_map_pending(e))
        except Exception as exc:
            warnings.append(f"فشل تحليل عملية: {exc}")

    cache_evals: list[CacheEvalRecord] = []
    if isinstance(cache_raw, dict):
        entries = cache_raw.get("entries") or cache_raw.get("cache") or []
    elif isinstance(cache_raw, list):
        entries = cache_raw
    else:
        entries = []
    for e in entries:
        if isinstance(e, dict):
            cache_evals.append(_map_cache(e))

    media_list: list[MediaRecord] = []
    if isinstance(media_raw, dict):
        m_entries = media_raw.get("records") or media_raw.get("media") or []
    elif isinstance(media_raw, list):
        m_entries = media_raw
    else:
        m_entries = []
    for e in m_entries:
        if not isinstance(e, dict):
            continue
        m = _map_media(e)
        m.physical_path = _resolve_media_physical(staging_dir, m)
        media_list.append(m)

    approvals: list[dict[str, Any]] = []
    if isinstance(approvals_raw, dict):
        ap = approvals_raw.get("approvals") or []
        if isinstance(ap, list):
            approvals = [dict(x) for x in ap if isinstance(x, dict)]
    elif isinstance(approvals_raw, list):
        approvals = [dict(x) for x in approvals_raw if isinstance(x, dict)]

    return RecoveryPackage(
        manifest=manifest,
        pending_ops=pending_ops,
        cache_evals=cache_evals,
        media=media_list,
        approvals=approvals,
        member_names=list(names),
        staging_dir=staging_dir,
        has_excel=(staging_dir / "Recovery_Report.xlsx").is_file(),
        parse_warnings=warnings,
    )


def parse_created_at(value: str) -> datetime:
    text = (value or "").strip()
    if not text:
        return datetime.min
    cleaned = text.replace("Z", "")
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(cleaned)
    except Exception:
        return datetime.min
