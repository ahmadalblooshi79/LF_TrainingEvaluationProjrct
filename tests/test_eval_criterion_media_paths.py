# -*- coding: utf-8 -*-
"""مسارات وسائط قوائم التقييم: وحدة/قائمة/بند بدون judge_id."""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.eval_criterion_media import (
    criterion_media_absolute_path,
    criterion_media_relpath,
    group_media_rows,
    is_legacy_judges_media_relpath,
    migrate_legacy_judge_media_records,
    new_media_filename,
    persist_criterion_medium,
    unlink_criterion_media_file,
)
from app.models import EvaluationCriterionMedia, Exercise, User
from app.models.user import RoleKey


class TestEvalCriterionMediaPaths(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="crit_media_"))
        self.media_root = self.tmp / "eval_criterion_media"
        self.media_root.mkdir()
        import app.config as cfg
        import app.eval_criterion_media as ecm

        self._old_cfg = cfg.EVAL_CRITERION_MEDIA_DIR
        self._old_ecm = ecm.EVAL_CRITERION_MEDIA_DIR
        cfg.EVAL_CRITERION_MEDIA_DIR = self.media_root
        ecm.EVAL_CRITERION_MEDIA_DIR = self.media_root

        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        Session = sessionmaker(bind=self.engine)
        self.db = Session()
        self.db.add(
            User(
                id=1,
                username="j1",
                password_hash="x",
                role_key=RoleKey.JUDGE.value,
            )
        )
        self.db.add(Exercise(id=1, code="T1", title="تمرين", owner_id=1))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        import app.config as cfg
        import app.eval_criterion_media as ecm

        cfg.EVAL_CRITERION_MEDIA_DIR = self._old_cfg
        ecm.EVAL_CRITERION_MEDIA_DIR = self._old_ecm
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_relpath_has_units_not_judges(self):
        rel = criterion_media_relpath(
            exercise_id=1,
            unit_level_key="ul_medical",
            list_item_id=5,
            bundle_action_eval_id=None,
            row_index=27,
            filename="IMG_20260910_131501_a82f.jpg",
        )
        self.assertEqual(
            rel,
            "uploads/exercises/1/units/ul_medical/evaluation_lists/5/items/27/"
            "IMG_20260910_131501_a82f.jpg",
        )
        self.assertNotIn("/judges/", rel)
        self.assertFalse(is_legacy_judges_media_relpath(rel))
        self.assertTrue(
            is_legacy_judges_media_relpath(
                "uploads/exercises/1/judges/1/images/x.jpg"
            )
        )

    def test_filenames_unique_prefixes(self):
        img = new_media_filename("photo", "image/jpeg")
        vid = new_media_filename("video", "video/mp4")
        self.assertTrue(img.startswith("IMG_"))
        self.assertTrue(img.endswith(".jpg"))
        self.assertTrue(vid.startswith("VIDEO_"))
        self.assertTrue(vid.endswith(".mp4"))
        self.assertNotEqual(
            new_media_filename("photo", "image/jpeg"),
            new_media_filename("photo", "image/jpeg"),
        )

    def _put(self, *, unit: str, list_id: int, row: int, kind: str, body: bytes, judge: int | None):
        mime = "video/mp4" if kind == "video" else "image/jpeg"
        return persist_criterion_medium(
            self.db,
            exercise_id=1,
            unit_level_key=unit,
            list_item_id=list_id,
            bundle_action_eval_id=None,
            row_index=row,
            media_kind=kind,
            mime_type_in=mime,
            bin_data=body,
            uploaded_by_id=judge,
        )

    def test_isolation_by_unit_list_item_without_judge(self):
        jpeg = b"\xff\xd8\xff" + b"x" * 20
        mp4 = b"\x00\x00\x00\x18ftypmp42" + b"y" * 40
        a1 = self._put(unit="ul_a", list_id=10, row=1, kind="photo", body=jpeg, judge=1)
        a2 = self._put(unit="ul_a", list_id=10, row=1, kind="photo", body=jpeg, judge=1)
        a3 = self._put(unit="ul_a", list_id=10, row=1, kind="video", body=mp4, judge=1)
        b = self._put(unit="ul_a", list_id=10, row=2, kind="photo", body=jpeg, judge=1)
        c = self._put(unit="ul_a", list_id=20, row=1, kind="photo", body=jpeg, judge=1)
        d = self._put(unit="ul_b", list_id=30, row=1, kind="photo", body=jpeg, judge=99)
        self.db.commit()
        for row in (a1, a2, a3, b, c, d):
            self.assertIn("/units/", row.file_relpath)
            self.assertNotIn("/judges/", row.file_relpath)
            abs_p = criterion_media_absolute_path(row.file_relpath)
            self.assertIsNotNone(abs_p)
            self.assertTrue(abs_p.is_file())

        list_a = group_media_rows(self.db, 1, list_item_id=10)
        self.assertEqual({m["id"] for m in list_a[1]}, {int(a1.id), int(a2.id), int(a3.id)})
        self.assertEqual({m["id"] for m in list_a[2]}, {int(b.id)})
        list_a20 = group_media_rows(self.db, 1, list_item_id=20)
        self.assertEqual({m["id"] for m in list_a20[1]}, {int(c.id)})
        list_b = group_media_rows(self.db, 1, list_item_id=30)
        self.assertEqual({m["id"] for m in list_b[1]}, {int(d.id)})
        other = (
            self.db.query(EvaluationCriterionMedia)
            .filter(
                EvaluationCriterionMedia.exercise_id == 1,
                EvaluationCriterionMedia.unit_level_key == "ul_b",
                EvaluationCriterionMedia.evaluation_list_item_id == 30,
                EvaluationCriterionMedia.row_index == 1,
            )
            .all()
        )
        self.assertEqual([int(r.id) for r in other], [int(d.id)])
        self.assertEqual(int(d.uploaded_by_id), 99)
        # الاسترجاع لا يشترط uploaded_by_id
        same_item_other_judge = (
            self.db.query(EvaluationCriterionMedia)
            .filter(
                EvaluationCriterionMedia.exercise_id == 1,
                EvaluationCriterionMedia.unit_level_key == "ul_a",
                EvaluationCriterionMedia.evaluation_list_item_id == 10,
                EvaluationCriterionMedia.row_index == 1,
            )
            .all()
        )
        self.assertEqual(len(same_item_other_judge), 3)

    def test_delete_only_target_file_and_empty_item_dir(self):
        jpeg = b"\xff\xd8\xff" + b"x" * 20
        one = self._put(unit="ul_a", list_id=5, row=1, kind="photo", body=jpeg, judge=1)
        two = self._put(unit="ul_a", list_id=5, row=1, kind="photo", body=jpeg, judge=1)
        other_item = self._put(unit="ul_a", list_id=5, row=2, kind="photo", body=jpeg, judge=1)
        self.db.commit()
        item1 = criterion_media_absolute_path(one.file_relpath).parent
        list_dir = item1.parent.parent
        unlink_criterion_media_file(one.file_relpath)
        self.db.delete(one)
        self.db.commit()
        self.assertFalse(criterion_media_absolute_path(one.file_relpath).is_file())
        self.assertTrue(criterion_media_absolute_path(two.file_relpath).is_file())
        self.assertTrue(item1.is_dir())
        unlink_criterion_media_file(two.file_relpath)
        self.db.delete(two)
        self.db.commit()
        self.assertFalse(item1.exists())
        self.assertTrue(list_dir.is_dir())
        self.assertTrue(criterion_media_absolute_path(other_item.file_relpath).is_file())

    def test_migrate_moves_when_ids_known_keeps_legacy_otherwise(self):
        jpeg = b"\xff\xd8\xff" + b"x" * 20
        old_rel = "uploads/exercises/1/judges/7/images/legacy.jpg"
        src = self.media_root / old_rel
        src.parent.mkdir(parents=True)
        src.write_bytes(jpeg)
        known = EvaluationCriterionMedia(
            exercise_id=1,
            unit_level_key="ul_a",
            evaluation_list_item_id=3,
            bundle_action_eval_id=None,
            row_index=1,
            media_kind="photo",
            mime_type="image/jpeg",
            file_relpath=old_rel,
            uploaded_by_id=7,
        )
        unknown = EvaluationCriterionMedia(
            exercise_id=1,
            unit_level_key="",
            evaluation_list_item_id=None,
            bundle_action_eval_id=None,
            row_index=1,
            media_kind="photo",
            mime_type="image/jpeg",
            file_relpath="uploads/exercises/1/judges/7/images/orphan.jpg",
            uploaded_by_id=7,
        )
        orphan_src = self.media_root / unknown.file_relpath
        orphan_src.write_bytes(jpeg)
        missing = EvaluationCriterionMedia(
            exercise_id=1,
            unit_level_key="ul_a",
            evaluation_list_item_id=9,
            bundle_action_eval_id=None,
            row_index=4,
            media_kind="photo",
            mime_type="image/jpeg",
            file_relpath="uploads/exercises/1/judges/7/images/gone.jpg",
            uploaded_by_id=7,
        )
        self.db.add_all([known, unknown, missing])
        self.db.commit()
        known_id = int(known.id)
        report = migrate_legacy_judge_media_records(self.db)
        self.db.commit()
        self.assertEqual(report["migrated"], 1)
        self.assertEqual(report["left_legacy"], 2)
        self.assertEqual(report["missing_disk"], 1)
        moved = self.db.get(EvaluationCriterionMedia, known_id)
        self.assertEqual(int(moved.id), known_id)
        self.assertEqual(int(moved.uploaded_by_id), 7)
        self.assertIn("/units/ul_a/evaluation_lists/3/items/1/", moved.file_relpath)
        self.assertNotIn("/judges/", moved.file_relpath)
        self.assertTrue(criterion_media_absolute_path(moved.file_relpath).is_file())
        self.assertFalse(src.exists())
        kept = self.db.get(EvaluationCriterionMedia, int(unknown.id))
        self.assertTrue(is_legacy_judges_media_relpath(kept.file_relpath))
        self.assertTrue(criterion_media_absolute_path(kept.file_relpath).is_file())


if __name__ == "__main__":
    unittest.main()
