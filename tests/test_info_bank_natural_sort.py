"""اختبار: ترتيب طبيعي للمجلدات والملفات في بنك المعلومات."""
from __future__ import annotations

import io
import unittest
import zipfile
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.info_bank_tree import (
    _natural_sort_key,
    _resort_siblings_by_natural_name,
    upload_files_to_parent,
)
from app.models import InformationBankTreeNode

KIND = "dilemma_eval"


class _FakeUpload:
    def __init__(self, filename: str, data: bytes):
        self.filename = filename
        self._data = data

    def read(self) -> bytes:
        return self._data


def _minimal_xlsx_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types></Types>')
    return buf.getvalue()


class NaturalSortKeyTests(unittest.TestCase):
    def test_numeric_prefix_order(self):
        names = [
            "10 تقييم.xlsx",
            "02 تقييم.xlsx",
            "01 تقييم.xlsx",
            "07 تقييم.xlsx",
        ]
        ordered = sorted(names, key=_natural_sort_key)
        self.assertEqual(
            ordered,
            [
                "01 تقييم.xlsx",
                "02 تقييم.xlsx",
                "07 تقييم.xlsx",
                "10 تقييم.xlsx",
            ],
        )

    def test_company_folder_order(self):
        names = ["السرية 3", "السرية 1", "السرية 2"]
        ordered = sorted(names, key=_natural_sort_key)
        self.assertEqual(ordered, ["السرية 1", "السرية 2", "السرية 3"])


class InfoBankUploadNaturalOrderTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.parent = InformationBankTreeNode(
            kind=KIND,
            parent_id=None,
            name="كتيبة",
            is_folder=True,
            sort_order=0,
        )
        self.db.add(self.parent)
        self.db.commit()
        self.xlsx = _minimal_xlsx_bytes()

    def _child_names(self, parent_id: int) -> list[str]:
        rows = (
            self.db.query(InformationBankTreeNode)
            .filter(InformationBankTreeNode.parent_id == int(parent_id))
            .order_by(InformationBankTreeNode.sort_order, InformationBankTreeNode.id)
            .all()
        )
        return [r.name for r in rows]

    def test_upload_folder_reversed_browser_order(self):
        uploads = [
            _FakeUpload("السرية 3/03.xlsx", self.xlsx),
            _FakeUpload("السرية 2/02.xlsx", self.xlsx),
            _FakeUpload("السرية 1/01.xlsx", self.xlsx),
        ]
        upload_files_to_parent(
            self.db,
            kind=KIND,
            parent_id=int(self.parent.id),
            file_storages=uploads,
        )
        self.db.commit()
        self.assertEqual(
            self._child_names(int(self.parent.id)),
            ["السرية 1", "السرية 2", "السرية 3"],
        )

    def test_reupload_appends_at_end(self):
        for name in ("02 b.xlsx", "03 c.xlsx", "04 d.xlsx"):
            upload_files_to_parent(
                self.db,
                kind=KIND,
                parent_id=int(self.parent.id),
                file_storages=[_FakeUpload(name, self.xlsx)],
            )
        self.db.commit()
        upload_files_to_parent(
            self.db,
            kind=KIND,
            parent_id=int(self.parent.id),
            file_storages=[_FakeUpload("01 a.xlsx", self.xlsx)],
        )
        self.db.commit()
        self.assertEqual(
            self._child_names(int(self.parent.id)),
            ["02 b.xlsx", "03 c.xlsx", "04 d.xlsx", "01 a.xlsx"],
        )

    def test_reupload_after_delete_appends_in_upload_order(self):
        existing = [
            "3. list-three.xlsx",
            "4. list-four.xlsx",
            "5. list-five.xlsx",
            "6. list-six.xlsx",
        ]
        for i, name in enumerate(existing):
            self.db.add(
                InformationBankTreeNode(
                    kind=KIND,
                    parent_id=int(self.parent.id),
                    name=name,
                    is_folder=False,
                    file_relpath=f"{KIND}/tree/t{i}/{name}",
                    sort_order=i,
                )
            )
        self.db.commit()
        upload_files_to_parent(
            self.db,
            kind=KIND,
            parent_id=int(self.parent.id),
            file_storages=[
                _FakeUpload("2. list-two.xlsx", self.xlsx),
                _FakeUpload("1. list-one.xlsx", self.xlsx),
            ],
        )
        self.db.commit()
        self.assertEqual(
            self._child_names(int(self.parent.id)),
            [
                "3. list-three.xlsx",
                "4. list-four.xlsx",
                "5. list-five.xlsx",
                "6. list-six.xlsx",
                "1. list-one.xlsx",
                "2. list-two.xlsx",
            ],
        )

    def test_resort_siblings_fixes_existing_order(self):
        for i, name in enumerate(("السرية 3", "السرية 2", "السرية 1")):
            self.db.add(
                InformationBankTreeNode(
                    kind=KIND,
                    parent_id=int(self.parent.id),
                    name=name,
                    is_folder=True,
                    sort_order=i,
                )
            )
        self.db.commit()
        _resort_siblings_by_natural_name(
            self.db, kind=KIND, parent_id=int(self.parent.id)
        )
        self.db.commit()
        self.assertEqual(
            self._child_names(int(self.parent.id)),
            ["السرية 1", "السرية 2", "السرية 3"],
        )


