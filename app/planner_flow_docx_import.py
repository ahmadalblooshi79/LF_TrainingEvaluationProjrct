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
_DILEMMA_FILLS = frozenset({"E5B8B7", "FFC7CE", "F8CBAD", "FFCCCC", "D99594", "C0504D"})

_HEADER_MARKERS = (
    "الوقت",
    "التوقيت",
    "وصف",
    "المكلف",
    "أسلوب",
    "رد الفعل",
    "الحقيقي",
    "كورا",
    "ملاحظات",
    "أنظمة",
    "التبليغ",
)

# صف حدث/معضلة فقط عند الترقيم: الحدث/1 ، المعضلة/2 أو معضلة/2
_NUMBERED_EVENT_RE = re.compile(r"الحدث\s*/\s*\d+")
_NUMBERED_DILEMMA_RE = re.compile(r"(?:ال)?معضلة\s*/\s*\d+")

# احتياطي لقالب الجاهزية ذي 6 أعمدة إن لم يُعثر على عنوان «المكلف»
_LEGACY_ASSIGNEE_COL_INDEX = 3
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


def _local_tag(el: ET.Element) -> str:
    tag = el.tag or ""
    return tag.split("}")[-1] if "}" in tag else tag


def _cell_text(tc: ET.Element) -> str:
    return _literal_cell_text(tc).replace("\n", " ")


def _paragraph_literal(p: ET.Element) -> str:
    """نص الفقرة كما في الملف — بدون دمج المسافات أو حذف الشرطات."""
    parts: list[str] = []
    for el in p.iter():
        tag = _local_tag(el)
        if tag == "t":
            parts.append(el.text or "")
        elif tag == "tab":
            parts.append("\t")
        elif tag in ("br", "cr"):
            parts.append("\n")
    return "".join(parts).replace("\u00a0", " ").strip()


def _literal_cell_text(tc: ET.Element) -> str:
    """محتوى الخلية حرفياً: كل فقرة سطر، بما في ذلك «سعت» وأي نص توقيت."""
    lines: list[str] = []
    for p in tc.findall("w:p", _NS):
        txt = _paragraph_literal(p)
        if txt:
            lines.append(txt)
    if lines:
        return "\n".join(lines)
    for p in tc.findall(".//w:p", _NS):
        txt = _paragraph_literal(p)
        if txt:
            lines.append(txt)
    return "\n".join(lines)


def _paragraph_text(p: ET.Element) -> str:
    txt = _paragraph_literal(p)
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


def _tc_grid_span(tc: ET.Element) -> int:
    gs = tc.find("w:tcPr/w:gridSpan", _NS)
    if gs is None:
        return 1
    try:
        return max(1, int(gs.get(f"{_W}val") or "1"))
    except ValueError:
        return 1


def _tc_vmerge_continue(tc: ET.Element) -> bool:
    vm = tc.find("w:tcPr/w:vMerge", _NS)
    if vm is None:
        return False
    val = (vm.get(f"{_W}val") or "").strip().lower()
    return val in ("", "continue")


def _tbl_grid_col_count(tbl: ET.Element) -> int:
    grid = tbl.find("w:tblGrid", _NS)
    if grid is None:
        return 0
    return len(grid.findall("w:gridCol", _NS))


def _logical_rows_from_tbl(tbl: ET.Element) -> list[tuple[list[str], list[str]]]:
    """يفك الدمج الأفقي/العمودي لتصبح كل صف بنفس عدد أعمدة الشبكة."""
    ncols = _tbl_grid_col_count(tbl)
    carry_text: list[str] = []
    carry_fill: list[str] = []
    rows: list[tuple[list[str], list[str]]] = []
    for tr in tbl.findall("w:tr", _NS):
        occupied = 0
        pieces: list[tuple[int, str, str, bool]] = []
        for tc in tr.findall("w:tc", _NS):
            span = _tc_grid_span(tc)
            pieces.append(
                (span, _literal_cell_text(tc), _cell_fill(tc), _tc_vmerge_continue(tc))
            )
            occupied += span
        width = max(ncols, occupied, 1)
        texts = [""] * width
        fills = [""] * width
        col = 0
        for span, txt, fl, is_cont in pieces:
            for k in range(span):
                i = col + k
                if i >= width:
                    texts.extend([""] * (i - width + 1))
                    fills.extend([""] * (i - width + 1))
                    width = i + 1
                if is_cont and i < len(carry_text) and not (txt or "").strip():
                    texts[i] = carry_text[i]
                    fills[i] = fl or (carry_fill[i] if i < len(carry_fill) else "")
                else:
                    texts[i] = txt
                    fills[i] = fl
            col += span
        if ncols < width:
            ncols = width
        carry_text = texts[:]
        carry_fill = fills[:]
        rows.append((texts, fills))
    return rows


def _row_cells(tr: ET.Element) -> list[str]:
    """كل الخلايا مع الحفاظ على أسطر القائمة — عمود المكلف يُحدَّد لاحقاً بالعنوان لا بالفهرس."""
    return [_literal_cell_text(tc) for tc in tr.findall("w:tc", _NS)]


def _row_fills(tr: ET.Element) -> list[str]:
    return [_cell_fill(tc) for tc in tr.findall("w:tc", _NS)]


def _normalize_header_blob(s: str) -> str:
    t = (s or "").replace("\u0640", "").replace(" ", "").replace("ـ", "")
    return t


