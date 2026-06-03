"""مطابقة أعمدة ورقة تقييم Excel وخيارات عمود «المكتسبة»."""
from __future__ import annotations

from typing import Any


def normalize_ar_header(s: str) -> str:
    return " ".join((s or "").replace("\u00a0", " ").split())


def match_evaluation_sheet_columns(headers: list[str]) -> dict[str, int | None]:
    """
    يحدد فهارس أعمدة: عناصر التقييم، القصوى، المكتسبة (أول تطابق لكل نوع).
    """
    idx: dict[str, int | None] = {"elements": None, "max": None, "acquired": None}
    for i, raw in enumerate(headers):
        h = normalize_ar_header(raw)
        if idx["elements"] is None and _is_elements_header(h):
            idx["elements"] = i
            continue
        if idx["max"] is None and _is_max_header(h):
            idx["max"] = i
            continue
        if idx["acquired"] is None and _is_acquired_header(h):
            idx["acquired"] = i
            continue
    return idx


def _is_elements_header(h: str) -> bool:
    return (
        ("عناصر" in h and "تقييم" in h)
        or ("عنصر" in h and "تقييم" in h)
        or ("بنود" in h and "تقييم" in h)
        or ("عناصر" in h and "أداء" in h)
        or ("اسم" in h and "بند" in h)
        or h in ("البند", "بند", "البند الوصفي", "الوصف", "الوصف الوظيفي")
    )


def try_named_eval_column_indices(header_row: list[str]) -> tuple[tuple[int, int, int], str] | None:
    """صف فيه عناوين الأعمدة الثلاثة بالأسماء: عناصر التقييم، القصوى، المكتسبة."""
    m = match_evaluation_sheet_columns(header_row)
    if (
        m.get("elements") is not None
        and m.get("max") is not None
        and m.get("acquired") is not None
    ):
        return (
            (int(m["elements"]), int(m["max"]), int(m["acquired"])),
            "named",
        )
    return None


def _is_max_header(h: str) -> bool:
    if "مكتسب" in h:
        return False
    return "قصوى" in h or ("حد" in h and "أقصى" in h) or "max" in h.lower()


def _is_acquired_header(h: str) -> bool:
    return "مكتسب" in h or "محصل" in h or "منجز" in h


def resolve_evaluation_column_indices(
    header_row: list[str], ncol: int
) -> tuple[tuple[int, int, int], str] | None:
    """
    (فهرس عناصر التقييم، القصوى، المكتسبة) ومصدر التعيين:
    ``named`` عند مطابقة العناوين، أو ``first_three`` عند استخدام الأعمدة الثلاثة الأولى.
    يعيد ``None`` إذا كان عدد الأعمدة أقل من 3.
    """
    ncols = max(len(header_row), int(ncol or 0))
    if ncols < 3:
        return None
    m = match_evaluation_sheet_columns(header_row)
    if (
        m.get("elements") is not None
        and m.get("max") is not None
        and m.get("acquired") is not None
    ):
        return (
            (int(m["elements"]), int(m["max"]), int(m["acquired"])),
            "named",
        )
    return ((0, 1, 2), "first_three")


def acquired_select_options() -> list[tuple[str, str]]:
    """قيمة النموذج، النص المعروض."""
    opts: list[tuple[str, str]] = [("", "—"), ("na", "لا ينطبق")]
    for step in range(21):
        n = round(step * 0.25, 2)
        opts.append((_score_key(n), _score_label(n)))
    return opts


def _score_key(n: float) -> str:
    if n == int(n):
        return str(int(n))
    return f"{n:.2f}".rstrip("0").rstrip(".")


def _score_label(n: float) -> str:
    if n == int(n):
        return str(int(n))
    s = f"{n:.2f}"
    if s.endswith("0"):
        s = s.rstrip("0").rstrip(".")
    return s


def snap_cell_to_acquired_value(cell: str, *, cap_five: bool = True) -> str:
    """يطابق محتوى خلية الملف مع قيمة خيار القائمة أو رقمًا عامًا."""
    s = normalize_ar_header(cell)
    if not s:
        return ""
    if "لا" in s and "ينطبق" in s:
        return "na"
    s = s.replace(",", ".").replace("٫", ".")
    try:
        v = float(s)
    except ValueError:
        return ""
    if cap_five:
        v = max(0.0, min(5.0, v))
    else:
        v = max(0.0, v)
    v = round(v * 4.0) / 4.0
    return _score_key(v)


