# -*- coding: utf-8 -*-
import unittest
from pathlib import Path

from app.ibank_dilemma_folder_import import (
    parse_day_no_from_dirname,
    parse_dilemma_folder_codes,
    parse_dilemma_no_from_text,
    parse_numbered_dilemma_item,
    scan_external_dilemma_folders,
)


class DilemmaFolderParseTests(unittest.TestCase):
    def test_parse_y_m_folder(self):
        self.assertEqual(
            parse_dilemma_folder_codes("1. ي1 - م1 - فرض الصمت"),
            (1, 1),
        )
        self.assertEqual(
            parse_dilemma_folder_codes("2. ي1 - م2- تعرض الاستطلاع لكمين"),
            (1, 2),
        )
        self.assertEqual(
            parse_dilemma_folder_codes("معضلة 2", parent_day_no=2),
            (2, 2),
        )
        self.assertEqual(
            parse_dilemma_folder_codes("1. كمين على الاستطلاع", parent_day_no=1),
            (1, 1),
        )
        self.assertEqual(
            parse_dilemma_folder_codes("4. فقدان الاتصال اللاسلكي", parent_day_no=1),
            (1, 4),
        )
        self.assertIsNone(parse_dilemma_folder_codes("1. اليوم 1", parent_day_no=1))
        self.assertIsNone(parse_dilemma_folder_codes("معاضل اليوم الأول", parent_day_no=1))

    def test_parse_numbered_dilemma_item(self):
        self.assertEqual(parse_numbered_dilemma_item("1. كمين على الاستطلاع"), 1)
        self.assertEqual(parse_numbered_dilemma_item("2. هجوم مسيرة"), 2)
        self.assertEqual(parse_numbered_dilemma_item("7- طائرة استطلاع معادية"), 7)
        self.assertIsNone(parse_numbered_dilemma_item("1. اليوم 1"))
        self.assertIsNone(parse_numbered_dilemma_item("معاضل اليوم الأول"))
        self.assertIsNone(parse_numbered_dilemma_item("كمين على الاستطلاع"))

    def test_parse_day_dir(self):
        self.assertEqual(parse_day_no_from_dirname("1. اليوم 1"), 1)
        self.assertEqual(parse_day_no_from_dirname("2. اليوم2"), 2)

    def test_assignees_collected_when_dilemma_title_uses_hyphen(self):
        import json

        from app.ibank_action_eval_dilemma_tree import _assignees_by_dilemma_from_flow

        raw = json.dumps(
            {
                "days": [
                    {
                        "id": "day-1",
                        "rows": [
                            {
                                "kind": "dilemma",
                                "text": "المعضلة-3: إنذار وهجوم طائرة مسيرة",
                            },
                            {
                                "kind": "row",
                                "assignee": "محكم الطبية\nمحكم الصيانة",
                            },
                        ],
                    }
                ]
            }
        )
        out = _assignees_by_dilemma_from_flow(raw)
        self.assertEqual(out["day-1"][3], ["محكم الطبية", "محكم الصيانة"])

    def test_scan_desktop_day1_if_present(self):
        root = Path(r"C:/Users/W10User/Desktop")
        if not root.is_dir():
            self.skipTest("Desktop missing")
        packs = scan_external_dilemma_folders(root)
        self.assertTrue(any(p["dilemma_no"] == 1 and p["day_no"] == 1 for p in packs))


class CollectLinkedNumberedFoldersTests(unittest.TestCase):
    def test_collects_xlsx_under_numbered_title_folders(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.database import Base
        from app.ibank_dilemma_folder_import import collect_linked_files_by_dilemma
        from app.info_bank_tree import flow_day_catalog_key
        from app.models.domain import InformationBankTreeNode

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()
        root = InformationBankTreeNode(
            kind="action_eval",
            parent_id=None,
            name="اليوم/1",
            is_folder=True,
            catalog_phase_key=flow_day_catalog_key("day-1"),
        )
        db.add(root)
        db.flush()
        group = InformationBankTreeNode(
            kind="action_eval",
            parent_id=int(root.id),
            name="معاضل اليوم الأول",
            is_folder=True,
        )
        db.add(group)
        db.flush()
        folder = InformationBankTreeNode(
            kind="action_eval",
            parent_id=int(group.id),
            name="1. كمين على الاستطلاع",
            is_folder=True,
        )
        db.add(folder)
        db.flush()
        db.add(
            InformationBankTreeNode(
                kind="action_eval",
                parent_id=int(folder.id),
                name="كمين على الاستطلاع.xlsx",
                is_folder=False,
                catalog_unit_key="ul_recon",
            )
        )
        db.commit()
        linked = collect_linked_files_by_dilemma(db)
        names = [f["name"] for f in (linked.get("day-1") or {}).get(1, [])]
        self.assertEqual(names, ["كمين على الاستطلاع.xlsx"])
        db.close()


if __name__ == "__main__":
    unittest.main()
