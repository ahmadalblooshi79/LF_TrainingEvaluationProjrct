"""تحليل أبرز الإيجابيات والسلبيات بالذكاء الاصطناعي — لكل مستوى وحدة."""
from __future__ import annotations

import sys
from pathlib import Path

# السماح بالتشغيل المباشر: python app/positives_negatives_ai.py
# أو: python -m app.positives_negatives_ai (من جذر المشروع)
if __package__ in (None, ""):
    _PROJECT_ROOT = Path(__file__).resolve().parents[1]
    if str(_PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(_PROJECT_ROOT))

import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL
from app.paths import data_dir
from app.evaluation_list_columns import grade_label_from_percent
from app.evaluation_workflow import eval_judge_approved
from app.unit_levels_catalog import label_for_unit_level_key

_CACHE_DIR = data_dir() / "instance" / "ai_pn_cache"
_MAX_CRITERIA_PER_UNIT = 80


def _cache_path(exercise_id: int) -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR / f"exercise_{int(exercise_id)}.json"


def _row_score_pct(row: dict) -> float | None:
    if not isinstance(row, dict):
        return None
    acq = row.get("acquired")
    if acq is None or acq == "" or str(acq).strip().lower() == "na":
        return None
    try:
        a = float(str(acq).replace(",", "."))
    except (TypeError, ValueError):
        return None
    mx_raw = row.get("max_val")
    mx = None
    if mx_raw not in (None, ""):
        try:
            mx = float(str(mx_raw).replace(",", "."))
        except (TypeError, ValueError):
            mx = None
    if mx is not None and mx > 0:
        return max(0.0, min(100.0, (a / mx) * 100.0))
    return max(0.0, min(100.0, (a / 5.0) * 100.0))


def _parse_saved_rows(payload_json: str | None) -> list[dict]:
    if not (payload_json or "").strip():
        return []
    try:
        data = json.loads(payload_json)
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    rows = data.get("rows") or []
    return rows if isinstance(rows, list) else []


def collect_unit_criteria(
    items,
    canonical_by_item: dict,
    *,
    phase_label_fn,
) -> dict[str, list[dict]]:
    """جمع معايير التقييم المعتمدة من المحكم مجمّعة حسب مستوى الوحدة."""
    by_unit: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        saved = canonical_by_item.get(int(it.id))
        if saved is None or not eval_judge_approved(saved):
            continue
        if not (getattr(saved, "payload_json", "") or "").strip():
            continue
        uk = (it.unit_level_key or "").strip()
        if not uk:
            continue
        list_title = (it.text or "قائمة تقييم").strip()
        phase_label = phase_label_fn(getattr(it, "exercise_phase", None))
        for row in _parse_saved_rows(saved.payload_json):
            if not isinstance(row, dict):
                continue
            if str(row.get("row_kind") or "score").strip().lower() == "section":
                continue
            element = (row.get("element") or "").strip()
            if not element:
                continue
            pct = _row_score_pct(row)
            note = (row.get("notes") or "").strip()
            by_unit[uk].append(
                {
                    "element": element[:240],
                    "pct": pct,
                    "grade": grade_label_from_percent(pct) if pct is not None else "—",
                    "note": note[:400],
                    "list_title": list_title[:120],
                    "phase_label": phase_label,
                }
            )
    return dict(by_unit)


