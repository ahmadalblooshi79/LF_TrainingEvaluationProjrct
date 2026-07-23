"""استثناءات محرك الذكاء الاصطناعي المحلي — رسائل عربية للمستخدم."""


class AILocalEngineError(Exception):
    """قاعدة أخطاء المحرك المحلي."""

    error_code = "ai_error"
    user_message = "حدث خطأ في محرك الذكاء الاصطناعي المحلي."

    def __init__(self, message: str | None = None, *, error_code: str | None = None):
        self.user_message = (message or self.user_message).strip()
        if error_code:
            self.error_code = error_code
        super().__init__(self.user_message)


class AIProviderNotConfiguredError(AILocalEngineError):
    error_code = "provider_not_configured"
    user_message = "مزود الذكاء الاصطناعي غير مضبوط. راجع إعدادات الاتصال."


class AIConnectionError(AILocalEngineError):
    error_code = "connection_error"
    user_message = (
        "تعذر الاتصال بخدمة Ollama. تأكد من تشغيل Ollama ومن صحة عنوان الخادم المحلي."
    )


class AIModelNotFoundError(AILocalEngineError):
    error_code = "model_not_found"
    user_message = (
        "النموذج المحدد غير مثبت محلياً. يرجى تثبيت النموذج يدوياً ثم إعادة اختبار الاتصال."
    )


class AIRequestTimeoutError(AILocalEngineError):
    error_code = "timeout"
    user_message = "انتهت مهلة انتظار استجابة النموذج المحلي. حاول لاحقاً أو زد قيمة المهلة."


class AIInvalidResponseError(AILocalEngineError):
    error_code = "invalid_response"
    user_message = "استجابة النموذج فارغة أو غير صالحة."


class AIProviderDisabledError(AILocalEngineError):
    error_code = "provider_disabled"
    user_message = "الذكاء الاصطناعي المحلي غير مفعّل. فعّله من إعدادات المركز."


class AIExternalConnectionBlockedError(AILocalEngineError):
    error_code = "external_blocked"
    user_message = (
        "تم منع الاتصال لأن العنوان المحدد ليس عنواناً محلياً أو عنوان شبكة داخلية مصرحاً بها."
    )


class AIConfigurationError(AILocalEngineError):
    error_code = "configuration_error"
    user_message = "إعدادات الذكاء الاصطناعي غير صالحة."


class AIProviderNotImplementedError(AILocalEngineError):
    error_code = "provider_not_ready"
    user_message = "هذا المزود غير مكتمل بعد في المرحلة الأولى. استخدم Ollama حالياً."
