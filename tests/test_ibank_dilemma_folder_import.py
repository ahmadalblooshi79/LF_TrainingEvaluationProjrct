# -*- coding: utf-8 -*-
import unittest
from pathlib import Path

from app.ibank_dilemma_folder_import import (
    parse_day_no_from_dirname,
    parse_dilemma_folder_codes,
    parse_dilemma_no_from_text,
    scan_external_dilemma_folders,
)


class DilemmaFolderParseTests(unittest.TestCase):
    def test_parse_y_m_folder(self):
        self.assertEqual(
            parse_dilemma_folder_codes("1. ي1 - م1 - فرض الصمت"),
            (1, 1),
        )
        self.assertEqual(
            parse_dilemma_folder_codes("2. ي1 - م2- تعرض الاستطلاع لكمين"),
            (1, 2),
        )
        self.assertEqual(
            parse_dilemma_folder_codes("معضلة 2", parent_day_no=2),
            (2, 2),
        )

    def test_parse_day_dir(self):
        self.assertEqual(parse_day_no_from_dirname("1. اليوم 1"), 1)
        self.assertEqual(parse_day_no_from_dirname("2. اليوم2"), 2)

    def test_assignees_collected_when_dilemma_title_uses_hyphen(self):
        import json

        from app.ibank_action_eval_dilemma_tree import _assignees_by_dilemma_from_flow

        raw = json.dumps(
            {
                "days": [
                    {
                        "id": "day-1",
                        "rows": [
                            {
                                "kind": "dilemma",
                                "text": "المعضلة-3: إنذار وهجوم طائرة مسيرة",
                            },
                            {
                                "kind": "row",
                                "assignee": "محكم الطبية\nمحكم الصيانة",
                            },
                        ],
                    }
                ]
            }
        )
        out = _assignees_by_dilemma_from_flow(raw)
        self.assertEqual(out["day-1"][3], ["محكم الطبية", "محكم الصيانة"])

    def test_scan_desktop_day1_if_present(self):
        root = Path(r"C:/Users/W10User/Desktop")
        if not root.is_dir():
            self.skipTest("Desktop missing")
        packs = scan_external_dilemma_folders(root)
        self.assertTrue(any(p["dilemma_no"] == 1 and p["day_no"] == 1 for p in packs))


if __name__ == "__main__":
    unittest.main()
