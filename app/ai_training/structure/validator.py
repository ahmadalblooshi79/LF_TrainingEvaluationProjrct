"""Structure Validator تقني (ليس Agent)."""

from __future__ import annotations

from typing import Any


def validate_structures(
    structures: list[dict[str, Any]],
    *,
    expected_block_ids: set[int],
) -> dict[str, Any]:
    warnings: list[str] = []
    errors: list[str] = []

    by_id: dict[int, dict[str, Any]] = {}
    block_ids_seen: set[int] = set()
    for s in structures:
        sid = s.get("id") or s.get("structure_id")
        bid = s.get("block_id")
        if bid is not None:
            block_ids_seen.add(int(bid))
            if int(bid) not in expected_block_ids:
                errors.append(f"structure_points_to_missing_block:{bid}")
        if sid is not None:
            by_id[int(sid)] = s

    missing = expected_block_ids - block_ids_seen
    if missing:
        warnings.append(f"unclassified_blocks:{len(missing)}")
        for bid in list(missing)[:20]:
            warnings.append(f"missing_structure_for_block:{bid}")

    # circular parents (by structure id or parent_block_id graph via block)
    parent_map: dict[int, int | None] = {}
    for s in structures:
        bid = s.get("block_id")
        if bid is None:
            continue
        parent_map[int(bid)] = s.get("parent_block_id")

    for bid in list(parent_map.keys()):
        seen: set[int] = set()
        cur: int | None = bid
        while cur is not None:
            if cur in seen:
                errors.append(f"circular_parent:{bid}")
                break
            seen.add(cur)
            cur = parent_map.get(cur)

    # parent level vs child level
    level_by_block = {
        int(s["block_id"]): s.get("numbering_level")
        for s in structures
        if s.get("block_id") is not None
    }
    for s in structures:
        bid = s.get("block_id")
        parent = s.get("parent_block_id")
        if bid is None or parent is None:
            continue
        cl = level_by_block.get(int(bid))
        pl = level_by_block.get(int(parent))
        if cl is not None and pl is not None and int(pl) >= int(cl):
            warnings.append(f"parent_level_not_less:{bid}->{parent}")

    # sequence order
    orders = [s.get("sequence_order") for s in structures if s.get("sequence_order") is not None]
    if orders and sorted(orders) != orders:
        warnings.append("sequence_order_not_monotonic")

    for s in structures:
        if (s.get("detected_role") or "unknown") == "unknown":
            warnings.append(f"unknown_role:block_{s.get('block_id')}")
        lvl = s.get("numbering_level")
        if lvl is not None and (int(lvl) < 1 or int(lvl) > 9):
            warnings.append(f"numbering_level_out_of_range:{s.get('block_id')}")
        if s.get("numbering_level") and int(s.get("numbering_level") or 0) > 1 and not s.get("parent_block_id"):
            warnings.append(f"child_without_parent:{s.get('block_id')}")

    # original text must not be modified by structure layer — content_text is a copy field only
    ok = len(errors) == 0
    return {
        "ok": ok,
        "errors": errors,
        "warnings": warnings,
        "expected_blocks": len(expected_block_ids),
        "structured_blocks": len(block_ids_seen),
    }


def prevent_circular_parent(
    structures: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """أزل علاقات أب تسبب دورة."""
    parent_map = {
        int(s["block_id"]): s.get("parent_block_id")
        for s in structures
        if s.get("block_id") is not None
    }

    def would_cycle(bid: int, parent: int | None) -> bool:
        if parent is None:
            return False
        seen = {bid}
        cur: int | None = int(parent)
        while cur is not None:
            if cur in seen:
                return True
            seen.add(cur)
            cur = parent_map.get(cur)
        return False

    out = []
    for s in structures:
        s2 = dict(s)
        bid = s2.get("block_id")
        parent = s2.get("parent_block_id")
        if bid is not None and parent is not None and would_cycle(int(bid), int(parent)):
            s2["parent_block_id"] = None
            warns = list(s2.get("warnings") or [])
            warns.append("circular_parent_cleared")
            s2["warnings"] = warns
            parent_map[int(bid)] = None
        out.append(s2)
    return out
