# -*- coding: utf-8 -*-
"""ربط أيام المجرى بمراحل التحليل حسب إدخال بنك المعلومات (phase_key لكل يوم)."""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.models.domain import (
    ExercisePlannerFlowBundle,
    ExercisePlannerFlowBundleActionEval,
    InformationBankTreeNode,
    PlannerFlowBundleEvalSavedResult,
)


def _normalize_phase_key(raw: str) -> str:
    pk = (raw or "").strip()
    aliases = {
        "main": "battle_exposure",
        "reorg": "reorganization",
        "evaluation_tracks": "reorganization",
    }
    return aliases.get(pk, pk)


def ibank_flow_day_phase_map(flow_days: list[dict[str, str]] | None) -> dict[str, str]:
    """day_id → phase_key من حقل المرحلة المحفوظ على يوم المجرى في بنك المعلومات."""
    out: dict[str, str] = {}
    for day in flow_days or []:
        day_id = str(day.get("id") or "").strip()
        if not day_id:
            continue
        pk = _normalize_phase_key(str(day.get("phase_key") or ""))
        if pk:
            out[day_id] = pk
    return out


# توافق مع الاستدعاءات القديمة
fixed_flow_day_phase_map = ibank_flow_day_phase_map


def flow_day_phase_rule_summary(flow_days: list[dict[str, str]] | None) -> list[dict[str, str]]:
    """ملخص للقراءة فقط في واجهة المحللين (مصدره بنك المعلومات)."""
    from app.information_bank_catalog import TRAINING_PHASES

    labels = {
        str(p.get("key") or "").strip(): str(p.get("label") or "").strip()
        for p in (TRAINING_PHASES or [])
        if str(p.get("key") or "").strip()
    }
    labels.setdefault("opening", "مرحلة الإنفتاح")
    labels.setdefault("battle_exposure", "مرحلة المعركة التعرضية")
    labels.setdefault("reorganization", "مرحلة مسارات التقييم")
    labels.setdefault("preparation", "مرحلة التحضير")

    rows: list[dict[str, str]] = []
    for day in flow_days or []:
        day_id = str(day.get("id") or "").strip()
        if not day_id:
            continue
        pk = _normalize_phase_key(str(day.get("phase_key") or ""))
        rows.append(
            {
                "day_id": day_id,
                "day_label": str(day.get("label") or day_id).strip() or day_id,
                "phase_key": pk,
                "phase_label": labels.get(pk, "— غير مرتبط —") if not pk else labels.get(pk, pk),
            }
        )
    return rows


def _payload_mark_totals(payload_json: str) -> tuple[float, float]:
    """(max_total, acquired_total) من حمولة قائمة تقييم محفوظة."""
    try:
        data = json.loads(payload_json or "")
    except (TypeError, json.JSONDecodeError):
        return 0.0, 0.0
    if isinstance(data, dict):
        rows = data.get("rows") or []
    elif isinstance(data, list):
        rows = data
    else:
        return 0.0, 0.0
    if not isinstance(rows, list):
        return 0.0, 0.0
    sum_max = 0.0
    sum_acq = 0.0
    for r in rows[:2000]:
        if not isinstance(r, dict):
            continue
        if str(r.get("row_kind") or "").strip().lower() == "section":
            continue
        raw_max = r.get("max_val")
        if raw_max is None:
            raw_max = r.get("max")
        try:
            mv = float(str(raw_max).replace(",", ".")) if raw_max not in (None, "") else 0.0
            if mv > 0:
                sum_max += mv
        except (TypeError, ValueError):
            pass
        acq = r.get("acquired")
        acq_s = ("" if acq is None else str(acq)).strip().lower()
        if acq_s and acq_s != "na":
            try:
                sum_acq += float(str(acq).replace(",", "."))
            except (TypeError, ValueError):
                pass
    return sum_max, sum_acq


def _payload_acquired_total(payload_json: str) -> float:
    _mx, acq = _payload_mark_totals(payload_json)
    return acq


