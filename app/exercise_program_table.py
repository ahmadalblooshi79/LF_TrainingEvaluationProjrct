"""استخراج وعرض جدول برنامج التمرين من شريحة PowerPoint."""

from __future__ import annotations

import html
import json
import re
from typing import Any

_DATE_RE = re.compile(r"^\s*(\d{1,2}/\d{1,2})\s*$")
_DATE_PREFIX_RE = re.compile(r"^(\d{1,2}/\d{1,2})(?:\s+|$)")
_AR_DAYS = (
    "الاثنين",
    "الإثنين",
    "الثلاثاء",
    "الأربعاء",
    "الخميس",
    "الجمعة",
    "السبت",
    "الأحد",
)


def _normalize_day(s: str) -> str:
    s = (s or "").strip()
    for ch in ("أ", "إ", "آ"):
        s = s.replace(ch, "ا")
    return s.replace("ى", "ي")


def _cell_fill_rgb(cell) -> tuple[int, int, int] | None:
    try:
        fill = cell.fill
        if fill.type is None:
            return None
        fc = fill.fore_color
        if fc.type is None:
            return None
        rgb = fc.rgb
        if rgb is None:
            return None
        return (int(rgb[0]), int(rgb[1]), int(rgb[2]))
    except Exception:
        return None


def _classify_week_band(rgb: tuple[int, int, int] | None) -> str:
    if rgb is None:
        return ""
    r, g, b = rgb
    if b >= 170 and b > r + 25 and b > g + 10:
        return "blue"
    if max(r, g, b) - min(r, g, b) < 35 and 150 <= (r + g + b) / 3 <= 230:
        return "grey"
    if r >= 210 and g >= 200 and b >= 170:
        return "beige"
    if r >= 180 and g >= 170 and b >= 140:
        return "beige"
    return ""


def _run_is_red(run) -> bool:
    try:
        color = run.font.color
        if color is None or color.type is None:
            return False
        rgb = color.rgb
        if rgb is None:
            return False
        r, g, b = int(rgb[0]), int(rgb[1]), int(rgb[2])
        return r >= 140 and g <= 110 and b <= 110 and r > g + 30
    except Exception:
        return False


def _cell_text_parts(cell) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    try:
        tf = cell.text_frame
    except Exception:
        text = (getattr(cell, "text", None) or "").strip()
        if text:
            parts.append({"text": text, "red": False})
        return parts
    for para in tf.paragraphs:
        runs = list(para.runs)
        if runs:
            for run in runs:
                t = (run.text or "").strip()
                if not t:
                    continue
                parts.append({"text": t, "red": _run_is_red(run)})
        else:
            t = (para.text or "").strip()
            if t:
                parts.append({"text": t, "red": False})
    if not parts:
        t = (cell.text or "").strip()
        if t:
            parts.append({"text": t, "red": False})
    return parts


def _cell_colspan(cell) -> int:
    try:
        span = cell._tc.gridSpan  # noqa: SLF001
        if not span:
            return 1
        return int(span)
    except Exception:
        return 1


def _cell_rowspan(table, row_idx: int, col_idx: int) -> int:
    try:
        cell = table.cell(row_idx, col_idx)
        if cell.is_spanned:
            return 0
        v_merge = cell._tc.vMerge  # noqa: SLF001
        if not v_merge:
            return 1
        if str(v_merge) != "restart":
            return 0
        count = 1
        for ri in range(row_idx + 1, len(table.rows)):
            below = table.cell(ri, col_idx)
            if str(below._tc.vMerge) == "continue":  # noqa: SLF001
                count += 1
            else:
                break
        return count
    except Exception:
        return 1


