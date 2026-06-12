import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.evaluation_list_ibank_sync import roster_eval_display_unit_keys
from app.models import (
    AnalystEvaluationCriteriaUnit,
    EvaluationListPdfItem,
    Exercise,
    ExerciseRosterKind,
    ExerciseRosterRow,
    ExerciseStatus,
    InformationBankUnitLevel,
    User,
)
from app.models.user import RoleKey
from app.planning_catalog_sync import sync_planning_catalogs_from_db
from app.views import _planner_unit_keys_for_exercise, _sync_analyst_criteria_units_from_planner


class AnalystCriteriaUnitsSyncTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        owner = User(
            username="analyst_test",
            password_hash="x",
            full_name="Test",
            role_key=RoleKey.ANALYST.value,
        )
        self.db.add(owner)
        self.db.flush()
        self.ex = Exercise(
            code="T-CRIT-1",
            title="exercise",
            owner_id=int(owner.id),
            status=ExerciseStatus.ACTIVE.value,
            exercise_type="trial",
            trained_unit="unit",
        )
        self.db.add(self.ex)
        self.db.add(
            InformationBankUnitLevel(
                key="ul_mech2_bn_cmd",
                label="قيادة كتيبة 2",
                included_in_exercise=True,
            )
        )
        self.db.add(
            InformationBankUnitLevel(
                key="ul_mech2_bn_c1",
                label="السرية 1",
                included_in_exercise=True,
            )
        )
        self.db.commit()
        sync_planning_catalogs_from_db(self.db, force=True)

    def test_planner_keys_from_judge_roster_without_published_lists(self):
        self.db.add(
            ExerciseRosterRow(
                exercise_id=self.ex.id,
                roster_kind=ExerciseRosterKind.JUDGE.value,
                unit_level_key="ul_mech2_bn_cmd",
                full_name="محكم 1",
            )
        )
        self.db.add(
            ExerciseRosterRow(
                exercise_id=self.ex.id,
                roster_kind=ExerciseRosterKind.JUDGE.value,
                unit_level_key="ul_mech2_bn_c1",
                full_name="محكم 2",
            )
        )
        self.db.commit()
        keys = _planner_unit_keys_for_exercise(self.db, self.ex)
        self.assertIn("ul_mech2_bn_cmd", keys)
        self.assertIn("ul_mech2_bn_c1", keys)
        self.assertEqual(len(roster_eval_display_unit_keys(self.db, self.ex.id)), 2)

    def test_sync_adds_missing_units_on_repeat_visit(self):
        self.db.add(
            ExerciseRosterRow(
                exercise_id=self.ex.id,
                roster_kind=ExerciseRosterKind.JUDGE.value,
                unit_level_key="ul_mech2_bn_cmd",
                full_name="محكم",
            )
        )
        self.db.commit()
        first = _sync_analyst_criteria_units_from_planner(self.db, self.ex)
        self.assertEqual(len(first), 1)

        self.db.add(
            ExerciseRosterRow(
                exercise_id=self.ex.id,
                roster_kind=ExerciseRosterKind.JUDGE.value,
                unit_level_key="ul_mech2_bn_c1",
                full_name="محكم 2",
            )
        )
        self.db.commit()
        second = _sync_analyst_criteria_units_from_planner(self.db, self.ex)
        self.assertEqual(len(second), 2)
        labels = {r.label for r in second}
        self.assertIn("السرية 1", labels)

    def test_planner_keys_include_published_eval_list_units(self):
        self.db.add(
            EvaluationListPdfItem(
                exercise_id=self.ex.id,
                exercise_phase="preparation",
                unit_level_key="ul_mech2_bn_cmd",
                unit_level_label="قيادة",
                text="قائمة 1",
                pdf_relpath="x/ul_mech2_bn_cmd/ibn_1.xlsx",
            )
        )
        self.db.commit()
        keys = _planner_unit_keys_for_exercise(self.db, self.ex)
        self.assertIn("ul_mech2_bn_cmd", keys)

    def test_sync_preserves_legacy_unit_not_in_planner_roster(self):
        self.db.add(
            ExerciseRosterRow(
                exercise_id=self.ex.id,
                roster_kind=ExerciseRosterKind.JUDGE.value,
                unit_level_key="ul_mech2_bn_cmd",
                full_name="محكم",
            )
        )
        legacy = AnalystEvaluationCriteriaUnit(
            exercise_id=self.ex.id,
            sort_order=0,
            label="وحدة قديمة",
        )
        self.db.add(legacy)
        self.db.commit()
        synced = _sync_analyst_criteria_units_from_planner(self.db, self.ex)
        self.assertEqual(len(synced), 2)
        labels = {r.label for r in synced}
        self.assertIn("وحدة قديمة", labels)
        self.assertIn("قيادة كتيبة 2", labels)


if __name__ == "__main__":
    unittest.main()
