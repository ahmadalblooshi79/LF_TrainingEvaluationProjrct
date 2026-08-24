"""عنوان قائمة التقييم: سطر من ملف Excel وسطر من معلومات التمرين."""
from __future__ import annotations

from types import SimpleNamespace

from app.evaluation_list_columns import (
    compose_eval_doc_banner_text,
    eval_doc_title_first_line,
    extract_eval_doc_title_from_grid,
    format_eval_exercise_subtitle,
    format_eval_exercise_subtitle_from_exercise,
)
from app.evaluation_list_export import export_eval_doc_banner_title


def test_eval_doc_title_first_line_keeps_excel_row():
    raw = "قائمة تقييم رفع الحالة\nتمرين تكتيكي الوحدة الأولى اسم التمرين"
    assert eval_doc_title_first_line(raw) == "قائمة تقييم رفع الحالة"


def test_extract_eval_doc_title_ignores_second_line():
    grid = [[
        "",
        "عنوان من ملف الإكسل\nنوع الوحدة اسم",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
    ]]
    assert extract_eval_doc_title_from_grid(grid) == "عنوان من ملف الإكسل"


def test_format_eval_exercise_subtitle_order():
    text = format_eval_exercise_subtitle("تمرين تكتيكي", "اللواء الأول", "تمرين الهجوم")
    assert text == "تمرين تكتيكي اللواء الأول تمرين الهجوم"


def test_format_eval_exercise_subtitle_skips_empty():
    assert format_eval_exercise_subtitle("", "اللواء الأول", "تمرين الهجوم") == "اللواء الأول تمرين الهجوم"
    assert format_eval_exercise_subtitle_from_exercise(None) == ""
    ex = SimpleNamespace(exercise_type="نوع", trained_unit="وحدة", title="اسم")
    assert format_eval_exercise_subtitle_from_exercise(ex) == "نوع وحدة اسم"


def test_compose_and_export_banner_two_lines():
    composed = compose_eval_doc_banner_text("عنوان القائمة.xlsx", "نوع وحدة اسم")
    assert composed.split("\n") == ["عنوان القائمة.xlsx", "نوع وحدة اسم"]
    exported = export_eval_doc_banner_title(
        excel_title="عنوان من الإكسل",
        exercise_subtitle="نوع وحدة اسم",
        item_title_fallback="01 قائمة.xlsx",
    )
    assert exported == "عنوان من الإكسل\nنوع وحدة اسم"


def test_export_banner_falls_back_to_item_title():
    exported = export_eval_doc_banner_title(
        excel_title="",
        exercise_subtitle="نوع وحدة اسم",
        item_title_fallback="01 تقييم رفع الحالة.xlsx",
    )
    assert exported == "01 تقييم رفع الحالة\nنوع وحدة اسم"
