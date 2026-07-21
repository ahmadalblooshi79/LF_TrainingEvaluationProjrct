import json
import unittest

from app.views import _extract_ibank_flow_dilemma_names


class IbankFlowDilemmaNamesTests(unittest.TestCase):
    def test_names_only_with_numbering(self):
        raw = json.dumps(
            {
                "version": 2,
                "days": [
                    {
                        "id": "day-1",
                        "label": "اليوم/1",
                        "rows": [
                            {"kind": "event", "text": "الحدث/1"},
                            {"kind": "row", "time": "سعت", "assignee": "أ"},
                            {"kind": "dilemma", "text": "المعضلة/1: فرض الصمت اللاسلكي"},
                            {"kind": "row", "time": "عند البدء", "assignee": "ب"},
                            {"kind": "dilemma", "text": "المعضلة/2: كمين"},
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        )
        by_day = _extract_ibank_flow_dilemma_names(raw)
        rows = by_day["day-1"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], {"num": 1, "text": "المعضلة/1: فرض الصمت اللاسلكي"})
        self.assertEqual(rows[1]["num"], 2)
        self.assertIn("كمين", rows[1]["text"])


if __name__ == "__main__":
    unittest.main()