def _split_date_and_parts(parts: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    if not parts:
        return "", []
    first = parts[0]["text"].strip()
    m = _DATE_RE.match(first)
    if m:
        return m.group(1), parts[1:]
    m2 = _DATE_PREFIX_RE.match(first)
    if m2:
        date_label = m2.group(1)
        rest = first[m2.end() :].strip()
        out = list(parts[1:])
        if rest:
            out.insert(0, {"text": rest, "red": bool(parts[0].get("red"))})
        return date_label, out
    return "", parts


def _append_parts_unique(target: list[dict[str, Any]], extra: list[dict[str, Any]]) -> None:
    seen = {p.get("text", "").strip() for p in target}
    for part in extra:
        text = (part.get("text") or "").strip()
        if not text or text in seen:
            continue
        target.append({"text": text, "red": bool(part.get("red"))})
        seen.add(text)


def _shape_text_parts(shape) -> list[dict[str, Any]]:
    if not getattr(shape, "has_text_frame", False):
        return []
    parts: list[dict[str, Any]] = []
    for para in shape.text_frame.paragraphs:
        runs = list(para.runs)
        if runs:
            for run in runs:
                t = (run.text or "").strip()
                if not t:
                    continue
                parts.append({"text": t, "red": _run_is_red(run)})
        else:
            t = (para.text or "").strip()
            if t:
                parts.append({"text": t, "red": False})
    if not parts:
        t = (shape.text or "").strip()
        if t:
            parts.append({"text": t, "red": False})
    return parts


def _iter_slide_text_shapes(shapes, *, skip: set[int] | None = None):
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    skip = skip or set()
    for shape in shapes:
        sid = id(shape)
        if sid in skip:
            continue
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from _iter_slide_text_shapes(shape.shapes, skip=skip)
            continue
        if getattr(shape, "has_table", False):
            continue
        if not getattr(shape, "has_text_frame", False):
            continue
        parts = _shape_text_parts(shape)
        if parts:
            yield shape, parts


def _table_cell_rects(table_shape) -> list[dict[str, Any]]:
    table = table_shape.table
    left = int(table_shape.left)
    top = int(table_shape.top)
    rects: list[dict[str, Any]] = []
    y = top
    for ri in range(len(table.rows)):
        x = left
        row_h = int(table.rows[ri].height)
        for ci in range(len(table.columns)):
            col_w = int(table.columns[ci].width)
            rects.append(
                {
                    "ri": ri,
                    "ci": ci,
                    "x1": x,
                    "y1": y,
                    "x2": x + col_w,
                    "y2": y + row_h,
                }
            )
            x += col_w
        y += row_h
    return rects


def _shape_center(shape) -> tuple[int, int]:
    return (
        int(shape.left + shape.width // 2),
        int(shape.top + shape.height // 2),
    )


def _hit_cell(rects: list[dict[str, Any]], px: int, py: int) -> dict[str, Any] | None:
    for rect in rects:
        if rect["x1"] <= px <= rect["x2"] and rect["y1"] <= py <= rect["y2"]:
            return rect
    return None


def _row_midpoints(rects: list[dict[str, Any]], nrows: int) -> list[int]:
    mids: list[int] = []
    for ri in range(nrows):
        row_rects = [r for r in rects if r["ri"] == ri]
        if not row_rects:
            mids.append(0)
            continue
        y1 = min(r["y1"] for r in row_rects)
        y2 = max(r["y2"] for r in row_rects)
        mids.append((y1 + y2) // 2)
    return mids


def _apply_overlay_shapes(
    slide,
    table_shape,
    data: dict[str, Any],
    *,
    header_rows: int,
) -> None:
    table = table_shape.table
    ncols = len(table.columns)
    rects = _table_cell_rects(table_shape)
    row_mids = _row_midpoints(rects, len(table.rows))
    rows: list[dict[str, Any]] = list(data.get("rows") or [])
    if not rows:
        return

    # خريطة (ri_body, ci) -> خلية في هيكل JSON (ri_body بدون صف العناوين)
    cell_map: dict[tuple[int, int], dict[str, Any]] = {}
    for body_ri, row in enumerate(rows):
        table_ri = body_ri + header_rows
        ci_cursor = 0
        for cell in row.get("cells") or []:
            while (table_ri, ci_cursor) in cell_map:
                ci_cursor += 1
            if ci_cursor >= ncols:
                break
            colspan = int(cell.get("colspan") or 1)
            for dc in range(colspan):
                cell_map[(table_ri, ci_cursor + dc)] = cell
            ci_cursor += colspan

    skip_ids = {id(table_shape)}
    try:
        if slide.shapes.title is not None:
            skip_ids.add(id(slide.shapes.title))
    except Exception:
        pass

    extra_bars: list[tuple[int, dict[str, Any]]] = []

    for shape, parts in _iter_slide_text_shapes(slide.shapes, skip=skip_ids):
        plain = _parts_to_plain(parts)
        if not plain:
            continue
        if _normalize_day(plain.split("\n", 1)[0]) and any(
            _normalize_day(plain.split("\n", 1)[0]) == _normalize_day(d) for d in _AR_DAYS
        ):
            continue
        if _normalize_day(plain) in {_normalize_day("برنامج التمرين"), _normalize_day("البرنامج")}:
            continue

        cx, cy = _shape_center(shape)
        wide = int(shape.width) >= int(table_shape.width * 0.55)
        hit = _hit_cell(rects, cx, cy)

        if wide:
            table_ri = 0
            for ri, mid in enumerate(row_mids):
                if cy >= mid:
                    table_ri = ri
            body_ri = table_ri - header_rows
            bar_cell = {
                "colspan": ncols,
                "rowspan": 1,
                "date": "",
                "parts": parts,
                "is_bar": True,
            }
            if body_ri < 0:
                extra_bars.append((0, bar_cell))
            elif body_ri < len(rows):
                row_cells = list(rows[body_ri].get("cells") or [])
                bar_idx = next(
                    (i for i, c in enumerate(row_cells) if c.get("is_bar")),
                    None,
                )
                if bar_idx is None:
                    row_cells.insert(0, bar_cell)
                else:
                    _append_parts_unique(row_cells[bar_idx].setdefault("parts", []), parts)
                rows[body_ri]["cells"] = row_cells
            else:
                extra_bars.append((len(rows), bar_cell))
            continue

        if not hit:
            continue

        table_ri = int(hit["ri"])
        ci = int(hit["ci"])
        body_ri = table_ri - header_rows
        if body_ri < 0:
            continue

        date_label, content_parts = _split_date_and_parts(parts)
        if _DATE_RE.match(plain):
            date_label = plain

        target = cell_map.get((table_ri, ci))
        if target is None and body_ri < len(rows):
            row_cells = rows[body_ri].get("cells") or []
            ci_pos = 0
            for cell in row_cells:
                if ci_pos <= ci < ci_pos + int(cell.get("colspan") or 1):
                    target = cell
                    break
                ci_pos += int(cell.get("colspan") or 1)

        if target is None:
            continue

        if date_label and not (target.get("date") or "").strip():
            target["date"] = date_label
        if content_parts:
            _append_parts_unique(target.setdefault("parts", []), content_parts)
        elif not date_label:
            _append_parts_unique(target.setdefault("parts", []), parts)

        if int(target.get("colspan") or 1) >= ncols and _parts_to_plain(target.get("parts") or []):
            target["is_bar"] = True

    for insert_at, bar_cell in sorted(extra_bars, key=lambda x: x[0]):
        insert_at = max(0, min(insert_at, len(rows)))
        rows.insert(insert_at, {"week_band": "", "cells": [bar_cell]})

    data["rows"] = rows


def _parts_to_plain(parts: list[dict[str, Any]]) -> str:
    return " ".join(p["text"] for p in parts if p.get("text")).strip()


def _extract_table_dict(slide, table_shape) -> dict[str, Any] | None:
    if not getattr(table_shape, "has_table", False):
        return None
    table = table_shape.table
    nrows = len(table.rows)
    ncols = len(table.columns)
    if nrows < 2 or ncols < 2:
        return None

    occupied = [[False] * ncols for _ in range(nrows)]
    header: list[str] = []
    body_rows: list[dict[str, Any]] = []

    for ri in range(nrows):
        row_cells: list[dict[str, Any]] = []
        row_band = ""
        for ci in range(ncols):
            if occupied[ri][ci]:
                continue
            cell = table.cell(ri, ci)
            if cell.is_spanned:
                continue
            rowspan = _cell_rowspan(table, ri, ci)
            colspan = _cell_colspan(cell)
            for dr in range(rowspan):
                for dc in range(colspan):
                    if ri + dr < nrows and ci + dc < ncols:
                        occupied[ri + dr][ci + dc] = True

            parts = _cell_text_parts(cell)
            date_label, content_parts = _split_date_and_parts(parts)
            plain = _parts_to_plain(content_parts if date_label else parts)
            fill_rgb = _cell_fill_rgb(cell)
            band = _classify_week_band(fill_rgb)
            if band and not row_band:
                row_band = band

            is_bar = colspan >= ncols and plain != ""
            cell_data: dict[str, Any] = {
                "colspan": colspan,
                "rowspan": rowspan,
                "date": date_label,
                "parts": content_parts if date_label else parts,
                "is_bar": is_bar,
            }
            row_cells.append(cell_data)

            if ri == 0 and plain and not header:
                norm = _normalize_day(plain)
                if any(_normalize_day(d) == norm for d in _AR_DAYS):
                    header = [(table.cell(0, c).text or "").strip() for c in range(ncols)]

        if ri == 0 and not header:
            texts = [(table.cell(0, c).text or "").strip() for c in range(ncols)]
            if sum(1 for t in texts if any(_normalize_day(t) == _normalize_day(d) for d in _AR_DAYS)) >= 4:
                header = texts

        if ri == 0 and header:
            continue
        if row_cells:
            body_rows.append({"week_band": row_band, "cells": row_cells})

    if not body_rows:
        return None
    header_rows = 1 if header else 0
    data = {"version": 1, "title": "برنامج التمرين", "header": header, "rows": body_rows}
    _apply_overlay_shapes(slide, table_shape, data, header_rows=header_rows)
    return data


def _largest_table_on_slide(slide) -> dict[str, Any] | None:
    best_shape = None
    best_score = 0
    for shape in slide.shapes:
        if not getattr(shape, "has_table", False):
            continue
        tbl = shape.table
        score = len(tbl.rows) * len(tbl.columns)
        if score > best_score:
            best_shape = shape
            best_score = score
    if not best_shape:
        return None
    return _extract_table_dict(slide, best_shape)


def extract_program_table_from_slide(slide) -> dict[str, Any] | None:
    return _largest_table_on_slide(slide)


def dumps_program_table(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False)


def loads_program_table(raw: str) -> dict[str, Any] | None:
    s = (raw or "").strip()
    if not s:
        return None
    try:
        data = json.loads(s)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("rows"):
        return None
    return data


def _render_parts_html(parts: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for part in parts:
        text = html.escape((part.get("text") or "").strip())
        if not text:
            continue
        if part.get("red"):
            chunks.append(f'<span class="exercise-program-text-red">{text}</span>')
        else:
            chunks.append(text)
    return " ".join(chunks)


# ترتيب الأيام المطلوب: الاثنين أولاً (يمين الجدول في RTL) حتى الأحد.
_CANONICAL_DAY_ORDER = (
    "الاثنين",
    "الثلاثاء",
    "الاربعاء",
    "الخميس",
    "الجمعة",
    "السبت",
    "الاحد",
)


def _canonical_day_index(label: str) -> int | None:
    norm = _normalize_day(label)
    for idx, day in enumerate(_CANONICAL_DAY_ORDER):
        if norm == _normalize_day(day):
            return idx
    return None


def _reorder_days_monday_first(
    header: list[str], rows: list[dict[str, Any]], ncols: int
) -> tuple[list[str], list[dict[str, Any]]]:
    """إعادة ترتيب أعمدة الأيام لتبدأ بالاثنين من اليمين."""
    if len(header) != ncols:
        return header, rows
    day_indices = [_canonical_day_index(h) for h in header]
    if any(idx is None for idx in day_indices):
        return header, rows
    # ترتيب الأعمدة تصاعدياً حسب اليوم القانوني (الاثنين=0 يظهر أولاً في RTL).
    order = sorted(range(ncols), key=lambda c: day_indices[c])
    if order == list(range(ncols)):
        return header, rows

    new_header = [header[c] for c in order]
    new_rows: list[dict[str, Any]] = []
    for row in rows:
        cells = list(row.get("cells") or [])
        is_bar_row = bool(cells) and all(cell.get("is_bar") for cell in cells)
        if is_bar_row or len(cells) != ncols:
            new_rows.append(row)
            continue
        row["cells"] = [cells[c] for c in order]
        new_rows.append(row)
    return new_header, new_rows


def _normalize_calendar_rows(
    rows: list[dict[str, Any]], ncols: int
) -> list[dict[str, Any]]:
    """فصل أشرطة التعليمات عن صفوف الأيام وترتيبها بعد الأسبوع التابع لها."""
    normalized: list[dict[str, Any]] = []
    leading_bars: list[dict[str, Any]] = []
    saw_date_row = False

    for row in rows:
        cells = list(row.get("cells") or [])
        bars = [cell for cell in cells if cell.get("is_bar")]
        date_cells = [cell for cell in cells if not cell.get("is_bar")]
        band = (row.get("week_band") or "").strip()

        if date_cells:
            # لا يُسمح لأي صف أسبوعي بتجاوز عدد أعمدة الأيام.
            date_row = {"week_band": band, "cells": date_cells[:ncols]}
            normalized.append(date_row)
            saw_date_row = True
            if leading_bars:
                normalized.extend(leading_bars)
                leading_bars = []

        for bar in bars:
            bar_row = {"week_band": band, "cells": [bar]}
            if saw_date_row:
                normalized.append(bar_row)
            else:
                leading_bars.append(bar_row)

    normalized.extend(leading_bars)

    # تنسيق الأسابيع كما في النموذج: تمهيدي، أسبوعان أزرقان، أسبوع بيج، ثم أبيض.
    week_bands = ("beige", "blue", "blue", "beige", "")
    week_index = -1
    current_band = ""
    for row in normalized:
        cells = list(row.get("cells") or [])
        is_bar_row = bool(cells) and all(cell.get("is_bar") for cell in cells)
        if not is_bar_row:
            week_index += 1
            current_band = week_bands[week_index] if week_index < len(week_bands) else ""
        row["week_band"] = current_band

    return normalized


def render_program_table_html(raw_json: str) -> str:
    data = loads_program_table(raw_json)
    if not data:
        return ""

    title = html.escape((data.get("title") or "برنامج التمرين").strip())
    header: list[str] = list(data.get("header") or [])
    rows: list[dict[str, Any]] = list(data.get("rows") or [])
    ncols = len(header) or 7
    rows = _normalize_calendar_rows(rows, ncols)
    header, rows = _reorder_days_monday_first(header, rows, ncols)

    out: list[str] = [
        '<div class="exercise-program-calendar-wrap">',
        '<div class="exercise-program-calendar-heading">',
        f'<h3 class="exercise-program-calendar-title">{title}</h3>',
        "</div>",
        '<table class="exercise-program-calendar" dir="rtl">',
    ]

    if header:
        out.append("<thead><tr>")
        for h in header:
            out.append(f"<th>{html.escape((h or '').strip())}</th>")
        out.append("</tr></thead>")

    out.append("<tbody>")
    for row in rows:
        band = (row.get("week_band") or "").strip()
        tr_cls = f' class="week-{band}"' if band else ""
        out.append(f"<tr{tr_cls}>")
        for cell in row.get("cells") or []:
            colspan = int(cell.get("colspan") or 1)
            rowspan = int(cell.get("rowspan") or 1)
            attrs = []
            if colspan > 1:
                attrs.append(f'colspan="{colspan}"')
            if rowspan > 1:
                attrs.append(f'rowspan="{rowspan}"')
            is_bar = bool(cell.get("is_bar"))
            if is_bar:
                attrs.append('class="exercise-program-bar-cell"')
            attr_s = (" " + " ".join(attrs)) if attrs else ""
            date_label = html.escape((cell.get("date") or "").strip())
            inner = _render_parts_html(list(cell.get("parts") or []))
            if is_bar:
                out.append(
                    f'<td{attr_s}><div class="exercise-program-bar-box">{inner}</div></td>'
                )
            else:
                date_html = (
                    f'<span class="exercise-program-cell-date">{date_label}</span>'
                    if date_label
                    else ""
                )
                box = (
                    f'<div class="exercise-program-cell-box">{inner}</div>'
                    if inner
                    else ""
                )
                out.append(f"<td{attr_s}>{date_html}{box}</td>")
        out.append("</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)