def _criteria_fingerprint(by_unit: dict[str, list[dict]]) -> str:
    payload = json.dumps(by_unit, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load_cache(exercise_id: int) -> dict | None:
    path = _cache_path(exercise_id)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_cache(exercise_id: int, data: dict) -> None:
    path = _cache_path(exercise_id)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _trim_criteria(rows: list[dict]) -> list[dict]:
    """اختيار معايير تمثل القمة والقاع والملاحظات لضبط حجم الطلب."""
    scored = [r for r in rows if r.get("pct") is not None]
    with_notes = [r for r in rows if (r.get("note") or "").strip()]
    unscored = [r for r in rows if r.get("pct") is None and not (r.get("note") or "").strip()]

    scored.sort(key=lambda r: float(r["pct"]), reverse=True)
    top = scored[:25]
    bottom = scored[-25:] if len(scored) > 25 else []
    picked: list[dict] = []
    seen: set[str] = set()

    def _key(r: dict) -> str:
        return f"{r.get('list_title')}|{r.get('element')}"

    for group in (with_notes, top, bottom, unscored[:10]):
        for r in group:
            k = _key(r)
            if k in seen:
                continue
            seen.add(k)
            picked.append(r)
            if len(picked) >= _MAX_CRITERIA_PER_UNIT:
                return picked
    return picked


def _format_unit_block(unit_key: str, unit_label: str, rows: list[dict]) -> str:
    lines = [f"### {unit_label} ({unit_key})"]
    for r in _trim_criteria(rows):
        pct = r.get("pct")
        pct_s = f"{float(pct):.1f}%" if pct is not None else "—"
        line = f"- [{pct_s} | {r.get('grade', '—')}] {r.get('element')} — {r.get('list_title')} — {r.get('phase_label')}"
        if r.get("note"):
            line += f" | ملاحظة: {r['note']}"
        lines.append(line)
    return "\n".join(lines)


def _parse_ai_json(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except Exception:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _fallback_unit_summary(unit_label: str, rows: list[dict]) -> dict:
    """تحليل قاعدي عند غياب مفتاح API أو فشل الاتصال."""
    scored = [r for r in rows if r.get("pct") is not None]
    scored.sort(key=lambda r: float(r["pct"]), reverse=True)
    positives: list[str] = []
    negatives: list[str] = []
    seen_pos: set[str] = set()
    seen_neg: set[str] = set()

    def _bullet(r: dict, kind: str) -> str:
        el = (r.get("element") or "").strip()
        if len(el) > 120:
            el = el[:117] + "…"
        pct = float(r["pct"])
        title = (r.get("list_title") or "").strip()
        note = (r.get("note") or "").strip()
        base = f"«{el}» ({pct:.0f}%"
        if title:
            base += f" — {title}"
        base += ")"
        if note:
            base += f": {note[:180]}"
        return base

    for r in scored:
        pct = float(r["pct"])
        if pct >= 75.0 and len(positives) < 6:
            item = _bullet(r, "pos")
            if item not in seen_pos:
                seen_pos.add(item)
                positives.append(f"نقطة قوة: {item}")
        if len(positives) >= 6:
            break

    for r in reversed(scored):
        pct = float(r["pct"])
        if pct < 75.0 and len(negatives) < 6:
            item = _bullet(r, "neg")
            if item not in seen_neg:
                seen_neg.add(item)
                negatives.append(f"نقطة ضعف: {item}")
        if len(negatives) >= 6:
            break

    for r in rows:
        note = (r.get("note") or "").strip()
        if not note:
            continue
        pct = r.get("pct")
        el = (r.get("element") or "معيار").strip()[:80]
        item = f"«{el}»: {note[:200]}"
        if pct is not None and float(pct) >= 75.0 and item not in seen_pos and len(positives) < 8:
            seen_pos.add(item)
            positives.append(item)
        elif pct is not None and float(pct) < 75.0 and item not in seen_neg and len(negatives) < 8:
            seen_neg.add(item)
            negatives.append(item)

    if not positives:
        positives = [f"لا توجد نقاط قوة بارزة كافية في بيانات {unit_label} بعد اعتماد المحكم."]
    if not negatives:
        negatives = [f"لا توجد نقاط ضعف بارزة في بيانات {unit_label} (معظم المعايير ≥ 75%)."]
    return {
        "unit_key": "",
        "unit_label": unit_label,
        "positives": positives[:8],
        "negatives": negatives[:8],
        "source": "fallback",
    }


def _call_ai_all_units(units_payload: dict[str, dict]) -> dict[str, dict] | None:
    if not OPENAI_API_KEY or not OPENAI_API_KEY.strip():
        return None

    blocks: list[str] = []
    for uk, info in units_payload.items():
        blocks.append(_format_unit_block(uk, info["unit_label"], info["rows"]))

    system = (
        "أنت ضابط عمليات وخبير عسكري ومعلّم تقييم في القوات المسلحة. "
        "تُحلّل نتائج معايير تقييم التمارين وتستخرج أبرز الإيجابيات والسلبيات "
        "بلغة عسكرية مهنية موجزة. لا تُخترع معلومات غير موجودة في البيانات."
    )
    user = (
        "اقرأ معايير التقييم التالية (مع النسب والملاحظات) لكل مستوى وحدة، "
        "ثم أعد JSON فقط بالشكل:\n"
        '{"units":{"UNIT_KEY":{"positives":["…"],"negatives":["…"]},…}}\n'
        "لكل وحدة: 3–6 نقاط إيجابية و3–6 سلبيات كجمل عربية قصيرة واضحة "
        "(قوة/ضعف تشغيلي أو تدريبي). استخدم مفاتيح الوحدات كما هي بين قوسين في العناوين.\n\n"
        + "\n\n".join(blocks)
    )
    try:
        with httpx.Client(timeout=120.0) as client:
            payload = {
                "model": OPENAI_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.35,
            }
            try:
                r = client.post(
                    f"{OPENAI_BASE_URL.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                    json={**payload, "response_format": {"type": "json_object"}},
                )
                r.raise_for_status()
            except httpx.HTTPStatusError:
                r = client.post(
                    f"{OPENAI_BASE_URL.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                    json=payload,
                )
                r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return None

    parsed = _parse_ai_json(content)
    if not parsed:
        return None
    units_out = parsed.get("units")
    if not isinstance(units_out, dict):
        return None
    return units_out


def build_ai_unit_summaries(
    exercise_id: int,
    by_unit: dict[str, list[dict]],
    *,
    force_refresh: bool = False,
) -> dict:
    """بناء/تحميل ملخصات الإيجابيات والسلبيات بالذكاء الاصطناعي لكل وحدة."""
    fingerprint = _criteria_fingerprint(by_unit)
    if not force_refresh:
        cached = _load_cache(exercise_id)
        if (
            cached
            and cached.get("fingerprint") == fingerprint
            and isinstance(cached.get("units"), list)
        ):
            return {
                "ai_unit_summaries": cached["units"],
                "ai_generated_at": cached.get("generated_at"),
                "ai_using_cache": True,
                "ai_has_api_key": bool(OPENAI_API_KEY and OPENAI_API_KEY.strip()),
            }

    units_payload: dict[str, dict] = {}
    for uk, rows in by_unit.items():
        if not rows:
            continue
        label = (label_for_unit_level_key(uk) or uk).strip()
        units_payload[uk] = {"unit_label": label, "rows": rows}

    ai_units = _call_ai_all_units(units_payload)
    summaries: list[dict] = []
    for uk, info in units_payload.items():
        label = info["unit_label"]
        rows = info["rows"]
        entry = {
            "unit_key": uk,
            "unit_label": label,
            "positives": [],
            "negatives": [],
            "source": "none",
            "n_criteria": len(rows),
        }
        if ai_units and uk in ai_units and isinstance(ai_units[uk], dict):
            pos = ai_units[uk].get("positives") or []
            neg = ai_units[uk].get("negatives") or []
            entry["positives"] = [str(x).strip() for x in pos if str(x).strip()][:8]
            entry["negatives"] = [str(x).strip() for x in neg if str(x).strip()][:8]
            entry["source"] = "ai"
        if not entry["positives"] and not entry["negatives"]:
            fb = _fallback_unit_summary(label, rows)
            entry["positives"] = fb["positives"]
            entry["negatives"] = fb["negatives"]
            entry["source"] = "fallback" if not ai_units else "ai_partial"
        summaries.append(entry)

    generated_at = datetime.now(timezone.utc).isoformat()
    _save_cache(
        exercise_id,
        {
            "fingerprint": fingerprint,
            "generated_at": generated_at,
            "units": summaries,
        },
    )
    return {
        "ai_unit_summaries": summaries,
        "ai_generated_at": generated_at,
        "ai_using_cache": False,
        "ai_has_api_key": bool(OPENAI_API_KEY and OPENAI_API_KEY.strip()),
    }


def _cli_main() -> int:
    """تحليل التمرين الحالي من سطر الأوامر (اختبار/تشغيل يدوي)."""
    from app.database import SessionLocal
    from app.exercise_phase_catalog import exercise_phase_label
    from app.models import EvaluationListPdfItem, Exercise
    from app.views import _evaluation_canonical_map_for_items

    force = "--refresh" in sys.argv
    db = SessionLocal()
    try:
        ex = db.query(Exercise).order_by(Exercise.id.desc()).first()
        if ex is None:
            print("لا يوجد تمرين في قاعدة البيانات.", file=sys.stderr)
            return 1
        items = (
            db.query(EvaluationListPdfItem)
            .filter(EvaluationListPdfItem.exercise_id == ex.id)
            .all()
        )
        item_ids = [int(it.id) for it in items if getattr(it, "id", None) is not None]
        canonical = _evaluation_canonical_map_for_items(db, int(ex.id), item_ids)
        by_unit = collect_unit_criteria(
            items,
            canonical,
            phase_label_fn=exercise_phase_label,
        )
        result = build_ai_unit_summaries(int(ex.id), by_unit, force_refresh=force)
        out = json.dumps(result, ensure_ascii=False, indent=2)
        if hasattr(sys.stdout, "reconfigure"):
            try:
                sys.stdout.reconfigure(encoding="utf-8")
            except Exception:
                pass
        if not result.get("ai_has_api_key"):
            print(
                "تنبيه: OPENAI_API_KEY غير مضبوط في .env — يُستخدم تحليل قاعدي (fallback).\n"
                "لتشغيل النظام: .venv\\Scripts\\python.exe run.py\n"
                "لتفعيل الذكاء الاصطناعي: انسخ .env.example إلى .env وأضف المفتاح.\n",
                file=sys.stderr,
            )
        print(out)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(_cli_main())
