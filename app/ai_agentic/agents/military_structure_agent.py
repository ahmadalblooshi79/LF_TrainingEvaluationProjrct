"""Military Document Structure Agent — Hybrid rules + optional Qwen via Gateway."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.ai_agentic.agents.base_agent import BaseAgent
from app.ai_agentic.json_util import dumps_json, loads_json
from app.ai_agentic.schemas import StructuredAgentOutput
from app.ai_training import structure_config as scfg
from app.ai_training.structure.chunking import StructureChunker
from app.ai_training.structure.prompt import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE
from app.ai_training.structure.rule_engine import StructureRuleEngine
from app.ai_training.structure.schema import parse_and_validate_llm_response
from app.ai_training.structure.validator import prevent_circular_parent, validate_structures
from app.ai_training.structure_constants import (
    MILITARY_STRUCTURE_AGENT_KEY,
    MILITARY_STRUCTURE_PROMPT_VERSION,
    SRC_HYBRID,
    SRC_LLM,
    SRC_RULE,
    STRUCTURE_VERSION,
)

logger = logging.getLogger(__name__)


class MilitaryStructureAgent(BaseAgent):
    agent_key = MILITARY_STRUCTURE_AGENT_KEY
    name = "Military Document Structure Agent"
    description = "Analyzes military document structure only. No content interpretation or rewriting."
    version = "1.0.0"
    model_name = scfg.AI_STRUCTURE_MODEL
    prompt_version = MILITARY_STRUCTURE_PROMPT_VERSION
    timeout_seconds = int(scfg.AI_STRUCTURE_TIMEOUT_SECONDS)
    max_retries = int(scfg.AI_STRUCTURE_MAX_RETRIES)

    def build_prompt(self, context: dict[str, Any]) -> tuple[str, str]:
        chunk = context.get("chunk") or {}
        blocks_json = json.dumps(chunk.get("blocks") or [], ensure_ascii=False, indent=2)
        user = USER_PROMPT_TEMPLATE.format(
            chunk_id=chunk.get("chunk_id") or "",
            previous_context=chunk.get("previous_context") or "(none)",
            next_preview=chunk.get("next_preview") or "(none)",
            blocks_json=blocks_json[: scfg.AI_STRUCTURE_MAX_CHARACTERS],
        )
        system = SYSTEM_PROMPT
        # Prefer active prompt from DB if loaded
        if self.prompt_version:
            try:
                row = self.prompt_svc.get_active_for_agent(self.agent_key)
                if row and row.system_prompt:
                    system = row.system_prompt
            except Exception:
                pass
        return system, user

    def validate_input(self, context: dict[str, Any]) -> None:
        super().validate_input(context)
        if not context.get("blocks"):
            from app.ai_agentic.exceptions import AgentValidationError

            raise AgentValidationError("blocks مطلوبة لتحليل البنية.")

    def run(self, context: dict[str, Any] | None = None, *, run_id: int | None = None) -> StructuredAgentOutput:
        ctx = dict(context or {})
        if not self.enabled:
            from app.ai_agentic.exceptions import AgentDisabledError

            raise AgentDisabledError(f"الوكيل معطّل: {self.agent_key}")
        if not scfg.AI_STRUCTURE_ENABLED:
            from app.ai_agentic.exceptions import AgentDisabledError

            raise AgentDisabledError("تحليل البنية معطّل إعداداً (AI_STRUCTURE_ENABLED=false).")

        try:
            self.validate_input(ctx)
            blocks = list(ctx["blocks"])
            event_cb = ctx.get("event_callback")  # optional callable(event_type, message, details)

            def emit(etype: str, message: str, details: dict | None = None) -> None:
                if callable(event_cb):
                    try:
                        event_cb(etype, message, details or {})
                    except Exception:
                        logger.debug("structure event callback failed", exc_info=True)

            emit("structure.analysis.started", "بدء تحليل البنية العسكرية", {"block_count": len(blocks)})

            engine = StructureRuleEngine()
            rule_results = engine.analyze_blocks(blocks)
            emit("structure.rules.completed", "انتهى Rule Engine", {"count": len(rule_results)})

            merged: dict[int, dict[str, Any]] = {}
            for r in rule_results:
                d = r.to_dict()
                d["detection_source"] = SRC_RULE
                d["rule_result"] = dict(d)
                d["llm_result"] = None
                merged[r.block_id] = d

            llm_warnings: list[str] = []
            llm_used = False
            uncertain_ids = {r.block_id for r in rule_results if r.needs_llm}

            if scfg.AI_STRUCTURE_LLM_ENABLED and uncertain_ids:
                chunker = StructureChunker()
                chunks = chunker.chunks_for_uncertain(blocks, uncertain_ids)
                for ch in chunks:
                    emit("structure.chunk.started", f"بدء chunk {ch.chunk_id}", {"blocks": len(ch.blocks)})
                    llm_used = True
                    try:
                        system_prompt, user_prompt = self.build_prompt(
                            {
                                "chunk": {
                                    "chunk_id": ch.chunk_id,
                                    "previous_context": ch.previous_context,
                                    "next_preview": ch.next_preview,
                                    "blocks": ch.to_prompt_blocks(),
                                }
                            }
                        )
                        gw = self.gateway.send_request(
                            agent_name=self.agent_key,
                            system_prompt=system_prompt,
                            user_prompt=user_prompt,
                            model=self.model_name or scfg.AI_STRUCTURE_MODEL,
                            run_id=run_id,
                            timeout=float(self.timeout_seconds),
                            prompt_version=self.prompt_version or None,
                            max_retries_override=self.max_retries,
                        )
                        if not gw.success:
                            llm_warnings.append(f"llm_unavailable:{ch.chunk_id}:{gw.error or 'fail'}")
                            emit("structure.chunk.failed", f"فشل chunk {ch.chunk_id}", {"error": gw.error})
                            continue
                        ok, errs, payload = parse_and_validate_llm_response(gw.content or "")
                        if not ok:
                            llm_warnings.append(f"json_validation_failed:{ch.chunk_id}")
                            emit("structure.json_validation_failure", f"JSON غير صالح في {ch.chunk_id}", {"errors": errs})
                            continue
                        for item in payload.get("structures") or []:
                            bid = int(item.get("block_id") or 0)
                            if bid not in merged:
                                continue
                            base = merged[bid]
                            # Merge: prefer LLM only for uncertain; keep rule evidence
                            rule_conf = float(base.get("confidence") or 0)
                            llm_conf = float(item.get("confidence") or 0)
                            conflict = False
                            if base.get("detected_role") != item.get("detected_role") and abs(rule_conf - llm_conf) < 0.15:
                                conflict = True
                                base.setdefault("warnings", []).append("rule_llm_conflict")
                            use_llm = llm_conf >= rule_conf or base.get("needs_llm")
                            if use_llm:
                                for key in (
                                    "detected_role",
                                    "numbering_text",
                                    "numbering_style",
                                    "numbering_level",
                                    "indentation_level",
                                    "parent_block_id",
                                    "title_text",
                                    "content_text",
                                    "is_heading",
                                    "confidence",
                                ):
                                    if key in item and item[key] is not None:
                                        base[key] = item[key]
                                if "is_heading" in item:
                                    base["is_content"] = not bool(item.get("is_heading"))
                                ev = list(base.get("evidence") or [])
                                for e in item.get("evidence") or []:
                                    if e not in ev:
                                        ev.append(e)
                                base["evidence"] = ev
                                base["detection_source"] = SRC_HYBRID if rule_conf >= self.medium else SRC_LLM
                            if scfg.AI_STRUCTURE_SAVE_LLM_RAW_RESPONSE:
                                base["llm_result"] = item
                            else:
                                base["llm_result"] = {
                                    "detected_role": item.get("detected_role"),
                                    "confidence": item.get("confidence"),
                                    "numbering_text": item.get("numbering_text"),
                                }
                            if conflict:
                                base["confidence"] = min(float(base.get("confidence") or 0), 0.59)
                        emit("structure.chunk.completed", f"انتهى chunk {ch.chunk_id}", {})
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("structure llm chunk failed: %s", exc)
                        llm_warnings.append(f"llm_exception:{ch.chunk_id}")
                        emit("structure.chunk.failed", f"استثناء chunk {ch.chunk_id}", {"error": str(exc)[:200]})
            elif not scfg.AI_STRUCTURE_LLM_ENABLED and uncertain_ids:
                llm_warnings.append("llm_disabled_rules_only")
                emit("structure.llm.skipped", "LLM معطّل — اعتماد القواعد فقط", {"uncertain": len(uncertain_ids)})

            structures = prevent_circular_parent(list(merged.values()))
            expected = {int(b["id"]) for b in blocks}
            # Ensure every block has an entry
            have = {int(s["block_id"]) for s in structures if s.get("block_id") is not None}
            for b in blocks:
                bid = int(b["id"])
                if bid not in have:
                    structures.append(
                        {
                            "block_id": bid,
                            "block_index": b.get("block_index"),
                            "detected_role": "unknown",
                            "numbering_text": None,
                            "numbering_style": "none",
                            "numbering_level": None,
                            "indentation_level": 0,
                            "parent_block_id": None,
                            "sequence_order": int(b.get("block_index") or 0) + 1,
                            "title_text": None,
                            "content_text": b.get("text_content") or "",
                            "is_heading": False,
                            "is_content": True,
                            "confidence": 0.2,
                            "evidence": ["fallback_unknown"],
                            "warnings": ["missing_from_engine"],
                            "detection_source": SRC_RULE,
                            "rule_result": None,
                            "llm_result": None,
                        }
                    )
            structures = prevent_circular_parent(structures)
            validation = validate_structures(structures, expected_block_ids=expected)
            emit("structure.validation.completed", "انتهى التحقق", validation)

            low = sum(1 for s in structures if float(s.get("confidence") or 0) < scfg.AI_STRUCTURE_CONFIDENCE_MEDIUM)
            conflicts = sum(1 for s in structures if "rule_llm_conflict" in (s.get("warnings") or []) or "duplicate_numbering" in (s.get("warnings") or []))

            status = "success"
            if validation["errors"] or (llm_warnings and not structures):
                status = "failed"
            elif validation["warnings"] or llm_warnings or low:
                status = "warning"

            emit("structure.analysis.completed", "اكتمل تحليل البنية", {"status": status, "low": low})

            return StructuredAgentOutput(
                agent_key=self.agent_key,
                agent_version=self.version,
                status=status,
                confidence=1.0 if status == "success" else 0.7,
                data={
                    "structures": structures,
                    "validation": validation,
                    "total_blocks": len(blocks),
                    "analyzed_blocks": len(structures),
                    "low_confidence_count": low,
                    "conflict_count": conflicts,
                    "llm_used": llm_used,
                    "structure_version": STRUCTURE_VERSION,
                    "prompt_version": self.prompt_version,
                },
                warnings=list(validation.get("warnings") or []) + llm_warnings,
                errors=list(validation.get("errors") or []),
                metadata={
                    "model": self.model_name if llm_used else "deterministic-rules",
                    "prompt_version": self.prompt_version or "n/a",
                    "knowledge_version": self.knowledge_version or "n/a",
                    "duration_ms": 0,
                    "llm_enabled": scfg.AI_STRUCTURE_LLM_ENABLED,
                    "rules_enabled": scfg.AI_STRUCTURE_RULES_ENABLED,
                },
            )
        except Exception as exc:  # noqa: BLE001
            return self.handle_error(exc)

    @property
    def medium(self) -> float:
        return float(scfg.AI_STRUCTURE_CONFIDENCE_MEDIUM)
