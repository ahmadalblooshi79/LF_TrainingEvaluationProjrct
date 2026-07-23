"""استخراج نقاط القوة والضعف من الأقسام والجداول."""

from __future__ import annotations

import re
from typing import Any

from app.ai_report_library.constants import CONFIDENCE_NEEDS_REVIEW

_SPLIT_RE = re.compile(r"(?:^|\n)\s*(?:\d+[\.\-\)]\s+|[\-\*•]\s+)")


def split_finding_lines(text: str) -> list[str]:
    if not (text or "").strip():
        return []
    parts = _SPLIT_RE.split(text.strip())
    out = []
    for p in parts:
        s = re.sub(r"\s+", " ", (p or "").strip(" \n\t-•*"))
        if len(s) >= 8:
            out.append(s)
    if not out and text.strip():
        # فقرات مفصولة بأسطر فارغة
        for para in re.split(r"\n\s*\n", text.strip()):
            s = re.sub(r"\s+", " ", para.strip())
            if len(s) >= 8:
                out.append(s)
    if not out and text.strip():
        out.append(text.strip())
    return out


def extract_findings(
    sections: list[dict[str, Any]],
    tables: list[dict[str, Any]],
    units: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    order = 0
    current_unit_name: str | None = None
    unit_by_norm = {u["normalized_unit_name"]: u for u in units}

    # تتبع وحدة من عناوين الأقسام
    for sec in sections:
        title = sec.get("original_title") or ""
        stype = sec.get("normalized_section_type") or "unknown"
        # هل العنوان وحدة؟
        for u in units:
            if u["original_unit_name"] in title or u["normalized_unit_name"] in title:
                current_unit_name = u["normalized_unit_name"]
                break
        if stype not in ("strengths", "weaknesses", "observations", "lessons_learned", "recommendations"):
            continue
        ftype = {
            "strengths": "strength",
            "weaknesses": "weakness",
            "observations": "observation",
            "lessons_learned": "lesson",
            "recommendations": "recommendation",
        }.get(stype, "unknown")
        for line in split_finding_lines(sec.get("cleaned_text") or sec.get("original_text") or ""):
            scope, linked = _infer_scope(line, current_unit_name, units)
            conf = 0.8 if linked else 0.55
            findings.append(
                {
                    "finding_type": ftype,
                    "original_text": line,
                    "cleaned_text": line,
                    "order_number": order,
                    "scope_type": scope,
                    "confidence_score": conf,
                    "review_status": "needs_review" if conf < CONFIDENCE_NEEDS_REVIEW else "auto_detected",
                    "detected_by": "rules",
                    "unit_names": linked,
                    "section_title": title,
                }
            )
            order += 1

    # جداول: وحدة | قوة | ضعف
    for tbl in tables:
        headers = [h.strip() for h in (tbl.get("headers") or [])]
        h_low = [h.lower() for h in headers]
        unit_col = _col_index(h_low, ("وحدة", "التشكيل", "الوحدة"))
        str_col = _col_index(h_low, ("قوة", "إيجاب"))
        weak_col = _col_index(h_low, ("ضعف", "قصور", "سلب"))
        if unit_col is None and str_col is None and weak_col is None:
            continue
        for row in tbl.get("rows") or []:
            unit_name = row[unit_col].strip() if unit_col is not None and unit_col < len(row) else ""
            if unit_name:
                current_unit_name = unit_name
            if str_col is not None and str_col < len(row):
                for line in split_finding_lines(row[str_col]):
                    findings.append(_from_cell(line, "strength", unit_name or current_unit_name, units, order))
                    order += 1
            if weak_col is not None and weak_col < len(row):
                for line in split_finding_lines(row[weak_col]):
                    findings.append(_from_cell(line, "weakness", unit_name or current_unit_name, units, order))
                    order += 1
    return findings


def _col_index(headers: list[str], keys: tuple[str, ...]) -> int | None:
    for i, h in enumerate(headers):
        for k in keys:
            if k in h:
                return i
    return None


def _infer_scope(text: str, current_unit: str | None, units: list[dict[str, Any]]) -> tuple[str, list[str]]:
    linked: list[str] = []
    for u in units:
        for name in (u["original_unit_name"], u["normalized_unit_name"]):
            if name and name in text:
                if u["normalized_unit_name"] not in linked:
                    linked.append(u["normalized_unit_name"])
    if "اللواء" in text and ("وحداته" in text or "على مستوى اللواء" in text or "التنسيق بين" in text):
        return "brigade", ["اللواء"] if any(u["normalized_unit_name"] == "اللواء" for u in units) else linked
    if len(linked) >= 2:
        return "multiple_units", linked
    if len(linked) == 1:
        return "single_unit", linked
    if current_unit:
        return "single_unit", [current_unit]
    return "unknown", []


def _from_cell(line: str, ftype: str, unit_name: str | None, units: list, order: int) -> dict:
    scope, linked = _infer_scope(line, unit_name, units)
    if not linked and unit_name:
        linked = [unit_name]
        scope = "single_unit"
    conf = 0.85 if linked else 0.6
    return {
        "finding_type": ftype,
        "original_text": line,
        "cleaned_text": line,
        "order_number": order,
        "scope_type": scope,
        "confidence_score": conf,
        "review_status": "needs_review" if conf < CONFIDENCE_NEEDS_REVIEW else "auto_detected",
        "detected_by": "table",
        "unit_names": linked,
        "section_title": "",
    }
