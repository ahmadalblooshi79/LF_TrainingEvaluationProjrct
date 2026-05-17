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


def build_structured_rows(
    body_rows: list[list[str]],
    ncol: int,
    i_el: int,
    i_mx: int,
    i_aq: int,
    *,
    acquired_cap_five: bool = True,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for r in body_rows:
        cells = list(r)
        while len(cells) < ncol:
            cells.append("")
        rows.append(
            {
                "element": cells[i_el] if i_el < len(cells) else "",
                "max_val": cells[i_mx] if i_mx < len(cells) else "",
                "acquired_initial": snap_cell_to_acquired_value(
                    cells[i_aq] if i_aq < len(cells) else "",
                    cap_five=acquired_cap_five,
                ),
            }
        )
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
        return "متوسط"
    if pct < 80:
        return "جيد"
    if pct < 90:
        return "جيد جدا"
    return "ممتاز"
