# -*- coding: utf-8 -*-
"""مساعد المساعدة — يوجّه المستخدم حسب سؤاله (لا يلصق فصول الدليل كاملة)."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import User
from app.permissions import (
    is_analyst,
    is_chief_judge,
    is_control,
    is_judge,
    is_planner,
    is_system_admin,
)
from app.user_manual import MANUAL_SECTIONS, MANUAL_TITLE

MAX_QUESTION_CHARS = 800
MAX_KNOWLEDGE_CHARS = 10000
MAX_ANSWER_TOKENS = 650

# إشارات نية شائعة → توجيه مختصر (بدون لصق مسار كامل)
_INTENT_GUIDES: list[tuple[tuple[str, ...], str]] = [
    (
        ("رقم سري", "كلمة المرور", "كلمه المرور", "باسورد", "password", "تغيير كلمة"),
        "فهمت أنك تسأل عن كلمة المرور.\n"
        "• إن كنت تريد تسجيل الدخول: افتح صفحة الدخول وأدخل اسم المستخدم وكلمة المرور، ثم «دخول».\n"
        "• إن نسيت كلمة المرور أو تريد تعيينها لمستخدم: من دور إدارة النظام ← إدارة المستخدمين (لا يغيّر المستخدمون كلمات مرورهم بأنفسهم عادة).\n"
        "وضّح إن قصدك: دخول؟ أم إنشاء مستخدم؟ أم إعادة تعيين كلمة مرور؟",
    ),
    (
        ("تسجيل الدخول", "دخول", "login", "خروج"),
        "للدخول: افتح رابط النظام ← أدخل اسم المستخدم وكلمة المرور ← «دخول».\n"
        "للخروج: من الشريط العلوي اختر «خروج».\n"
        "راجع فرع «البدء والواجهة» في التشجير أعلاه لمزيد من التفاصيل.",
    ),
    (
        ("نشر", "قوائم التقييم", "نشر القوائم"),
        "لنشر قوائم التقييم:\n"
        "1) تأكد من وجود تمرين حالي وبنك معلومات/مجرى جاهز.\n"
        "2) من أوامر التخطيط افتح صفحة نشر قوائم التقييم.\n"
        "3) اختر اليوم/المرحلة والوحدات ثم حدّد القوائم واضغط «نشر القوائم».\n"
        "هل تقصد قوائم تقييم الإجراءات (المجرى) أم قوائم التقييم العادية؟",
    ),
    (
        ("اعتماد", "مسار الاعتماد", "كبير المحكم"),
        "مسار الاعتماد باختصار: المحكم يحفظ ويعتمد ← كبير المحكمين يراجع (يعتمد أو يعيد) ← ثم تصل للسيطرة حسب الإعداد.\n"
        "راجع فرع «المحكم» و«كبير المحكمين» في التشجير.\n"
        "هل أنت محكم أم كبير محكمين الآن؟",
    ),
    (
        ("مجرى", "معضلة", "أحداث ومعاضل"),
        "مجرى الأحداث والمعاضل يُعدّ من بنك المعلومات أو حزمة التخطيط، ثم تُبنى عليه أيام وقوائم تقييم الإجراءات.\n"
        "افتح التشجير ← التخطيط أو إدارة النظام ← بنك المعلومات حسب دورك.\n"
        "هل تريد إعداد المجرى أم نشر قوائم مرتبطة به؟",
    ),
    (
        ("إنشاء تمرين", "تمرين جديد", "فتح تمرين"),
        "من إدارة النظام ← إنشاء تمرين جديد (أو فتح تمرين محفوظ). بدون تمرين حالي لن تعمل أوامر التخطيط والمحكمين.\n"
        "هل تريد خطوات الإنشاء أم اختيار تمرين موجود؟",
    ),
]


def role_label_ar(user: User) -> str:
    if is_system_admin(user):
        return "إدارة النظام"
    if is_planner(user):
        return "التخطيط"
    if is_chief_judge(user):
        return "كبير المحكمين"
    if is_judge(user):
        return "المحكم"
    if is_control(user):
        return "السيطرة"
    if is_analyst(user):
        return "المحلل"
    return "مستخدم"


def build_knowledge_corpus(*, max_chars: int = MAX_KNOWLEDGE_CHARS) -> str:
    parts: list[str] = [f"# {MANUAL_TITLE}", ""]
    for sec in MANUAL_SECTIONS:
        title = (sec.get("title") or "").strip()
        audience = (sec.get("audience") or "").strip()
        intro = (sec.get("intro") or "").strip()
        parts.append(f"## {title}")
        if audience:
            parts.append(f"الجمهور: {audience}")
        if intro:
            parts.append(intro)
        for i, st in enumerate((sec.get("steps") or [])[:5], start=1):
            st_title = (st.get("title") or "").strip()
            where = (st.get("where") or "").strip()
            action = (st.get("action") or "").strip()
            line = f"{i}. {st_title}"
            if where:
                line += f" | أين: {where}"
            if action:
                line += f" | افعل: {action}"
            parts.append(line)
        parts.append("")
    text = "\n".join(parts).strip()
    if len(text) > max_chars:
        return text[: max_chars - 20].rstrip() + "\n…(مختصر)"
    return text


def _match_intent_guide(question: str) -> str | None:
    q = (question or "").strip().lower()
    if not q:
        return None
    for keys, guide in _INTENT_GUIDES:
        if any(k in q for k in keys):
            return guide
    return None


def guide_fallback(question: str, *, role: str) -> dict[str, Any]:
    """توجيه مختصر — لا يلصق فصول الدليل."""
    intent = _match_intent_guide(question)
    if intent:
        answer = intent + f"\n\n(دورك الحالي: {role})"
        return {
            "ok": True,
            "source": "guide",
            "answer": answer,
            "matched_section": None,
        }
    return {
        "ok": True,
        "source": "guide",
        "answer": (
            "أحتاج توضيحاً بسيطاً لأوجّهك بدقة.\n"
            "هل سؤالك عن: تسجيل الدخول؟ إعداد التمرين؟ المجرى والمعاضل؟ نشر القوائم؟ أم مسار الاعتماد؟\n"
            "يمكنك أيضاً اختيار فرعاً من التشجير أعلاه أو فتح دليل المستخدم التفصيلي.\n"
            f"(دورك الحالي: {role})"
        ),
        "matched_section": None,
    }


def _system_prompt(role: str) -> str:
    return (
        "أنت مرشد مساعدة داخل «نظام إدارة التمارين».\n"
        "مهمتك: تقرأ سؤال المستخدم وتفهم قصده، ثم توجّهه إلى المكان الصحيح في النظام "
        "بخطوات قصيرة (3–5 كحد أقصى) وبأسلوب حواري.\n"
        "قواعد صارمة:\n"
        "1) لا تلصق فصولاً كاملة من الدليل ولا تسرد مسارات غير مرتبطة بالسؤال.\n"
        "2) إن كان السؤال غامضاً: اسأل سؤال توضيح واحد، ثم اقترح أقرب مسارين ممكنين.\n"
        "3) ابدأ بجملة تُظهر أنك فهمت القصد، ثم قل أين يذهب المستخدم (القائمة/الصفحة/الزر).\n"
        "4) اعتمد فقط على معرفة الدليل المرفقة؛ لا تخترع شاشات.\n"
        "5) لا تطلب/تكشف بيانات تمارين أو أسماء أشخاص أو نتائج.\n"
        "6) أجب بالعربية المبسطة المختصرة.\n"
        f"دور السائل: {role}."
    )


def ask_help_assistant(
    db: Session,
    user: User,
    question: str,
) -> dict[str, Any]:
    q = (question or "").strip()
    if not q:
        return {"ok": False, "error": "empty", "error_message": "اكتب سؤالاً أولاً."}
    if len(q) > MAX_QUESTION_CHARS:
        return {
            "ok": False,
            "error": "too_long",
            "error_message": f"السؤال طويل جداً (الحد {MAX_QUESTION_CHARS} حرفاً).",
        }

    role = role_label_ar(user)

    # توجيه سريع للنوايا الواضحة قبل استدعاء النموذج (أفضل من لصق دليل خاطئ)
    quick = _match_intent_guide(q)
    if quick:
        return {
            "ok": True,
            "source": "guide",
            "answer": quick + f"\n\n(دورك الحالي: {role})",
            "ai_enabled": False,
            "matched_section": None,
        }

    knowledge = build_knowledge_corpus()

    from app.ai_local_engine.exceptions import AILocalEngineError
    from app.ai_local_engine.schemas.request_schema import GenerateTextRequest
    from app.ai_local_engine.services.ai_service import AIService

    svc = AIService(db)
    settings = svc.get_settings()
    if not settings.enabled or not (settings.model_name or "").strip():
        out = guide_fallback(q, role=role)
        out["ai_enabled"] = False
        return out

    user_prompt = (
        "ملخص معرفة النظام (مرجع فقط — لا تلصقه):\n"
        f"{knowledge}\n\n"
        "———\n"
        f"سؤال المستخدم: {q}\n\n"
        "اكتب رداً موجّهاً: افهم القصد → وجّه للصفحة/الزر → خطوات قصيرة → "
        "إن لزم اسأل توضيحاً واحداً. ممنوع سرد مسار كامل غير مطلوب."
    )
    try:
        result = svc.generate_text(
            GenerateTextRequest(
                prompt=user_prompt,
                system_prompt=_system_prompt(role),
                max_tokens=min(int(settings.max_tokens or MAX_ANSWER_TOKENS), MAX_ANSWER_TOKENS),
                temperature=min(float(settings.temperature or 0.25), 0.4),
            )
        )
    except AILocalEngineError as exc:
        out = guide_fallback(q, role=role)
        out["ai_enabled"] = True
        out["ai_error"] = exc.user_message
        return out
    except Exception:
        out = guide_fallback(q, role=role)
        out["ai_enabled"] = True
        out["ai_error"] = "تعذر الاتصال بمحرك الذكاء الاصطناعي المحلي."
        return out

    if not result.success or not (result.text or "").strip():
        out = guide_fallback(q, role=role)
        out["ai_enabled"] = True
        out["ai_error"] = result.error_message or result.error_code or "فشل التوليد"
        return out

    return {
        "ok": True,
        "source": "ai",
        "answer": (result.text or "").strip(),
        "ai_enabled": True,
        "matched_section": None,
        "response_ms": int(result.response_time_ms or 0),
    }