def parse_max_cell(s: str | None) -> float | None:
    """يستخرج الرقم من عمود القصوى."""
    t = normalize_ar_header(str(s or "")).replace(",", ".").replace("٫", ".")
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def resolve_rubric_subheader_indices(header_row: list[str]) -> tuple[int, int, int] | None:
    """
    صف يحتوي عناوين «القصوى» و«المكتسبة» (قوالب قائمة التقييم).
    يعيد (فهرس عمود عناصر التقييم، القصوى، المكتسبة) مع استنتاج عمود العناصر من العناوين إن وُجد.
    """
    i_mx: int | None = None
    i_aq: int | None = None
    for i, raw in enumerate(header_row):
        h = normalize_ar_header(raw)
        if not h:
            continue
        if i_mx is None and ("قصوى" in h) and ("مكتسب" not in h):
            i_mx = i
            continue
        if i_aq is None and ("مكتسب" in h or "محصل" in h or "منجز" in h):
            i_aq = i
            continue
    if i_mx is None or i_aq is None:
        return None
    # لا نفترض أن عمود العناصر هو A دائماً (غالباً عمود تسلسل أو «م» قبل «عناصر التقييم»).
    m = match_evaluation_sheet_columns(header_row)
    i_el = 0
    if m.get("elements") is not None:
        cand = int(m["elements"])
        if cand not in (i_mx, i_aq) and cand <= max(i_mx, i_aq):
            i_el = cand
    return (i_el, i_mx, i_aq)


# قالب قائمة التقييم العسكري الموحّد — أعمدة Excel (1-based → 0-based)
EVAL_IMPORT_COL_ELEMENTS = 1  # B
EVAL_IMPORT_COL_MAX = 4  # E
EVAL_IMPORT_COL_ACQUIRED = 5  # F
EVAL_IMPORT_COL_PCT = 6  # G
EVAL_IMPORT_COL_GRADE = 7  # H
EVAL_IMPORT_COL_NOTES = 8  # I

EVAL_IMPORT_SKIP_ROWS_1BASED = frozenset({1, 2, 3, 4, 7})

EVAL_IMPORT_SKIP_ROW_KEYWORDS: tuple[str, ...] = (
    "إجمالي العلام",
    "النسبة العامة",
    "النسبة المئوية الفعلية",
    "التقدير العام",
    "المحكم",
    "التوقيع",
    "ملاحظات",
)

# عند ظهور أي من هذه العلامات في عمود (ب) أو (ج) أو (د) يُوقَف الاستيراد (التذييل).
EVAL_IMPORT_FOOTER_STOP_MARKERS: tuple[str, ...] = (
    "إجمالي العلام",
    "النسبة العامة",
    "التقدير العام",
)


def _normalize_footer_text(s: str) -> str:
    t = normalize_ar_header(s or "")
    return t.replace("ـ", "").replace(":", "").replace("،", "").strip()


def _row_text_in_label_columns(cells: list[str], max_col: int = 4) -> str:
    parts: list[str] = []
    for ci in range(1, min(max_col, len(cells))):
        parts.append(_normalize_footer_text(cells[ci]))
    return " ".join(p for p in parts if p).strip()


def is_evaluation_import_footer_stop_row(cells: list[str]) -> bool:
    """صف يُنهي جسم الاستيراد (إجمالي / نسبة عامة / تقدير عام / ملاحظات / محكم / توقيع)."""
    label_blob = _row_text_in_label_columns(cells)
    if not label_blob:
        return False
    for marker in EVAL_IMPORT_FOOTER_STOP_MARKERS:
        if _normalize_footer_text(marker) in label_blob:
            return True
    if label_blob.startswith("ملاحظ") or "ملاحظات" in label_blob.split()[0:1]:
        return True
    if "ملاحظات" in label_blob and "1." in label_blob:
        return True
    if "المحكم" in label_blob:
        return True
    if "التوقيع" in label_blob:
        return True
    joined = _normalize_footer_text(" ".join(cells))
    for kw in EVAL_IMPORT_SKIP_ROW_KEYWORDS:
        if _normalize_footer_text(kw) in joined:
            return True
    return False


def import_body_end_row_index(
    grid: list[list[str]], *, rubric_row_index: int, ncol: int
) -> int:
    """فهرس (حصري) لنهاية بيانات التقييم قبل التذييل."""
    for ri in range(rubric_row_index + 1, len(grid)):
        cells = list(grid[ri])
        while len(cells) < ncol:
            cells.append("")
        if is_evaluation_import_footer_stop_row(cells):
            return ri
    return len(grid)


def military_template_column_indices(ncol: int) -> tuple[int, int, int, int, int, int] | None:
    """أعمدة B,E,F,G,H,I — يتطلب 9 أعمدة على الأقل (A..I)."""
    if ncol < 9:
        return None
    return (
        EVAL_IMPORT_COL_ELEMENTS,
        EVAL_IMPORT_COL_MAX,
        EVAL_IMPORT_COL_ACQUIRED,
        EVAL_IMPORT_COL_PCT,
        EVAL_IMPORT_COL_GRADE,
        EVAL_IMPORT_COL_NOTES,
    )


