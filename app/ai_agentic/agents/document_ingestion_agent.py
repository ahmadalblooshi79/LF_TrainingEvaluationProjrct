"""Document Ingestion Agent — استخراج حتمي بدون تعليم مؤسسي."""

from __future__ import annotations

from typing import Any

from app.ai_agentic.agents.base_agent import BaseAgent
from app.ai_agentic.schemas import StructuredAgentOutput
from app.ai_training.constants import DOCUMENT_INGESTION_AGENT_KEY
from app.ai_training.exceptions import DocumentExtractionError, TrainingCenterError
from app.ai_training.services.ingestion_service import IngestionService


class DocumentIngestionAgent(BaseAgent):
    agent_key = DOCUMENT_INGESTION_AGENT_KEY
    name = "Document Ingestion Agent"
    description = "Extracts text/pages/blocks from uploaded training documents. No institutional learning."
    version = "1.0.0"
    max_retries = 0

    def build_prompt(self, context: dict[str, Any]) -> tuple[str, str]:
        # لا يستخدم LLM في الوضع الافتراضي
        return "", ""

    def execute(self, context: dict[str, Any], *, run_id: int | None = None):
        # يتجاوز Gateway/LLM عمداً
        raise NotImplementedError("Ingestion Agent لا يستدعي النموذج في Phase B1 الافتراضي.")

    def run(self, context: dict[str, Any] | None = None, *, run_id: int | None = None) -> StructuredAgentOutput:
        ctx = dict(context or {})
        if not self.enabled:
            from app.ai_agentic.exceptions import AgentDisabledError

            raise AgentDisabledError(f"الوكيل معطّل: {self.agent_key}")
        try:
            self.validate_input(ctx)
            doc_id = int(ctx.get("document_id") or 0)
            if not doc_id:
                raise DocumentExtractionError("document_id مطلوب.")
            result = IngestionService(self.db).run_extraction(doc_id)
            status = "success"
            if result.status in ("PARTIAL_SUCCESS", "OCR_REQUIRED"):
                status = "warning"
            elif not result.success or result.status == "FAILED":
                status = "failed"
            return StructuredAgentOutput(
                agent_key=self.agent_key,
                agent_version=self.version,
                status=status,
                confidence=1.0 if status == "success" else 0.5,
                data={
                    "extraction_status": result.status,
                    "page_count": result.page_count,
                    "paragraph_count": result.paragraph_count,
                    "table_count": result.table_count,
                    "block_count": len(result.blocks),
                    "character_count": result.character_count,
                    "document_id": doc_id,
                    "warnings": result.warnings,
                },
                warnings=list(result.warnings or []),
                errors=list(result.errors or []),
                metadata={
                    "model": "deterministic-parser",
                    "prompt_version": self.prompt_version or "n/a",
                    "knowledge_version": self.knowledge_version or "n/a",
                    "duration_ms": 0,
                    "llm_assisted": False,
                },
            )
        except TrainingCenterError as exc:
            return self.handle_error(exc)
        except Exception as exc:  # noqa: BLE001
            return self.handle_error(exc)
