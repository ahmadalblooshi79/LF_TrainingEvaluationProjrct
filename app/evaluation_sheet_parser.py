"""
قراءة ورقة قائمة تقييم Excel مع دعم القوالب التي تبدأ بصفوف تعريف (وحدة، تاريخ…)
ثم صف عناوين «القصوى / المكتسبة» — كما في النماذج العسكرية الموحدة.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.evaluation_list_columns import (
    annotate_evaluation_row_kinds,
    build_structured_rows,
    normalize_ar_header,
    parse_max_cell,
    resolve_evaluation_column_indices,
    resolve_rubric_subheader_indices,
)
from app.xlsx_grid_preview import read_xlsx_sheet_preview


def _pad_grid(grid: list[list[str]], ncol: int) -> list[list[str]]:
    out: list[list[str]] = []
    for r in grid:
        cells = list(r)
        while len(cells) < ncol:
            cells.append("")
        out.append(cells[:ncol])
    return out


def _find_rubric_subheader_row_index(grid: list[list[str]]) -> int | None:
    for ri, row in enumerate(grid):
        parts = [normalize_ar_header(c) for c in row]
        joined = " ".join(parts)
        if "قصوى" in joined and "مكتسب" in joined:
            return ri
    return None


def read_evaluation_list_sheet(path: Path, *, sheet_index: int = 0) -> dict[str, Any]:
    """
    يعيد نفس مفاتيح ``read_xlsx_sheet_preview`` تقريبًا، مع:
    - ``eval_layout``: ``rubric`` | ``legacy``
    - ``eval_structured``, ``eval_rows``, ``eval_column_source``, ``eval_input_mode``
    """
    base = read_xlsx_sheet_preview(path, sheet_index=sheet_index)
    out: dict[str, Any] = dict(base)
    out["eval_layout"] = "legacy"
    out["eval_structured"] = False
    out["eval_rows"] = []
    out["eval_column_source"] = None
    out["eval_input_mode"] = "scale5"

    if base.get("error"):
        return out

    grid = base.get("grid_rows") or []
    if not grid:
        return out

    ncol = max(int(base.get("ncol") or 0), max((len(r) for r in grid), default=0))
    ncol = max(ncol, 1)
    grid = _pad_grid(grid, ncol)
    out["ncol"] = ncol
    out["header_row"] = grid[0]
    out["body_rows"] = grid[1:] if len(grid) > 1 else []

    rubric_i = _find_rubric_subheader_row_index(grid)

    if rubric_i is not None:
        sub_header = grid[rubric_i]
        triple_r = resolve_rubric_subheader_indices(sub_header)
        if triple_r is not None:
            i_el, i_mx, i_aq = triple_r
            src = "rubric_subheader"
            acquired_cap_five = False
        else:
            resolved = resolve_evaluation_column_indices(sub_header, ncol)
            if resolved is None:
                return out
            (i_el, i_mx, i_aq), src = resolved
            acquired_cap_five = True

        body_rows = grid[rubric_i + 1 :]
        raw_rows = build_structured_rows(
            body_rows, ncol, i_el, i_mx, i_aq, acquired_cap_five=acquired_cap_five
        )
        eval_rows = annotate_evaluation_row_kinds(raw_rows)
        if not eval_rows and raw_rows:
            eval_rows = [
                {
                    **r,
                    "row_kind": "score",
                    "max_num": parse_max_cell(r.get("max_val")),
                }
                for r in raw_rows
            ]
        out["eval_rows"] = eval_rows
        out["eval_structured"] = len(eval_rows) > 0
        out["eval_column_source"] = src
        out["eval_layout"] = "rubric"
        out["eval_input_mode"] = "variable"
        out["body_rows"] = body_rows
        return out

    header_row = grid[0]
    resolved = resolve_evaluation_column_indices(header_row, ncol)
    if resolved is None:
        return out
    (i_el, i_mx, i_aq), src = resolved
    body_rows = grid[1:]
    raw_rows = build_structured_rows(
        body_rows, ncol, i_el, i_mx, i_aq, acquired_cap_five=True
    )
    eval_rows = [
        {
            **r,
            "row_kind": "score",
            "max_num": parse_max_cell(r.get("max_val")),
        }
        for r in raw_rows
    ]
    out["eval_rows"] = eval_rows
    out["eval_structured"] = len(eval_rows) > 0
    out["eval_column_source"] = src
    out["eval_layout"] = "legacy"
    out["eval_input_mode"] = "scale5"
    out["body_rows"] = body_rows
    return out


def ratio_to_performance_band(ratio: float) -> str:
    """نطاق أداء البند من النسبة المكتسبة/القصوى (0..1) — يطابق حدود النتائج الشائعة."""
    pct = max(0.0, min(100.0, float(ratio) * 100.0))
    if pct < 50:
        return "راسب"
    if pct < 65:
        return "مقبول"
    if pct < 75:
        return "جيد"
    if pct < 90:
        return "جيد_جدا"
    return "ممتاز"


def extract_rubric_classification_dataset(
    paths: list[Path],
    *,
    sheet_index: int = 0,
) -> tuple[list[list[Any]], list[str], list[str], str]:
    """
    يستخرج من كل ملف بنود التقييم ذات قصوى رقمية وعلامة مكتسبة مدخلة.
    الميزات: [نص البند، القصوى كرقم]. الهدف: نطاق الأداء من نسبة (مكتسب÷قصوى).

    يعيد (صفوف_X، قائمة_y، أسماء_الميزات، رسالة_خطأ).
    """
    xs: list[list[Any]] = []
    ys: list[str] = []
    feat_names = ["بند", "القصوى"]

    for p in paths:
        info = read_evaluation_list_sheet(p, sheet_index=sheet_index)
        if info.get("error") or not info.get("eval_structured"):
            continue
        for row in info.get("eval_rows") or []:
            if row.get("row_kind") != "score":
                continue
            mx = row.get("max_num")
            if mx is None:
                mx = parse_max_cell(row.get("max_val"))
            if mx is None or float(mx) <= 0:
                continue
            aq_raw = (row.get("acquired_initial") or "").strip()
            if not aq_raw or aq_raw == "na":
                continue
            try:
                aq_s = aq_raw.replace(",", ".").replace("٫", ".")
                aq = float(aq_s)
            except ValueError:
                continue
            mx_f = float(mx)
            aq = max(0.0, min(mx_f, aq))
            ratio = aq / mx_f if mx_f > 0 else 0.0
            el = (row.get("element") or "").strip() or "___فارغ___"
            xs.append([el, float(mx)])
            ys.append(ratio_to_performance_band(ratio))

    if not ys:
        return (
            [],
            [],
            feat_names,
            "لم يُستخرج أي بند فيه علامة مكتسبة من ملفات الإكسل (إن كانت القوالب فارغة عندك، جرّب التدريب من نتائج النظام المحفوظة: --format saved).",
        )
    return xs, ys, feat_names, ""
