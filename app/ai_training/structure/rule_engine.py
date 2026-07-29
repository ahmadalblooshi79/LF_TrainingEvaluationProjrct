"""Rule Engine — اكتشاف بنية حتمي قبل مساعدة LLM."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.ai_training import structure_config as scfg
from app.ai_training.structure.numbering_rules import detect_numbering, style_level_hint
from app.ai_training.structure_constants import (
    NUM_NONE,
    SRC_RULE,
)


@dataclass
class RuleStructureResult:
    block_id: int
    block_index: int
    detected_role: str
    numbering_text: str | None
    numbering_style: str
    numbering_level: int | None
    indentation_level: int
    parent_block_id: int | None
    sequence_order: int
    title_text: str | None
    content_text: str | None
    is_heading: bool
    is_content: bool
    confidence: float
    evidence: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    needs_llm: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _meta_flags(metadata: dict[str, Any] | None) -> dict[str, Any]:
    m = metadata or {}
    return {
        "bold": bool(m.get("bold") or m.get("is_bold")),
        "underline": bool(m.get("underline") or m.get("is_underline")),
        "font_size": m.get("font_size") or m.get("fontSize"),
        "alignment": (m.get("alignment") or "").lower() if isinstance(m.get("alignment"), str) else "",
        "indent": m.get("indent") or m.get("indentation") or 0,
    }


class StructureRuleEngine:
    """Configuration-driven deterministic structure detection."""

    def __init__(self, *, enabled: bool | None = None):
        self.enabled = scfg.AI_STRUCTURE_RULES_ENABLED if enabled is None else bool(enabled)
        self.high = float(scfg.AI_STRUCTURE_CONFIDENCE_HIGH)
        self.medium = float(scfg.AI_STRUCTURE_CONFIDENCE_MEDIUM)

    def analyze_blocks(self, blocks: list[dict[str, Any]]) -> list[RuleStructureResult]:
        if not self.enabled:
            return [
                RuleStructureResult(
                    block_id=int(b["id"]),
                    block_index=int(b.get("block_index") or 0),
                    detected_role="unknown",
                    numbering_text=b.get("numbering_text"),
                    numbering_style=NUM_NONE,
                    numbering_level=None,
                    indentation_level=int(b.get("list_level") or 0),
                    parent_block_id=None,
                    sequence_order=i + 1,
                    title_text=None,
                    content_text=b.get("text_content") or "",
                    is_heading=False,
                    is_content=True,
                    confidence=0.3,
                    evidence=["rules_disabled"],
                    warnings=["rules_disabled"],
                    needs_llm=True,
                )
                for i, b in enumerate(blocks)
            ]

        results: list[RuleStructureResult] = []
        heading_stack: list[tuple[int, int]] = []  # (level, block_id)

        for i, b in enumerate(blocks):
            bid = int(b["id"])
            text = (b.get("text_content") or "").strip()
            btype = (b.get("block_type") or "paragraph").lower()
            style = b.get("style_name") or ""
            list_level = int(b.get("list_level") or 0)
            heading_level = b.get("heading_level")
            existing_num = (b.get("numbering_text") or "").strip() or None
            meta = _meta_flags(b.get("metadata") if isinstance(b.get("metadata"), dict) else {})
            evidence: list[str] = []
            warnings: list[str] = []
            confidence = 0.55
            needs_llm = False

            role = "paragraph"
            is_heading = False
            is_content = True
            title_text = None
            content_text = text
            numbering_text = existing_num
            numbering_style = NUM_NONE
            numbering_level: int | None = None
            indentation_level = list_level

            if btype == "table":
                role = "table"
                is_content = True
                confidence = 0.95
                evidence.append("block_type=table")
            elif btype == "header":
                role = "header"
                is_content = False
                confidence = 0.9
                evidence.append("block_type=header")
            elif btype == "footer":
                role = "footer"
                is_content = False
                confidence = 0.9
                evidence.append("block_type=footer")
            elif btype == "page_break":
                role = "page_break"
                is_content = False
                confidence = 0.95
                evidence.append("block_type=page_break")
            elif btype == "heading" or (heading_level and int(heading_level) > 0 and btype != "list"):
                role = "heading" if int(heading_level or 1) <= 1 else "subheading"
                is_heading = True
                is_content = False
                title_text = text
                content_text = ""
                numbering_level = int(heading_level or 1)
                confidence = 0.9
                evidence.append("block_type=heading")
                if style:
                    evidence.append(f"style_name={style}")
            else:
                style_lvl, style_ev = style_level_hint(style)
                evidence.extend(style_ev)
                if style_lvl is not None and (style or "").lower().startswith("heading"):
                    role = "heading" if style_lvl <= 1 else "subheading"
                    is_heading = True
                    is_content = False
                    title_text = text
                    content_text = ""
                    numbering_level = style_lvl
                    confidence = max(confidence, 0.88)

                num = detect_numbering(text)
                if existing_num and not num:
                    num = detect_numbering(f"{existing_num} {text}")
                if num:
                    numbering_text = num.numbering_text
                    numbering_style = num.numbering_style
                    numbering_level = num.numbering_level
                    evidence.extend(list(num.evidence))
                    confidence = max(confidence, num.confidence)
                    rem = num.remainder
                    short = len(rem) <= 80 or len(text) <= 100
                    if short and (meta["bold"] or meta["underline"] or is_heading or btype == "list"):
                        is_heading = True
                        role = "heading" if numbering_level == 1 else "subheading"
                        title_text = rem or text
                        content_text = ""
                        is_content = False
                        if meta["bold"]:
                            evidence.append("bold text")
                        if meta["underline"]:
                            evidence.append("underline text")
                        confidence = max(confidence, 0.86)
                    elif btype == "list" or numbering_style != NUM_NONE:
                        role = "list_item"
                        is_heading = short and (meta["bold"] or len(rem) <= 60)
                        if is_heading:
                            role = "heading" if numbering_level == 1 else "subheading"
                            title_text = rem or text
                            content_text = ""
                            is_content = False
                        else:
                            content_text = rem or text
                        evidence.append("list/numbering pattern")
                        confidence = max(confidence, 0.8)
                    else:
                        # numbered paragraph that may be a section heading
                        if short and (meta["bold"] or text.endswith(":") or len(rem.split()) <= 12):
                            is_heading = True
                            role = "heading" if numbering_level == 1 else "subheading"
                            title_text = rem or text
                            content_text = ""
                            is_content = False
                            evidence.append("short numbered text likely heading")
                            confidence = max(confidence, 0.78)
                            if confidence < self.high:
                                needs_llm = True
                        else:
                            role = "list_item"
                            content_text = rem or text
                            evidence.append("numbered content")

                if btype == "list" and role == "paragraph":
                    role = "list_item"
                    evidence.append("block_type=list")
                    confidence = max(confidence, 0.75)

                # Short bold/underline without numbering
                if role == "paragraph" and len(text) <= 80 and (meta["bold"] or meta["underline"]):
                    is_heading = True
                    role = "subheading"
                    title_text = text
                    content_text = ""
                    is_content = False
                    evidence.append("short bold/underline may be heading")
                    confidence = max(confidence, 0.65)
                    needs_llm = True

            if indentation_level == 0 and numbering_level:
                indentation_level = max(0, numbering_level - 1)
            if meta.get("indent"):
                try:
                    indentation_level = max(indentation_level, int(meta["indent"]))
                except (TypeError, ValueError):
                    pass

            # Parent from heading stack
            parent_block_id = None
            if is_heading and numbering_level:
                while heading_stack and heading_stack[-1][0] >= numbering_level:
                    heading_stack.pop()
                if heading_stack:
                    parent_block_id = heading_stack[-1][1]
                heading_stack.append((numbering_level, bid))
            elif not is_heading and heading_stack:
                parent_block_id = heading_stack[-1][1]
                evidence.append("inherits parent from previous heading")

            if confidence < self.medium:
                needs_llm = True
                warnings.append("low_confidence")
            if role == "unknown":
                needs_llm = True

            # Very short / empty
            if not text and role not in ("table", "page_break", "header", "footer"):
                role = "unknown"
                confidence = min(confidence, 0.4)
                needs_llm = True
                warnings.append("empty_text")

            results.append(
                RuleStructureResult(
                    block_id=bid,
                    block_index=int(b.get("block_index") or i),
                    detected_role=role,
                    numbering_text=numbering_text,
                    numbering_style=numbering_style or NUM_NONE,
                    numbering_level=numbering_level,
                    indentation_level=indentation_level,
                    parent_block_id=parent_block_id,
                    sequence_order=i + 1,
                    title_text=title_text,
                    content_text=content_text,
                    is_heading=is_heading,
                    is_content=is_content,
                    confidence=round(float(confidence), 4),
                    evidence=evidence,
                    warnings=warnings,
                    needs_llm=needs_llm,
                )
            )

        self._post_warnings(results)
        return results

    def _post_warnings(self, results: list[RuleStructureResult]) -> None:
        seen_nums: dict[tuple[str, int | None], int] = {}
        prev_level1: int | None = None
        for r in results:
            if r.numbering_text and r.numbering_level:
                key = (r.numbering_text, r.numbering_level)
                seen_nums[key] = seen_nums.get(key, 0) + 1
            if r.numbering_style == "arabic_dot" and r.numbering_text:
                try:
                    n = int(str(r.numbering_text).rstrip("."))
                    if prev_level1 is not None and n not in (prev_level1, prev_level1 + 1):
                        r.warnings.append("numbering_sequence_break")
                        r.needs_llm = True
                    prev_level1 = n
                except ValueError:
                    pass
            if r.numbering_level and r.numbering_level > 1 and r.parent_block_id is None:
                r.warnings.append("missing_parent")
                r.needs_llm = True
        for r in results:
            if r.numbering_text and r.numbering_level:
                if seen_nums.get((r.numbering_text, r.numbering_level), 0) > 1:
                    r.warnings.append("duplicate_numbering")
                    r.needs_llm = True
