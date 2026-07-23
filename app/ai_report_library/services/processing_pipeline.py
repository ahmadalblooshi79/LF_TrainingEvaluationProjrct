"""خط معالجة التقرير بالكامل."""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.ai_report_library.models import (
    AIReportFinding,
    AIReportFindingUnit,
    AIReportProcessingLog,
    AIReportSection,
    AIReportSource,
    AIReportTable,
    AIReportUnit,
)
from app.ai_report_library.paths import report_extracted_dir
from app.ai_report_library.services.docx_parser import parse_docx
from app.ai_report_library.services.finding_extraction_service import extract_findings
from app.ai_report_library.services.pdf_parser import parse_pdf
from app.ai_report_library.services.section_detection_service import detect_sections_from_elements
from app.ai_report_library.services.text_cleaning_service import TextCleaningService
from app.ai_report_library.services.unit_detection_service import detect_units_from_elements


def _log(
    db: Session,
    report_id: int,
    step: str,
    status: str,
    *,
    started: float,
    warning: str | None = None,
    error: str | None = None,
    meta: dict | None = None,
) -> None:
    now = datetime.utcnow()
    db.add(
        AIReportProcessingLog(
            report_id=report_id,
            processing_step=step,
            status=status,
            started_at=now,
            completed_at=now,
            duration_ms=int(round((time.perf_counter() - started) * 1000)),
            warning_message=warning,
            error_message=error,
            metadata_json=json.dumps(meta or {}, ensure_ascii=False) if meta else None,
            created_at=now,
        )
    )


