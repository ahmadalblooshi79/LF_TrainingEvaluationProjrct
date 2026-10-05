import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from openpyxl import Workbook, load_workbook

from app.evaluation_list_export import (
    build_evaluation_list_xlsx_bytes,
    export_download_filename,
)
from app.evaluation_sheet_parser import read_evaluation_list_sheet


def _write_sample_eval_xlsx(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "قائمة التقييم"
    ws["B1"] = "عنوان القائمة"
    ws["B2"] = "عناصــــــر التقييـــــم"
    ws["E2"] = "العلامـــــــات"
    ws["I2"] = "ملاحظــــــات"
    ws["E3"] = "القصوى"
    ws["F3"] = "المكتسبة"
    ws["G3"] = "النسبة"
    ws["H3"] = "النتيجة"
    ws["B4"] = "( أ )"
    ws["E4"] = "(ب)"
    ws["F4"] = "(جـ)"
    for i in range(1, 5):
        r = 4 + i
        ws[f"B{r}"] = f"{i}. بند"
        ws[f"E{r}"] = 5
        ws[f"F{r}"] = "أدخل العلامة"
        ws[f"G{r}"] = f'=IFERROR(F{r}/E{r},"")'
        ws[f"G{r}"].number_format = "0%"
        ws[f"H{r}"] = f'=_xlfn.IFS(G{r}>=90%,"ممتاز",G{r}>=80%,"جيد جدا",G{r}>=70%,"جيد",G{r}>=60%,"مقبول",G{r}<60%,"راسب")'
    ws["B9"] = "إجمالي العلامات"
    ws["E9"] = "=SUM(E5:E8)"
    ws["F9"] = "=SUM(F5:F8)"
    ws["B10"] = "النسبة العامة"
    ws["E10"] = "=F9/E9"
    ws["E10"].number_format = "0.00%"
    ws["B11"] = "التقدير العام"
    ws["E11"] = '=_xlfn.IFS(E10>=90%,"ممتاز",E10>=80%,"جيد جدا",E10>=70%,"جيد",E10>=60%,"مقبول",E10<60%,"راسب")'
    ws["E12"] = "المحكم:"
    ws["G12"] = "أدخل اسم المحكم"
    ws["E13"] = "التوقيع:"
    wb.save(path)
    wb.close()


class EvaluationListPdfExportTests(unittest.TestCase):
    def test_download_filename_pdf_ext(self):
        self.assertTrue(export_download_filename("قائمة.xlsx", ext="pdf").endswith(".pdf"))
        self.assertTrue(export_download_filename("قائمة", ext="pdf").endswith(".pdf"))

    def test_materialize_uses_system_scores_and_totals(self):
        with TemporaryDirectory() as td:
            src = Path(td) / "src.xlsx"
            _write_sample_eval_xlsx(src)
            eval_rows = read_evaluation_list_sheet(src).get("eval_rows") or []
            saved = [
                {"acquired": "4", "notes": "", "row_kind": "score"},
                {"acquired": "4.25", "notes": "", "row_kind": "score"},
                {"acquired": "3.5", "notes": "", "row_kind": "score"},
                {"acquired": "5", "notes": "", "row_kind": "score"},
            ]
            data = build_evaluation_list_xlsx_bytes(
                src,
                doc_title="عنوان القائمة",
                unit_label="وحدة",
                date_str="2026-09-21",
                commander_name="قائد",
                judge_name="سالم",
                eval_rows=eval_rows,
                saved_rows=saved,
                materialize_computed=True,
            )
        wb = load_workbook(io.BytesIO(data))
        try:
            ws = wb.active
            self.assertEqual(ws["F5"].value, 4)
            self.assertEqual(ws["G5"].value, 0.8)
            self.assertEqual(ws["H5"].value, "جيد جدا")
            self.assertEqual(ws["F6"].value, 4.25)
            self.assertEqual(ws["H6"].value, "جيد جدا")
            self.assertIn("BAE6FD", str(ws["H6"].fill.fgColor.rgb or "").upper())
            self.assertEqual(ws["H8"].value, "ممتاز")
            self.assertIn("BBF7D0", str(ws["H8"].fill.fgColor.rgb or "").upper())
            self.assertEqual(ws["E9"].value, 20)
            self.assertEqual(ws["F9"].value, 16.75)
            self.assertAlmostEqual(float(ws["E10"].value), 16.75 / 20.0, places=5)
            self.assertEqual(ws["E11"].value, "جيد جدا")
            self.assertEqual(ws["G12"].value, "سالم")
            self.assertFalse(str(ws["G5"].value).startswith("="))
            self.assertFalse(str(ws["E11"].value).startswith("="))
        finally:
            wb.close()

    def test_excel_export_excludes_na_from_max_and_acquired_totals(self):
        with TemporaryDirectory() as td:
            src = Path(td) / "src.xlsx"
            _write_sample_eval_xlsx(src)
            eval_rows = read_evaluation_list_sheet(src).get("eval_rows") or []
            saved = [
                {"acquired": "4", "notes": "", "row_kind": "score"},
                {"acquired": "4.25", "notes": "", "row_kind": "score"},
                {"acquired": "3.5", "notes": "", "row_kind": "score"},
                {"acquired": "na", "notes": "", "row_kind": "score"},
            ]
            data = build_evaluation_list_xlsx_bytes(
                src,
                doc_title="عنوان القائمة",
                unit_label="وحدة",
                date_str="2026-09-21",
                commander_name="قائد",
                judge_name="سالم",
                eval_rows=eval_rows,
                saved_rows=saved,
                materialize_computed=True,
            )
        wb = load_workbook(io.BytesIO(data))
        try:
            ws = wb.active
            self.assertEqual(ws["F8"].value, "لا ينطبق")
            self.assertEqual(ws["G8"].value, "—")
            self.assertEqual(ws["H8"].value, "غير محسوب")
            self.assertEqual(ws["G5"].value, 0.8)
            self.assertEqual(ws["H5"].value, "جيد جدا")
            self.assertFalse(str(ws["G5"].value).startswith("="))
            self.assertFalse(str(ws["H5"].value).startswith("="))
            self.assertEqual(ws["E9"].value, 15)
            self.assertEqual(ws["F9"].value, 11.75)
            self.assertAlmostEqual(float(ws["E10"].value), 11.75 / 15.0, places=5)
            self.assertEqual(ws["E11"].value, "جيد")
            self.assertNotEqual(ws["E9"].value, 20)
        finally:
            wb.close()

    def test_military_template_not_mutated_by_narrative_insert(self):
        """القوالب العسكرية (وحدة/قائد/مجرى أحداث) تُصدَّر دون إدراج صفوف وصف النظام."""
        with TemporaryDirectory() as td:
            src = Path(td) / "military.xlsx"
            wb = Workbook()
            ws = wb.active
            ws.title = "قائمة التقييم"
            ws["B1"] = "13. تقييم إنقاذ وإخلاء المصابين"
            ws["B2"] = "الوحدة"
            ws["C2"] = "فصيل الطبية /1"
            ws["E2"] = "التاريخ"
            ws["F2"] = "2026-09-23"
            ws["B3"] = "قائد الوحدة"
            ws["C3"] = "أدخل اسم قائد الوحدة الخاضعة للتقييم"
            ws["E3"] = "المحكم"
            ws["F3"] = "أدخل اسم المحكم"
            ws["B4"] = "مجرى الأحداث والمعاضل"
            ws["E4"] = "رقم المعضلة"
            ws["B5"] = "نوع التمرين"
            ws["B7"] = "عناصــــــر التقييـــــم"
            ws["E7"] = "القصوى"
            ws["F7"] = "المكتسبة"
            ws["B8"] = "1. بند"
            ws["E8"] = 3
            ws["F8"] = "أدخل العلامة"
            ws["B20"] = "التقدير العام"
            ws["E20"] = "راسب"
            wb.save(src)
            wb.close()

            data = build_evaluation_list_xlsx_bytes(
                src,
                doc_title="13. تقييم إنقاذ وإخلاء المصابين",
                unit_label="فصيل الطبية /1",
                date_str="2026-09-23",
                commander_name="قائد",
                judge_name="محكم",
                eval_rows=[{"row_kind": "score", "max_num": 3}],
                saved_rows=[{"acquired": None, "notes": ""}],
                dilemma_description="يجب ألا يُكتب هنا فوق القالب",
                dilemma_requirements="ولا هنا",
            )
        out = load_workbook(io.BytesIO(data))
        try:
            ws = out.active
            self.assertEqual(ws["B2"].value, "الوحدة")
            self.assertNotIn("وصف المعضلة", str(ws["B2"].value or ""))
            self.assertEqual(ws["B3"].value, "قائد الوحدة")
            self.assertEqual(ws["B4"].value, "مجرى الأحداث والمعاضل")
            self.assertEqual(ws["C2"].value, "فصيل الطبية /1")
        finally:
            out.close()

    def test_military_inspection_template_writes_system_values_without_formulas(self):
        with TemporaryDirectory() as td:
            src = Path(td) / "n.xlsx"
            wb = Workbook()
            ws = wb.active
            ws.title = "قائمة التقييم"
            ws.merge_cells("B1:J1")
            ws["B1"] = "تقييم معضلة تعرض فرد للدغة عقرب"
            ws["B2"] = "وصف المعضلة: نص"
            ws["B3"] = "متطلبات تنفيذ المعضلة: تفرض المعضلة من قبل المحكم شفهياً."
            ws["B4"] = "الوحدة:"
            ws["C4"] = "أدخل الوحدة الخاضعة للتقييم"
            ws["E4"] = "التاريخ:"
            ws["F4"] = "اليوم"
            ws["H4"] = "الشهر"
            ws["J4"] = "السنة"
            ws["B5"] = "قائد الوحدة:"
            ws["C5"] = "أدخل اسم قائد الوحدة"
            ws["E5"] = "المحكم:"
            ws["F5"] = "أدخل اسم المحكم"
            ws["B8"] = "عناصــــــر التقييـــــم"
            ws["E8"] = "العلامـــــــات"
            ws["I8"] = "ملاحظــــــات"
            ws["E9"] = "القصوى"
            ws["F9"] = "المكتسبة"
            ws["G9"] = "النسبة"
            ws["H9"] = "النتيجة"
            items = [
                "1. إجراء الإسعاف الأولي",
                "2. ربط المنطقة",
                "3. إخلاء المصابين",
                "4. يفترض المحكم وفاة المصاب عند تأخر الإخلاء.",
                "5. إسعاف المصاب",
                "6. إبلاغ مركز التسمم",
                "7. رفع تقرير",
                "8. تفعيل دور الصحة العامة",
            ]
            for i, title in enumerate(items, start=11):
                ws[f"B{i}"] = title
                ws[f"E{i}"] = 3
                ws[f"F{i}"] = "أدخل العلامة"
                ws[f"G{i}"] = f'=IFERROR(F{i}/E{i},"")'
                ws[f"H{i}"] = (
                    f'=IFS(F{i}="أدخل العلامة","",F{i}="لا ينطبق","تم الإلغاء",'
                    f'G{i}>=90%,"ممتاز",G{i}<60%,"راسب")'
                )
            ws["B19"] = "إجمالي العلامات"
            ws["E19"] = "=SUM(E11:E18)"
            ws["F19"] = "=SUM(F11:F18)"
            ws["B20"] = "النسبة العامة"
            ws["E20"] = "=F19/E19"
            extra = wb.create_sheet("بيانات التقييم")
            extra["A1"] = "أدخل الوحدة الخاضعة للتقييم"
            extra["A2"] = "سرية القناصة"
            extra["A3"] = "=A2"
            wb.save(src)
            wb.close()

            eval_rows = read_evaluation_list_sheet(src).get("eval_rows") or []
            scores = [r for r in eval_rows if r.get("row_kind") == "score"]
            self.assertEqual(len(scores), 8)
            saved = [
                {"acquired": "2", "notes": "", "row_kind": r.get("row_kind") or "score"}
                for r in eval_rows
            ]
            data = build_evaluation_list_xlsx_bytes(
                src,
                doc_title="تقييم معضلة تعرض فرد للدغة عقرب",
                unit_label="سرية القناصة",
                date_str="2026-09-21",
                commander_name="قائد الوحدة",
                judge_name="علي حميد",
                eval_rows=eval_rows,
                saved_rows=saved,
            )
        out = load_workbook(io.BytesIO(data))
        try:
            self.assertEqual(out.sheetnames, ["قائمة التقييم", "بيانات التقييم"])
            ws = out["قائمة التقييم"]
            self.assertEqual(ws["C4"].value, "سرية القناصة")
            self.assertEqual(ws["F4"].value, 21)
            self.assertEqual(ws["H4"].value, 9)
            self.assertEqual(ws["J4"].value, 2026)
            self.assertEqual(ws["C5"].value, "قائد الوحدة")
            self.assertEqual(ws["F5"].value, "علي حميد")
            for r in range(11, 19):
                self.assertEqual(ws[f"B{r}"].value, items[r - 11])
                self.assertEqual(ws[f"E{r}"].value, 3)
                self.assertEqual(ws[f"F{r}"].value, 2)
                self.assertAlmostEqual(float(ws[f"G{r}"].value), 2 / 3, places=5)
                self.assertEqual(ws[f"H{r}"].value, "مقبول")
                self.assertFalse(str(ws[f"G{r}"].value).startswith("="))
                self.assertFalse(str(ws[f"H{r}"].value).startswith("="))
            self.assertEqual(ws["E19"].value, 24)
            self.assertEqual(ws["F19"].value, 16)
            self.assertAlmostEqual(float(ws["E20"].value), 16 / 24, places=5)
            self.assertFalse(str(ws["E19"].value).startswith("="))
            extra_ws = out["بيانات التقييم"]
            self.assertEqual(extra_ws["A2"].value, "سرية القناصة")
            self.assertIsNone(extra_ws["A3"].value)
            for row in ws.iter_rows(min_row=1, max_row=22, max_col=10, values_only=True):
                for val in row:
                    if isinstance(val, str):
                        self.assertFalse(val.startswith("="), val)
        finally:
            out.close()

    def test_pdf_fallback_produces_pdf(self):
        from app.evaluation_list_pdf import build_evaluation_list_pdf_bytes

        with TemporaryDirectory() as td:
            src = Path(td) / "src.xlsx"
            _write_sample_eval_xlsx(src)
            eval_rows = read_evaluation_list_sheet(src).get("eval_rows") or []
            saved = [{"acquired": "4", "notes": "ملاحظة", "row_kind": "score"} for _ in eval_rows]
            xlsx = build_evaluation_list_xlsx_bytes(
                src,
                doc_title="عنوان القائمة",
                unit_label="وحدة",
                date_str="2026-09-21",
                commander_name="قائد",
                judge_name="سالم",
                eval_rows=eval_rows,
                saved_rows=saved,
                materialize_computed=True,
            )
        with patch("app.evaluation_list_pdf.convert_xlsx_bytes_to_pdf", return_value=None):
            pdf = build_evaluation_list_pdf_bytes(xlsx)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 500)


if __name__ == "__main__":
    unittest.main()
