import httpx

from app.config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL


def suggest_instructions_or_notes(
    purpose: str,
    context: str,
    language: str = "ar",
) -> str:
    """
    يولّد تعليمات أو عناصر قوائم أو ملاحظات مقترحة للمقيمين.
    بدون مفتاح API يعيد نصاً إرشادياً ثابتاً.
    """
    if not OPENAI_API_KEY or not OPENAI_API_KEY.strip():
        return _fallback_suggestion(purpose, context)

    system = (
        "أنت مساعد تقني في إدارة تمارين التقييم. "
        "أجب بجمل قصيرة وعملية، مناسبة للمقيمين والمحكمين. "
        "أعطِ قوائم نقطية عند الطلب."
    )
    user = f"الغرض: {purpose}\n\nسياق المستخدم:\n{context}\n\nاللغة المطلوبة: {language}"
    try:
        with httpx.Client(timeout=60.0) as client:
            r = client.post(
                f"{OPENAI_BASE_URL.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                json={
                    "model": OPENAI_MODEL,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.4,
                },
            )
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"تعذر الاتصال بنموذج الذكاء الاصطناعي: {e}\n\n" + _fallback_suggestion(
            purpose, context
        )


def _fallback_suggestion(purpose: str, context: str) -> str:
    return (
        "— وضع التجربة بدون مفتاح OpenAI —\n"
        "• ركّز على وضوح التعليمات وقابلية القياس.\n"
        "• اربط كل بند تقييم بمرجع من المكتبة.\n"
        "• سجّل الوقت، الملاحظة، والدليل (إن وجد).\n"
        f"— الغرض الممرر: {purpose}\n"
        f"— السياق (مختصر): {context[:500]}{'…' if len(context) > 500 else ''}\n"
        "أضف OPENAI_API_KEY في ملف .env لتفعيل الاقتراحات الذكية."
    )
