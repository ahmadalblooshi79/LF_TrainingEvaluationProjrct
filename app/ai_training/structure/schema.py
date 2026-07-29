"""JSON Schema validation لنتائج Structure Agent."""

from __future__ import annotations

import json
import re
from typing import Any

from app.ai_training.structure_constants import DETECTED_ROLES, NUMBERING_STYLES

STRUCTURE_ITEM_REQUIRED = (
    "block_id",
    "detected_role",
    "confidence",
    "evidence",
)


def _extract_json_object(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    # strip markdown fences
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    # find first { ... }
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(raw[start : end + 1])
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            return None
    return None


def validate_structure_chunk_payload(payload: dict[str, Any] | None) -> tuple[bool, list[str], dict[str, Any]]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return False, ["payload_not_object"], {}
    structures = payload.get("structures")
    if not isinstance(structures, list):
        return False, ["structures_not_list"], payload
    cleaned: list[dict[str, Any]] = []
    for i, item in enumerate(structures):
        if not isinstance(item, dict):
            errors.append(f"item_{i}_not_object")
            continue
        for req in STRUCTURE_ITEM_REQUIRED:
            if req not in item:
                errors.append(f"item_{i}_missing_{req}")
        role = item.get("detected_role") or "unknown"
        if role not in DETECTED_ROLES:
            errors.append(f"item_{i}_invalid_role")
            item = dict(item)
            item["detected_role"] = "unknown"
        style = item.get("numbering_style") or "none"
        if style not in NUMBERING_STYLES:
            item = dict(item)
            item["numbering_style"] = "other"
        try:
            conf = float(item.get("confidence"))
        except (TypeError, ValueError):
            errors.append(f"item_{i}_bad_confidence")
            conf = 0.0
            item = dict(item)
            item["confidence"] = conf
        evidence = item.get("evidence")
        if evidence is None:
            item = dict(item)
            item["evidence"] = []
        elif not isinstance(evidence, list):
            errors.append(f"item_{i}_evidence_not_list")
            item = dict(item)
            item["evidence"] = [str(evidence)]
        cleaned.append(item)
    out = {
        "chunk_id": payload.get("chunk_id") or "",
        "structures": cleaned,
        "chunk_warnings": list(payload.get("chunk_warnings") or [])
        if isinstance(payload.get("chunk_warnings"), list)
        else [],
    }
    # soft-fail: accept if at least some structures valid
    ok = len(cleaned) > 0 and not any(e.endswith("_not_object") or e == "structures_not_list" for e in errors)
    return ok, errors, out


def parse_and_validate_llm_response(text: str) -> tuple[bool, list[str], dict[str, Any]]:
    data = _extract_json_object(text)
    if data is None:
        return False, ["invalid_json"], {}
    return validate_structure_chunk_payload(data)