def build_dilemma_reaction_table_for_unit_phase(
    db: Session,
    *,
    exercise_id: int,
    unit_level_key: str,
    phase_key: str,
) -> dict:
    """جدول تقييم رد الفعل على المعاضل لوحدة ومرحلة: أيام المجرى → معاضل → قوائم → نتائج.

    يعيد dict:
      title, day_labels, dilemma_count, list_count, rows, total_acquired, total_max, total_pct
    """
    from app.action_eval_ibank_sync import parse_action_eval_storage_relpath
    from app.ibank_action_eval_dilemma_tree import build_action_eval_dilemma_judge_tree
    from app.info_bank_tree import ibank_event_flow_days

    uk = (unit_level_key or "").strip()
    want_phase = _normalize_phase_key(phase_key)
    flow_days = ibank_event_flow_days(db)
    day_map = ibank_flow_day_phase_map(flow_days)
    seen_day: set[str] = set()
    days_for_phase: list[dict] = []
    for d in flow_days or []:
        did = str(d.get("id") or "").strip()
        if not did or did in seen_day:
            continue
        pk = _normalize_phase_key(
            str(d.get("phase_key") or "") or day_map.get(did, "")
        )
        if pk != want_phase:
            continue
        seen_day.add(did)
        days_for_phase.append(d)

    title = "تقييم رد الفعل على المعاضل التنقل التعبوي"
    empty = {
        "title": title,
        "day_labels": [],
        "dilemma_count": 0,
        "list_count": 0,
        "rows": [],
        "total_acquired": None,
        "total_max": None,
        "total_pct": None,
    }
    if not uk or not want_phase or not days_for_phase:
        return empty

    tree = build_action_eval_dilemma_judge_tree(db, exercise_id=int(exercise_id))

    # فهرس: node_id → (slot_id, acquired, max, pct, published)
    slot_by_node: dict[int, dict] = {}
    action_rows = (
        db.query(ExercisePlannerFlowBundleActionEval)
        .join(ExercisePlannerFlowBundle)
        .filter(
            ExercisePlannerFlowBundle.exercise_id == int(exercise_id),
            ExercisePlannerFlowBundle.unit_level_key == uk,
        )
        .all()
    )
    for slot in action_rows:
        nid = parse_action_eval_storage_relpath(slot.file_relpath)
        if nid is None:
            continue
        saved = (
            db.query(PlannerFlowBundleEvalSavedResult)
            .filter(
                PlannerFlowBundleEvalSavedResult.bundle_action_eval_id == int(slot.id)
            )
            .first()
        )
        mx = acq = 0.0
        pct = None
        if saved is not None and (getattr(saved, "payload_json", None) or "").strip():
            mx, acq = _payload_mark_totals(saved.payload_json)
            if mx > 0:
                pct = round((acq / mx) * 100.0, 2)
        slot_by_node[int(nid)] = {
            "slot_id": int(slot.id),
            "acquired": acq if acq > 0 or mx > 0 else None,
            "max_mark": mx if mx > 0 else None,
            "pct": pct,
            "published": True,
        }

    rows_out: list[dict] = []
    dilemma_nos: set[int] = set()
    seq = 0
    sum_acq = 0.0
    sum_max = 0.0
    any_score = False

    for day in days_for_phase:
        day_id = str(day.get("id") or "").strip()
        day_label = str(day.get("label") or day_id).strip() or day_id
        dilemmas = list(tree.get(day_id) or [])
        for d in dilemmas:
            dno = int(d.get("dilemma_no") or d.get("num") or 0)
            dtext = str(d.get("text") or f"المعضلة/{dno}").strip()
            unit_files: list[dict] = []
            seen_nodes: set[int] = set()
            for j in d.get("judges") or []:
                juk = str(j.get("unit_key") or "").strip()
                for fmeta in j.get("files") or []:
                    nid = int(fmeta.get("node_id") or 0)
                    if nid and nid in seen_nodes:
                        continue
                    # قوائم المحكّم لنفس الوحدة، أو ملفات غير مربوطة نُشرت لهذه الوحدة
                    if juk == uk or (not juk and nid and nid in slot_by_node):
                        if nid:
                            seen_nodes.add(nid)
                        unit_files.append(fmeta)
            if not unit_files:
                # معضلة بلا قوائم لهذه الوحدة — صف فارغ للنتيجة
                dilemma_nos.add(dno)
                seq += 1
                rows_out.append(
                    {
                        "seq": seq,
                        "day_id": day_id,
                        "day_label": day_label,
                        "dilemma_no": dno,
                        "dilemma_text": dtext,
                        "list_title": "—",
                        "node_id": None,
                        "acquired": None,
                        "max_mark": None,
                        "pct": None,
                        "published": False,
                    }
                )
                continue
            for fmeta in unit_files:
                nid = int(fmeta.get("node_id") or 0)
                title_list = (
                    (fmeta.get("procedure_title") or "").strip()
                    or (fmeta.get("name") or "").strip()
                    or "قائمة تقييم إجراءات"
                )
                score = slot_by_node.get(nid) if nid else None
                dilemma_nos.add(dno)
                seq += 1
                acq_v = score.get("acquired") if score else None
                max_v = score.get("max_mark") if score else None
                pct_v = score.get("pct") if score else None
                if isinstance(acq_v, (int, float)):
                    sum_acq += float(acq_v)
                    any_score = True
                if isinstance(max_v, (int, float)) and float(max_v) > 0:
                    sum_max += float(max_v)
                    any_score = True
                rows_out.append(
                    {
                        "seq": seq,
                        "day_id": day_id,
                        "day_label": day_label,
                        "dilemma_no": dno,
                        "dilemma_text": dtext,
                        "list_title": title_list[:500],
                        "node_id": nid or None,
                        "acquired": acq_v,
                        "max_mark": max_v,
                        "pct": pct_v,
                        "published": bool(score and score.get("published")),
                    }
                )

    total_pct = None
    if sum_max > 0:
        total_pct = round((sum_acq / sum_max) * 100.0, 2)

    return {
        "title": title,
        "day_labels": [str(d.get("label") or d.get("id") or "") for d in days_for_phase],
        "dilemma_count": len(dilemma_nos),
        "list_count": sum(1 for r in rows_out if r.get("node_id")),
        "rows": rows_out,
        "total_acquired": round(sum_acq, 2) if any_score else None,
        "total_max": round(sum_max, 2) if sum_max > 0 else None,
        "total_pct": total_pct,
    }


