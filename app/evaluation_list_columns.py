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
        or h in ("البند", "بند", "البند الوصفي", "الوصف")
    )


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


def snap_cell_to_acquired_value(cell: str) -> str:
    """يطابق محتوى خلية الملف مع قيمة خيار القائمة."""
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
    v = max(0.0, min(5.0, v))
    v = round(v * 4.0) / 4.0
    return _score_key(v)


def build_structured_rows(
    body_rows: list[list[str]],
    ncol: int,
    i_el: int,
    i_mx: int,
    i_aq: int,
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
                    cells[i_aq] if i_aq < len(cells) else ""
                ),
            }
        )
    return rows


def grade_label_from_percent(pct: float | None) -> str:
    """
    تقدير النتيجة من النسبة (0 = 0٪، 5 نقاط = 100٪).
    حدود تقريبية شائعة للدرجات الحرفية.
    """
    if pct is None:
        return "غير محسوب"
    if pct < 50:
        return "راسب"
    if pct < 65:
        return "مقبول"
    if pct < 75:
        return "جيد"
    if pct < 90:
        return "جيد جدا"
    return "ممتاز"
