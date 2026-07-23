"""مساعدات JSON متوافقة مع SQLite (تخزين كنص)."""

from __future__ import annotations

import json
from typing import Any


def dumps_json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, default=str)


def loads_json(raw: str | None, default: Any = None) -> Any:
    if raw is None or raw == "":
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def extract_json_object(text: str) -> dict[str, Any] | None:
    """استخراج أول كائن JSON من نص قد يحتوي على Markdown أو ضوضاء."""
    if not text:
        return None
    s = text.strip()
    # إزالة سياج markdown الشائع
    if s.startswith("```"):
        lines = s.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        s = "\n".join(lines).strip()
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    start = s.find("{")
    end = s.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(s[start : end + 1])
            if isinstance(obj, dict):
                return obj
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
    return None
