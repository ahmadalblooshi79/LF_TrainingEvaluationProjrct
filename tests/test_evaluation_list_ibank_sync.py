import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.evaluation_list_ibank_sync import (
    INFO_BANK_EVAL_LIST_KIND,
    _deepest_unit_key_for_file_node,
    _file_belongs_to_phase_unit,
    _ibank_context_for_file_node,
    collect_ibank_eval_files_for_phase_unit,
    ibank_eval_storage_relpath,
    parse_ibank_eval_storage_relpath,
    publish_all_evaluation_lists_from_ibank,
    remap_publish_selections_by_ibank_context,
    unit_eval_group_visible_for_phase,
    resolve_ibank_eval_publish_unit_key,
)
from app.models import InformationBankTreeNode


class EvaluationListIbankSyncTests(unittest.TestCase):
    def test_ibank_eval_storage_relpath_roundtrip(self):
        rel = ibank_eval_storage_relpath("ul_brigade_grp_cmd", 42)
        self.assertEqual(rel, "ul_brigade_grp_cmd/ibn_42.xlsx")
        self.assertEqual(parse_ibank_eval_storage_relpath(rel), 42)

    def test_parse_ibank_eval_storage_relpath_rejects_manual_uploads(self):
        self.assertIsNone(parse_ibank_eval_storage_relpath("ul_brigade_grp_cmd/abc.xlsx"))


class EvalListNestedUnitDedupTests(unittest.TestCase):
    """ملفات السرايا داخل مجلد الكتيبة لا تُعرض تحت مستوى قيادة الكتيبة."""

    PARENT_UK = "ul_mech2_bn_cmd"
    CHILD_UK = "ul_mech2_bn_c1"
    PHASE = "preparation"

    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        phase_root = InformationBankTreeNode(
            kind=INFO_BANK_EVAL_LIST_KIND,
            parent_id=None,
            name="مرحلة التحضير",
            is_folder=True,
            catalog_phase_key=self.PHASE,
            sort_order=0,
        )
        self.db.add(phase_root)
        self.db.flush()
        battalion = InformationBankTreeNode(
            kind=INFO_BANK_EVAL_LIST_KIND,
            parent_id=int(phase_root.id),
            name="قيادة كتيبة",
            is_folder=True,
            catalog_unit_key=self.PARENT_UK,
            catalog_phase_key=self.PHASE,
            sort_order=0,
        )
        self.db.add(battalion)
        self.db.flush()
        self.battalion_id = int(battalion.id)
        company = InformationBankTreeNode(
            kind=INFO_BANK_EVAL_LIST_KIND,
            parent_id=int(battalion.id),
            name="السرية 1",
            is_folder=True,
            catalog_unit_key=self.CHILD_UK,
            catalog_phase_key=self.PHASE,
            sort_order=0,
        )
        self.db.add(company)
        self.db.flush()
        self.file_node = InformationBankTreeNode(
            kind=INFO_BANK_EVAL_LIST_KIND,
            parent_id=int(company.id),
            name="01 تقييم.xlsx",
            is_folder=False,
            file_relpath="dilemma_eval/test.xlsx",
            catalog_unit_key=self.CHILD_UK,
            catalog_phase_key=self.PHASE,
            sort_order=0,
        )
        self.db.add(self.file_node)
        self.db.commit()

    def test_deepest_unit_key_nested_subfolder_without_assignment_stays_empty(self):
        company_no_catalog = InformationBankTreeNode(
            kind=INFO_BANK_EVAL_LIST_KIND,
            parent_id=self.battalion_id,
            name="السرية 1",
            is_folder=True,
            catalog_phase_key=self.PHASE,
            sort_order=1,
        )
        self.db.add(company_no_catalog)
        self.db.flush()
        nested_file = InformationBankTreeNode(
            kind=INFO_BANK_EVAL_LIST_KIND,
            parent_id=int(company_no_catalog.id),
            name="07 تقييم.xlsx",
            is_folder=False,
            file_relpath="dilemma_eval/nested.xlsx",
            catalog_phase_key=self.PHASE,
            sort_order=0,
        )
        self.db.add(nested_file)
        self.db.commit()
        self.assertEqual(_deepest_unit_key_for_file_node(self.db, nested_file), "")
        f_pk, f_uk = _ibank_context_for_file_node(self.db, nested_file)
        self.assertEqual(f_uk, "")
        self.assertFalse(
            _file_belongs_to_phase_unit(
                self.db,
                nested_file,
                phase_key=self.PHASE,
                unit_key=self.PARENT_UK,
            )
        )
        self.assertFalse(
            _file_belongs_to_phase_unit(
                self.db,
                nested_file,
                phase_key=self.PHASE,
                unit_key=self.CHILD_UK,
            )
        )

    def test_nested_company_file_not_attributed_to_parent_unit(self):
        self.assertFalse(
            _file_belongs_to_phase_unit(
                self.db,
                self.file_node,
                phase_key=self.PHASE,
                unit_key=self.PARENT_UK,
            )
        )
        self.assertTrue(
            _file_belongs_to_phase_unit(
                self.db,
                self.file_node,
                phase_key=self.PHASE,
                unit_key=self.CHILD_UK,
            )
        )

    @patch("app.evaluation_list_ibank_sync.prepare_dilemma_eval_ibank_tree")
    @patch("app.evaluation_list_ibank_sync._file_node_to_source")
    def test_collect_excludes_child_files_from_parent_unit(
        self, mock_source, _mock_prepare
    ):
        mock_source.return_value = {
            "node_id": int(self.file_node.id),
            "title": "01 تقييم",
            "src_relpath": "dilemma_eval/test.xlsx",
            "src_path": None,
            "sort_order": 0,
        }
        parent_files = collect_ibank_eval_files_for_phase_unit(
            self.db, phase_key=self.PHASE, unit_key=self.PARENT_UK
        )
        child_files = collect_ibank_eval_files_for_phase_unit(
            self.db, phase_key=self.PHASE, unit_key=self.CHILD_UK
        )
        self.assertEqual(parent_files, [])
        self.assertEqual(len(child_files), 1)
        self.assertEqual(int(child_files[0]["node_id"]), int(self.file_node.id))

    def test_publish_unit_resolves_from_file_context(self):
        uk = resolve_ibank_eval_publish_unit_key(
            self.db,
            node_id=int(self.file_node.id),
            fallback_unit_key=self.PARENT_UK,
        )
        self.assertEqual(uk, self.CHILD_UK)

    def test_remap_publish_selections_moves_nodes_to_child_unit(self):
        remapped = remap_publish_selections_by_ibank_context(
            self.db,
            kind=INFO_BANK_EVAL_LIST_KIND,
            phase_key=self.PHASE,
            selections_by_unit={self.PARENT_UK: {int(self.file_node.id)}},
        )
        self.assertEqual(remapped.get(self.CHILD_UK), {int(self.file_node.id)})
        self.assertNotIn(self.PARENT_UK, remapped)


