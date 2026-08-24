"""استيراد مجرى الأحداث: عمود المكلف يُحدَّد بالعنوان لا بترتيبه."""
from __future__ import annotations

import unittest

from io import BytesIO
from xml.etree import ElementTree as ET
import zipfile

from app.planner_flow_docx_import import (
    _W,
    _W_NS,
    _col_map_from_header_row,
    _has_numbered_dilemma,
    _has_numbered_event,
    _logical_rows_from_tbl,
    _map_data_row,
    parse_planner_flow_docx_bytes,
)


class PlannerFlowAssigneeColTests(unittest.TestCase):
    def test_assignee_column_detected_by_header_fourth(self):
        headers = [
            "ت",
            "الوقت",
            "وصف الحدث/ المعضلة",
            "المكلف بالإجراء والمتابعة",
            "أسلوب فرض المعضلة",
            "رد الفعل المتوقع",
        ]
        cmap = _col_map_from_header_row(headers)
        self.assertEqual(cmap["assignee"], 3)
        row = _map_data_row(
            ["", "0800", "وصف", "محكم الاستطلاع", "فرض", "تعامل"],
            cmap,
        )
        self.assertEqual(row["assignee"], "محكم الاستطلاع")
        self.assertEqual(row["description"], "وصف")
        self.assertEqual(row["time"], "0800")

    def test_assignee_column_detected_by_header_eighth_wargame(self):
        headers = [
            "ت",
            "التوقيت الحقيقي",
            "توقيت نظام كورا",
            "من",
            "إلى",
            "أنظمة التبليغ",
            "وصف المعضلة/الحدث",
            "المكلف بالإجراء والمتابعة",
            "رد الفعل المتوقع",
            "الملاحظات",
        ]
        cmap = _col_map_from_header_row(headers)
        self.assertEqual(cmap["assignee"], 7)
        self.assertEqual(cmap["time"], 1)
        self.assertEqual(cmap["time_kora"], 2)
        self.assertEqual(cmap["time_from"], 3)
        self.assertEqual(cmap["time_to"], 4)
        self.assertEqual(cmap["report_systems"], 5)
        self.assertEqual(cmap["description"], 6)
        self.assertEqual(cmap["reaction"], 8)
        self.assertEqual(cmap["notes"], 9)
        row = _map_data_row(
            [
                "",
                "08:00",
                "H+1",
                "08:00",
                "08:30",
                "لاسلكي",
                "وصف",
                "محكم كتيبة 12\nمحكم الطبية",
                "تعامل",
                "ملاحظة",
            ],
            cmap,
        )
        self.assertEqual(row["assignee"], "محكم كتيبة 12\nمحكم الطبية")
        self.assertEqual(row["time"], "08:00")
        self.assertEqual(row["time_kora"], "H+1")
        self.assertEqual(row["time_from"], "08:00")
        self.assertEqual(row["report_systems"], "لاسلكي")
        self.assertEqual(row["notes"], "ملاحظة")
        self.assertEqual(row["method"], "")

    def test_kora_time_header_is_not_report_systems(self):
        cmap = _col_map_from_header_row(
            ["ت", "التوقيت الحقيقي", "توقيت نظام كورا", "أنظمة التبليغ", "المكلف"]
        )
        self.assertEqual(cmap["time_kora"], 2)
        self.assertEqual(cmap["report_systems"], 3)
        self.assertEqual(cmap["assignee"], 4)

    def test_numbered_event_and_dilemma_labels(self):
        self.assertTrue(_has_numbered_event("الحدث/1"))
        self.assertTrue(_has_numbered_dilemma("المعضلة/2"))
        self.assertTrue(_has_numbered_dilemma("معضلة/3"))
        self.assertFalse(_has_numbered_dilemma("وصف المعضلة في النص"))

    def test_grid_span_keeps_saat_in_both_time_columns(self):
        W = _W

        def tc(text, span=1):
            el = ET.Element(f"{W}tc")
            pr = ET.SubElement(el, f"{W}tcPr")
            if span > 1:
                gs = ET.SubElement(pr, f"{W}gridSpan")
                gs.set(f"{W}val", str(span))
            p = ET.SubElement(el, f"{W}p")
            r = ET.SubElement(p, f"{W}r")
            t = ET.SubElement(r, f"{W}t")
            t.text = text
            return el

        tbl = ET.Element(f"{W}tbl")
        grid = ET.SubElement(tbl, f"{W}tblGrid")
        for _ in range(10):
            ET.SubElement(grid, f"{W}gridCol")
        tr = ET.SubElement(tbl, f"{W}tr")
        values = [
            ("6", 1),
            ("سعت", 2),
            ("سعت", 1),
            ("السيطرة العليا", 1),
            ("قيادة مجموعة اللواء", 1),
            ("منظومة القيادة والسيطرة (C4I)", 1),
            ("السيطرة العليا (ركن العمليات)", 1),
            ("إنذار مبكر", 1),
            ("إصدار إنذار", 1),
        ]
        for text, span in values:
            tr.append(tc(text, span))
        logical, _fills = _logical_rows_from_tbl(tbl)[0]
        self.assertEqual(len(logical), 10)
        self.assertEqual(logical[1], "سعت")
        self.assertEqual(logical[2], "سعت")
        self.assertEqual(logical[3], "سعت")
        self.assertEqual(logical[4], "السيطرة العليا")
        self.assertEqual(logical[7], "السيطرة العليا (ركن العمليات)")
        headers = [
            "ت",
            "التوقيت الحقيقي",
            "توقيت نظام كورا",
            "من",
            "إلى",
            "أنظمة التبليغ",
            "وصف المعضلة/الحدث",
            "المكلف بالإجراء والمتابعة",
            "رد الفعل المتوقع",
            "الملاحظات",
        ]
        row = _map_data_row(logical, _col_map_from_header_row(headers))
        self.assertEqual(row["time"], "سعت")
        self.assertEqual(row["time_kora"], "سعت")
        self.assertEqual(row["time_from"], "سعت")
        self.assertEqual(row["time_to"], "السيطرة العليا")
        self.assertEqual(row["report_systems"], "قيادة مجموعة اللواء")
        self.assertEqual(row["description"], "منظومة القيادة والسيطرة (C4I)")
        self.assertEqual(row["assignee"], "السيطرة العليا (ركن العمليات)")

    def test_parse_docx_keeps_saat_literally(self):
        W = f"{{{_W_NS}}}"

        def tc(text, span=1, fill="FFFFFF"):
            el = ET.Element(f"{W}tc")
            pr = ET.SubElement(el, f"{W}tcPr")
            shd = ET.SubElement(pr, f"{W}shd")
            shd.set(f"{W}fill", fill)
            if span > 1:
                gs = ET.SubElement(pr, f"{W}gridSpan")
                gs.set(f"{W}val", str(span))
            p = ET.SubElement(el, f"{W}p")
            r = ET.SubElement(p, f"{W}r")
            t = ET.SubElement(r, f"{W}t")
            t.text = text
            return el

        def data_row(*cells):
            tr = ET.Element(f"{W}tr")
            for text in cells:
                tr.append(tc(text))
            return tr

        document = ET.Element(f"{W}document")
        body = ET.SubElement(document, f"{W}body")
        tbl = ET.SubElement(body, f"{W}tbl")
        grid = ET.SubElement(tbl, f"{W}tblGrid")
        for _ in range(10):
            ET.SubElement(grid, f"{W}gridCol")
        header = ET.SubElement(tbl, f"{W}tr")
        for title in (
            "ت",
            "التوقيت الحقيقي",
            "توقيت نظام كورا",
            "من",
            "إلى",
            "أنظمة التبليغ",
            "وصف المعضلة/الحدث",
            "المكلف بالإجراء والمتابعة",
            "رد الفعل المتوقع",
            "الملاحظات",
        ):
            header.append(tc(title, fill="FBD4B4"))
        event = ET.SubElement(tbl, f"{W}tr")
        event.append(tc("الحدث/1: بدء التقدم", span=10, fill="FFFF00"))
        tbl.append(
            data_row(
                "1",
                "سعت",
                "سعت",
                "سعت",
                "السيطرة العليا",
                "قيادة مجموعة اللواء",
                "منظومة القيادة والسيطرة (C4I)",
                "السيطرة العليا (ركن العمليات)",
                "إنذار مبكر",
                "إصدار إنذار",
            )
        )
        xml = ET.tostring(document, encoding="utf-8", xml_declaration=True)
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "[Content_Types].xml",
                "<Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'></Types>",
            )
            zf.writestr("word/document.xml", xml)
        parsed = parse_planner_flow_docx_bytes(buf.getvalue())
        self.assertTrue(parsed["ok"], parsed)
        kinds = [r["kind"] for r in parsed["rows"]]
        self.assertEqual(kinds, ["event", "row"])
        row = parsed["rows"][1]
        self.assertEqual(row["time"], "سعت")
        self.assertEqual(row["time_kora"], "سعت")
        self.assertEqual(row["time_from"], "سعت")
        self.assertEqual(row["assignee"], "السيطرة العليا (ركن العمليات)")


if __name__ == "__main__":
    unittest.main()
