import io
import unittest
import zipfile
from types import SimpleNamespace

from app.eval_lists_admin_export import (
    filter_admin_eval_export_entries,
    zip_entries_for_selected,
)
from app.evaluation_list_export import eval_export_list_folder_relpath
from app.evaluation_workflow import eval_admin_export_status_key


class AdminEvalExportTests(unittest.TestCase):
    def test_status_key_pending_approved_saved(self):
        pending = SimpleNamespace(
            payload_json="{}",
            is_approved=False,
            reopened_for_judge=False,
        )
        approved = SimpleNamespace(
            payload_json="{}",
            is_approved=True,
            reopened_for_judge=False,
        )
        reopened = SimpleNamespace(
            payload_json="{}",
            is_approved=True,
            reopened_for_judge=True,
        )
        empty = SimpleNamespace(payload_json="", is_approved=False, reopened_for_judge=False)
        self.assertEqual(eval_admin_export_status_key(pending), "pending")
        self.assertEqual(eval_admin_export_status_key(approved), "approved")
        self.assertEqual(eval_admin_export_status_key(reopened), "saved")
        self.assertIsNone(eval_admin_export_status_key(empty))

    def test_filter_by_unit_phase_list_status(self):
        entries = [
            {
                "key": "eval:1",
                "unit_key": "u1",
                "phase_key": "preparation",
                "status": "pending",
            },
            {
                "key": "action:2",
                "unit_key": "u2",
                "phase_key": "opening",
                "status": "approved",
            },
        ]
        out = filter_admin_eval_export_entries(
            entries,
            units={"u1"},
            phases=None,
            list_keys=None,
            statuses={"pending"},
        )
        self.assertEqual([e["key"] for e in out], ["eval:1"])
        none = filter_admin_eval_export_entries(
            entries, units=set(), phases=None, list_keys=None, statuses=None
        )
        self.assertEqual(none, [])

    def test_folder_tree_and_media_in_same_dir(self):
        used: set[str] = set()
        folder = eval_export_list_folder_relpath(
            phase_label="مرحلة التحضير",
            unit_label="سرية الهاون",
            list_title="01 تقييم رفع الحالة",
            item_id=9,
            used=used,
        )
        self.assertEqual(folder, "مرحلة التحضير/سرية الهاون/01 تقييم رفع الحالة")
        selected = [
            {
                "key": "eval:9",
                "item_id": 9,
                "title": "01 تقييم رفع الحالة",
                "phase_label": "مرحلة التحضير",
                "unit_label": "سرية الهاون",
            }
        ]
        entries = zip_entries_for_selected(
            selected,
            xlsx_by_key={"eval:9": b"xlsx"},
            media_by_key={"eval:9": [("صورة_بند_0_3.jpg", b"img")]},
        )
        names = [rel for rel, _ in entries]
        self.assertEqual(
            names,
            [
                "مرحلة التحضير/سرية الهاون/01 تقييم رفع الحالة/01 تقييم رفع الحالة.xlsx",
                "مرحلة التحضير/سرية الهاون/01 تقييم رفع الحالة/صورة_بند_0_3.jpg",
            ],
        )
        packed = zip_entries_for_selected(
            selected,
            xlsx_by_key={"eval:9": b"xlsx"},
            media_by_key={"eval:9": [("صورة_بند_0_3.jpg", b"img")]},
        )
        from app.eval_lists_admin_export import pack_admin_eval_export_zip

        data = pack_admin_eval_export_zip(packed)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            self.assertEqual(set(zf.namelist()), set(names))


if __name__ == "__main__":
    unittest.main()
