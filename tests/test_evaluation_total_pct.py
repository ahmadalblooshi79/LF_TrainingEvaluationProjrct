"""اختبار: النسبة الإجمالية = مجموع المكتسبة ÷ مجموع القصوى (> 0)."""
from __future__ import annotations

import unittest

from app.views import _evaluation_grade_from_payload_rows, _evaluation_payload_mark_totals


class TestEvaluationTotalPct(unittest.TestCase):
    def test_total_pct_is_acquired_over_positive_max_sum(self):
        rows = [
            {"row_kind": "score", "max_val": "100", "acquired": "80"},
            {"row_kind": "score", "max_val": "230", "acquired": "160"},
        ]
        sum_max, sum_acq = _evaluation_payload_mark_totals(rows)
        self.assertEqual(sum_max, 330.0)
        self.assertEqual(sum_acq, 240.0)
        total_pct, _ = _evaluation_grade_from_payload_rows(rows)
        self.assertIsNotNone(total_pct)
        self.assertAlmostEqual(total_pct, (240.0 / 330.0) * 100.0, places=2)

    def test_na_acquired_excluded_from_max_and_acquired(self):
        rows = [
            {"row_kind": "score", "max_val": "10", "acquired": "8"},
            {"row_kind": "score", "max_val": "5", "acquired": "na"},
        ]
        sum_max, sum_acq = _evaluation_payload_mark_totals(rows)
        self.assertEqual(sum_max, 10.0)
        self.assertEqual(sum_acq, 8.0)
        total_pct, _ = _evaluation_grade_from_payload_rows(rows)
        self.assertIsNotNone(total_pct)
        self.assertAlmostEqual(total_pct, 80.0, places=2)

    def test_judge_sum_totals_skips_na_max(self):
        from app.views import _evaluation_list_judge_sum_totals

        template = [
            {"row_kind": "score", "max_num": 10, "max_val": "10"},
            {"row_kind": "score", "max_num": 5, "max_val": "5"},
        ]
        saved = [
            {"row_kind": "score", "max_val": "10", "acquired": "8"},
            {"row_kind": "score", "max_val": "5", "acquired": "na"},
        ]
        sum_max, sum_acq = _evaluation_list_judge_sum_totals(saved, template)
        self.assertEqual(sum_max, 10.0)
        self.assertEqual(sum_acq, 8.0)

    def test_zero_max_rows_excluded_from_denominator(self):
        rows = [
            {"row_kind": "score", "max_val": "0", "acquired": "10"},
            {"row_kind": "score", "max_val": "", "acquired": "5"},
        ]
        total_pct, _ = _evaluation_grade_from_payload_rows(rows)
        self.assertIsNone(total_pct)


if __name__ == "__main__":
    unittest.main()