class AutoflushOffUploadTests(unittest.TestCase):
    """محاكاة جلسة الإنتاج (autoflush=False)."""

    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
        self.parent = InformationBankTreeNode(
            kind=KIND,
            parent_id=None,
            name="كتيبة",
            is_folder=True,
            sort_order=0,
        )
        self.db.add(self.parent)
        self.db.flush()
        for i, name in enumerate(
            (
                "3. list-three.xlsx",
                "4. list-four.xlsx",
                "5. list-five.xlsx",
                "6. list-six.xlsx",
            )
        ):
            self.db.add(
                InformationBankTreeNode(
                    kind=KIND,
                    parent_id=int(self.parent.id),
                    name=name,
                    is_folder=False,
                    file_relpath=f"{KIND}/tree/old{i}/{name}",
                    sort_order=i,
                )
            )
        self.db.commit()
        self.xlsx = _minimal_xlsx_bytes()

    def _child_names(self, parent_id: int) -> list[str]:
        rows = (
            self.db.query(InformationBankTreeNode)
            .filter(InformationBankTreeNode.parent_id == int(parent_id))
            .order_by(InformationBankTreeNode.sort_order, InformationBankTreeNode.id)
            .all()
        )
        return [r.name for r in rows]

    def test_reupload_sorted_with_autoflush_off(self):
        upload_files_to_parent(
            self.db,
            kind=KIND,
            parent_id=int(self.parent.id),
            file_storages=[
                _FakeUpload("2. list-two.xlsx", self.xlsx),
                _FakeUpload("1. list-one.xlsx", self.xlsx),
            ],
        )
        self.db.commit()
        self.assertEqual(
            self._child_names(int(self.parent.id)),
            [
                "3. list-three.xlsx",
                "4. list-four.xlsx",
                "5. list-five.xlsx",
                "6. list-six.xlsx",
                "1. list-one.xlsx",
                "2. list-two.xlsx",
            ],
        )


    def test_single_file_uploads_one_by_one(self):
        for name in ("1. list-one.xlsx", "2. list-two.xlsx"):
            upload_files_to_parent(
                self.db,
                kind=KIND,
                parent_id=int(self.parent.id),
                file_storages=[_FakeUpload(name, self.xlsx)],
            )
            self.db.commit()
        self.assertEqual(
            self._child_names(int(self.parent.id)),
            [
                "3. list-three.xlsx",
                "4. list-four.xlsx",
                "5. list-five.xlsx",
                "6. list-six.xlsx",
                "1. list-one.xlsx",
                "2. list-two.xlsx",
            ],
        )


if __name__ == "__main__":
    unittest.main()
