"""Chunking لوثائق طويلة — لا يرسل الوثيقة كاملة لـ Qwen."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.ai_training import structure_config as scfg


@dataclass
class StructureChunk:
    chunk_id: str
    block_ids: list[int]
    blocks: list[dict[str, Any]]
    previous_context: str
    next_preview: str
    start_index: int
    end_index: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_prompt_blocks(self) -> list[dict[str, Any]]:
        out = []
        for b in self.blocks:
            out.append(
                {
                    "block_id": b.get("id"),
                    "block_index": b.get("block_index"),
                    "page_number": b.get("page_number"),
                    "text": (b.get("text_content") or "")[:2000],
                    "style_name": b.get("style_name"),
                    "block_type": b.get("block_type"),
                    "numbering_text": b.get("numbering_text"),
                    "list_level": b.get("list_level"),
                    "heading_level": b.get("heading_level"),
                }
            )
        return out


class StructureChunker:
    def __init__(
        self,
        *,
        chunk_blocks: int | None = None,
        context_before: int | None = None,
        context_after: int | None = None,
        max_characters: int | None = None,
    ):
        self.chunk_blocks = max(5, int(chunk_blocks if chunk_blocks is not None else scfg.AI_STRUCTURE_CHUNK_BLOCKS))
        self.context_before = max(0, int(context_before if context_before is not None else scfg.AI_STRUCTURE_CONTEXT_BEFORE))
        self.context_after = max(0, int(context_after if context_after is not None else scfg.AI_STRUCTURE_CONTEXT_AFTER))
        self.max_characters = max(1000, int(max_characters if max_characters is not None else scfg.AI_STRUCTURE_MAX_CHARACTERS))

    def build_chunks(self, blocks: list[dict[str, Any]]) -> list[StructureChunk]:
        """قسّم كل Blocks إلى chunks متتابعة مع تداخل سياقي."""
        if not blocks:
            return []
        chunks: list[StructureChunk] = []
        n = len(blocks)
        i = 0
        chunk_no = 0
        while i < n:
            chunk_no += 1
            end = min(n, i + self.chunk_blocks)
            # تجنب قطع تسلسل ترقيم مترابط إن أمكن: مدّد قليلاً إن كان آخر عنصر heading قصير
            while end < n and end - i < self.chunk_blocks + 5:
                t = (blocks[end - 1].get("text_content") or "").strip()
                if len(t) < 40 and end < n:
                    # keep boundary; break on long paragraph
                    nxt = (blocks[end].get("text_content") or "").strip()
                    if len(nxt) > 200:
                        break
                    end += 1
                else:
                    break

            slice_blocks = blocks[i:end]
            # character budget
            chars = 0
            trimmed: list[dict[str, Any]] = []
            for b in slice_blocks:
                tlen = len(b.get("text_content") or "")
                if trimmed and chars + tlen > self.max_characters:
                    break
                trimmed.append(b)
                chars += tlen
            if not trimmed:
                trimmed = [slice_blocks[0]]
                end = i + 1
            else:
                end = i + len(trimmed)

            before = blocks[max(0, i - self.context_before) : i]
            after = blocks[end : min(n, end + self.context_after)]
            prev_summary = " | ".join(
                f"#{b.get('block_index')}:{(b.get('text_content') or '')[:60]}" for b in before
            ) or "(none)"
            next_preview = " | ".join(
                f"#{b.get('block_index')}:{(b.get('text_content') or '')[:60]}" for b in after
            ) or "(none)"

            chunks.append(
                StructureChunk(
                    chunk_id=f"chunk-{chunk_no}",
                    block_ids=[int(b["id"]) for b in trimmed],
                    blocks=trimmed,
                    previous_context=prev_summary[:1500],
                    next_preview=next_preview[:1500],
                    start_index=i,
                    end_index=end - 1,
                    metadata={"char_count": chars},
                )
            )
            # overlap: step forward but keep small overlap via context_before on next iteration
            i = end
        return chunks

    def chunks_for_uncertain(
        self,
        blocks: list[dict[str, Any]],
        uncertain_block_ids: set[int],
    ) -> list[StructureChunk]:
        """أنشئ chunks تركز على المناطق غير المؤكدة مع سياق متداخل."""
        if not uncertain_block_ids:
            return []
        # Expand uncertain indices into windows
        index_by_id = {int(b["id"]): idx for idx, b in enumerate(blocks)}
        indices = sorted(index_by_id[i] for i in uncertain_block_ids if i in index_by_id)
        if not indices:
            return []
        windows: list[tuple[int, int]] = []
        start = max(0, indices[0] - self.context_before)
        end = min(len(blocks) - 1, indices[0] + self.context_after)
        for idx in indices[1:]:
            ns = max(0, idx - self.context_before)
            ne = min(len(blocks) - 1, idx + self.context_after)
            if ns <= end + 1:
                end = max(end, ne)
            else:
                windows.append((start, end))
                start, end = ns, ne
        windows.append((start, end))

        # Materialize as block slices then re-chunk if too large
        out: list[StructureChunk] = []
        for w_start, w_end in windows:
            slice_blocks = blocks[w_start : w_end + 1]
            out.extend(self.build_chunks(slice_blocks))
        # re-number chunk ids
        for i, c in enumerate(out, start=1):
            c.chunk_id = f"unc-{i}"
        return out
