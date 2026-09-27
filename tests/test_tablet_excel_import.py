import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook

from app.tablet_excel_import import METADATA_SHEET, _read_xlsx_bytes, _source_from_meta


class TabletExcelParseTests(unittest.TestCase):
    def test_metadata_and_rows_roundtrip(self):
        wb = Workbook()
        ws = wb.active
        ws.title = "تقييم القيادة والسيطرة"
        ws.append(["م", "نوع الصف", "عناصر التقييم", "القصوى", "المكتسبة", "الملاحظات"])
        ws.append(["1", "criterion", "قيادة", "10", "7", "جيد"])
        meta = wb.create_sheet(METADATA_SHEET)
        meta.append(["key", "value"])
        meta.append(["export_format_version", "1"])
        meta.append(["eval_item_id", "180"])
        meta.append(["unit_id", "snipers"])
        meta.append(["unit_name", "سرية القناصة"])
        meta.append(["evaluation_list_name", "تقييم القيادة والسيطرة"])
        meta.append(["evaluation_type", "evaluation_list"])
        meta.append(["client_op_id", "op-180"])
        meta.sheet_state = "hidden"
        buf = BytesIO()
        wb.save(buf)
        meta_map, rows, _name = _read_xlsx_bytes(buf.getvalue())
        self.assertEqual(meta_map["eval_item_id"], "180")
        self.assertEqual(meta_map["unit_name"], "سرية القناصة")
        self.assertEqual(rows[0]["acquired"], "7")
        src = _source_from_meta(meta_map, rows)
        self.assertEqual(src.eval_item_id, 180)
        self.assertEqual(src.client_op_id, "op-180")


if __name__ == "__main__":
    unittest.main()
