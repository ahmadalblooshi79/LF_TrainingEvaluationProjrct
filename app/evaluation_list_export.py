"""تصدير صفحة قائمة التقييم إلى ملف Excel مطابق للقالب العسكري."""
from __future__ import annotations

import io
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from app.evaluation_list_columns import (
    EVAL_IMPORT_COL_ACQUIRED,
    EVAL_IMPORT_COL_GRADE,
    EVAL_IMPORT_COL_MAX,
    EVAL_IMPORT_COL_NOTES,
    EVAL_IMPORT_COL_PCT,
    EVAL_NARRATIVE_DESC_LABEL,
    EVAL_NARRATIVE_REQ_LABEL,
    compose_eval_doc_banner_text,
    eval_doc_title_first_line,
    format_eval_narrative_cell,
    grade_label_from_percent,
    is_acquired_entry_placeholder,
    is_evaluation_import_footer_stop_row,
    normalize_ar_header,
    parse_max_cell,
    should_skip_evaluation_import_row,
)
from app.evaluation_sheet_parser import _find_rubric_subheader_row_index, _pad_grid
from app.xlsx_grid_preview import _cell_to_str


def zip_safe_segment(name: str, fallback: str = "بند") -> str:
    """جزء مسار داخل أرشيف ZIP — بلا فواصل أو رموز ممنوعة."""
    t = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", (name or "").strip())
    t = t.replace("..", "_").strip(" .")
    return (t or fallback)[:120]


def pending_eval_list_zip_relpath(
    *,
    phase_label: str,
    unit_label: str,
    list_title: str,
    item_id: int,
    used: set[str],
) -> str:
    """مسار الملف داخل الأرشيف: المرحلة/الوحدة/اسم القائمة.xlsx"""
    phase = zip_safe_segment(phase_label, "مرحلة")
    unit = zip_safe_segment(unit_label, "وحدة")
    fname = export_download_filename(list_title)
    rel = f"{phase}/{unit}/{fname}"
    if rel in used:
        stem = re.sub(r"\.(xlsx|xlsm|xls)$", "", fname, flags=re.I).strip() or "قائمة_التقييم"
        rel = f"{phase}/{unit}/{stem}_{int(item_id)}.xlsx"
    n = 2
    base = rel
    while rel in used:
        stem = re.sub(r"\.(xlsx|xlsm|xls)$", "", base, flags=re.I).strip() or "قائمة_التقييم"
        rel = f"{phase}/{unit}/{stem}_{n}.xlsx"
        n += 1
    used.add(rel)
    return rel


