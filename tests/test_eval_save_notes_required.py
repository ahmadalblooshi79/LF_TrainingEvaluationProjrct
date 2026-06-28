"""اختبار: صف مقبول/راسب يتطلب ملاحظات قبل الحفظ."""
from __future__ import annotations

import unittest

from app.evaluation_list_columns import (
    payload_rows_missing_required_notes,
    payload_valid_for_save,
)


class TestEvalSaveNotesRequired(unittest.TestCase):
    def test_fail_row_without_notes_blocks_save(self):
        rows = [
            {
                "row_kind": "score",
                "max_val": "10",
                "acquired": "5",
                "notes": "",
            }
        ]
        self.assertEqual(payload_rows_missing_required_notes(rows), [0])
        self.assertFalse(payload_valid_for_save(rows))

    def test_fail_row_with_notes_allows_save(self):
        rows = [
            {
                "row_kind": "score",
                "max_val": "10",
                "acquired": "5",
                "notes": "ملاحظة",
            }
        ]
        self.assertEqual(payload_rows_missing_required_notes(rows), [])
        self.assertTrue(payload_valid_for_save(rows))

    def test_good_row_without_notes_allows_save(self):
        rows = [
            {
                "row_kind": "score",
                "max_val": "10",
                "acquired": "8",
                "notes": "",
            }
        ]
        self.assertEqual(payload_rows_missing_required_notes(rows), [])
        self.assertTrue(payload_valid_for_save(rows))


if __name__ == "__main__":
    unittest.main()
