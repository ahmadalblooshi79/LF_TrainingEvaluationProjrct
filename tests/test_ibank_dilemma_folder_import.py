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

    def test_parse_text_no(self):
        self.assertEqual(parse_dilemma_no_from_text("المعضلة/7: عطل"), 7)

    def test_scan_desktop_day1_if_present(self):
        root = Path(r"C:/Users/W10User/Desktop")
        if not root.is_dir():
            self.skipTest("Desktop missing")
        packs = scan_external_dilemma_folders(root)
        self.assertTrue(any(p["dilemma_no"] == 1 and p["day_no"] == 1 for p in packs))


if __name__ == "__main__":
    unittest.main()
