"""مساعد Qwen عبر AIService فقط — مقاطع قصيرة عند انخفاض الثقة."""

from __future__ import annotations

import json
import re

from sqlalchemy.orm import Session

from app.ai_local_engine.schemas.request_schema import GenerateTextRequest
from app.ai_local_engine.services.ai_service import AIService
from app.ai_report_library.models import AIReportSection


def maybe_assist_unknown_sections(db: Session, report_id: int) -> int:
    """يقترح نوع القسم للأقسام unknown. يعيد عدد التحديثات."""
    sections = (
        db.query(AIReportSection)
        .filter(
            AIReportSection.report_id == report_id,
            AIReportSection.normalized_section_type == "unknown",
        )
        .limit(8)
        .all()
    )
    if not sections:
        return 0
    svc = AIService(db)
    settings = svc.get_settings()
    if not settings.enabled or not (settings.model_name or "").strip():
        return 0
    updated = 0
    for sec in sections:
        prompt = (
            "صنّف عنوان قسم تقرير عسكري إلى واحد فقط من: "
            "executive_summary,introduction,objectives,strengths,weaknesses,"
            "observations,lessons_learned,recommendations,conclusion,annex,unknown\n"
            f"العنوان: {sec.original_title[:200]}\n"
            'أجب JSON فقط: {"type":"...","confidence":0.0}'
        )
        resp = svc.generate_text(
            GenerateTextRequest(
                prompt=prompt,
                system_prompt="مساعد تصنيف أقسام. أجب JSON مختصر فقط.",
                max_tokens=120,
                temperature=0.1,
            )
        )
        if not resp.success or not resp.text:
            continue
        m = re.search(r"\{.*?\}", resp.text, re.S)
        if not m:
            continue
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
        stype = str(data.get("type") or "unknown").strip()
        try:
            conf = float(data.get("confidence") or 0.5)
        except (TypeError, ValueError):
            conf = 0.5
        if stype and stype != "unknown":
            sec.normalized_section_type = stype
            sec.confidence_score = conf
            sec.detection_source = "ai"
            sec.review_status = "needs_review"
            updated += 1
    if updated:
        db.commit()
    return updated
