"""عمود الموقف يصبح «لا ينطبق» عندما تكون كل العناصر لا ينطبق، حتى بعد الاعتماد."""
import json
import unittest
from types import SimpleNamespace

from app.evaluation_workflow import (
    build_evaluation_list_row,
    build_planner_flow_eval_row,
    eval_status_label_ar,
    payload_rows_all_na,
)


def _saved(rows, *, approved=False):
    return SimpleNamespace(
        payload_json=json.dumps({"rows": rows}),
        is_approved=approved,
        reopened_for_judge=False,
        is_chief_approved=False,
        is_control_approved=False,
        total_pct=None,
        grade_label="",
        updated_at=None,
        approved_at=None,
    )


class EvalStatusAllNaTests(unittest.TestCase):
    def test_all_score_rows_na_ignores_sections(self):
        self.assertTrue(
            payload_rows_all_na(
                [
                    {"row_kind": "section", "acquired": ""},
                    {"row_kind": "score", "acquired": "na"},
                    {"row_kind": "score", "acquired": "لا ينطبق"},
                ]
            )
        )

    def test_mixed_or_empty_is_not_all_na(self):
        self.assertFalse(
            payload_rows_all_na(
                [
                    {"row_kind": "score", "acquired": "na"},
                    {"row_kind": "score", "acquired": "4"},
                ]
            )
        )
        self.assertFalse(payload_rows_all_na([{"row_kind": "score", "acquired": ""}]))
        self.assertFalse(payload_rows_all_na([]))

    def test_label_stays_na_after_approval(self):
        saved = _saved(
            [
                {"row_kind": "score", "acquired": "na"},
                {"row_kind": "score", "acquired": "na"},
            ],
            approved=True,
        )
        self.assertEqual(eval_status_label_ar(saved), "لا ينطبق")
        item = SimpleNamespace(id=3, text="قائمة", created_at=None)
        exercise = SimpleNamespace(exercise_type="", trained_unit="")
        row = build_evaluation_list_row(
            item=item, saved=saved, exercise=exercise, open_href="#"
        )
        self.assertTrue(row["status_all_na"])
        self.assertTrue(row["status_done"])
        self.assertEqual(row["status_label"], "لا ينطبق")

        flow = build_planner_flow_eval_row(
            slot_index=1,
            item_title="معضلة",
            saved=saved,
            exercise=exercise,
            open_href="#",
        )
        self.assertTrue(flow["status_all_na"])
        self.assertEqual(flow["status_label"], "لا ينطبق")

    def test_approved_scored_list_stays_done_label(self):
        saved = _saved([{"row_kind": "score", "acquired": "4"}], approved=True)
        self.assertEqual(eval_status_label_ar(saved), "معتمد")


if __name__ == "__main__":
    unittest.main()