def _is_table_header_row(texts: list[str]) -> bool:
    joined = _normalize_header_blob(" ".join(texts))
    if not joined:
        return False
    if _has_numbered_event(joined) or _has_numbered_dilemma(joined):
        return False
    hits = sum(1 for m in _HEADER_MARKERS if m.replace(" ", "") in joined)
    return hits >= 2


def _cell_header_key(s: str) -> str:
    return _normalize_header_blob(s or "")


def _col_map_from_header_row(texts: list[str]) -> dict[str, int]:
    """يربط اسم الحقل بفهرس العمود من صف العناوين — المكلف بالاسم لا بالترتيب."""
    mapping: dict[str, int] = {}
    for i, raw in enumerate(texts):
        key = _cell_header_key(raw)
        if not key:
            continue
        if "المكلف" in key:
            mapping["assignee"] = i
        elif "وصف" in key:
            mapping["description"] = i
        elif "أسلوب" in key:
            mapping["method"] = i
        elif "ردالفعل" in key or "ردالفعلالمتوقع" in key:
            mapping["reaction"] = i
        elif "ملاحظات" in key:
            mapping["notes"] = i
        elif "توقيت" in key and "كورا" in key:
            mapping["time_kora"] = i
        elif "أنظمة" in key or "التبليغ" in key:
            mapping["report_systems"] = i
        elif key in ("إلى", "الى"):
            mapping["time_to"] = i
        elif key == "من":
            mapping["time_from"] = i
        elif "التوقيتالحقيقي" in key or ("توقيت" in key and "الحقيقي" in key):
            mapping["time"] = i
        elif "الوقت" in key:
            mapping.setdefault("time", i)
        elif "كورا" in key:
            mapping.setdefault("time_kora", i)
        elif "الحقيقي" in key:
            mapping.setdefault("time", i)
    return mapping


def _cell_at(texts: list[str], index: int | None) -> str:
    if index is None or index < 0 or index >= len(texts):
        return ""
    return texts[index] or ""


def _map_data_row(texts: list[str], col_map: dict[str, int] | None = None) -> dict | None:
    if not any((c or "").strip() for c in texts):
        return None
    cmap = dict(col_map or {})
    if cmap:
        assignee_i = cmap.get("assignee")
        if assignee_i is None:
            assignee_i = _LEGACY_ASSIGNEE_COL_INDEX
        return {
            "kind": "row",
            "time": _cell_at(texts, cmap.get("time")),
            "time_kora": _cell_at(texts, cmap.get("time_kora")),
            "time_from": _cell_at(texts, cmap.get("time_from")),
            "time_to": _cell_at(texts, cmap.get("time_to")),
            "report_systems": _cell_at(texts, cmap.get("report_systems")),
            "report_real": _cell_at(texts, cmap.get("report_real")),
            "report_kora": _cell_at(texts, cmap.get("report_kora")),
            "description": _cell_at(texts, cmap.get("description")),
            "assignee": _cell_at(texts, assignee_i),
            "method": _cell_at(texts, cmap.get("method")),
            "reaction": _cell_at(texts, cmap.get("reaction")),
            "notes": _cell_at(texts, cmap.get("notes")),
        }
    return {
        "kind": "row",
        "time": _cell_at(texts, 1 if len(texts) > 1 else None),
        "time_kora": "",
        "time_from": "",
        "time_to": "",
        "report_systems": "",
        "description": _cell_at(texts, 2 if len(texts) > 2 else None),
        "assignee": _cell_at(texts, _LEGACY_ASSIGNEE_COL_INDEX),
        "method": _cell_at(texts, 4 if len(texts) > 4 else None),
        "reaction": _cell_at(texts, 5 if len(texts) > 5 else None),
        "notes": "",
    }


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
    parts: list[str] = []
    seen: set[str] = set()
    for t in texts:
        s = (t or "").strip()
        if s and s not in seen:
            seen.add(s)
            parts.append(s)
    return " ".join(parts).strip()


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
    col_map: dict[str, int] = {}

    for texts, fills in _logical_rows_from_tbl(tbl):
        if _is_table_header_row(texts):
            skipped_headers += 1
            row_map = _col_map_from_header_row(texts)
            if "assignee" not in row_map and col_map:
                for key in (
                    "report_real",
                    "report_kora",
                    "report_systems",
                    "time_from",
                    "time_to",
                    "time_kora",
                    "time",
                ):
                    if key in row_map:
                        col_map[key] = row_map[key]
            else:
                col_map.update(row_map)
            continue

        # الصفوف البيضاء تبقى صفوف بيانات حتى لو وردت فيها «حدث» أو «معضلة».
        if _is_white_row(fills):
            item = _map_data_row(texts, col_map)
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

        item = _map_data_row(texts, col_map)
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
                    "time_kora": str(item.get("time_kora") or "")[:500],
                    "time_from": str(item.get("time_from") or "")[:500],
                    "time_to": str(item.get("time_to") or "")[:500],
                    "report_systems": str(
                        item.get("report_systems")
                        or item.get("report_real")
                        or item.get("report_kora")
                        or ""
                    )[:500],
                    "description": str(item.get("description") or "")[:4000],
                    "assignee": str(item.get("assignee") or "")[:4000],
                    "method": str(item.get("method") or "")[:500],
                    "reaction": str(item.get("reaction") or "")[:500],
                    "notes": str(item.get("notes") or "")[:2000],
                }
            )
    return out