def pack_pending_eval_lists_zip(entries: list[tuple[str, bytes]]) -> bytes:
    """أرشيف ZIP من أزواج (المسار النسبي، بايتات Excel)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel, data in entries:
            info = zipfile.ZipInfo((rel or "").replace("\\", "/"))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.flag_bits |= 0x800
            zf.writestr(info, data)
    return buf.getvalue()


def export_download_filename(
    item_title: str | None,
    fallback: str = "قائمة_التقييم.xlsx",
    *,
    ext: str | None = None,
) -> str:
    """اسم ملف التنزيل من عنوان القائمة الظاهر في الصفحة."""
    name = (item_title or "").strip() or fallback
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = name.strip(" .")
    if not name:
        name = fallback
    low = name.lower()
    if not (
        low.endswith(".xlsx")
        or low.endswith(".xlsm")
        or low.endswith(".xls")
        or low.endswith(".pdf")
    ):
        name = f"{name}.xlsx"
    if ext:
        stem = re.sub(r"\.(xlsx|xlsm|xls|pdf)$", "", name, flags=re.I).strip() or "قائمة_التقييم"
        name = f"{stem}.{str(ext).lstrip('.')}"
    return name


def export_doc_title_from_list_page(item_title: str | None, *, fallback: str = "") -> str:
    """
    عنوان صف B1:J1 عند التصدير — يُقتبس من عنوان قائمة التقييم في صفحة النظام
    (مثل «01 تقييم رفع الحالة.xlsx») مع إزالة امتداد الملف للعرض داخل Excel.
    """
    raw = normalize_ar_header(item_title or "")
    if not raw:
        return normalize_ar_header(fallback or "")
    title = re.sub(r"\.(xlsx|xlsm|xls)$", "", raw, flags=re.I).strip()
    return title or raw


def export_eval_doc_banner_title(
    *,
    excel_title: str | None,
    exercise_subtitle: str | None,
    item_title_fallback: str | None = "",
) -> str:
    """سطر عنوان ملف Excel + سطر معلومات التمرين داخل نفس خلية B1:J1."""
    line1 = eval_doc_title_first_line(excel_title or "")
    if not line1:
        line1 = export_doc_title_from_list_page(item_title_fallback, fallback="")
    return compose_eval_doc_banner_text(line1, exercise_subtitle or "")


def _sheet_grid(ws, max_row: int, max_col: int) -> list[list[str]]:
    grid: list[list[str]] = []
    for row in ws.iter_rows(
        min_row=1,
        max_row=max_row,
        min_col=1,
        max_col=max_col,
        values_only=True,
    ):
        grid.append([_cell_to_str(c) for c in row])
    return _pad_grid(grid, max_col)


def _acquired_export_value(raw: Any) -> Any:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if s == "na":
        return "لا ينطبق"
    try:
        v = float(s.replace(",", ".").replace("٫", "."))
    except ValueError:
        return s
    if v == int(v):
        return int(v)
    return round(v, 2)


def _footer_label_key(s: str) -> str:
    return (
        normalize_ar_header(s or "")
        .replace("ـ", "")
        .replace(":", "")
        .replace("：", "")
        .replace(".", "")
        .strip()
    )


def _is_name_placeholder(value: Any) -> bool:
    s = str(value or "").strip()
    if not s:
        return True
    return "أدخل" in s


def _writable_cell(ws, row: int, col: int):
    """يعيد خلية قابلة للكتابة (أصل الدمج إن وُجد)."""
    cell = ws.cell(row, col)
    try:
        from openpyxl.cell.cell import MergedCell  # type: ignore
    except Exception:
        MergedCell = ()  # type: ignore
    if MergedCell and isinstance(cell, MergedCell):
        for merged in ws.merged_cells.ranges:
            if cell.coordinate in merged:
                return ws.cell(merged.min_row, merged.min_col)
    return cell


def _set_cell_value(ws, row: int, col: int, value: Any) -> None:
    _writable_cell(ws, row, col).value = value


def _is_marks_header_cell(value: Any) -> bool:
    t = _footer_label_key(_cell_to_str(value))
    if not t:
        return False
    return any(
        k in t
        for k in ("قصوى", "مكتسب", "علام", "عناصر", "نتيج", "نسبه", "نسبة", "ملاحظ")
    )


def _set_meta_if_not_header(ws, row: int, col: int, value: Any) -> None:
    cell = _writable_cell(ws, row, col)
    if _is_marks_header_cell(cell.value):
        return
    cell.value = value


def _export_number(value: float) -> int | float:
    if value == int(value):
        return int(value)
    return round(value, 2)


def _is_na_acquired(value: Any) -> bool:
    s = ("" if value is None else str(value)).strip().lower()
    return s in {"na", "n/a", "لا ينطبق"}


def _row_acquired_and_max(
    trow: dict[str, Any],
    srow: dict[str, Any],
    *,
    excel_max: float | None,
) -> tuple[Any, float | None]:
    aq = None
    if isinstance(srow, dict) and "acquired" in srow:
        aq = _acquired_export_value(srow.get("acquired"))
    elif trow.get("acquired_initial"):
        aq = _acquired_export_value(trow.get("acquired_initial"))
    mx = trow.get("max_num")
    if mx is None:
        mx = parse_max_cell(trow.get("max_val"))
    if mx is None:
        mx = excel_max
    try:
        mx_f = float(mx) if mx is not None else None
    except (TypeError, ValueError):
        mx_f = None
    return aq, mx_f


_GRADE_FILL_HEX = {
    "na": "FFFFFF",
    "fail": "FECACA",
    "mid": "FED7AA",
    "good": "FEF08A",
    "vgood": "BAE6FD",
    "excellent": "BBF7D0",
}


def _grade_fill_hex(pct: float | None) -> str:
    if pct is None:
        return _GRADE_FILL_HEX["na"]
    if pct < 60:
        return _GRADE_FILL_HEX["fail"]
    if pct < 70:
        return _GRADE_FILL_HEX["mid"]
    if pct < 80:
        return _GRADE_FILL_HEX["good"]
    if pct < 90:
        return _GRADE_FILL_HEX["vgood"]
    return _GRADE_FILL_HEX["excellent"]


def _apply_grade_fill(cell, pct: float | None) -> None:
    """خلفية خلية النتيجة بنفس ألوان صفحة القائمة."""
    try:
        from openpyxl.styles import PatternFill  # type: ignore
    except Exception:
        return
    argb = "FF" + _grade_fill_hex(pct)
    cell.fill = PatternFill(patternType="solid", fgColor=argb)


def _sqref_targets_grade_colors(sqref: str) -> bool:
    token = (sqref or "").upper().replace("$", "").replace(",", " ")
    for part in token.split():
        if not part:
            continue
        if part.startswith("E19") or part.endswith("E19") or ":E19" in part:
            return True
        if part.startswith("H") and any(ch.isdigit() for ch in part):
            return True
    return False


def _remove_grade_conditional_formatting(ws) -> None:
    """يحذف تنسيق القالب الشرطي لعمود النتيجة حتى تظهر ألوان النظام."""
    cf = getattr(ws, "conditional_formatting", None)
    rules = getattr(cf, "_cf_rules", None) if cf is not None else None
    if not rules:
        return
    for fmt in list(rules.keys()):
        sqref = str(getattr(fmt, "sqref", "") or "")
        if _sqref_targets_grade_colors(sqref):
            try:
                del rules[fmt]
            except Exception:
                pass


def _write_system_pct_grade(ws, excel_r: int, pct: float | None) -> None:
    """يكتب النسبة والتقدير من النظام ويستبدل صيغ القالب."""
    g_cell = _writable_cell(ws, excel_r, EVAL_IMPORT_COL_PCT + 1)
    h_cell = _writable_cell(ws, excel_r, EVAL_IMPORT_COL_GRADE + 1)
    if pct is None:
        g_cell.value = "—"
        h_cell.value = "غير محسوب"
        _apply_grade_fill(h_cell, None)
        return
    g_cell.value = round(pct / 100.0, 6)
    g_cell.number_format = "0%"
    h_cell.value = grade_label_from_percent(pct)
    _apply_grade_fill(h_cell, pct)


def _fill_footer_system_totals(
    ws,
    *,
    sum_max: float,
    sum_acq: float,
    any_acquired: bool,
    start_row: int,
    max_row: int,
    max_col: int,
) -> None:
    """يكتب إجمالي/نسبة/تقدير من بيانات النظام بدل صيغ Excel غير المحسوبة."""
    overall_pct = (sum_acq / sum_max * 100.0) if (any_acquired and sum_max > 0) else None
    overall_grade = grade_label_from_percent(overall_pct) if overall_pct is not None else ""
    scan_to = max(int(start_row), 1)
    for r in range(scan_to, int(max_row) + 1):
        blob_parts: list[str] = []
        for c in range(1, min(int(max_col), 12) + 1):
            blob_parts.append(_cell_to_str(_writable_cell(ws, r, c).value))
        key = _footer_label_key(" ".join(blob_parts))
        if not key:
            continue
        if "إجمالي" in key or "اجمالي" in key:
            if sum_max > 0:
                _set_cell_value(ws, r, EVAL_IMPORT_COL_MAX + 1, _export_number(sum_max))
            if any_acquired:
                _set_cell_value(ws, r, EVAL_IMPORT_COL_ACQUIRED + 1, _export_number(sum_acq))
            continue
        if "النسبة" in key and "عام" in key:
            if overall_pct is not None:
                cell = _writable_cell(ws, r, EVAL_IMPORT_COL_MAX + 1)
                cell.value = round(overall_pct / 100.0, 6)
                cell.number_format = "0.00%"
            continue
        if "التقدير" in key and "عام" in key:
            if overall_grade:
                cell = _writable_cell(ws, r, EVAL_IMPORT_COL_MAX + 1)
                cell.value = overall_grade
                _apply_grade_fill(cell, overall_pct)


def _normalize_export_banner_title(raw: str) -> str:
    """يحافظ على فاصل السطرين داخل خلية العنوان ولا يدمج السطرين في سطر واحد."""
    text = (raw or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ""
    lines = [normalize_ar_header(ln) for ln in text.split("\n")]
    lines = [ln for ln in lines if ln]
    return "\n".join(lines)


def _apply_title_wrap(ws, row: int, col: int, title: str) -> None:
    """يلف النص داخل خلية B1 المدمجة ويعطي الصف ارتفاعاً يكفي سطرين."""
    cell = _writable_cell(ws, row, col)
    try:
        from openpyxl.styles import Alignment  # type: ignore
    except Exception:
        return
    prev = getattr(cell, "alignment", None)
    cell.alignment = Alignment(
        wrap_text=True,
        horizontal=(getattr(prev, "horizontal", None) if prev is not None else None) or "center",
        vertical=(getattr(prev, "vertical", None) if prev is not None else None) or "center",
        textRotation=(getattr(prev, "textRotation", None) if prev is not None else None) or 0,
        indent=(getattr(prev, "indent", None) if prev is not None else None) or 0,
        readingOrder=(getattr(prev, "readingOrder", None) if prev is not None else None) or 0,
    )
    if "\n" not in (title or ""):
        return
    dim = ws.row_dimensions[row]
    current = float(dim.height or 0)
    dim.height = max(current, 32.0)


def _cell_text(ws, row: int, col: int) -> str:
    return normalize_ar_header(_cell_to_str(_writable_cell(ws, row, col).value))


def _looks_like_marks_header_row(ws, row: int) -> bool:
    blob_parts: list[str] = []
    for c in range(2, 10):
        blob_parts.append(_cell_text(ws, row, c))
    blob = " ".join(p for p in blob_parts if p)
    if not blob:
        return False
    if "قصوى" in blob or "مكتسب" in blob:
        return True
    return "عناصر" in blob and "تقييم" in blob


def _looks_like_narrative_header(ws) -> bool:
    t2 = _cell_text(ws, 2, 2)
    t3 = _cell_text(ws, 3, 2)
    return EVAL_NARRATIVE_DESC_LABEL in t2 or EVAL_NARRATIVE_REQ_LABEL in t3


def _looks_like_unit_meta_row(ws, row: int) -> bool:
    blob_parts: list[str] = []
    for c in range(2, 8):
        blob_parts.append(_cell_text(ws, row, c))
    blob = " ".join(p for p in blob_parts if p)
    if not blob or _looks_like_marks_header_row(ws, row):
        return False
    return "الوحدة" in blob or "قائد الوحدة" in blob


def _is_classic_military_eval_layout(ws) -> bool:
    """قوالب عسكرية جاهزة (وحدة/قائد/مجرى أحداث/…) — لا ندرج صفوف وصف النظام فوقها."""
    if _looks_like_narrative_header(ws):
        return False
    markers = (
        "مجرى الأحداث",
        "رقم المعضلة",
        "نوع التمرين",
        "قائد الوحدة",
        "التقدير العام",
        "النسبة العامة",
    )
    hits = 0
    mr = min(int(getattr(ws, "max_row", None) or 1), 18)
    mc = min(int(getattr(ws, "max_column", None) or 1), 12)
    for r in range(1, mr + 1):
        parts: list[str] = []
        for c in range(1, mc + 1):
            parts.append(_cell_text(ws, r, c))
        blob = " ".join(p for p in parts if p)
        if not blob:
            continue
        for m in markers:
            if m in blob:
                hits += 1
                break
        if hits >= 2:
            return True
    return False


def _ensure_eval_narrative_header_rows(ws) -> None:
    """يدرج صفي الوصف/المتطلبات فقط للقوالب المبسّطة — لا يمس القالب العسكري الجاهز."""
    if _looks_like_narrative_header(ws):
        return
    if _is_classic_military_eval_layout(ws):
        return
    if _looks_like_marks_header_row(ws, 2) or _looks_like_marks_header_row(ws, 3):
        return
    if not (_looks_like_unit_meta_row(ws, 2) or _looks_like_unit_meta_row(ws, 3)):
        return
    try:
        ws.insert_rows(2, 2)
    except Exception:
        return
    try:
        ws.merge_cells("B2:J2")
        ws.merge_cells("B3:J3")
    except Exception:
        pass


def _apply_narrative_wrap(ws, row: int, col: int, text: str) -> None:
    cell = _writable_cell(ws, row, col)
    try:
        from openpyxl.styles import Alignment, Font  # type: ignore
    except Exception:
        return
    prev = getattr(cell, "alignment", None)
    cell.alignment = Alignment(
        wrap_text=True,
        horizontal="right",
        vertical="top",
        textRotation=(getattr(prev, "textRotation", None) if prev is not None else None) or 0,
        indent=(getattr(prev, "indent", None) if prev is not None else None) or 0,
        readingOrder=(getattr(prev, "readingOrder", None) if prev is not None else None) or 2,
    )
    try:
        prev_font = getattr(cell, "font", None)
        cell.font = Font(
            name=(getattr(prev_font, "name", None) or "Arial"),
            size=(getattr(prev_font, "size", None) or 14),
            bold=True,
        )
    except Exception:
        pass
    lines = max(1, str(text or "").count("\n") + 1)
    dim = ws.row_dimensions[row]
    current = float(dim.height or 0)
    dim.height = max(current, 45.0 if lines <= 2 else min(28.0 * lines, 96.0))


def _write_eval_narrative_header(
    ws, *, dilemma_description: str, dilemma_requirements: str
) -> None:
    # لا تُكتب صفوف الوصف إلا إن وُجدت مسبقاً في القالب — تجنّب كسر القالب العسكري
    if not _looks_like_narrative_header(ws):
        return
    if _looks_like_marks_header_row(ws, 2):
        return
    desc_cell = format_eval_narrative_cell(EVAL_NARRATIVE_DESC_LABEL, dilemma_description)
    _set_cell_value(ws, 2, 2, desc_cell)
    _apply_narrative_wrap(ws, 2, 2, desc_cell)
    if _looks_like_marks_header_row(ws, 3):
        return
    req_cell = format_eval_narrative_cell(EVAL_NARRATIVE_REQ_LABEL, dilemma_requirements)
    _set_cell_value(ws, 3, 2, req_cell)
    _apply_narrative_wrap(ws, 3, 2, req_cell)


def _eval_meta_row_numbers(ws) -> tuple[int, int]:
    """صف الوحدة/التاريخ وصف قائد الوحدة/المحكم بعد صفوف الوصف."""
    if _looks_like_narrative_header(ws) or _looks_like_unit_meta_row(ws, 4):
        return 4, 5
    return 2, 3


def _looks_like_split_date_headers(ws, row: int) -> bool:
    """القالب العسكري: التاريخ مقسوم إلى يوم / شهر / سنة في F و H و J."""
    f = _footer_label_key(_cell_text(ws, row, 6))
    h = _footer_label_key(_cell_text(ws, row, 8))
    j = _footer_label_key(_cell_text(ws, row, 10))
    return ("يوم" in f) and ("شهر" in h) and ("سنة" in j)


def _write_export_date(ws, row: int, date_str: str) -> None:
    raw = normalize_ar_header(date_str or "")
    if not raw:
        return
    if _looks_like_split_date_headers(ws, row):
        parts = re.findall(r"\d+", raw)
        if len(parts) >= 3:
            if len(parts[0]) == 4:
                year, month, day = parts[0], parts[1], parts[2]
            else:
                day, month, year = parts[0], parts[1], parts[2]
            _set_cell_value(ws, row, 6, int(day) if day.isdigit() else day)
            _set_cell_value(ws, row, 8, int(month) if month.isdigit() else month)
            _set_cell_value(ws, row, 10, int(year) if year.isdigit() else year)
            return
    _set_meta_if_not_header(ws, row, 6, raw)


def _cell_has_formula(cell) -> bool:
    return _value_is_formula(getattr(cell, "value", None))


def _value_is_formula(value: Any) -> bool:
    if isinstance(value, str) and value.startswith("="):
        return True
    if value is None:
        return False
    return type(value).__name__ in {"ArrayFormula", "DataTableFormula"}


def _strip_sheet_formulas(ws) -> None:
    """يحذف صيغ الخلايا ويُبقي القيمة/التنسيق بعد تعبئة بيانات النظام."""
    mr = int(getattr(ws, "max_row", None) or 0)
    mc = int(getattr(ws, "max_column", None) or 0)
    if mr < 1 or mc < 1:
        return
    for r in range(1, mr + 1):
        for c in range(1, mc + 1):
            cell = _writable_cell(ws, r, c)
            if _value_is_formula(getattr(cell, "value", None)):
                cell.value = None


def _strip_workbook_formulas(wb) -> None:
    for name in list(getattr(wb, "sheetnames", None) or []):
        _strip_sheet_formulas(wb[name])


def _merge_worksheet_extlst(src_xml: bytes, exp_xml: bytes) -> bytes:
    """يعيد قوائم x14 المنسدلة التي يحذفها openpyxl من القالب العسكري."""
    try:
        src = src_xml.decode("utf-8")
        exp = exp_xml.decode("utf-8")
    except UnicodeDecodeError:
        return exp_xml
    if "x14:dataValidations" in exp:
        return exp_xml
    m = re.search(r"<extLst>.*?</extLst>", src, flags=re.DOTALL)
    if not m:
        return exp_xml
    ext = m.group(0)
    src_tag = re.search(r"<worksheet\b[^>]*>", src)
    exp_tag = re.search(r"<worksheet\b[^>]*>", exp)
    if src_tag and exp_tag:
        decls = re.findall(r'\sxmlns(?::[A-Za-z0-9]+)="[^"]*"', src_tag.group(0))
        extra = ""
        for decl in decls:
            prefix = decl.strip().split("=", 1)[0]
            if prefix not in exp_tag.group(0):
                extra += " " + decl.strip()
        if "xmlns:x14=" not in exp_tag.group(0) and "xmlns:x14=" in ext:
            extra += ' xmlns:x14="http://schemas.microsoft.com/office/spreadsheetml/2009/9/main"'
        if "xmlns:xm=" not in exp_tag.group(0) and "xmlns:xm=" in ext:
            extra += ' xmlns:xm="http://schemas.microsoft.com/office/excel/2006/main"'
        if extra:
            old = exp_tag.group(0)
            new = old[:-1] + extra + ">"
            exp = exp[: exp_tag.start()] + new + exp[exp_tag.end() :]
    if "<extLst>" in exp:
        exp = re.sub(r"<extLst>.*?</extLst>", ext, exp, count=1, flags=re.DOTALL)
    else:
        exp = exp.replace("</worksheet>", ext + "</worksheet>", 1)
    return exp.encode("utf-8")


def _restore_template_xlsx_parts(source_path: Path, exported: bytes) -> bytes:
    """يحافظ على أجزاء القالب التي يُسقطها openpyxl (قوائم منسدلة / طابعة)."""
    src_path = Path(source_path)
    if not src_path.is_file() or not exported:
        return exported
    try:
        src_bytes = src_path.read_bytes()
    except OSError:
        return exported
    try:
        with zipfile.ZipFile(io.BytesIO(src_bytes)) as srcz, zipfile.ZipFile(
            io.BytesIO(exported)
        ) as expz:
            src_names = set(srcz.namelist())
            exp_names = set(expz.namelist())
            out = io.BytesIO()
            with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as outz:
                for name in expz.namelist():
                    data = expz.read(name)
                    if (
                        name.startswith("xl/worksheets/sheet")
                        and name.endswith(".xml")
                        and name in src_names
                    ):
                        data = _merge_worksheet_extlst(srcz.read(name), data)
                    outz.writestr(name, data)
            return out.getvalue()
    except Exception:
        return exported


def _fill_footer_judge_name(ws, judge_name: str, *, max_row: int, max_col: int) -> None:
    """
    يملأ صف تذييل «المحكم» باسم المحكم من صفحة قائمة التقييم.
    القالب الشائع: E=«المحكم:» و G=«أدخل اسم المحكم» (أو خلية مجاورة).
    """
    name = normalize_ar_header(judge_name or "")
    if not name or name == "—":
        return

    start = max(1, max_row - 30)
    for r in range(max_row, start - 1, -1):
        for c in range(1, min(max_col, 12) + 1):
            cell = _writable_cell(ws, r, c)
            raw = _cell_to_str(cell.value)
            if not raw:
                continue
            key = _footer_label_key(raw)

            # الخلية نفسها نص placeholder لاسم المحكم
            if "أدخل" in raw and "محكم" in raw.replace("ـ", ""):
                cell.value = name
                return

            # تسمية المحكم فقط (ليست ملاحظات طويلة ولا صف الترويسة العلوي)
            if key != "المحكم" and not (key.startswith("المحكم") and len(key) <= 12):
                continue
            if len(raw) > 40:
                continue

            # اكتب في أقرب خلية اسم (غالباً G أو F أو العمود التالي)
            candidates = [c + 2, c + 1, 7, 6, 3]
            for nc in candidates:
                if nc < 1 or nc > max_col or nc == c:
                    continue
                target = _writable_cell(ws, r, nc)
                if _is_name_placeholder(target.value) or (
                    target.value is not None and "أدخل" in str(target.value)
                ):
                    target.value = name
                    return
            # احتياطي: العمود G إن وُجد
            _set_cell_value(ws, r, 7 if max_col >= 7 else min(c + 2, max_col), name)
            return


def _is_signature_label(raw: str) -> bool:
    key = _footer_label_key(raw)
    if not key:
        return False
    if len(raw) > 40:
        return False
    return key == "التوقيع" or (key.startswith("التوقيع") and len(key) <= 12)


def _visual_left_value_cell(ws, row: int, label_col: int, *, max_col: int):
    """الخانة المقابلة يسار التسمية في ورقة RTL (عمود أعلى رقماً)."""
    for nc in (label_col + 2, label_col + 1, 7, 6):
        if nc < 1 or nc == label_col:
            continue
        if nc > max(max_col, 8):
            continue
        target = _writable_cell(ws, row, nc)
        tv = target.value
        if _is_name_placeholder(tv) or tv is None or not str(tv).strip():
            return target
    return _writable_cell(ws, row, min(label_col + 2, max(max_col, 7)))


def _find_signature_anchor_cell(ws, *, max_row: int, max_col: int):
    """خلية خانة التوقيع: يسار كلمة «التوقيع» في تذييل القائمة."""
    start = max(1, int(max_row) - 40)
    scan_cols = min(int(max_col), 12)
    for r in range(int(max_row), start - 1, -1):
        for c in range(1, scan_cols + 1):
            cell = _writable_cell(ws, r, c)
            raw = _cell_to_str(cell.value)
            if not raw or not _is_signature_label(raw):
                continue
            label_col = int(getattr(cell, "column", None) or c)
            return _visual_left_value_cell(ws, int(getattr(cell, "row", None) or r), label_col, max_col=max_col)
    for r in range(int(max_row), start - 1, -1):
        for c in range(1, scan_cols + 1):
            cell = _writable_cell(ws, r, c)
            raw = _cell_to_str(cell.value)
            if not raw:
                continue
            key = _footer_label_key(raw)
            if key != "المحكم" and not (key.startswith("المحكم") and len(key) <= 12):
                continue
            if len(raw) > 40:
                continue
            label_col = int(getattr(cell, "column", None) or c)
            return _visual_left_value_cell(
                ws, int(getattr(cell, "row", None) or r) + 1, label_col, max_col=max_col
            )
    return _writable_cell(ws, max(int(max_row), 1), 7)


def _embed_transparent_signature(
    ws,
    png_bytes: bytes | None,
    *,
    max_row: int,
    max_col: int,
) -> str | None:
    """يدرج PNG بألفا في خانة التوقيع (يسار كلمة التوقيع) دون تسطيح على خلفية بيضاء."""
    if not png_bytes:
        return None
    from openpyxl.drawing.image import Image as XLImage
    from openpyxl.utils import get_column_letter
    from PIL import Image as PILImage

    try:
        im = PILImage.open(io.BytesIO(png_bytes))
        if im.mode != "RGBA":
            return None
        w, h = im.size
    except Exception:
        return None
    if w <= 0 or h <= 0:
        return None
    max_h, max_w = 58.0, 190.0
    scale = min(max_w / float(w), max_h / float(h), 1.0)
    disp_w = max(24, int(w * scale))
    disp_h = max(16, int(h * scale))
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.write(png_bytes)
    tmp.close()
    img = XLImage(tmp.name)
    img.width = disp_w
    img.height = disp_h
    target = _find_signature_anchor_cell(ws, max_row=max_row, max_col=max_col)
    anchor_row = int(getattr(target, "row", None) or max_row)
    anchor_col = int(getattr(target, "column", None) or 7)
    img.anchor = f"{get_column_letter(anchor_col)}{anchor_row}"
    ws.add_image(img)
    dim = ws.row_dimensions[anchor_row]
    current = float(dim.height or 0)
    dim.height = max(current, disp_h * 0.75, 28.0)
    return tmp.name


def build_evaluation_list_xlsx_bytes(
    source_path: Path,
    *,
    doc_title: str,
    unit_label: str,
    date_str: str,
    commander_name: str,
    judge_name: str,
    eval_rows: list[dict[str, Any]] | None,
    saved_rows: list[dict[str, Any]] | None,
    dilemma_description: str = "",
    dilemma_requirements: str = "",
    signature_png: bytes | None = None,
    approved_at: Any | None = None,
    materialize_computed: bool = True,
    remove_grade_cf: bool = False,
) -> bytes:
    """
    ينسخ ملف المصدر، يحدّث العنوان والبيانات الوصفية وعلامات المحكم،
    ويكتب النسبة/النتيجة والإجمالي من بيانات النظام بدل صيغ Excel.
    يُبقي الأوراق الإضافية والتنسيق العام (حدود/خطوط/دمج/تنسيق شرطي ما لم يُطلب حذفه).
    ``remove_grade_cf`` يُستخدم لتصدير PDF حتى تظهر ألوان النظام دون قواعد القالب.
    """
    try:
        from openpyxl import load_workbook  # type: ignore
    except ModuleNotFoundError as exc:
        raise RuntimeError("مكتبة openpyxl غير مثبتة") from exc

    path = Path(source_path)
    if not path.is_file():
        raise FileNotFoundError(str(path))

    # keep_vba يحافظ على xlsm؛ data_only=False ثم تُستبدل الصيغ بقيم النظام
    wb = load_workbook(filename=str(path), data_only=False, keep_vba=path.suffix.lower() == ".xlsm")
    try:
        # اختر ورقة التقييم دون حذف الأوراق الأخرى (ملاحظات/مفتاح ألوان إن وُجدت)
        keep = None
        for name in list(wb.sheetnames):
            if name == "قائمة التقييم":
                keep = name
                break
        if keep is None:
            keep = wb.sheetnames[0] if wb.sheetnames else None
        ws = wb[keep] if keep else wb.active
        if remove_grade_cf:
            _remove_grade_conditional_formatting(ws)

        # IMPORTANT: preserve the original Excel template structure during export.
        # Do not insert rows or create new merged ranges here; some military
        # templates already contain complex merges and modifying them can make
        # Excel repair/remove mergeCells records when the exported file opens.
        # Narrative rows are written only when they already exist in the template.

        mr = int(getattr(ws, "max_row", None) or 1)
        mc = int(getattr(ws, "max_column", None) or 1)
        grid = _sheet_grid(ws, mr, mc)
        rubric_i = _find_rubric_subheader_row_index(grid)
        start_excel = (rubric_i + 2) if rubric_i is not None else 2

        title = _normalize_export_banner_title(doc_title or "")
        if title:
            _set_cell_value(ws, 1, 2, title)  # B1 — سطران في نفس الخلية المدمجة
            _apply_title_wrap(ws, 1, 2, title)

        _write_eval_narrative_header(
            ws,
            dilemma_description=dilemma_description or "",
            dilemma_requirements=dilemma_requirements or "",
        )

        unit_row, cmd_row = _eval_meta_row_numbers(ws)
        # لا تُكتب البيانات الوصفية فوق عناوين أعمدة العلامات (القصوى/المكتسبة/…)
        if unit_label and unit_label != "—":
            _set_meta_if_not_header(ws, unit_row, 3, unit_label)
        if date_str:
            _write_export_date(ws, unit_row, date_str)
        if commander_name and commander_name != "—":
            _set_meta_if_not_header(ws, cmd_row, 3, commander_name)
        if judge_name and judge_name != "—":
            _set_meta_if_not_header(ws, cmd_row, 6, judge_name)

        template_rows = eval_rows or []
        saved = saved_rows or []
        ti = 0
        sum_max = 0.0
        sum_acq = 0.0
        any_acquired = False
        footer_start = mr + 1
        for excel_r in range(start_excel, mr + 1):
            cells = list(grid[excel_r - 1]) if excel_r - 1 < len(grid) else []
            while len(cells) < mc:
                cells.append("")
            if is_evaluation_import_footer_stop_row(cells):
                footer_start = excel_r
                break
            if should_skip_evaluation_import_row(cells, excel_row_1based=excel_r):
                continue
            if not any(str(c).strip() for c in cells):
                continue
            if ti >= len(template_rows):
                break
            trow = template_rows[ti]
            srow = saved[ti] if ti < len(saved) and isinstance(saved[ti], dict) else {}
            ti += 1

            if (trow.get("row_kind") or "score") == "section":
                continue

            excel_max = parse_max_cell(
                cells[EVAL_IMPORT_COL_MAX] if len(cells) > EVAL_IMPORT_COL_MAX else ""
            )
            aq, mx = _row_acquired_and_max(trow, srow, excel_max=excel_max)
            if materialize_computed and mx is not None:
                _set_cell_value(
                    ws, excel_r, EVAL_IMPORT_COL_MAX + 1, _export_number(float(mx))
                )

            saved_has_acquired = isinstance(srow, dict) and "acquired" in srow
            if aq is not None and (
                saved_has_acquired
                or not is_acquired_entry_placeholder(str(aq))
            ):
                _set_cell_value(ws, excel_r, EVAL_IMPORT_COL_ACQUIRED + 1, aq)
            elif materialize_computed:
                _set_cell_value(ws, excel_r, EVAL_IMPORT_COL_ACQUIRED + 1, "—")

            notes = ""
            if isinstance(srow, dict):
                notes = normalize_ar_header(str(srow.get("notes") or ""))
            if not notes:
                notes = normalize_ar_header(str(trow.get("notes_initial") or ""))
            if notes:
                _set_cell_value(ws, excel_r, EVAL_IMPORT_COL_NOTES + 1, notes)

            if materialize_computed:
                na = _is_na_acquired(aq)
                if not na and mx is not None and float(mx) > 0:
                    sum_max += float(mx)
                if na:
                    _write_system_pct_grade(ws, excel_r, None)
                elif aq is not None:
                    try:
                        aq_f = float(aq)
                    except (TypeError, ValueError):
                        aq_f = None
                    if aq_f is not None:
                        sum_acq += aq_f
                        any_acquired = True
                        if mx is not None and float(mx) > 0:
                            _write_system_pct_grade(
                                ws, excel_r, (aq_f / float(mx)) * 100.0
                            )
                        else:
                            _write_system_pct_grade(ws, excel_r, None)
                    else:
                        _write_system_pct_grade(ws, excel_r, None)
                else:
                    _write_system_pct_grade(ws, excel_r, None)
            elif (
                aq is not None
                and not _is_na_acquired(aq)
                and mx is not None
                and float(mx) > 0
            ):
                try:
                    aq_f = float(aq)
                    pct = (aq_f / float(mx)) * 100.0
                    g_cell = _writable_cell(ws, excel_r, EVAL_IMPORT_COL_PCT + 1)
                    h_cell = _writable_cell(ws, excel_r, EVAL_IMPORT_COL_GRADE + 1)
                    if not _cell_has_formula(g_cell):
                        g_cell.value = round(pct / 100.0, 4)
                    if not _cell_has_formula(h_cell):
                        h_cell.value = grade_label_from_percent(pct)
                except (TypeError, ValueError):
                    pass

        if materialize_computed:
            _fill_footer_system_totals(
                ws,
                sum_max=sum_max,
                sum_acq=sum_acq,
                any_acquired=any_acquired,
                start_row=footer_start,
                max_row=mr,
                max_col=mc,
            )
        if remove_grade_cf:
            try:
                ws.page_setup.paperSize = getattr(ws.page_setup, "PAPERSIZE_A4", 9)
                ws.page_setup.orientation = "portrait"
                ws.page_setup.fitToPage = True
                ws.page_setup.fitToWidth = 1
                ws.page_setup.fitToHeight = 1
                ws.sheet_properties.pageSetUpPr.fitToPage = True
            except Exception:
                pass

        # صف التذييل «المحكم» — اسم المحكم من صفحة قائمة التقييم
        _fill_footer_judge_name(ws, judge_name, max_row=mr, max_col=mc)
        tmp_sig = _embed_transparent_signature(
            ws, signature_png, max_row=mr, max_col=mc
        )
        if materialize_computed:
            _strip_workbook_formulas(wb)

        buf = io.BytesIO()
        try:
            wb.save(buf)
        finally:
            if tmp_sig:
                try:
                    Path(tmp_sig).unlink(missing_ok=True)
                except Exception:
                    pass
        buf.seek(0)
        data = buf.getvalue()
        if not materialize_computed:
            data = _restore_template_xlsx_parts(path, data)
        return data
    finally:
        try:
            wb.close()
        except Exception:
            pass
