"""ثوابت مكتبة التقارير الذكية — المرحلة الثانية."""

from __future__ import annotations

ALLOWED_EXTENSIONS = frozenset({".docx", ".pdf"})
BLOCKED_EXTENSIONS = frozenset({".doc", ".exe", ".zip", ".bat", ".cmd", ".ps1", ".js", ".vbs", ".msi"})
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_BULK_FILES = 20

PROCESSING_STATUSES = (
    "uploaded",
    "queued",
    "processing",
    "ready",
    "needs_review",
    "failed",
    "excluded",
    "archived",
)

REVIEW_STATUSES = (
    "auto_detected",
    "needs_review",
    "reviewed",
    "approved",
    "rejected",
)

REPORT_TYPES = (
    ("after_action", "تقرير ما بعد التمرين"),
    ("exercise_eval", "تقرير تقييم تمرين"),
    ("objectives", "تقرير تحقيق الأهداف التدريبية"),
    ("strengths_weaknesses", "تقرير نقاط القوة وأوجه القصور"),
    ("lessons", "تقرير الدروس المستفادة"),
    ("brief_command", "تقرير مختصر للقيادة"),
    ("detailed", "تقرير تفصيلي"),
    ("other", "نوع آخر"),
)

UNIT_LEVELS = (
    ("brigade", "لواء"),
    ("battalion", "كتيبة"),
    ("company", "سرية"),
    ("platoon", "فصيلة"),
    ("squad", "جماعة"),
    ("command", "قيادة"),
    ("ops_center", "مركز عمليات"),
    ("support", "وحدة إسناد"),
    ("specialist", "وحدة تخصصية"),
    ("other", "مستوى آخر"),
)

SECTION_TYPES = (
    "executive_summary",
    "introduction",
    "exercise_overview",
    "objectives",
    "evaluation_scope",
    "brigade_level",
    "unit_section",
    "strengths",
    "weaknesses",
    "observations",
    "lessons_learned",
    "recommendations",
    "conclusion",
    "annex",
    "tables",
    "unknown",
)

FINDING_TYPES = (
    "strength",
    "weakness",
    "observation",
    "lesson",
    "recommendation",
    "unknown",
)

SCOPE_TYPES = (
    "brigade",
    "single_unit",
    "multiple_units",
    "general",
    "unknown",
)

# عناوين أقسام → نوع موحّد
SECTION_TITLE_MAP: dict[str, str] = {
    "الملخص التنفيذي": "executive_summary",
    "ملخص تنفيذي": "executive_summary",
    "المقدمة": "introduction",
    "مقدمة": "introduction",
    "نبذة عن التمرين": "exercise_overview",
    "لمحة عن التمرين": "exercise_overview",
    "أهداف التمرين": "objectives",
    "الأهداف": "objectives",
    "نطاق التقييم": "evaluation_scope",
    "نقاط القوة": "strengths",
    "الجوانب الإيجابية": "strengths",
    "الملاحظات الإيجابية": "strengths",
    "نقاط الضعف": "weaknesses",
    "أوجه القصور": "weaknesses",
    "الجوانب التي تحتاج إلى تطوير": "weaknesses",
    "الملاحظات السلبية": "weaknesses",
    "الملاحظات": "observations",
    "الدروس المستفادة": "lessons_learned",
    "العبر المستخلصة": "lessons_learned",
    "النتائج المستفادة": "lessons_learned",
    "التوصيات": "recommendations",
    "الخاتمة": "conclusion",
    "الخلاصة": "conclusion",
    "الملاحق": "annex",
    "ملحق": "annex",
}

CONFIDENCE_NEEDS_REVIEW = 0.65