class UnitEvalGroupPhaseVisibilityTests(unittest.TestCase):
    def test_visible_only_with_ibank_or_published(self):
        self.assertFalse(
            unit_eval_group_visible_for_phase(ibank_sources=[], eval_items=[])
        )
        self.assertTrue(
            unit_eval_group_visible_for_phase(
                ibank_sources=[{"node_id": 1}], eval_items=[]
            )
        )
        self.assertTrue(
            unit_eval_group_visible_for_phase(
                ibank_sources=[], eval_items=[object()]
            )
        )


class PublishAllDoesNotAutoPublishTests(unittest.TestCase):
    @patch("app.evaluation_list_ibank_sync.prepare_dilemma_eval_ibank_tree")
    @patch("app.evaluation_list_ibank_sync.roster_eval_display_unit_keys")
    @patch("app.evaluation_list_ibank_sync.effective_eval_list_phase_keys")
    @patch("app.evaluation_list_ibank_sync.publish_evaluation_lists_from_ibank")
    @patch("app.evaluation_list_ibank_sync.prune_ibank_evaluation_lists_not_in_roster")
    def test_publish_all_passes_empty_selection(
        self,
        mock_prune,
        mock_publish,
        mock_phases,
        mock_units,
        _mock_prepare,
    ):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()
        mock_units.return_value = {"ul_mech2_bn_c1"}
        mock_phases.return_value = ["preparation"]
        mock_publish.return_value = {
            "added": 0,
            "updated": 0,
            "removed": 2,
            "sources": 0,
            "sources_available": 5,
        }
        mock_prune.return_value = 0

        stats = publish_all_evaluation_lists_from_ibank(db, exercise_id=1)

        mock_publish.assert_called_once()
        _args, kwargs = mock_publish.call_args
        self.assertEqual(kwargs.get("selected_node_ids"), set())
        self.assertEqual(int(stats["sources_available"]), 5)
        self.assertEqual(int(stats["removed"]), 2)
        self.assertEqual(int(stats["added"]), 0)
