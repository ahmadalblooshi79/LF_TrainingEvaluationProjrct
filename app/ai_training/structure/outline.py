"""توليد Document Outline من نتائج البنية."""

from __future__ import annotations

from typing import Any


def build_outline_rows(
    structures: list[dict[str, Any]],
    *,
    block_page_map: dict[int, int | None] | None = None,
) -> list[dict[str, Any]]:
    """يبني صفوف outline من headings فقط مع علاقات parent."""
    page_map = block_page_map or {}
    headings = [
        s
        for s in structures
        if s.get("is_heading") or (s.get("detected_role") in ("heading", "subheading"))
    ]
    headings.sort(key=lambda s: int(s.get("sequence_order") or 0))

    # Map block_id -> temporary outline index for parent linking
    block_to_outline_key: dict[int, int] = {}
    rows: list[dict[str, Any]] = []
    stack: list[tuple[int, int]] = []  # (level, block_id)

    for seq, s in enumerate(headings, start=1):
        bid = int(s["block_id"]) if s.get("block_id") is not None else None
        level = int(s.get("numbering_level") or s.get("indentation_level") or 1)
        level = max(1, min(level, 9))
        title = (s.get("title_text") or s.get("content_text") or "").strip()
        if not title and bid is not None:
            title = f"Block {bid}"
        while stack and stack[-1][0] >= level:
            stack.pop()
        parent_block_id = stack[-1][1] if stack else None
        parent_outline_key = block_to_outline_key.get(parent_block_id) if parent_block_id else None
        row = {
            "temp_key": seq,
            "structure_block_id": bid,
            "parent_temp_key": parent_outline_key,
            "title": title[:512],
            "numbering_text": s.get("numbering_text"),
            "outline_level": level,
            "sequence_order": seq,
            "page_number": page_map.get(bid) if bid is not None else None,
            "structure_ref": s,
        }
        rows.append(row)
        if bid is not None:
            block_to_outline_key[bid] = seq
            stack.append((level, bid))
    return rows
