"""تسميات عرض الوكلاء (عربي) — مصدر واحد دون Hardcode مبعثر."""

from __future__ import annotations

# agent_key -> اسم عربي للواجهة فقط (لا يغيّر قاعدة البيانات)
AGENT_DISPLAY_NAME_AR: dict[str, str] = {
    "system_health_agent": "وكيل فحص صحة النظام",
    "document_ingestion_agent": "وكيل استيعاب الوثائق",
    "military_structure_agent": "وكيل تحليل البنية العسكرية للوثيقة",
}


def agent_display_name_ar(agent_key: str, fallback: str | None = None) -> str:
    key = (agent_key or "").strip()
    if key in AGENT_DISPLAY_NAME_AR:
        return AGENT_DISPLAY_NAME_AR[key]
    return (fallback or key or "—").strip() or "—"
