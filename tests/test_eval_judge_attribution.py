import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.eval_judge_attribution import (
    assigned_judge_user_for_unit,
    attribution_user_id_for_eval_actor,
    reattribute_admin_saved_eval_rows,
    user_is_admin_attribution_source,
)
from app.models import (
    EvaluationListPdfItem,
    EvaluationListSavedResult,
    Exercise,
    ExerciseRosterKind,
    ExerciseRosterRow,
    ExerciseStatus,
    JudgeTraineeAssignment,
    User,
)
from app.models.user import RoleKey
from app.views import _eval_sheet_judge_display_name


class EvalJudgeAttributionTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.admin = User(
            username="admin1",
            password_hash="x",
            full_name="إدارة النظام",
            role_key=RoleKey.SYSTEM_ADMIN.value,
        )
        self.judge = User(
            username="j100",
            password_hash="x",
            full_name="محكم الوحدة",
            role_key=RoleKey.JUDGE.value,
        )
        self.db.add_all([self.admin, self.judge])
        self.db.flush()
        self.ex = Exercise(
            code="T-ATTR-1",
            title="تمرين إسناد",
            owner_id=int(self.admin.id),
            status=ExerciseStatus.ACTIVE.value,
            exercise_type="trial",
            trained_unit="unit",
        )
        self.db.add(self.ex)
        self.db.flush()
        self.uk = "ul_test_bn"
        self.db.add(
            JudgeTraineeAssignment(
                exercise_id=int(self.ex.id),
                judge_user_id=int(self.judge.id),
                unit_level_key=self.uk,
                exercise_phase="preparation",
            )
        )
        self.db.add(
            ExerciseRosterRow(
                exercise_id=int(self.ex.id),
                roster_kind=ExerciseRosterKind.JUDGE.value,
                sort_order=0,
                military_number="j100",
                full_name="محكم الوحدة",
                unit_level_key=self.uk,
                exercise_phase="preparation",
            )
        )
        item = EvaluationListPdfItem(
            exercise_id=int(self.ex.id),
            exercise_phase="preparation",
            unit_level_key=self.uk,
            text="قائمة",
            pdf_relpath="x.xlsx",
        )
        self.db.add(item)
        self.db.flush()
        self.item = item
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_admin_user_is_attribution_source(self):
        self.assertTrue(user_is_admin_attribution_source(self.admin))
        self.assertFalse(user_is_admin_attribution_source(self.judge))

    def test_assigned_judge_from_assignment(self):
        u = assigned_judge_user_for_unit(
            self.db,
            exercise_id=int(self.ex.id),
            unit_key=self.uk,
            phase_key="preparation",
        )
        self.assertIsNotNone(u)
        self.assertEqual(int(u.id), int(self.judge.id))

    def test_admin_save_attributes_to_assigned_judge(self):
        uid = attribution_user_id_for_eval_actor(
            self.db,
            self.admin,
            exercise_id=int(self.ex.id),
            unit_key=self.uk,
            phase_key="preparation",
        )
        self.assertEqual(uid, int(self.judge.id))
        uid_j = attribution_user_id_for_eval_actor(
            self.db,
            self.judge,
            exercise_id=int(self.ex.id),
            unit_key=self.uk,
            phase_key="preparation",
        )
        self.assertEqual(uid_j, int(self.judge.id))

    def test_display_skips_admin_name(self):
        saved = EvaluationListSavedResult(
            evaluation_item_id=int(self.item.id),
            exercise_id=int(self.ex.id),
            exercise_phase="preparation",
            unit_level_key=self.uk,
            payload_json="{}",
            saved_by_id=int(self.admin.id),
        )
        self.db.add(saved)
        self.db.flush()
        self.assertEqual(
            _eval_sheet_judge_display_name(
                self.db,
                exercise_id=int(self.ex.id),
                unit_key=self.uk,
                phase_key="preparation",
                saved=saved,
            ),
            "محكم الوحدة",
        )

    def test_reattribute_admin_saved_rows(self):
        saved = EvaluationListSavedResult(
            evaluation_item_id=int(self.item.id),
            exercise_id=int(self.ex.id),
            exercise_phase="preparation",
            unit_level_key=self.uk,
            payload_json="{}",
            saved_by_id=int(self.admin.id),
            approved_by_id=int(self.admin.id),
            is_approved=True,
        )
        self.db.add(saved)
        self.db.flush()
        n = reattribute_admin_saved_eval_rows(self.db, int(self.ex.id))
        self.db.commit()
        self.assertEqual(n, 1)
        self.db.refresh(saved)
        self.assertEqual(int(saved.saved_by_id), int(self.judge.id))
        self.assertEqual(int(saved.approved_by_id), int(self.judge.id))


if __name__ == "__main__":
    unittest.main()
