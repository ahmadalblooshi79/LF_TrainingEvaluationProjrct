"""اختبارات استيراد قائمة التقييم من Excel (قالب B,E,F,G,H,I)."""
from __future__ import annotations

from app.evaluation_list_columns import (
    build_structured_rows,
    is_evaluation_import_footer_stop_row,
    military_template_column_indices,
    should_skip_evaluation_import_row,
)


def test_military_column_indices():
    assert military_template_column_indices(9) == (1, 4, 5, 6, 7, 8)
    assert military_template_column_indices(8) is None


def test_skip_meta_and_footer_rows():
    meta = ["", "وحدة", "", "", "", "", "", "", "", ""]
    assert should_skip_evaluation_import_row(meta, excel_row_1based=2)
    assert should_skip_evaluation_import_row(
        ["", "إجمالي العلامات المكتسبة", "", "", "150", "107.5", "", "", "", ""],
        excel_row_1based=34,
    )
    assert should_skip_evaluation_import_row(
        ["", "", "", "", "", "", "", "", "", ""],
        excel_row_1based=7,
    )


def test_footer_stop_with_tatweel_and_notes():
    pct_row = ["", "النسبــــة العامــــــة", "", "", "0.7166666666666667", "", "", "", "", ""]
    assert is_evaluation_import_footer_stop_row(pct_row)
    assert should_skip_evaluation_import_row(pct_row, excel_row_1based=35)
    notes_row = [
        "",
        "ملاحظـــات: \n1. تقييم مستوى الوحدة من خلال مراقبة الآداء أو طرح الأسئلة.",
        "",
        "",
        "المحكـــــــــم:",
        "",
        "",
        "",
        "",
        "",
    ]
    assert is_evaluation_import_footer_stop_row(notes_row)
    assert should_skip_evaluation_import_row(notes_row, excel_row_1based=37)


def test_build_structured_rows_imports_notes_and_scores():
    body = [
        ["", "بند 1", "", "", "5", "4", "0.8", "جيد جدا", "ملاحظة", ""],
        ["", "", "", "", "10", "7", "0.7", "جيد", "", ""],
    ]
    mil = military_template_column_indices(10)
    assert mil is not None
    i_el, i_mx, i_aq, i_pct, i_grade, i_notes = mil
    rows = build_structured_rows(
        body,
        10,
        i_el,
        i_mx,
        i_aq,
        acquired_cap_five=False,
        i_pct=i_pct,
        i_grade=i_grade,
        i_notes=i_notes,
        body_start_row_1based=9,
    )
    assert len(rows) == 2
    assert rows[0]["element"] == "بند 1"
    assert rows[0]["max_val"] == "5"
    assert rows[0]["acquired_initial"] == "4"
    assert rows[0]["notes_initial"] == "ملاحظة"
    assert rows[0]["grade_initial"] == "جيد جدا"
