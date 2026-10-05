import io
import unittest
import zipfile
from types import SimpleNamespace

from app.evaluation_list_export import (
    pack_pending_eval_lists_zip,
    pending_eval_list_zip_relpath,
    zip_safe_segment,
)
from app.evaluation_workflow import eval_dispatch_status_ar, pending_dispatch_eval_items


def _item(iid, *, text="قائمة", unit="u1", phase="p1"):
    return SimpleNamespace(id=iid, text=text, unit_level_key=unit, exercise_phase=phase)


def _saved(*, payload="{}", approved=False, reopened=False):
    return SimpleNamespace(
        payload_json=payload,
        is_approved=approved,
        reopened_for_judge=reopened,
    )


class PendingEvalListsZipTests(unittest.TestCase):
    def test_zip_relpath_is_phase_unit_list(self):
        used: set[str] = set()
        rel = pending_eval_list_zip_relpath(
            phase_label="مرحلة مسارات التقييم",
            unit_label="لواء المشاة",
            list_title="01 تقييم رفع الحالة.xlsx",
            item_id=7,
            used=used,
        )
        self.assertEqual(
            rel,
            "مرحلة مسارات التقييم/لواء المشاة/01 تقييم رفع الحالة.xlsx",
        )
        self.assertIn(rel, used)

    def test_zip_relpath_collision_appends_id(self):
        used: set[str] = set()
        first = pending_eval_list_zip_relpath(
            phase_label="مرحلة",
            unit_label="وحدة",
            list_title="قائمة.xlsx",
            item_id=1,
            used=used,
        )
        second = pending_eval_list_zip_relpath(
            phase_label="مرحلة",
            unit_label="وحدة",
            list_title="قائمة.xlsx",
            item_id=12,
            used=used,
        )
        self.assertEqual(first, "مرحلة/وحدة/قائمة.xlsx")
        self.assertEqual(second, "مرحلة/وحدة/قائمة_12.xlsx")

    def test_zip_safe_segment_strips_separators(self):
        self.assertEqual(zip_safe_segment("أ/ب\\ج:د"), "أ_ب_ج_د")

    def test_pack_zip_keeps_folder_tree(self):
        data = pack_pending_eval_lists_zip(
            [
                ("مرحلة أ/وحدة 1/قائمة.xlsx", b"PK\x03\x04fake"),
                ("مرحلة ب/وحدة 2/أخرى.xlsx", b"PK\x03\x04fake2"),
            ]
        )
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())
        self.assertEqual(
            names,
            {
                "مرحلة أ/وحدة 1/قائمة.xlsx",
                "مرحلة ب/وحدة 2/أخرى.xlsx",
            },
        )

    def test_pending_filter_keeps_only_awaiting_approval(self):
        items = [
            _item(1, text="لم يرسل"),
            _item(2, text="بانتظار"),
            _item(3, text="مرسل"),
            _item(4, text="معاد"),
        ]
        canonical = {
            2: _saved(payload='{"rows":[]}'),
            3: _saved(payload='{"rows":[]}', approved=True),
            4: _saved(payload='{"rows":[]}', reopened=True),
        }
        pending = pending_dispatch_eval_items(items, canonical)
        self.assertEqual([it.id for it in pending], [2])
        self.assertEqual(eval_dispatch_status_ar(canonical[2]), ("بانتظار الإعتماد", "pending"))

    def test_pending_filter_scopes_unit_and_ids(self):
        items = [
            _item(10, unit="alpha"),
            _item(11, unit="beta"),
            _item(12, unit="alpha"),
        ]
        canonical = {
            10: _saved(payload='{"rows":[]}'),
            11: _saved(payload='{"rows":[]}'),
            12: _saved(payload='{"rows":[]}'),
        }
        pending = pending_dispatch_eval_items(
            items,
            canonical,
            item_id_allow={10, 11},
            unit_keys_allow={"alpha"},
        )
        self.assertEqual([it.id for it in pending], [10])


if __name__ == "__main__":
    unittest.main()