def should_skip_evaluation_import_row(
    cells: list[str], *, excel_row_1based: int
) -> bool:
    """صفوف/تذييل يُستبعد من استيراد قائمة التقييم."""
    if excel_row_1based in EVAL_IMPORT_SKIP_ROWS_1BASED:
        return True
    if is_evaluation_import_footer_stop_row(cells):
        return True
    label_blob = _row_text_in_label_columns(cells)
    for kw in EVAL_IMPORT_SKIP_ROW_KEYWORDS:
        if _normalize_footer_text(kw) in label_blob:
            return True
    # صف «عناصر التقييم» / «العلامات» دون بيانات بند (مثل الصف 5)
    el = _normalize_footer_text(
        cells[EVAL_IMPORT_COL_ELEMENTS] if len(cells) > EVAL_IMPORT_COL_ELEMENTS else ""
    )
    if "عناصر" in el and "تقييم" in el and parse_max_cell(
        cells[EVAL_IMPORT_COL_MAX] if len(cells) > EVAL_IMPORT_COL_MAX else ""
    ) is None:
        if excel_row_1based <= 6:
            return True
    # صف نسبة عامة بقيمة نسبة في عمود القصوى (0.xx) وليس علامة بند
    mx = parse_max_cell(cells[EVAL_IMPORT_COL_MAX] if len(cells) > EVAL_IMPORT_COL_MAX else "")
    if mx is not None and 0 < float(mx) < 1.0 and (
        "نسبة" in label_blob or "نسبة" in el
    ):
        return True
    return False


def parse_pct_cell(s: str | None) -> str:
    """نسبة من Excel: قد تكون 0.8 أو 80% أو 80."""
    t = normalize_ar_header(str(s or "")).replace("%", "").replace(",", ".").replace("٫", ".")
    if not t:
        return ""
    try:
        v = float(t)
    except ValueError:
        return ""
    if 0 < v <= 1.0:
        v *= 100.0
    return str(round(v, 2)).rstrip("0").rstrip(".")


def parse_grade_cell(s: str | None) -> str:
    """تقدير من عمود النتيجة — للعرض الأولي فقط."""
    t = normalize_ar_header(str(s or ""))
    if not t:
        return ""
    t = t.replace("جيد جداً", "جيد جدا").replace("جيد جداٌ", "جيد جدا")
    return t


def build_structured_rows(
    body_rows: list[list[str]],
    ncol: int,
    i_el: int,
    i_mx: int,
    i_aq: int,
    *,
    acquired_cap_five: bool = True,
    i_pct: int | None = None,
    i_grade: int | None = None,
    i_notes: int | None = None,
    body_start_row_1based: int = 1,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for offset, r in enumerate(body_rows):
        cells = list(r)
        while len(cells) < ncol:
            cells.append("")
        excel_row = body_start_row_1based + offset
        if should_skip_evaluation_import_row(cells, excel_row_1based=excel_row):
            continue
        row: dict[str, Any] = {
            "element": cells[i_el] if i_el < len(cells) else "",
            "max_val": cells[i_mx] if i_mx < len(cells) else "",
            "acquired_initial": snap_cell_to_acquired_value(
                cells[i_aq] if i_aq < len(cells) else "",
                cap_five=acquired_cap_five,
            ),
        }
        if i_pct is not None:
            row["pct_initial"] = parse_pct_cell(cells[i_pct] if i_pct < len(cells) else "")
        if i_grade is not None:
            row["grade_initial"] = parse_grade_cell(
                cells[i_grade] if i_grade < len(cells) else ""
            )
        if i_notes is not None:
            row["notes_initial"] = normalize_ar_header(
                cells[i_notes] if i_notes < len(cells) else ""
            )
        rows.append(row)
    return rows


def annotate_evaluation_row_kinds(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """يصنّف كل صف: score (له قصوى رقمية > 0) أو section (عنوان فرعي فقط)."""
    out: list[dict[str, Any]] = []
    for r in rows:
        mx = parse_max_cell(r.get("max_val"))
        el = (r.get("element") or "").strip()
        if mx is not None and mx > 0:
            out.append({**r, "row_kind": "score", "max_num": mx})
        elif el:
            out.append({**r, "row_kind": "section", "max_num": None})
        else:
            aq = (r.get("acquired_initial") or "").strip()
            if not aq:
                continue
            out.append({**r, "row_kind": "section", "max_num": None})
    return out


def grade_label_from_percent(pct: float | None) -> str:
    """
    تقدير النتيجة من النسبة المئوية لقائمة التقييم.
    """
    if pct is None:
        return "غير محسوب"
    if pct < 60:
        return "راسب"
    if pct < 70:
        return "مقبول"
    if pct < 80:
        return "جيد"
    if pct < 90:
        return "جيد جدا"
    return "ممتاز"


_NON_APPROVABLE_GRADES = frozenset({"راسب", "مقبول", "متوسط"})


def display_grade_label(label: str | None) -> str:
    """عرض التقدير — يوحّد «متوسط» القديم إلى «مقبول»."""
    g = (label or "").strip()
    if g == "متوسط":
        return "مقبول"
    return g


def grade_allows_judge_approve(
    grade_label: str | None = None,
    *,
    total_pct: float | None = None,
) -> bool:
    """الاعتماد مسموح فقط لتقديرات جيد فما فوق (لا راسب ولا مقبول)."""
    if total_pct is not None:
        return grade_label_from_percent(float(total_pct)) not in _NON_APPROVABLE_GRADES
    g = display_grade_label(grade_label)
    if not g or g == "غير محسوب":
        return False
    return g not in _NON_APPROVABLE_GRADES
