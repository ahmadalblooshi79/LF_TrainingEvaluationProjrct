"""استيراد جدول مجرى الأحداث والمعاضل من ملف Word (.docx)."""

from __future__ import annotations

import re
import zipfile
from io import BytesIO
from xml.etree import ElementTree as ET

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_NS = {"w": _W_NS}
_W = f"{{{_W_NS}}}"

_YELLOW_FILLS = frozenset({"FFFF00", "FFF2CC", "FFF9C4"})
_DILEMMA_FILLS = frozenset({"E5B8B7", "FFC7CE", "F8CBAD", "FFCCCC"})

_HEADER_MARKERS = (
    "الوقت",
    "وصف",
    "المكلف",
    "أسلوب",
    "رد الفعل",
)

# صف حدث/معضلة فقط عند الترقيم: الحدث/1 ، المعضلة/2
_NUMBERED_EVENT_RE = re.compile(r"الحدث\s*/\s*\d+")
_NUMBERED_DILEMMA_RE = re.compile(r"المعضلة\s*/\s*\d+")

_ASSIGNEE_COL_INDEX = 3
_BULLET_SPLIT_RE = re.compile(
    r"[\n\r]+|(?:\s*[\u2022\u2023\u25E6\u00B7\u2013\u2014●○◦▪▫]\s*)|(?:\s+-\s+)"
)
_BULLET_LEAD_RE = re.compile(
    r"^[\-\u2022\u2023\u25E6\u00B7\u2013\u2014●○◦▪▫]+\s*"
)


def _cell_fill(tc: ET.Element) -> str:
    shd = tc.find("w:tcPr/w:shd", _NS)
    if shd is None:
        return ""
    return (shd.get(f"{_W}fill") or "").strip().upper()


def _cell_text(tc: ET.Element) -> str:
    parts = [t.text or "" for t in tc.findall(".//w:t", _NS)]
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def _paragraph_text(p: ET.Element) -> str:
    parts = [t.text or "" for t in p.findall(".//w:t", _NS)]
    txt = re.sub(r"\s+", " ", "".join(parts)).strip()
    return _BULLET_LEAD_RE.sub("", txt).strip()


def _paragraph_texts_in_cell(tc: ET.Element) -> list[str]:
    """كل فقرة (نقطة قائمة) في خلية Word = سطر مستقل."""
    lines: list[str] = []
    for p in tc.findall(".//w:p", _NS):
        txt = _paragraph_text(p)
        if txt:
            lines.append(txt)
    return lines


def _split_inline_bullets(text: str) -> list[str]:
    if not (text or "").strip():
        return []
    parts = [_BULLET_LEAD_RE.sub("", p).strip() for p in _BULLET_SPLIT_RE.split(text)]
    return [p for p in parts if p]


def _cell_assignee_text(tc: ET.Element) -> str:
    para_lines = _paragraph_texts_in_cell(tc)
    if len(para_lines) > 1:
        return "\n".join(para_lines)
    if len(para_lines) == 1:
        bullets = _split_inline_bullets(para_lines[0])
        if len(bullets) > 1:
            return "\n".join(bullets)
        return para_lines[0]
    flat = _cell_text(tc)
    bullets = _split_inline_bullets(flat)
    if len(bullets) > 1:
        return "\n".join(bullets)
    return flat


def _row_cells(tr: ET.Element) -> list[str]:
    out: list[str] = []
    for i, tc in enumerate(tr.findall("w:tc", _NS)):
        if i == _ASSIGNEE_COL_INDEX:
            out.append(_cell_assignee_text(tc))
        else:
            out.append(_cell_text(tc))
    return out


def _row_fills(tr: ET.Element) -> list[str]:
    return [_cell_fill(tc) for tc in tr.findall("w:tc", _NS)]


def _normalize_header_blob(s: str) -> str:
    t = (s or "").replace("\u0640", "").replace(" ", "").replace("ـ", "")
    return t


def _is_table_header_row(texts: list[str]) -> bool:
    joined = _normalize_header_blob(" ".join(texts))
    if not joined:
        return False
    hits = sum(1 for m in _HEADER_MARKERS if m.replace(" ", "") in joined)
    return hits >= 3


def _row_has_fill(fills: list[str], palette: frozenset[str]) -> bool:
    return any(f in palette for f in fills if f)


def _is_yellow_row(fills: list[str]) -> bool:
    return _row_has_fill(fills, _YELLOW_FILLS)


def _is_red_row(fills: list[str]) -> bool:
    return _row_has_fill(fills, _DILEMMA_FILLS)


def _is_white_row(fills: list[str]) -> bool:
    """صف بيانات (أبيض): ليس أصفراً وليس أحمر معضلة."""
    return not _is_yellow_row(fills) and not _is_red_row(fills)


