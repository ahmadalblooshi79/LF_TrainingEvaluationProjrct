# -*- coding: utf-8 -*-
"""اختبارات استيراد حزمة استعادة التابلت."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import (
    EvaluationCriterionMedia,
    EvaluationListPdfItem,
    EvaluationListSavedResult,
    Exercise,
    TabletClientOp,
    TabletRecoveryImport,
    User,
)
from app.models.user import RoleKey
from app.tablet_recovery.parser import (
    RecoveryPackageError,
    count_notes,
    count_scored,
    extract_save_rows,
    parse_body_raw,
    parse_created_at,
    parse_recovery_zip,
    rows_fingerprint,
    sha256_file,
    validate_zip_members,
)
from app.tablet_recovery.preview import build_recovery_preview
from app.tablet_recovery.restore import restore_selected_evaluations
from app.tablet_recovery.storage import new_staging_dir, recovery_root


def _make_zip(tmp: Path, *, manifest=None, pending=None, cache=None, media=None, files=None) -> Path:
    zpath = tmp / "pkg.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr(
            "manifest.json",
            json.dumps(manifest or {"exercise_id": 1, "judge_id": 1}, ensure_ascii=False),
        )
        zf.writestr(
            "data/pending_ops.json",
            json.dumps(pending if pending is not None else {"operations": []}, ensure_ascii=False),
        )
        if cache is not None:
            zf.writestr("data/cache_evaluations.json", json.dumps(cache, ensure_ascii=False))
        if media is not None:
            zf.writestr("data/media_manifest.json", json.dumps(media, ensure_ascii=False))
        for rel, content in (files or {}).items():
            zf.writestr(rel, content)
    return zpath


def _save_op(*, op_id, item_id, created, acquired_list, notes_list=None, exercise_id=1, user_id=1):
    notes_list = notes_list or [""] * len(acquired_list)
    rows = []
    for i, acq in enumerate(acquired_list):
        rows.append(
            {
                "row_kind": "score",
                "element": f"E{i}",
                "max_val": "10",
                "acquired": acq,
                "notes": notes_list[i] if i < len(notes_list) else "",
            }
        )
    body = {
        "client_op_id": op_id,
        "payload": {"rows": rows, "dilemma_description": "", "dilemma_requirements": ""},
    }
    return {
        "id": op_id,
        "method": "PUT",
        "path": f"/api/tablet/evaluation-lists/u/{item_id}/results",
        "kind": f"حفظ نتائج قائمة تقييم #{item_id}",
        "op_type": "save_results",
        "created_at": created,
        "attempts": 0,
        "last_error": None,
        "sync_status": "pending",
        "judge_id": user_id,
        "user_id": user_id,
        "exercise_id": exercise_id,
        "list_id": f"evaluation_list_detail:u:{item_id}",
        "eval_item_id": item_id,
        "media_local_path": None,
        "body_raw": json.dumps(body, ensure_ascii=False),
        "body": body,
        "client_op_id": op_id,
    }


class TestRecoveryParser(unittest.TestCase):
    def test_valid_zip(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            z = _make_zip(
                tmp,
                pending={"operations": [_save_op(op_id="a", item_id=557, created="2026-01-01T10:00:00", acquired_list=["7"])]},
            )
            staging = tmp / "stg"
            staging.mkdir()
            pkg = parse_recovery_zip(z, staging)
            self.assertEqual(len(pkg.pending_ops), 1)
            self.assertTrue(pkg.pending_ops[0].is_save_results)
            self.assertEqual(pkg.pending_ops[0].scored_count, 1)

    def test_missing_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            zpath = tmp / "bad.zip"
            with zipfile.ZipFile(zpath, "w") as zf:
                zf.writestr("data/pending_ops.json", "{}")
            staging = tmp / "stg"
            staging.mkdir()
            with self.assertRaises(RecoveryPackageError):
                parse_recovery_zip(zpath, staging)

    def test_malformed_json(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            zpath = tmp / "bad.zip"
            with zipfile.ZipFile(zpath, "w") as zf:
                zf.writestr("manifest.json", "{not-json")
                zf.writestr("data/pending_ops.json", "{}")
            staging = tmp / "stg"
            staging.mkdir()
            with self.assertRaises(RecoveryPackageError):
                parse_recovery_zip(zpath, staging)

    def test_malformed_pending_body(self):
        parsed, ok = parse_body_raw("{bad")
        self.assertFalse(ok)
        self.assertIsNone(parsed)
        self.assertEqual(extract_save_rows(None), [])

    def test_path_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            zpath = tmp / "trav.zip"
            with zipfile.ZipFile(zpath, "w") as zf:
                zf.writestr("manifest.json", "{}")
                zf.writestr("../evil.txt", "x")
                zf.writestr("data/pending_ops.json", '{"operations":[]}')
            with zipfile.ZipFile(zpath, "r") as zf:
                with self.assertRaises(RecoveryPackageError):
                    validate_zip_members(zf)

    def test_multiple_saves_chronology(self):
        older = _save_op(
            op_id="v1",
            item_id=557,
            created="2026-01-01T10:00:00",
            acquired_list=["7"] * 29,
            notes_list=["n"] + [""] * 28,
        )
        newer = _save_op(
            op_id="v2",
            item_id=557,
            created="2026-01-02T10:00:00",
            acquired_list=["9"] * 32,
            notes_list=["a", "b"] + [""] * 30,
        )
        # Earlier timestamp with more scores must NOT win
        ops = [newer, older]
        ops.sort(key=lambda o: parse_created_at(o["created_at"]))
        self.assertEqual(ops[-1]["id"], "v2")
        self.assertEqual(count_scored(extract_save_rows(json.loads(ops[-1]["body_raw"]))), 32)

    def test_fingerprint_match_mismatch(self):
        a = [{"element": "A", "acquired": "7", "notes": "x", "max_val": "10", "row_kind": "score"}]
        b = [{"element": "A", "acquired": "", "notes": "", "max_val": "10", "row_kind": "score"}]
        self.assertNotEqual(rows_fingerprint(a), rows_fingerprint(b))
        self.assertEqual(rows_fingerprint(a), rows_fingerprint(a))


class TestRecoveryPreviewRestore(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rec_imp_"))
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        Session = sessionmaker(bind=self.engine)
        self.db = Session()
        self.db.add(
            User(id=1, username="judge1", password_hash="x", role_key=RoleKey.JUDGE.value, full_name="محكم")
        )
        self.db.add(Exercise(id=1, title="تمرين اختبار", code="T1", owner_id=1))
        self.db.add(
            EvaluationListPdfItem(
                id=557,
                exercise_id=1,
                unit_level_key="unit_a",
                text="list557.xlsx",
            )
        )
        self.db.add(
            EvaluationListPdfItem(
                id=561,
                exercise_id=1,
                unit_level_key="unit_a",
                text="list561.xlsx",
            )
        )
        self.db.commit()

        import app.config as cfg
        import app.eval_criterion_media as ecm

        self._old_cfg = cfg.EVAL_CRITERION_MEDIA_DIR
        self._old_ecm = ecm.EVAL_CRITERION_MEDIA_DIR
        self.media_root = self.tmp / "eval_criterion_media"
        self.media_root.mkdir(parents=True, exist_ok=True)
        cfg.EVAL_CRITERION_MEDIA_DIR = self.media_root
        ecm.EVAL_CRITERION_MEDIA_DIR = self.media_root

    def tearDown(self):
        import app.config as cfg
        import app.eval_criterion_media as ecm

        cfg.EVAL_CRITERION_MEDIA_DIR = self._old_cfg
        ecm.EVAL_CRITERION_MEDIA_DIR = self._old_ecm
        self.db.close()
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def _pkg(self, ops, cache=None, media=None, files=None):
        z = _make_zip(
            self.tmp,
            manifest={"exercise_id": 1, "judge_id": 1, "device_id": "test-dev"},
            pending={"operations": ops},
            cache=cache,
            media=media,
            files=files,
        )
        staging = self.tmp / f"stg_{len(list(self.tmp.iterdir()))}"
        staging.mkdir()
        return parse_recovery_zip(z, staging)

    def test_preview_multiple_saves_and_mismatch(self):
        ops = [
            _save_op(op_id="v1", item_id=557, created="2026-01-01T10:00:00", acquired_list=["7"] * 29, notes_list=["n"] + [""] * 28),
            _save_op(op_id="v2", item_id=557, created="2026-01-02T12:00:00", acquired_list=["9"] * 32, notes_list=["a", "b"] + [""] * 30),
            _save_op(op_id="w1", item_id=561, created="2026-01-01T11:00:00", acquired_list=["5", "6"]),
        ]
        cache = {
            "entries": [
                {
                    "cache_key": "u1:evaluation_list_detail:unit_a:557",
                    "sync_status": "pending",
                    "updated_at": "2026-01-01T10:00:00",
                    "json_body_raw": json.dumps(
                        {
                            "saved_rows": [
                                {"row_kind": "score", "element": "E0", "max_val": "10", "acquired": "", "notes": ""}
                            ],
                            "locally_modified": True,
                        }
                    ),
                }
            ]
        }
        pkg = self._pkg(ops, cache=cache)
        preview = build_recovery_preview(self.db, pkg)
        e557 = next(e for e in preview["evaluations"] if e["eval_item_id"] == 557)
        self.assertEqual(e557["saved_versions"], 2)
        self.assertEqual(e557["candidate_client_op_id"], "v2")
        self.assertEqual(e557["match_status"], "SOURCE_MISMATCH")
        self.assertEqual(e557["scored_rows"], 32)
        e561 = next(e for e in preview["evaluations"] if e["eval_item_id"] == 561)
        self.assertGreaterEqual(e561["scored_rows"], 2)

    def test_pending_only_and_cache_only(self):
        ops = [_save_op(op_id="p1", item_id=557, created="2026-01-01T10:00:00", acquired_list=["1"])]
        cache = {
            "entries": [
                {
                    "cache_key": "u1:evaluation_list_detail:unit_a:561",
                    "sync_status": "pending",
                    "updated_at": "2026-01-01T10:00:00",
                    "json_body_raw": json.dumps(
                        {
                            "saved_payload": {
                                "rows": [
                                    {
                                        "row_kind": "score",
                                        "element": "X",
                                        "max_val": "10",
                                        "acquired": "3",
                                        "notes": "c",
                                    }
                                ]
                            },
                            "locally_modified": True,
                        }
                    ),
                }
            ]
        }
        pkg = self._pkg(ops, cache=cache)
        preview = build_recovery_preview(self.db, pkg)
        e557 = next(e for e in preview["evaluations"] if e["eval_item_id"] == 557)
        e561 = next(e for e in preview["evaluations"] if e["eval_item_id"] == 561)
        self.assertEqual(e557["match_status"], "PENDING_ONLY")
        self.assertEqual(e561["match_status"], "CACHE_ONLY")
        self.assertIn("CACHE ONLY", e561["status"])

    def test_missing_list_and_wrong_exercise(self):
        ops = [_save_op(op_id="p1", item_id=999, created="2026-01-01T10:00:00", acquired_list=["1"])]
        pkg = self._pkg(ops)
        preview = build_recovery_preview(self.db, pkg)
        e = preview["evaluations"][0]
        self.assertEqual(e["status"], "قائمة غير موجودة")

    def test_approved_conflict_and_identical(self):
        payload = {
            "rows": [
                {"row_kind": "score", "element": "E0", "max_val": "10", "acquired": "7", "notes": ""}
            ]
        }
        self.db.add(
            EvaluationListSavedResult(
                evaluation_item_id=557,
                exercise_id=1,
                unit_level_key="unit_a",
                payload_json=json.dumps(payload),
                saved_by_id=1,
                is_approved=True,
            )
        )
        self.db.commit()
        ops = [
            _save_op(op_id="same", item_id=557, created="2026-01-02T10:00:00", acquired_list=["7"]),
        ]
        # different
        ops2 = [
            _save_op(op_id="diff", item_id=557, created="2026-01-02T10:00:00", acquired_list=["1"]),
        ]
        p1 = build_recovery_preview(self.db, self._pkg(ops))
        self.assertEqual(p1["evaluations"][0]["status"], "موجود مسبقاً")
        p2 = build_recovery_preview(self.db, self._pkg(ops2))
        self.assertEqual(p2["evaluations"][0]["status"], "تعارض مع قائمة معتمدة")
        self.assertFalse(p2["evaluations"][0]["default_selected"])

    def test_duplicate_client_op(self):
        self.db.add(
            TabletClientOp(
                user_id=1,
                exercise_id=1,
                client_op_id="dup1",
                op_type="save_evaluation_list",
                path="/x",
                response_json="{}",
            )
        )
        self.db.commit()
        ops = [_save_op(op_id="dup1", item_id=557, created="2026-01-01T10:00:00", acquired_list=["2"])]
        preview = build_recovery_preview(self.db, self._pkg(ops))
        self.assertEqual(preview["evaluations"][0]["status"], "تم استلامها مسبقاً")

    def test_restore_idempotent_twice(self):
        ops = [
            _save_op(op_id="r1", item_id=557, created="2026-01-01T10:00:00", acquired_list=["9"], notes_list=[""]),
            _save_op(
                op_id="r2",
                item_id=561,
                created="2026-01-01T11:00:00",
                acquired_list=["4"],
                notes_list=["ملاحظة راسب مطلوبة"],
            ),
        ]
        # add a tiny image for 557
        img_bytes = b"\xff\xd8\xff\xd9"
        files = {"images/r1.jpg": img_bytes}
        media = {
            "records": [
                {
                    "id": "media1",
                    "client_uuid": "media1",
                    "evaluation_list_item_id": 557,
                    "row_index": 0,
                    "media_kind": "photo",
                    "local_path": "/x/r1.jpg",
                    "local_filename": "r1.jpg",
                    "mime_type": "image/jpeg",
                    "file_size": len(img_bytes),
                    "export_relative_path": "images/r1.jpg",
                    "file_exists": True,
                }
            ]
        }
        pkg = self._pkg(ops, media=media, files=files)
        preview = build_recovery_preview(self.db, pkg)
        # force ready
        for e in preview["evaluations"]:
            e["default_selected"] = True
            e["status"] = "جاهز للاستعادة"
        r1 = restore_selected_evaluations(self.db, pkg, preview, selected_item_ids=[557, 561])
        self.assertEqual(r1["restored"], 2)
        saved = (
            self.db.query(EvaluationListSavedResult)
            .filter(EvaluationListSavedResult.evaluation_item_id == 557)
            .count()
        )
        self.assertEqual(saved, 1)
        media_count = self.db.query(EvaluationCriterionMedia).count()
        self.assertGreaterEqual(media_count, 1)

        # second import same ops → skipped via client_op
        preview2 = build_recovery_preview(self.db, pkg)
        r2 = restore_selected_evaluations(self.db, pkg, preview2, selected_item_ids=[557, 561])
        self.assertEqual(r2["restored"], 0)
        self.assertGreaterEqual(r2["skipped"], 1)
        self.assertEqual(
            self.db.query(EvaluationListSavedResult).filter(EvaluationListSavedResult.evaluation_item_id == 557).count(),
            1,
        )
        self.assertEqual(self.db.query(EvaluationCriterionMedia).count(), media_count)

    def test_missing_media_does_not_block_eval(self):
        ops = [_save_op(op_id="m1", item_id=557, created="2026-01-01T10:00:00", acquired_list=["8"])]
        media = {
            "records": [
                {
                    "id": "missing",
                    "client_uuid": "missing",
                    "evaluation_list_item_id": 557,
                    "row_index": 0,
                    "media_kind": "photo",
                    "local_path": "/nope.jpg",
                    "local_filename": "nope.jpg",
                    "mime_type": "image/jpeg",
                    "export_relative_path": "images/nope.jpg",
                    "file_exists": False,
                }
            ]
        }
        pkg = self._pkg(ops, media=media)
        preview = build_recovery_preview(self.db, pkg)
        for e in preview["evaluations"]:
            e["status"] = "جاهز للاستعادة"
        result = restore_selected_evaluations(self.db, pkg, preview, selected_item_ids=[557])
        self.assertEqual(result["restored"], 1)
        self.assertGreaterEqual(result["missing_media"], 1)

    def test_package_hash_stable(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            z = _make_zip(tmp, pending={"operations": []})
            h1 = sha256_file(z)
            h2 = sha256_file(z)
            self.assertEqual(h1, h2)

    def test_preview_makes_zero_eval_changes(self):
        ops = [
            _save_op(op_id="z1", item_id=557, created="2026-01-01T10:00:00", acquired_list=["9"]),
        ]
        before = self.db.query(EvaluationListSavedResult).count()
        before_media = self.db.query(EvaluationCriterionMedia).count()
        before_ops = self.db.query(TabletClientOp).count()
        build_recovery_preview(self.db, self._pkg(ops))
        self.assertEqual(self.db.query(EvaluationListSavedResult).count(), before)
        self.assertEqual(self.db.query(EvaluationCriterionMedia).count(), before_media)
        self.assertEqual(self.db.query(TabletClientOp).count(), before_ops)

    def test_wrong_judge_missing_user(self):
        ops = [_save_op(op_id="wj", item_id=557, created="2026-01-01T10:00:00", acquired_list=["9"])]
        z = _make_zip(
            self.tmp,
            manifest={"exercise_id": 1, "judge_id": 99999, "device_id": "d"},
            pending={"operations": ops},
        )
        staging = self.tmp / "stg_wj"
        staging.mkdir()
        pkg = parse_recovery_zip(z, staging)
        preview = build_recovery_preview(self.db, pkg)
        self.assertEqual(preview["evaluations"][0]["status"], "محكم غير مطابق")
        self.assertFalse(preview["evaluations"][0]["default_selected"])

    def test_unapproved_conflict_not_auto_selected(self):
        payload = {
            "rows": [
                {"row_kind": "score", "element": "E0", "max_val": "10", "acquired": "2", "notes": "قديم"}
            ]
        }
        self.db.add(
            EvaluationListSavedResult(
                evaluation_item_id=557,
                exercise_id=1,
                unit_level_key="unit_a",
                payload_json=json.dumps(payload),
                saved_by_id=1,
                is_approved=False,
            )
        )
        self.db.commit()
        ops = [_save_op(op_id="uc", item_id=557, created="2026-01-02T10:00:00", acquired_list=["9"])]
        preview = build_recovery_preview(self.db, self._pkg(ops))
        e = preview["evaluations"][0]
        self.assertEqual(e["status"], "تعارض")
        self.assertFalse(e["default_selected"])

    def test_exported_path_alias_resolves(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            img = b"\xff\xd8\xff\xd9"
            files = {"images/media-1_media-1.jpg": img}
            media = {
                "records": [
                    {
                        "id": "media-1",
                        "client_uuid": "media-1",
                        "evaluation_list_item_id": 557,
                        "row_index": 2,
                        "media_kind": "photo",
                        "local_path": "/x/media-1.jpg",
                        "local_filename": "media-1.jpg",
                        "mime_type": "image/jpeg",
                        "file_size": len(img),
                        "exported_path": "images/media-1_media-1.jpg",
                        "file_exists": "YES",
                    }
                ]
            }
            z = _make_zip(tmp, pending={"operations": []}, media=media, files=files)
            staging = tmp / "stg"
            staging.mkdir()
            pkg = parse_recovery_zip(z, staging)
            self.assertEqual(len(pkg.media), 1)
            self.assertEqual(pkg.media[0].export_relative_path, "images/media-1_media-1.jpg")
            self.assertIsNotNone(pkg.media[0].physical_path)
            self.assertTrue(pkg.media[0].physical_path.is_file())

    def test_media_backfill_when_results_already_exist(self):
        payload = {
            "rows": [
                {"row_kind": "score", "element": "E0", "max_val": "10", "acquired": "9", "notes": ""}
            ]
        }
        self.db.add(
            EvaluationListSavedResult(
                evaluation_item_id=557,
                exercise_id=1,
                unit_level_key="unit_a",
                payload_json=json.dumps(payload),
                saved_by_id=1,
                is_approved=False,
            )
        )
        self.db.commit()
        ops = [
            _save_op(op_id="same", item_id=557, created="2026-01-01T10:00:00", acquired_list=["9"]),
        ]
        img_bytes = b"\xff\xd8\xff\xd9"
        files = {"images/m1.jpg": img_bytes}
        media = {
            "records": [
                {
                    "id": "m1",
                    "client_uuid": "m1",
                    "evaluation_list_item_id": 557,
                    "row_index": 0,
                    "media_kind": "photo",
                    "local_path": "/x/m1.jpg",
                    "local_filename": "m1.jpg",
                    "mime_type": "image/jpeg",
                    "file_size": len(img_bytes),
                    "exported_path": "images/m1.jpg",
                    "file_exists": "YES",
                }
            ]
        }
        pkg = self._pkg(ops, media=media, files=files)
        preview = build_recovery_preview(self.db, pkg)
        self.assertEqual(preview["evaluations"][0]["status"], "موجود مسبقاً")
        result = restore_selected_evaluations(self.db, pkg, preview, selected_item_ids=[557])
        self.assertEqual(result["restored"], 0)
        self.assertGreaterEqual(result["media_restored"], 1)
        self.assertEqual(self.db.query(EvaluationCriterionMedia).count(), 1)


if __name__ == "__main__":
    unittest.main()
