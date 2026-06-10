import unittest

from app.evaluation_list_ibank_sync import (
    ibank_eval_storage_relpath,
    parse_ibank_eval_storage_relpath,
)


class EvaluationListIbankSyncTests(unittest.TestCase):
    def test_ibank_eval_storage_relpath_roundtrip(self):
        rel = ibank_eval_storage_relpath("ul_brigade_grp_cmd", 42)
        self.assertEqual(rel, "ul_brigade_grp_cmd/ibn_42.xlsx")
        self.assertEqual(parse_ibank_eval_storage_relpath(rel), 42)

    def test_parse_ibank_eval_storage_relpath_rejects_manual_uploads(self):
        self.assertIsNone(parse_ibank_eval_storage_relpath("ul_brigade_grp_cmd/abc.xlsx"))
