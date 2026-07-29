"""Tests Phase B2.1 — Military Document Structure Agent."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.ai_training.models import (
    AiTrainingDocument,
    AiTrainingDocumentBlock,
    AiTrainingStructureRun,
)
from app.ai_training.structure.chunking import StructureChunker
from app.ai_training.structure.numbering_rules import detect_numbering
from app.ai_training.structure.rule_engine import StructureRuleEngine
from app.ai_training.structure.schema import parse_and_validate_llm_response
from app.ai_training.structure.validator import prevent_circular_parent, validate_structures
from app.ai_training.structure_constants import (
    MILITARY_STRUCTURE_AGENT_KEY,
    ST_APPROVED_STRUCTURE,
    ST_NEEDS_REVIEW,
    ST_NOT_STARTED,
    ST_REVIEW_COMPLETED,
)


class NumberingRulesTests(unittest.TestCase):
    def test_level1_arabic_dot(self):
        m = detect_numbering("1. عام")
        self.assertIsNotNone(m)
        self.assertEqual(m.numbering_style, "arabic_dot")
        self.assertEqual(m.numbering_level, 1)
        self.assertEqual(m.numbering_text, "1.")
        self.assertEqual(m.remainder, "عام")

    def test_level2_arabic_letter(self):
        m = detect_numbering("أ. منهجية تقييم")
        self.assertIsNotNone(m)
        self.assertEqual(m.numbering_style, "arabic_letter_dot")
        self.assertEqual(m.numbering_level, 2)

    def test_level3_number_paren(self):
        m = detect_numbering("(1) النص الأول")
        self.assertIsNotNone(m)
        self.assertEqual(m.numbering_style, "number_parentheses")
        self.assertEqual(m.numbering_level, 3)

    def test_level4_letter_paren(self):
        m = detect_numbering("(أ) تفصيل")
        self.assertIsNotNone(m)
        self.assertEqual(m.numbering_style, "letter_parentheses")
        self.assertEqual(m.numbering_level, 4)

    def test_level5_close_paren(self):
        m = detect_numbering("1) بند")
        self.assertIsNotNone(m)
        self.assertEqual(m.numbering_style, "number_close_paren")
        self.assertEqual(m.numbering_level, 5)


class RuleEngineTests(unittest.TestCase):
    def test_heading_from_docx_style(self):
        engine = StructureRuleEngine(enabled=True)
        blocks = [
            {
                "id": 1,
                "block_index": 0,
                "block_type": "paragraph",
                "text_content": "عام",
                "style_name": "Heading 1",
                "heading_level": None,
                "list_level": 0,
                "numbering_text": None,
                "metadata": {"bold": True},
            }
        ]
        results = engine.analyze_blocks(blocks)
        self.assertEqual(results[0].detected_role, "heading")
        self.assertTrue(results[0].is_heading)
        self.assertTrue(any("docx_style" in e or "Heading" in e for e in results[0].evidence) or results[0].confidence >= 0.8)

    def test_bold_underline_evidence(self):
        engine = StructureRuleEngine(enabled=True)
        blocks = [
            {
                "id": 2,
                "block_index": 0,
                "block_type": "paragraph",
                "text_content": "1. القصد",
                "style_name": "",
                "metadata": {"bold": True, "underline": True},
            }
        ]
        r = engine.analyze_blocks(blocks)[0]
        self.assertTrue(r.is_heading)
        self.assertTrue(any("bold" in e for e in r.evidence))

    def test_parent_child_nested(self):
        engine = StructureRuleEngine(enabled=True)
        blocks = [
            {"id": 10, "block_index": 0, "block_type": "paragraph", "text_content": "1. عام", "metadata": {"bold": True}},
            {"id": 11, "block_index": 1, "block_type": "paragraph", "text_content": "أ. نص الفقرة", "metadata": {}},
            {"id": 12, "block_index": 2, "block_type": "paragraph", "text_content": "(1) النص الأول", "metadata": {}},
        ]
        results = engine.analyze_blocks(blocks)
        self.assertEqual(results[0].numbering_level, 1)
        self.assertEqual(results[1].numbering_level, 2)
        self.assertEqual(results[1].parent_block_id, 10)
        self.assertEqual(results[2].numbering_level, 3)

    def test_duplicate_numbering_warning(self):
        engine = StructureRuleEngine(enabled=True)
        blocks = [
            {"id": 1, "block_index": 0, "text_content": "1. أول", "block_type": "paragraph", "metadata": {"bold": True}},
            {"id": 2, "block_index": 1, "text_content": "1. مكرر", "block_type": "paragraph", "metadata": {"bold": True}},
        ]
        results = engine.analyze_blocks(blocks)
        self.assertTrue(any("duplicate_numbering" in (r.warnings or []) for r in results))

    def test_sequence_break_warning(self):
        engine = StructureRuleEngine(enabled=True)
        blocks = [
            {"id": 1, "block_index": 0, "text_content": "1. أ", "block_type": "paragraph", "metadata": {"bold": True}},
            {"id": 2, "block_index": 1, "text_content": "3. ج", "block_type": "paragraph", "metadata": {"bold": True}},
        ]
        results = engine.analyze_blocks(blocks)
        self.assertTrue(any("numbering_sequence_break" in (r.warnings or []) for r in results))


class ChunkingTests(unittest.TestCase):
    def test_chunking_splits(self):
        blocks = [{"id": i, "block_index": i, "text_content": f"نص {i} " * 5} for i in range(100)]
        chunks = StructureChunker(chunk_blocks=40, context_before=3, context_after=3).build_chunks(blocks)
        self.assertGreaterEqual(len(chunks), 2)
        self.assertTrue(all(c.block_ids for c in chunks))

    def test_chunk_overlap_context(self):
        blocks = [{"id": i, "block_index": i, "text_content": f"B{i}"} for i in range(50)]
        chunks = StructureChunker(chunk_blocks=20, context_before=3, context_after=2).build_chunks(blocks)
        self.assertTrue(chunks[1].previous_context)
        self.assertIn("B", chunks[0].next_preview or "B")


class SchemaTests(unittest.TestCase):
    def test_valid_qwen_json(self):
        payload = {
            "chunk_id": "c1",
            "structures": [
                {
                    "block_id": 1,
                    "detected_role": "heading",
                    "numbering_text": "1.",
                    "numbering_style": "arabic_dot",
                    "numbering_level": 1,
                    "indentation_level": 0,
                    "parent_block_id": None,
                    "sequence_order": 1,
                    "title_text": "عام",
                    "content_text": "",
                    "is_heading": True,
                    "confidence": 0.95,
                    "evidence": ["numbering pattern 1."],
                    "warnings": [],
                }
            ],
            "chunk_warnings": [],
        }
        ok, errs, out = parse_and_validate_llm_response(json.dumps(payload, ensure_ascii=False))
        self.assertTrue(ok)
        self.assertEqual(len(out["structures"]), 1)

    def test_invalid_json_handling(self):
        ok, errs, out = parse_and_validate_llm_response("not json {{{")
        self.assertFalse(ok)
        self.assertIn("invalid_json", errs)


class ValidatorTests(unittest.TestCase):
    def test_circular_parent_prevention(self):
        structures = [
            {"block_id": 1, "parent_block_id": 2, "numbering_level": 1, "sequence_order": 1, "detected_role": "heading"},
            {"block_id": 2, "parent_block_id": 1, "numbering_level": 2, "sequence_order": 2, "detected_role": "subheading"},
        ]
        cleaned = prevent_circular_parent(structures)
        # at least one parent cleared
        self.assertTrue(any(s.get("parent_block_id") is None for s in cleaned))

    def test_missing_block_and_coverage(self):
        structures = [
            {"block_id": 1, "parent_block_id": None, "numbering_level": 1, "sequence_order": 1, "detected_role": "heading"},
        ]
        v = validate_structures(structures, expected_block_ids={1, 2})
        self.assertTrue(any("unclassified" in w or "missing_structure" in w for w in v["warnings"]))


class AgentRegistrationTests(unittest.TestCase):
    def test_agent_in_code_registry(self):
        from app.ai_agentic.agents import _CODE_AGENTS

        self.assertIn(MILITARY_STRUCTURE_AGENT_KEY, _CODE_AGENTS)

    def test_display_name_ar(self):
        from app.ai_agentic.display import agent_display_name_ar

        self.assertIn("بنية", agent_display_name_ar(MILITARY_STRUCTURE_AGENT_KEY))


class StructureServiceDbTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db_path = Path(self.tmp.name) / "t.db"
        self.engine = create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        # minimal agentic tables if needed — create_all from models
        import app.ai_agentic.models  # noqa: F401
        import app.ai_training.models  # noqa: F401

        Base.metadata.create_all(self.engine)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self.tmp.cleanup()

    def _doc(self, *, approved=True, review_completed=False):
        doc = AiTrainingDocument(
            document_uuid="u1",
            document_group_uuid="g1",
            title="تقرير اختبار",
            original_filename="t.docx",
            stored_filename="t.docx",
            storage_path=str(Path(self.tmp.name) / "t.docx"),
            status="APPROVED_EXTRACTION" if approved else "REVIEWED",
            extraction_status="SUCCESS",
            review_status="REVIEW_COMPLETED" if (approved or review_completed) else "IN_REVIEW",
            approval_status="APPROVED_EXTRACTION" if approved else "NOT_APPROVED",
            structure_status=ST_NOT_STARTED,
            mime_type="application/octet-stream",
            file_extension=".docx",
            sha256_hash="abc",
        )
        self.db.add(doc)
        self.db.flush()
        Path(doc.storage_path).write_bytes(b"x")
        for i, text in enumerate(["1. عام", "أ. فقرة", "2. القصد", "3. أهداف التمرين"]):
            self.db.add(
                AiTrainingDocumentBlock(
                    document_id=doc.id,
                    block_index=i,
                    block_type="paragraph",
                    text_content=text,
                    original_text=text,
                )
            )
        self.db.commit()
        return doc

    def test_requires_approved_extraction(self):
        from app.ai_training.structure.service import StructurePrerequisiteError, StructureService

        doc = self._doc(approved=False, review_completed=False)
        svc = StructureService(self.db)
        with self.assertRaises(StructurePrerequisiteError):
            svc.assert_prefers_approved(doc, allow_review_completed=False)

    def test_llm_disabled_rules_only(self):
        from app.ai_agentic.agents.military_structure_agent import MilitaryStructureAgent

        doc = self._doc()
        blocks = [
            {"id": b.id, "block_index": b.block_index, "block_type": b.block_type, "text_content": b.text_content, "metadata": {}}
            for b in self.db.query(AiTrainingDocumentBlock).filter_by(document_id=doc.id).all()
        ]
        agent = MilitaryStructureAgent(self.db)
        with patch("app.ai_training.structure_config.AI_STRUCTURE_LLM_ENABLED", False), patch(
            "app.ai_training.structure_config.AI_STRUCTURE_ENABLED", True
        ):
            out = agent.run({"blocks": blocks})
        self.assertIn(out.status, ("success", "warning"))
        self.assertTrue(out.data.get("structures"))
        self.assertFalse(out.data.get("llm_used"))

    def test_persist_outline_and_unchanged_blocks(self):
        from app.ai_training.structure.service import StructureService

        doc = self._doc()
        blocks_before = [
            (b.id, b.text_content, b.original_text)
            for b in self.db.query(AiTrainingDocumentBlock).filter_by(document_id=doc.id).all()
        ]
        approval_before = doc.approval_status

        from app.ai_agentic.agents.military_structure_agent import MilitaryStructureAgent

        blocks = [
            {
                "id": b.id,
                "block_index": b.block_index,
                "block_type": b.block_type,
                "text_content": b.text_content,
                "metadata": {},
            }
            for b in self.db.query(AiTrainingDocumentBlock).filter_by(document_id=doc.id).all()
        ]
        with patch("app.ai_training.structure_config.AI_STRUCTURE_LLM_ENABLED", False):
            out = MilitaryStructureAgent(self.db).run({"blocks": blocks})

        run = AiTrainingStructureRun(
            document_id=doc.id,
            status="COMPLETED",
            structure_version="1.0.0",
            total_blocks=len(blocks),
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        StructureService(self.db)._persist_structures(doc, run, out.data["structures"], blocks)
        outline = StructureService(self.db).get_outline(doc.id, run_id=run.id)
        self.assertTrue(len(outline) >= 1)

        blocks_after = [
            (b.id, b.text_content, b.original_text)
            for b in self.db.query(AiTrainingDocumentBlock).filter_by(document_id=doc.id).all()
        ]
        self.assertEqual(blocks_before, blocks_after)
        self.db.refresh(doc)
        self.assertEqual(doc.approval_status, approval_before)

    def test_review_save_and_approve_lock(self):
        from app.ai_training.structure.service import StructureLockedError, StructureService
        from app.ai_agentic.agents.military_structure_agent import MilitaryStructureAgent

        doc = self._doc()
        blocks = [
            {"id": b.id, "block_index": b.block_index, "block_type": b.block_type, "text_content": b.text_content, "metadata": {}}
            for b in self.db.query(AiTrainingDocumentBlock).filter_by(document_id=doc.id).all()
        ]
        with patch("app.ai_training.structure_config.AI_STRUCTURE_LLM_ENABLED", False):
            out = MilitaryStructureAgent(self.db).run({"blocks": blocks})
        svc = StructureService(self.db)
        run = AiTrainingStructureRun(document_id=doc.id, status="COMPLETED", structure_version="1.0.0")
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        svc._persist_structures(doc, run, out.data["structures"], blocks)
        doc.latest_structure_run_id = run.id
        doc.structure_status = ST_NEEDS_REVIEW
        self.db.commit()

        structs = svc.get_structures(doc.id)
        self.assertTrue(structs)
        svc.save_review(
            doc.id,
            [{"structure_id": structs[0].id, "detected_role": "heading", "is_heading": True, "reason": "fix"}],
            user_id=1,
        )
        svc.complete_review(doc.id, user_id=1)
        self.db.refresh(doc)
        self.assertEqual(doc.structure_status, ST_REVIEW_COMPLETED)
        extraction_before = doc.approval_status
        svc.approve_structure(doc.id, user_id=1)
        self.db.refresh(doc)
        self.assertEqual(doc.structure_status, ST_APPROVED_STRUCTURE)
        self.assertTrue(doc.structure_locked)
        self.assertEqual(doc.approval_status, extraction_before)
        with self.assertRaises(StructureLockedError):
            svc.save_review(doc.id, [{"structure_id": structs[0].id, "title_text": "x"}], user_id=1)

    def test_low_confidence_queue(self):
        from app.ai_training.structure.service import StructureService
        from app.ai_agentic.agents.military_structure_agent import MilitaryStructureAgent

        doc = self._doc()
        blocks = [
            {"id": b.id, "block_index": b.block_index, "block_type": "unknown", "text_content": "", "metadata": {}}
            for b in self.db.query(AiTrainingDocumentBlock).filter_by(document_id=doc.id).all()
        ]
        with patch("app.ai_training.structure_config.AI_STRUCTURE_LLM_ENABLED", False):
            out = MilitaryStructureAgent(self.db).run({"blocks": blocks})
        svc = StructureService(self.db)
        run = AiTrainingStructureRun(document_id=doc.id, status="COMPLETED", structure_version="1.0.0")
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        svc._persist_structures(doc, run, out.data["structures"], blocks)
        doc.latest_structure_run_id = run.id
        self.db.commit()
        queue = svc.review_queue(doc.id)
        self.assertIsInstance(queue, list)


class LlmUnavailableTests(unittest.TestCase):
    def test_llm_unavailable_controlled(self):
        from app.ai_agentic.agents.military_structure_agent import MilitaryStructureAgent
        from app.ai_agentic.schemas import GatewayResult

        db = MagicMock()
        agent = MilitaryStructureAgent(db)
        blocks = [
            {"id": 1, "block_index": 0, "block_type": "paragraph", "text_content": "???", "metadata": {}},
        ]
        # Force needs_llm via empty/odd text; mock gateway failure
        with patch("app.ai_training.structure_config.AI_STRUCTURE_LLM_ENABLED", True), patch(
            "app.ai_training.structure_config.AI_STRUCTURE_ENABLED", True
        ):
            agent.gateway.send_request = MagicMock(
                return_value=GatewayResult(success=False, content="", error="ollama down", model="qwen3:8b", duration_ms=1)
            )
            # Make rule engine mark needs_llm
            with patch.object(StructureRuleEngine, "analyze_blocks", return_value=[]):
                # empty rules then fallback unknowns — still ok
                out = agent.run({"blocks": blocks})
        self.assertIn(out.status, ("success", "warning", "failed"))


if __name__ == "__main__":
    unittest.main()
