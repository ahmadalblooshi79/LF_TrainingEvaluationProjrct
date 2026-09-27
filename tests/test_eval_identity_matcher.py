import unittest
from types import SimpleNamespace

from app.eval_identity_matcher import (
    CandidateTarget,
    SourceIdentity,
    match_evaluation,
    normalize_ar_text,
    remember_mapping,
)


def _cand(**kwargs):
    defaults = dict(
        eval_item_id=557,
        unit_id="snipers",
        unit_name="سرية القناصة",
        list_name="تقييم القيادة والسيطرة",
        evaluation_type="evaluation_list",
        stage_id="operations",
        stage_name="العمليات",
        dilemma_id=None,
        dilemma_name="",
        exercise_id=2,
        judge_id=9,
        judge_name="محكم أ",
        approved=False,
        chief_approved=False,
    )
    defaults.update(kwargs)
    return CandidateTarget(**defaults)


class FakeQuery:
    def __init__(self, rows=None):
        self._rows = list(rows or [])

    def filter(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None

    def one_or_none(self):
        return self._rows[0] if self._rows else None


class FakeDb:
    def __init__(self, items=None, mappings=None, saved=None):
        self.items = {int(i.id): i for i in (items or [])}
        self.mappings = list(mappings or [])
        self.saved = dict(saved or {})
        self.added = []

    def get(self, model, pk):
        name = getattr(model, "__name__", str(model))
        if "PdfItem" in name or "EvaluationListPdfItem" in name:
            return self.items.get(int(pk))
        return None

    def query(self, model):
        name = getattr(model, "__name__", str(model))
        if "Mapping" in name:
            return FakeQuery(self.mappings)
        if "SavedResult" in name:
            return FakeQuery(list(self.saved.values()))
        return FakeQuery([])

    def add(self, row):
        self.added.append(row)

    def flush(self):
        for row in self.added:
            if getattr(row, "id", None) is None:
                row.id = 1


class EvalIdentityMatcherTests(unittest.TestCase):
    def test_normalize_ar_variants(self):
        self.assertEqual(normalize_ar_text("  سريّة   القناصة  "), normalize_ar_text("سرية القناصة"))
        self.assertEqual(normalize_ar_text("إدارة"), normalize_ar_text("ادارة"))
        self.assertEqual(normalize_ar_text("كبرى"), normalize_ar_text("كبرى"))

    def test_exact_id_same_unit(self):
        item = SimpleNamespace(
            id=180,
            exercise_id=2,
            unit_level_key="snipers",
            unit_level_label="سرية القناصة",
            text="تقييم القيادة والسيطرة",
            exercise_phase="operations",
        )
        db = FakeDb(items=[item])
        src = SourceIdentity(
            exercise_id=2,
            unit_id="snipers",
            unit_name="سرية القناصة",
            eval_item_id=180,
            evaluation_list_name="تقييم القيادة والسيطرة",
            evaluation_type="evaluation_list",
        )
        r = match_evaluation(db, src, current_exercise_id=2, candidates=[_cand(eval_item_id=180)])
        self.assertEqual(r.status, "MATCHED_EXACT")
        self.assertEqual(r.target.eval_item_id, 180)

    def test_old_id_fallback_unit_list_type(self):
        cands = [_cand(eval_item_id=557)]
        db = FakeDb()
        src = SourceIdentity(
            exercise_id=1,
            unit_id="snipers",
            unit_name="سرية القناصة",
            eval_item_id=180,
            evaluation_list_name="تقييم القيادة والسيطرة",
            evaluation_type="evaluation_list",
        )
        r = match_evaluation(db, src, current_exercise_id=2, candidates=cands)
        self.assertEqual(r.status, "MATCHED_BY_UNIT_LIST")
        self.assertEqual(r.target.eval_item_id, 557)
        self.assertIn("UNIT", r.match_method)

    def test_judge_changed_unit_list_same(self):
        cands = [_cand(eval_item_id=557, judge_id=99, judge_name="محكم ب")]
        db = FakeDb()
        src = SourceIdentity(
            unit_id="snipers",
            unit_name="سرية القناصة",
            eval_item_id=180,
            evaluation_list_name="تقييم القيادة والسيطرة",
            evaluation_type="evaluation_list",
            judge_id=3,
            judge_name="محكم أ",
        )
        r = match_evaluation(db, src, current_exercise_id=2, candidates=cands)
        self.assertEqual(r.status, "MATCHED_BY_UNIT_LIST")
        self.assertEqual(r.target.eval_item_id, 557)

    def test_unit_id_changed_normalized_name(self):
        cands = [_cand(eval_item_id=557, unit_id="sniper-co", unit_name="سرية القناصة")]
        db = FakeDb()
        src = SourceIdentity(
            unit_id="old-snipers",
            unit_name="  سريّة   القناصة ",
            evaluation_list_name="تقييم القيادة والسيطرة",
            evaluation_type="evaluation_list",
            eval_item_id=180,
        )
        r = match_evaluation(db, src, current_exercise_id=2, candidates=cands)
        self.assertEqual(r.status, "MATCHED_BY_UNIT_LIST")

    def test_similar_names_ambiguous(self):
        cands = [
            _cand(eval_item_id=557, list_name="تقييم القيادة والسيطرة"),
            _cand(eval_item_id=561, list_name="تقييم القيادة والسيطرة"),
        ]
        db = FakeDb()
        src = SourceIdentity(
            unit_id="snipers",
            unit_name="سرية القناصة",
            evaluation_list_name="تقييم القيادة والسيطرة",
            evaluation_type="evaluation_list",
        )
        r = match_evaluation(db, src, current_exercise_id=2, candidates=cands)
        self.assertEqual(r.status, "AMBIGUOUS")
        self.assertIsNone(r.target)

    def test_closed_reopened_recreated_lists(self):
        cands = [_cand(eval_item_id=557, exercise_id=9)]
        db = FakeDb()
        src = SourceIdentity(
            exercise_id=1,
            unit_id="snipers",
            unit_name="سرية القناصة",
            eval_item_id=180,
            evaluation_list_name="تقييم القيادة والسيطرة",
            evaluation_type="evaluation_list",
            stage_id="operations",
        )
        r = match_evaluation(db, src, current_exercise_id=9, candidates=cands)
        self.assertEqual(r.target.eval_item_id, 557)
        self.assertIn(r.status, ("MATCHED_BY_UNIT_LIST", "MATCHED_BY_CONTEXT"))

    def test_approved_conflict_default_skip(self):
        cands = [_cand(eval_item_id=557, approved=True)]
        db = FakeDb()
        src = SourceIdentity(
            unit_id="snipers",
            unit_name="سرية القناصة",
            eval_item_id=557,
            evaluation_list_name="تقييم القيادة والسيطرة",
        )
        r = match_evaluation(db, src, current_exercise_id=2, candidates=cands)
        self.assertEqual(r.status, "CONFLICT")
        self.assertIn("معتمدة", "".join(r.conflicts))

    def test_manual_mapping_remembered(self):
        mapping = SimpleNamespace(
            id=11,
            source_exercise_id=1,
            source_eval_item_id=180,
            source_unit_id="snipers",
            source_unit_name="سرية القناصة",
            source_eval_name="تقييم القيادة والسيطرة",
            target_exercise_id=2,
            target_eval_item_id=557,
        )
        db = FakeDb(mappings=[mapping])
        src = SourceIdentity(
            exercise_id=1,
            unit_id="snipers",
            unit_name="سرية القناصة",
            eval_item_id=180,
            evaluation_list_name="تقييم القيادة والسيطرة",
        )
        r = match_evaluation(db, src, current_exercise_id=2, candidates=[_cand(eval_item_id=557)])
        self.assertEqual(r.status, "MATCHED_EXACT")
        self.assertEqual(r.match_method, "MANUAL_MAPPING")
        self.assertEqual(r.target.eval_item_id, 557)


if __name__ == "__main__":
    unittest.main()
