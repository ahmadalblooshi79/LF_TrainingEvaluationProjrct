import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from app.tablet_recovery import (
    _ensure_iterable,
    build_preview,
    parse_pending_body,
    selected_eval_item_ids,
)


class _Form:
    def __init__(self, values):
        self._values = values

    def getlist(self, name):
        return list(self._values.get(name, []))


class TabletRecoveryTests(unittest.TestCase):
    def test_parse_save_results_body(self):
        raw = json.dumps(
            {
                "client_op_id": "op-1",
                "payload": {
                    "rows": [
                        {
                            "row_kind": "criterion",
                            "element": "A",
                            "max_val": "10",
                            "acquired": "7",
                            "notes": "RECOVERY TEST 001",
                        }
                    ]
                },
            }
        )
        parsed = parse_pending_body(raw)
        self.assertTrue(parsed["parse_ok"])
        self.assertEqual(parsed["rows"][0]["acquired"], "7")
        self.assertEqual(parsed["rows"][0]["notes"], "RECOVERY TEST 001")
        self.assertEqual(parsed["raw"], raw)

    def test_malformed_body_does_not_crash(self):
        parsed = parse_pending_body("{not-json")
        self.assertFalse(parsed["parse_ok"])
        self.assertEqual(parsed["rows"], [])

    def test_selected_ids_calls_getlist(self):
        form = _Form({"eval_item_id": ["180", "182", "x"]})
        self.assertEqual(selected_eval_item_ids(form), [180, 182])

    def test_method_is_not_iterable(self):
        with self.assertRaises(TypeError):
            _ensure_iterable({}.keys, name="keys")
        with self.assertRaises(TypeError):
            _ensure_iterable(_Form({}).getlist, name="getlist")

    def test_preview_pending_and_mismatch(self):
        pending_rows = [
            {
                "row_kind": "criterion",
                "element": "A",
                "max_val": "10",
                "acquired": "7",
                "notes": "pending",
            }
        ]
        cache_rows = [
            {
                "row_kind": "criterion",
                "element": "A",
                "max_val": "10",
                "acquired": "1",
                "notes": "cache",
            }
        ]
        body = json.dumps({"payload": {"rows": pending_rows}, "client_op_id": "op"})
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "data").mkdir()
            (root / "manifest.json").write_text(
                json.dumps(
                    {
                        "device_id": "tablet-test",
                        "app_version": "2.7.26",
                        "exercise_id": 1,
                        "judge_id": 174,
                    }
                ),
                encoding="utf-8",
            )
            (root / "data" / "pending_ops.json").write_text(
                json.dumps(
                    {
                        "operations": [
                            {
                                "id": "op-180",
                                "op_type": "save_results",
                                "path": "/api/tablet/evaluation-lists/u/180/results",
                                "eval_item_id": 180,
                                "body": body,
                                "sync_status": "pending",
                                "created_at": "2026-09-27T10:00:00",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (root / "data" / "cache_evaluations.json").write_text(
                json.dumps(
                    {
                        "entries": [
                            {
                                "cache_key": "u174:evaluation_list_detail:unit:180",
                                "json_body": json.dumps(
                                    {
                                        "saved_rows": cache_rows,
                                        "saved_payload": {"rows": cache_rows},
                                    }
                                ),
                                "sync_status": "pending",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (root / "data" / "media_manifest.json").write_text(
                json.dumps({"records": []}),
                encoding="utf-8",
            )
            preview = build_preview(root, zip_hash="abc", zip_name="x.zip")
        item = preview.items[0]
        self.assertEqual(item.eval_item_id, 180)
        self.assertTrue(item.ready)
        self.assertTrue(item.source_mismatch)
        self.assertEqual(item.rows[0]["acquired"], "7")
        self.assertEqual(preview.ready_count, 1)

    def test_zip_roundtrip_extract(self):
        from app.tablet_recovery import extract_recovery_zip

        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "p.zip"
            dest = Path(td) / "out"
            with zipfile.ZipFile(src, "w") as zf:
                zf.writestr("manifest.json", json.dumps({"device_id": "d"}))
            extract_recovery_zip(src, dest)
            self.assertTrue((dest / "manifest.json").is_file())


if __name__ == "__main__":
    unittest.main()
