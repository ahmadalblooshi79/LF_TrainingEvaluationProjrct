import io
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import (
    EvaluationListPdfItem,
    EvaluationListSavedResult,
    Exercise,
    ExerciseRosterKind,
    ExerciseRosterRow,
    ExerciseStatus,
    User,
)
from app.models.user import RoleKey
from app.roster_import import parse_roster_rows_from_upload
from app.views import _eval_items_owned_by_judge, _eval_sheet_judge_display_name


class _Upload:
    def __init__(self, filename: str, data: bytes):
        self.filename = filename
        self._data = data

    def read(self):
        return self._data


class JudgePhaseAttributionTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        owner = User(
            username="admin_phase",
            password_hash="x",
            full_name="مدير",
            role_key=RoleKey.SYSTEM_ADMIN.value,
        )
        self.db.add(owner)
        self.db.flush()
        self.saver = User(
            username="j_prep",
            password_hash="x",
            full_name="محكم التحضير",
            role_key=RoleKey.JUDGE.value,
        )
        self.approver = User(
            username="j_open",
            password_hash="x",
            full_name="محكم الانفتاح",
            role_key=RoleKey.JUDGE.value,
        )
        self.db.add_all([self.saver, self.approver])
        self.db.flush()
        self.ex = Exercise(
            code="T-JP-1",
            title="تمرين مراحل",
            owner_id=int(owner.id),
            status=ExerciseStatus.ACTIVE.value,
            exercise_type="trial",
            trained_unit="unit",
        )
        self.db.add(self.ex)
        self.db.flush()
        uk = "ul_mech2_bn_cmd"
        self.db.add(
            ExerciseRosterRow(
                exercise_id=self.ex.id,
                roster_kind=ExerciseRosterKind.JUDGE.value,
                sort_order=0,
                military_number="j_prep",
                full_name="محكم التحضير",
                unit_level_key=uk,
                exercise_phase="preparation",
            )
        )
        self.db.add(
            ExerciseRosterRow(
                exercise_id=self.ex.id,
                roster_kind=ExerciseRosterKind.JUDGE.value,
                sort_order=1,
                military_number="j_open",
                full_name="محكم الانفتاح",
                unit_level_key=uk,
                exercise_phase="opening",
            )
        )
        self.db.commit()
        self.uk = uk

    def tearDown(self):
        self.db.close()

    def test_roster_phase_picks_matching_judge(self):
        self.assertEqual(
            _eval_sheet_judge_display_name(
                self.db,
                exercise_id=int(self.ex.id),
                unit_key=self.uk,
                phase_key="opening",
            ),
            "محكم الانفتاح",
        )
        self.assertEqual(
            _eval_sheet_judge_display_name(
                self.db,
                exercise_id=int(self.ex.id),
                unit_key=self.uk,
                phase_key="preparation",
            ),
            "محكم التحضير",
        )

    def test_saved_and_approved_user_override_roster(self):
        saved = EvaluationListSavedResult(
            evaluation_item_id=1,
            exercise_id=int(self.ex.id),
            exercise_phase="opening",
            unit_level_key=self.uk,
            payload_json="{}",
            saved_by_id=int(self.saver.id),
            approved_by_id=int(self.approver.id),
            is_approved=True,
        )
        self.assertEqual(
            _eval_sheet_judge_display_name(
                self.db,
                exercise_id=int(self.ex.id),
                unit_key=self.uk,
                phase_key="opening",
                saved=saved,
            ),
            "محكم الانفتاح",
        )
        saved.approved_by_id = None
        self.assertEqual(
            _eval_sheet_judge_display_name(
                self.db,
                exercise_id=int(self.ex.id),
                unit_key=self.uk,
                phase_key="opening",
                saved=saved,
            ),
            "محكم التحضير",
        )

    def test_roster_csv_reads_fifth_phase_column(self):
        raw = "الرقم,الرتبة,الاسم,الوحدة,المرحلة\n1,رقيب,علي,قيادة,opening\n".encode(
            "utf-8-sig"
        )
        rows = parse_roster_rows_from_upload(_Upload("judges.csv", raw))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][4], "opening")

    def test_same_phase_judges_get_different_lists(self):
        for r in (
            self.db.query(ExerciseRosterRow)
            .filter(ExerciseRosterRow.exercise_id == int(self.ex.id))
            .all()
        ):
            r.exercise_phase = "opening"
        for i in range(4):
            self.db.add(
                EvaluationListPdfItem(
                    exercise_id=int(self.ex.id),
                    exercise_phase="opening",
                    unit_level_key=self.uk,
                    unit_level_label="قيادة",
                    sort_order=i,
                    text=f"قائمة {i}",
                    pdf_relpath=f"l{i}.xlsx",
                )
            )
        self.db.commit()
        items = (
            self.db.query(EvaluationListPdfItem)
            .filter(EvaluationListPdfItem.exercise_id == int(self.ex.id))
            .order_by(EvaluationListPdfItem.sort_order)
            .all()
        )
        a = _eval_items_owned_by_judge(self.db, self.saver, self.ex, items)
        b = _eval_items_owned_by_judge(self.db, self.approver, self.ex, items)
        ids_a = {int(x.id) for x in a}
        ids_b = {int(x.id) for x in b}
        self.assertEqual(len(ids_a), 2)
        self.assertEqual(len(ids_b), 2)
        self.assertFalse(ids_a & ids_b)
        self.assertEqual(ids_a | ids_b, {int(x.id) for x in items})


if __name__ == "__main__":
    unittest.main()