def _has_numbered_event(text: str) -> bool:
    return bool(_NUMBERED_EVENT_RE.search(text or ""))


def _has_numbered_dilemma(text: str) -> bool:
    return bool(_NUMBERED_DILEMMA_RE.search(text or ""))


def _is_numbered_event_row(fills: list[str], texts: list[str]) -> bool:
    return _is_yellow_row(fills) and _has_numbered_event(_merged_row_text(texts))


def _is_numbered_dilemma_row(fills: list[str], texts: list[str]) -> bool:
    return _is_red_row(fills) and _has_numbered_dilemma(_merged_row_text(texts))


def _merged_row_text(texts: list[str]) -> str:
    parts = [t for t in texts if (t or "").strip()]
    return " ".join(parts).strip()


def _pad_cells(texts: list[str], n: int = 6) -> list[str]:
    cells = list(texts)
    while len(cells) < n:
        cells.append("")
    return cells[:n]


def _map_data_row(texts: list[str]) -> dict | None:
    cells = _pad_cells(texts, 6)
    if not any((c or "").strip() for c in cells):
        return None
    return {
        "kind": "row",
        "time": cells[1] or "",
        "description": cells[2] or "",
        "assignee": cells[3] or "",
        "method": cells[4] or "",
        "reaction": cells[5] or "",
    }


def _paragraphs_before_table(body: ET.Element) -> list[str]:
    out: list[str] = []
    for el in body:
        tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        if tag == "tbl":
            break
        if tag != "p":
            continue
        parts = [t.text or "" for t in el.findall(".//w:t", _NS)]
        txt = re.sub(r"\s+", " ", "".join(parts)).strip()
        if txt:
            out.append(txt)
    return out


def parse_planner_flow_docx_bytes(data: bytes) -> dict:
    """
    يُرجع: { ok: bool, note: str, rows: list[dict], warnings: list[str], error?: str }
    """
    if not data:
        return {"ok": False, "error": "empty_file", "note": "", "rows": [], "warnings": []}
    try:
        with zipfile.ZipFile(BytesIO(data)) as zf:
            if not any(n.startswith("word/") for n in zf.namelist()):
                return {
                    "ok": False,
                    "error": "not_docx",
                    "note": "",
                    "rows": [],
                    "warnings": [],
                }
            root = ET.fromstring(zf.read("word/document.xml"))
    except (zipfile.BadZipFile, KeyError, ET.ParseError, OSError):
        return {"ok": False, "error": "invalid_docx", "note": "", "rows": [], "warnings": []}

    body = root.find(".//w:body", _NS)
    if body is None:
        return {"ok": False, "error": "no_body", "note": "", "rows": [], "warnings": []}

    note_parts = _paragraphs_before_table(body)
    note = "\n".join(note_parts).strip()[:4000]

    tbl = body.find("w:tbl", _NS)
    if tbl is None:
        return {
            "ok": False,
            "error": "no_table",
            "note": note,
            "rows": [],
            "warnings": [],
        }

    rows_out: list[dict] = []
    warnings: list[str] = []
    skipped_headers = 0

    for tr in tbl.findall("w:tr", _NS):
        texts = _row_cells(tr)
        fills = _row_fills(tr)

        if _is_table_header_row(texts):
            skipped_headers += 1
            continue

        # الصفوف البيضاء تبقى صفوف بيانات حتى لو وردت فيها «حدث» أو «معضلة».
        if _is_white_row(fills):
            item = _map_data_row(texts)
            if item is not None:
                rows_out.append(item)
            continue

        if _is_numbered_event_row(fills, texts):
            text = _merged_row_text(texts)
            if text:
                rows_out.append({"kind": "event", "text": text})
            continue

        if _is_numbered_dilemma_row(fills, texts):
            text = _merged_row_text(texts)
            if text:
                rows_out.append({"kind": "dilemma", "text": text})
            continue

        item = _map_data_row(texts)
        if item is not None:
            rows_out.append(item)

    rows_out = _normalize_import_rows(rows_out)

    if skipped_headers > 1:
        warnings.append(f"تم تجاهل {skipped_headers} صف/صفوف عناوين متكررة.")

    if not rows_out and not note:
        return {
            "ok": False,
            "error": "empty_content",
            "note": "",
            "rows": [],
            "warnings": warnings,
        }

    return {
        "ok": True,
        "note": note,
        "rows": rows_out,
        "warnings": warnings,
    }


def _normalize_import_rows(raw_rows: list) -> list[dict]:
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
                    "assignee": str(item.get("assignee") or "")[:4000],
                    "method": str(item.get("method") or "")[:500],
                    "reaction": str(item.get("reaction") or "")[:500],
                }
            )
    return out
