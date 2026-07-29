"""ثوابت تحليل البنية العسكرية (Phase B2.1)."""

from __future__ import annotations

MILITARY_STRUCTURE_AGENT_KEY = "military_structure_agent"
MILITARY_STRUCTURE_WORKFLOW_KEY = "military_structure_analysis"
MILITARY_STRUCTURE_PROMPT_KEY = "military_structure_agent_v1"
MILITARY_STRUCTURE_PROMPT_VERSION = "1.0.0"
STRUCTURE_VERSION = "1.0.0"

# Structure Status (مستقل عن Extraction Approval)
ST_NOT_STARTED = "NOT_STARTED"
ST_QUEUED = "QUEUED"
ST_RUNNING = "RUNNING"
ST_COMPLETED = "COMPLETED"
ST_COMPLETED_WITH_WARNINGS = "COMPLETED_WITH_WARNINGS"
ST_NEEDS_REVIEW = "NEEDS_REVIEW"
ST_REVIEW_COMPLETED = "REVIEW_COMPLETED"
ST_APPROVED_STRUCTURE = "APPROVED_STRUCTURE"
ST_FAILED = "FAILED"

STRUCTURE_STATUSES = frozenset(
    {
        ST_NOT_STARTED,
        ST_QUEUED,
        ST_RUNNING,
        ST_COMPLETED,
        ST_COMPLETED_WITH_WARNINGS,
        ST_NEEDS_REVIEW,
        ST_REVIEW_COMPLETED,
        ST_APPROVED_STRUCTURE,
        ST_FAILED,
    }
)

# Structure run statuses (workflow-aligned)
RUN_CREATED = "CREATED"
RUN_QUEUED = "QUEUED"
RUN_RUNNING = "RUNNING"
RUN_COMPLETED = "COMPLETED"
RUN_COMPLETED_WITH_WARNINGS = "COMPLETED_WITH_WARNINGS"
RUN_FAILED = "FAILED"
RUN_CANCELLED = "CANCELLED"

# Reviewer status per structure row
RV_PENDING = "PENDING"
RV_ACCEPTED = "ACCEPTED"
RV_CORRECTED = "CORRECTED"
RV_FLAGGED = "FLAGGED"

# Detection source
SRC_RULE = "rule"
SRC_LLM = "llm"
SRC_HYBRID = "hybrid"
SRC_MANUAL = "manual"

# Numbering styles
NUM_ARABIC_DOT = "arabic_dot"  # 1.
NUM_ARABIC_LETTER_DOT = "arabic_letter_dot"  # أ.
NUM_NUMBER_PAREN = "number_parentheses"  # (1)
NUM_LETTER_PAREN = "letter_parentheses"  # (أ)
NUM_NUMBER_CLOSE = "number_close_paren"  # 1)
NUM_NONE = "none"
NUM_OTHER = "other"

NUMBERING_STYLES = frozenset(
    {
        NUM_ARABIC_DOT,
        NUM_ARABIC_LETTER_DOT,
        NUM_NUMBER_PAREN,
        NUM_LETTER_PAREN,
        NUM_NUMBER_CLOSE,
        NUM_NONE,
        NUM_OTHER,
    }
)

DETECTED_ROLES = frozenset(
    {
        "heading",
        "subheading",
        "paragraph",
        "list_item",
        "table",
        "header",
        "footer",
        "page_break",
        "unknown",
    }
)

STRUCTURE_TABLES = (
    "ai_training_structure_runs",
    "ai_training_document_structures",
    "ai_training_structure_corrections",
    "ai_training_document_outlines",
    "ai_training_structure_events",
)

STRUCTURE_STATUS_LABELS_AR = {
    ST_NOT_STARTED: "لم يبدأ تحليل البنية",
    ST_QUEUED: "تحليل البنية في الطابور",
    ST_RUNNING: "جاري تحليل البنية",
    ST_COMPLETED: "اكتمل تحليل البنية",
    ST_COMPLETED_WITH_WARNINGS: "اكتمل مع تحذيرات",
    ST_NEEDS_REVIEW: "يحتاج مراجعة البنية",
    ST_REVIEW_COMPLETED: "اكتملت مراجعة البنية",
    ST_APPROVED_STRUCTURE: "تم اعتماد البنية العسكرية",
    ST_FAILED: "فشل تحليل البنية",
}


def structure_label_ar(code: str | None) -> str:
    if not code:
        return "—"
    return STRUCTURE_STATUS_LABELS_AR.get(code, code)
