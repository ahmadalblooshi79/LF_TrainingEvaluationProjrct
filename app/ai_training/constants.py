"""ثوابت مركز التدريب."""

from __future__ import annotations

from app.ai_training import config as cfg

DOCUMENT_INGESTION_AGENT_KEY = "document_ingestion_agent"
DOCUMENT_INGESTION_WORKFLOW_KEY = "document_ingestion"

DOCUMENT_TYPES = (
    ("previous_report", "تقرير سابق"),
    ("staff_duties_manual", "كراسة واجبات أركان"),
    ("guide", "دليل"),
    ("study", "دراسة"),
    ("research", "بحث"),
    ("circular", "تعميم"),
    ("report_template", "نموذج تقرير"),
    ("institutional_reference", "مرجع مؤسسي"),
    ("other", "وثيقة أخرى"),
)

DOCUMENT_TYPE_KEYS = frozenset(k for k, _ in DOCUMENT_TYPES)

DOC_UPLOADED = "UPLOADED"
DOC_QUEUED = "QUEUED"
DOC_PROCESSING = "PROCESSING"
DOC_EXTRACTED = "EXTRACTED"
DOC_NEEDS_REVIEW = "NEEDS_REVIEW"
DOC_REVIEWED = "REVIEWED"
DOC_APPROVED_EXTRACTION = "APPROVED_EXTRACTION"
DOC_FAILED = "FAILED"
DOC_ARCHIVED = "ARCHIVED"

EXT_NOT_STARTED = "NOT_STARTED"
EXT_RUNNING = "RUNNING"
EXT_SUCCESS = "SUCCESS"
EXT_PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
EXT_FAILED = "FAILED"
EXT_OCR_REQUIRED = "OCR_REQUIRED"

REV_NOT_REVIEWED = "NOT_REVIEWED"
REV_IN_REVIEW = "IN_REVIEW"
REV_CHANGES_REQUIRED = "CHANGES_REQUIRED"
REV_COMPLETED = "REVIEW_COMPLETED"

APR_NOT_APPROVED = "NOT_APPROVED"
APR_APPROVED_EXTRACTION = "APPROVED_EXTRACTION"
APR_REJECTED = "REJECTED"

BLOCK_TYPES = (
    "paragraph",
    "heading",
    "table",
    "list",
    "header",
    "footer",
    "page_break",
    "text_box",
    "unknown",
)

CORRECTION_TYPES = (
    "TEXT_CORRECTION",
    "BLOCK_TYPE_CHANGE",
    "ORDER_CHANGE",
    "BLOCK_ADDED",
    "BLOCK_REMOVED",
    "TABLE_CORRECTION",
    "PAGE_MAPPING_CORRECTION",
    "OTHER",
)

ALLOWED_EXTENSIONS = frozenset(
    f".{x.strip()}" for x in cfg.AI_TRAINING_ALLOWED_EXTENSIONS.split(",") if x.strip()
) or frozenset({".docx", ".pdf", ".txt"})

BLOCKED_EXTENSIONS = frozenset(
    {".doc", ".exe", ".zip", ".bat", ".cmd", ".ps1", ".js", ".vbs", ".msi", ".scr", ".com"}
)

MAX_UPLOAD_BYTES = max(1, int(cfg.AI_TRAINING_MAX_FILE_SIZE_MB)) * 1024 * 1024

TRAINING_TABLES = (
    "ai_training_documents",
    "ai_training_document_pages",
    "ai_training_document_blocks",
    "ai_training_document_reviews",
    "ai_training_document_corrections",
    "ai_training_document_events",
)

STATUS_LABELS_AR = {
    DOC_UPLOADED: "تم الرفع",
    DOC_QUEUED: "في الطابور",
    DOC_PROCESSING: "جاري المعالجة",
    DOC_EXTRACTED: "تم الاستخراج",
    DOC_NEEDS_REVIEW: "يحتاج مراجعة",
    DOC_REVIEWED: "تمت المراجعة",
    DOC_APPROVED_EXTRACTION: "تم اعتماد جودة الاستخراج",
    DOC_FAILED: "فشل",
    DOC_ARCHIVED: "مؤرشف",
    EXT_NOT_STARTED: "لم يبدأ",
    EXT_RUNNING: "جاري الاستخراج",
    EXT_SUCCESS: "نجاح",
    EXT_PARTIAL_SUCCESS: "نجاح جزئي",
    EXT_FAILED: "فشل الاستخراج",
    EXT_OCR_REQUIRED: "يتطلب OCR",
    REV_NOT_REVIEWED: "لم تُراجع",
    REV_IN_REVIEW: "قيد المراجعة",
    REV_CHANGES_REQUIRED: "تحتاج تعديلات",
    REV_COMPLETED: "اكتملت المراجعة",
    APR_NOT_APPROVED: "غير معتمد",
    APR_APPROVED_EXTRACTION: "معتمد (استخراج)",
    APR_REJECTED: "مرفوض",
}


def label_ar(code: str | None) -> str:
    if not code:
        return "—"
    return STATUS_LABELS_AR.get(code, code)