def process_report(db: Session, report_id: int, *, use_qwen: bool = True) -> AIReportSource:
    report = db.query(AIReportSource).filter(AIReportSource.id == report_id).first()
    if not report:
        raise ValueError("التقرير غير موجود.")

    report.processing_status = "processing"
    report.processing_started_at = datetime.utcnow()
    report.processing_error = None
    report.updated_at = datetime.utcnow()
    db.commit()

    cleaner = TextCleaningService()
    elements: list[dict[str, Any]] = []
    pages: list[str] = []
    warning_ocr = None

    # 1) قراءة الملف
    t0 = time.perf_counter()
    try:
        path = Path(report.stored_file_path)
        if report.file_type == "docx":
            parsed = parse_docx(path)
            elements = [e.to_dict() for e in parsed]
            pages = ["\n".join(e.text for e in parsed)]
            report.page_count = None
            report.word_count = sum(len((e.text or "").split()) for e in parsed)
        else:
            pdf = parse_pdf(path)
            elements = pdf.elements
            pages = pdf.pages
            report.page_count = pdf.page_count
            report.word_count = pdf.word_count
            report.needs_ocr = pdf.needs_ocr
            warning_ocr = pdf.warning
            if pdf.needs_ocr:
                report.processing_status = "needs_review"
                report.processing_error = pdf.warning
                _log(db, report.id, "parse_pdf", "warning", started=t0, warning=pdf.warning)
                report.processing_completed_at = datetime.utcnow()
                db.commit()
                return report
        _log(db, report.id, "parse", "ok", started=t0, meta={"elements": len(elements)})
    except Exception as exc:
        report.processing_status = "failed"
        report.processing_error = f"تعذر قراءة الملف: {exc}"
        _log(db, report.id, "parse", "error", started=t0, error=report.processing_error)
        report.processing_completed_at = datetime.utcnow()
        db.commit()
        return report

    # مسح نتائج سابقة عند إعادة المعالجة
    for model in (AIReportFindingUnit, AIReportFinding, AIReportTable, AIReportSection, AIReportUnit):
        if model is AIReportFindingUnit:
            finding_ids = [f.id for f in db.query(AIReportFinding).filter_by(report_id=report.id).all()]
            if finding_ids:
                db.query(AIReportFindingUnit).filter(AIReportFindingUnit.finding_id.in_(finding_ids)).delete(
                    synchronize_session=False
                )
        else:
            db.query(model).filter_by(report_id=report.id).delete(synchronize_session=False)
    db.commit()

    # 2) حفظ العناصر المستخرجة
    t1 = time.perf_counter()
    out_dir = report_extracted_dir(report.public_id)
    (out_dir / "extracted.json").write_text(
        json.dumps(elements, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    full_original = "\n".join(pages)
    full_cleaned = cleaner.clean(full_original)
    (out_dir / "full_original.txt").write_text(full_original, encoding="utf-8")
    (out_dir / "full_cleaned.txt").write_text(full_cleaned, encoding="utf-8")
    _log(db, report.id, "extract_store", "ok", started=t1)

    # 3) أقسام
    t2 = time.perf_counter()
    sections_data = detect_sections_from_elements(elements)
    for s in sections_data:
        s["cleaned_text"] = cleaner.clean(s.get("original_text") or "")
        row = AIReportSection(
            report_id=report.id,
            original_title=s["original_title"],
            normalized_section_type=s["normalized_section_type"],
            section_order=s["section_order"],
            original_text=s.get("original_text"),
            cleaned_text=s.get("cleaned_text"),
            page_start=s.get("page_start"),
            confidence_score=s.get("confidence_score", 0.7),
            review_status=s.get("review_status", "auto_detected"),
            detection_source=s.get("detection_source", "rules"),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(row)
    db.flush()
    _log(db, report.id, "sections", "ok", started=t2, meta={"count": len(sections_data)})

    # 4) جداول
    t3 = time.perf_counter()
    tables_data = []
    for el in elements:
        if el.get("element_type") != "table":
            continue
        tables_data.append(
            {
                "headers": el.get("headers") or [],
                "rows": el.get("rows") or [],
                "page_number": el.get("page_hint"),
                "table_order": el.get("table_reference") or 0,
                "original_text": el.get("text") or "",
            }
        )
        db.add(
            AIReportTable(
                report_id=report.id,
                page_number=el.get("page_hint"),
                table_order=int(el.get("table_reference") or 0),
                headers_json=json.dumps(el.get("headers") or [], ensure_ascii=False),
                rows_json=json.dumps(el.get("rows") or [], ensure_ascii=False),
                original_text=el.get("text"),
                confidence_score=0.85,
                review_status="auto_detected",
                created_at=datetime.utcnow(),
            )
        )
    (out_dir / "tables.json").write_text(
        json.dumps(tables_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    db.flush()
    _log(db, report.id, "tables", "ok", started=t3, meta={"count": len(tables_data)})

    # 5) وحدات
    t4 = time.perf_counter()
    units_data = detect_units_from_elements(elements)
    unit_rows: list[AIReportUnit] = []
    for u in units_data:
        row = AIReportUnit(
            report_id=report.id,
            original_unit_name=u["original_unit_name"],
            normalized_unit_name=u["normalized_unit_name"],
            unit_level=u["unit_level"],
            unit_order=u["unit_order"],
            is_brigade_level=u["is_brigade_level"],
            detection_source=u["detection_source"],
            confidence_score=u["confidence_score"],
            review_status=u["review_status"],
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(row)
        unit_rows.append(row)
    db.flush()
    # ربط الأب: غير اللواء تحت اللواء
    bde = next((u for u in unit_rows if u.is_brigade_level), None)
    if bde:
        for u in unit_rows:
            if u.id != bde.id and u.unit_level in ("battalion", "company", "support", "ops_center", "command"):
                u.parent_unit_id = bde.id
    _log(db, report.id, "units", "ok", started=t4, meta={"count": len(unit_rows)})

    # 6) نقاط
    t5 = time.perf_counter()
    findings_data = extract_findings(sections_data, tables_data, units_data)
    unit_map = {u.normalized_unit_name: u for u in unit_rows}
    # أيضاً بالاسم الأصلي
    for u in unit_rows:
        unit_map.setdefault(u.original_unit_name, u)

    needs_review = False
    for f in findings_data:
        row = AIReportFinding(
            report_id=report.id,
            finding_type=f["finding_type"],
            original_text=f["original_text"],
            cleaned_text=f["cleaned_text"],
            order_number=f["order_number"],
            scope_type=f["scope_type"],
            confidence_score=f["confidence_score"],
            review_status=f["review_status"],
            detected_by=f["detected_by"],
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        if row.review_status == "needs_review":
            needs_review = True
        db.add(row)
        db.flush()
        for uname in f.get("unit_names") or []:
            urow = unit_map.get(uname)
            if not urow:
                continue
            rel = "brigade_level" if f["scope_type"] == "brigade" else (
                "shared" if f["scope_type"] == "multiple_units" else "primary"
            )
            db.add(
                AIReportFindingUnit(
                    finding_id=row.id,
                    report_unit_id=urow.id,
                    relation_type=rel,
                    confidence_score=f["confidence_score"],
                    created_at=datetime.utcnow(),
                )
            )
    _log(db, report.id, "findings", "ok", started=t5, meta={"count": len(findings_data)})

    # إحصاءات
    report.sections_count = len(sections_data)
    report.units_count = len(unit_rows)
    report.strengths_count = sum(1 for f in findings_data if f["finding_type"] == "strength")
    report.weaknesses_count = sum(1 for f in findings_data if f["finding_type"] == "weakness")
    report.processing_completed_at = datetime.utcnow()
    report.updated_at = datetime.utcnow()
    if warning_ocr:
        report.processing_status = "needs_review"
    elif needs_review or not unit_rows or not findings_data:
        report.processing_status = "needs_review"
        if not findings_data:
            report.processing_error = "لم يتم اكتشاف نقاط قوة أو ضعف بشكل كافٍ — راجع التقرير."
        elif not unit_rows:
            report.processing_error = "لم يتم اكتشاف وحدات — راجع الهيكل يدوياً."
    else:
        report.processing_status = "ready"
        report.processing_error = None

    (out_dir / "sections.json").write_text(
        json.dumps(sections_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log_path = out_dir / "processing.log"
    log_path.write_text(
        f"completed_at={report.processing_completed_at.isoformat()}\nstatus={report.processing_status}\n",
        encoding="utf-8",
    )
    db.commit()
    db.refresh(report)

    # Qwen اختياري عند انخفاض الثقة — لا يفشل المعالجة
    if use_qwen and report.processing_status == "needs_review":
        try:
            from app.ai_report_library.services.qwen_assist_service import maybe_assist_unknown_sections

            maybe_assist_unknown_sections(db, report.id)
        except Exception:
            pass
    return report
