import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace

from app.eval_lists_admin_export import (
    filter_admin_eval_export_entries,
    layout_admin_export_files,
    pack_admin_eval_export_zip,
    stored_zip_add_file,
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
        by_kind = filter_admin_eval_export_entries(
            [
                {**entries[0], "kind": "eval"},
                {**entries[1], "kind": "action"},
            ],
            units=None,
            phases=None,
            list_keys=None,
            statuses=None,
            kinds={"action"},
        )
        self.assertEqual([e["key"] for e in by_kind], ["action:2"])
        blank_phase = filter_admin_eval_export_entries(
            [{"key": "eval:9", "kind": "eval", "unit_key": "u1", "phase_key": "", "status": "saved"}],
            units=None,
            phases={"__none__"},
            list_keys=None,
            statuses=None,
            kinds={"eval"},
        )
        self.assertEqual([e["key"] for e in blank_phase], ["eval:9"])

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
            for info in zf.infolist():
                self.assertEqual(info.compress_type, zipfile.ZIP_STORED)

    def test_kinds_export_into_separate_folders(self):
        selected = [
            {
                "key": "eval:1",
                "kind": "eval",
                "item_id": 1,
                "title": "قائمة مشتركة",
                "phase_label": "مرحلة التحضير",
                "unit_label": "سرية الهاون",
            },
            {
                "key": "action:2",
                "kind": "action",
                "item_id": 2,
                "title": "قائمة مشتركة",
                "phase_label": "مرحلة التحضير",
                "unit_label": "سرية الهاون",
            },
        ]
        layout = layout_admin_export_files(
            selected,
            {"eval:1": ["صورة_بند_0_3.jpg"], "action:2": []},
        )
        self.assertTrue(layout["eval:1"]["xlsx_relpath"].startswith("قوائم تقييم الإجراءات/"))
        self.assertTrue(layout["eval:1"]["media"][0]["relpath"].startswith("قوائم تقييم الإجراءات/"))
        self.assertTrue(layout["action:2"]["xlsx_relpath"].startswith("قوائم تقييم المعاضل/"))
        self.assertNotEqual(
            layout["eval:1"]["xlsx_relpath"].split("/")[0],
            layout["action:2"]["xlsx_relpath"].split("/")[0],
        )

    def test_long_dilemma_title_stays_within_windows_path(self):
        title = (
            "إنذار بتهديد جوي ودفاع سلبي وايجابي — معضلة 30: المعضلة 30 "
            "إنذار وهجوم طائرة مسيرة انتحارية على موقع سرية الحرب الإلكترونية وتدمير محطة استطلاع"
        )
        selected = [
            {
                "key": "action:30",
                "kind": "action",
                "item_id": 30,
                "title": title,
                "phase_label": "مرحلة العمليات التعرضية الآلية",
                "unit_label": "فصيل الحرب الإلكترونية_1",
            },
            {
                "key": "action:31",
                "kind": "action",
                "item_id": 31,
                "title": title + " نسخة",
                "phase_label": "مرحلة العمليات التعرضية الآلية",
                "unit_label": "فصيل الحرب الإلكترونية_1",
            },
        ]
        layout = layout_admin_export_files(selected, {})
        for key in ("action:30", "action:31"):
            rel = layout[key]["xlsx_relpath"]
            self.assertLess(len(rel), 180)
            for part in rel.split("/"):
                self.assertLessEqual(len(part), 80)
            self.assertLessEqual(len(rel.split("/")[-2]), 48)
        self.assertNotEqual(layout["action:30"]["folder"], layout["action:31"]["folder"])

    def test_stored_zip_keeps_arabic_name_from_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "photo.bin"
            src.write_bytes(b"img-bytes")
            dest = Path(tmp) / "out.zip"
            with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_STORED) as zf:
                stored_zip_add_file(zf, "قوائم تقييم المعاضل/صورة.jpg", src)
            with zipfile.ZipFile(dest) as zf:
                self.assertEqual(zf.namelist(), ["قوائم تقييم المعاضل/صورة.jpg"])
                self.assertEqual(zf.read("قوائم تقييم المعاضل/صورة.jpg"), b"img-bytes")
                self.assertEqual(zf.getinfo("قوائم تقييم المعاضل/صورة.jpg").compress_type, zipfile.ZIP_STORED)


if __name__ == "__main__":
    unittest.main()
