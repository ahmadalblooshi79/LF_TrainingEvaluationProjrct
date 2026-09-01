import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.ibank_section_ctx import register_ibank_section_session_events
from app.models import RoleKey, User
from app.library_tree import (
    build_tree_payload,
    exercise_papers_kind,
    is_exercise_papers_kind,
    is_library_tree_kind,
    library_kind_title,
    parse_exercise_papers_eid,
    purge_library_tree,
)
from app.models import InformationBankTreeNode


class ExercisePapersKindTests(unittest.TestCase):
    def test_kind_helpers(self):
        self.assertEqual(exercise_papers_kind(12), "ex_p_12")
        self.assertEqual(parse_exercise_papers_eid("ex_p_12"), 12)
        self.assertTrue(is_exercise_papers_kind("ex_p_12"))
        self.assertTrue(is_library_tree_kind("ex_p_12"))
        self.assertFalse(is_exercise_papers_kind("land_forces"))
        self.assertEqual(library_kind_title("ex_p_12"), "أوراق التمرين")
        self.assertIsNone(parse_exercise_papers_eid("ex_p_"))
        self.assertIsNone(parse_exercise_papers_eid("land_forces"))


class ExercisePapersTreeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        register_ibank_section_session_events()

    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()

    def tearDown(self):
        self.db.close()

    def test_trees_are_isolated_per_exercise(self):
        k1 = exercise_papers_kind(1)
        k2 = exercise_papers_kind(2)
        self.db.add(
            InformationBankTreeNode(
                kind=k1, parent_id=None, name="مجلد أ", is_folder=True
            )
        )
        self.db.add(
            InformationBankTreeNode(
                kind=k2, parent_id=None, name="مجلد ب", is_folder=True
            )
        )
        self.db.commit()
        self.assertEqual([n["name"] for n in build_tree_payload(self.db, k1)], ["مجلد أ"])
        self.assertEqual([n["name"] for n in build_tree_payload(self.db, k2)], ["مجلد ب"])

    def test_purge_one_exercise_keeps_the_other(self):
        k1 = exercise_papers_kind(1)
        k2 = exercise_papers_kind(2)
        self.db.add(
            InformationBankTreeNode(
                kind=k1, parent_id=None, name="يحذف", is_folder=True
            )
        )
        self.db.add(
            InformationBankTreeNode(
                kind=k2, parent_id=None, name="يبقى", is_folder=True
            )
        )
        self.db.commit()
        purge_library_tree(self.db, k1)
        self.db.commit()
        self.assertEqual(build_tree_payload(self.db, k1), [])
        self.assertEqual([n["name"] for n in build_tree_payload(self.db, k2)], ["يبقى"])

    def test_only_existing_files_hides_missing(self):
        k = exercise_papers_kind(3)
        self.db.add(
            InformationBankTreeNode(
                kind=k,
                parent_id=None,
                name="مفقود.pdf",
                is_folder=False,
                file_relpath="ex_p_3/tree/n1/مفقود.pdf",
            )
        )
        self.db.commit()
        self.assertEqual(
            build_tree_payload(self.db, k, only_existing_files=True),
            [],
        )


class ExercisePapersPageSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import create_app
        from app.database import SessionLocal
        from app.models import Exercise

        cls.app = create_app()
        cls.app.config["TESTING"] = True
        db = SessionLocal()
        try:
            ex = db.query(Exercise).order_by(Exercise.id).first()
            cls.eid = int(ex.id) if ex else None
        finally:
            db.close()

    def test_papers_tab_requires_login(self):
        if not self.eid:
            self.skipTest("no exercise in database")
        client = self.app.test_client()
        resp = client.get(f"/exercises/{self.eid}?tab=papers", follow_redirects=False)
        self.assertIn(resp.status_code, (302, 401))

    @patch("app.views.get_current_user_optional")
    def test_papers_tab_renders_library_toolbar(self, mock_user):
        if not self.eid:
            self.skipTest("no exercise in database")
        u = MagicMock(spec=User)
        u.role_key = RoleKey.SYSTEM_ADMIN.value
        u.id = 1
        u.display_name = "مدير"
        mock_user.return_value = u
        client = self.app.test_client()
        resp = client.get(f"/exercises/{self.eid}?tab=papers")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("أوراق التمرين", html)
        self.assertIn("إضافة مجلد", html)
        self.assertIn("إرفاق ملفات", html)
        self.assertIn("إرفاق مجلد", html)
        self.assertIn("حذف جميع الملفات", html)
        self.assertIn(f"/exercises/{self.eid}/papers/tree/folder", html)


if __name__ == "__main__":
    unittest.main()