def collect_flow_acquired_by_unit_phase(
    db: Session,
    *,
    exercise_id: int,
    day_to_phase: dict[str, str] | None = None,
    flow_days: list[dict[str, str]] | None = None,
) -> dict[tuple[str, str], float]:
    """(unit_level_key, phase_key) → مكتسبة قوائم إجراءات المجرى حسب يوم الملف."""
    from app.action_eval_ibank_sync import (
        _flow_day_id_for_node,
        parse_action_eval_storage_relpath,
    )
    from app.info_bank_tree import ibank_event_flow_days

    mapping = day_to_phase or ibank_flow_day_phase_map(
        flow_days if flow_days is not None else ibank_event_flow_days(db)
    )
    if not mapping:
        return {}

    action_rows = (
        db.query(ExercisePlannerFlowBundleActionEval)
        .join(ExercisePlannerFlowBundle)
        .filter(ExercisePlannerFlowBundle.exercise_id == int(exercise_id))
        .all()
    )
    if not action_rows:
        return {}

    out: dict[tuple[str, str], float] = {}
    for action_row in action_rows:
        bundle = action_row.bundle
        if bundle is None:
            continue
        saved = (
            db.query(PlannerFlowBundleEvalSavedResult)
            .filter(
                PlannerFlowBundleEvalSavedResult.bundle_action_eval_id
                == int(action_row.id)
            )
            .first()
        )
        if saved is None or not (getattr(saved, "payload_json", None) or "").strip():
            continue

        day_id = ""
        node_id = parse_action_eval_storage_relpath(action_row.file_relpath)
        if node_id:
            node = db.get(InformationBankTreeNode, int(node_id))
            if node is not None:
                day_id = (_flow_day_id_for_node(db, node) or "").strip()
        if not day_id:
            continue
        phase_key = _normalize_phase_key(mapping.get(day_id, "") or "")
        if not phase_key:
            continue

        uk = (
            (getattr(saved, "unit_level_key", None) or "").strip()
            or (getattr(bundle, "unit_level_key", None) or "").strip()
        )
        if not uk:
            continue

        acquired = _payload_acquired_total(saved.payload_json)
        if acquired <= 0:
            continue
        key = (uk, phase_key)
        out[key] = out.get(key, 0.0) + float(acquired)
    return out
