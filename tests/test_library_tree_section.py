import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.ibank_section_ctx import (
    current_ibank_section,
    register_ibank_section_session_events,
    set_ibank_section,
)
from app.ibank_ui import IBANK_SECTION_MISSION, IBANK_SECTION_WARGAMES
from app.library_tree import build_tree_payload, purge_library_tree
from app.models import InformationBankTreeNode


class LibraryTreeSectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        register_ibank_section_session_events()

    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.db.add(
            InformationBankTreeNode(
                kind="land_forces",
                parent_id=None,
                name="عقيدة اختبار",
                is_folder=True,
                ibank_section=IBANK_SECTION_WARGAMES,
            )
        )
        self.db.commit()

    def tearDown(self):
        set_ibank_section(IBANK_SECTION_MISSION)
        self.db.close()

    def test_payload_lists_library_when_section_is_wargames(self):
        set_ibank_section(IBANK_SECTION_WARGAMES)
        self.assertEqual(current_ibank_section(), IBANK_SECTION_WARGAMES)
        tree = build_tree_payload(self.db, "land_forces")
        self.assertEqual([n["name"] for n in tree], ["عقيدة اختبار"])

    def test_payload_lists_library_when_section_is_mission(self):
        set_ibank_section(IBANK_SECTION_MISSION)
        tree = build_tree_payload(self.db, "land_forces")
        self.assertEqual([n["name"] for n in tree], ["عقيدة اختبار"])

    def test_purge_removes_all_nodes_in_kind(self):
        self.db.add(
            InformationBankTreeNode(
                kind="land_forces",
                parent_id=None,
                name="ملف.pdf",
                is_folder=False,
                file_relpath="land_forces/tree/n1/file.pdf",
                ibank_section=IBANK_SECTION_WARGAMES,
            )
        )
        self.db.add(
            InformationBankTreeNode(
                kind="other_branches",
                parent_id=None,
                name="يبقى",
                is_folder=True,
                ibank_section=IBANK_SECTION_WARGAMES,
            )
        )
        self.db.commit()
        removed = purge_library_tree(self.db, "land_forces")
        self.db.commit()
        self.assertGreaterEqual(removed, 2)
        self.assertEqual(build_tree_payload(self.db, "land_forces"), [])
        other = build_tree_payload(self.db, "other_branches")
        self.assertEqual([n["name"] for n in other], ["يبقى"])


if __name__ == "__main__":
    unittest.main()
