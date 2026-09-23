import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.exercise_phase_catalog import EXERCISE_PHASE_OPTIONS
from app.information_bank_catalog import TRAINING_PHASES, TRAINING_PHASE_ORDER
from app.info_bank_tree import _phase_rows
from app.models import InformationBankTrainingPhase
from app.planning_catalog_sync import sync_planning_exercise_phases_from_db
from app.views import _ensure_information_bank_catalog_rows, _information_bank_training_phases


class EmptyExercisePhasesCatalogTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        EXERCISE_PHASE_OPTIONS.clear()

    def tearDown(self):
        EXERCISE_PHASE_OPTIONS.clear()
        self.db.close()

    def test_builtin_templates_are_empty(self):
        self.assertEqual(TRAINING_PHASES, [])
        self.assertEqual(TRAINING_PHASE_ORDER, ())

    def test_ensure_does_not_seed_phases(self):
        _ensure_information_bank_catalog_rows(self.db)
        self.assertEqual(self.db.query(InformationBankTrainingPhase).count(), 0)
        self.assertEqual(_information_bank_training_phases(self.db), [])
        self.assertEqual(_phase_rows(self.db), [])

    def test_ensure_keeps_user_added_phase_and_label(self):
        self.db.add(
            InformationBankTrainingPhase(
                key="phase_custom1",
                label="مرحلة المستخدم",
                sort_order=3,
                is_system=False,
                included_in_exercise=True,
            )
        )
        self.db.commit()
        _ensure_information_bank_catalog_rows(self.db)
        row = (
            self.db.query(InformationBankTrainingPhase)
            .filter_by(key="phase_custom1")
            .first()
        )
        self.assertIsNotNone(row)
        self.assertEqual(row.label, "مرحلة المستخدم")
        self.assertEqual(row.sort_order, 3)
        sync_planning_exercise_phases_from_db(self.db)
        self.assertEqual(list(EXERCISE_PHASE_OPTIONS), [("phase_custom1", "مرحلة المستخدم")])


if __name__ == "__main__":
    unittest.main()
