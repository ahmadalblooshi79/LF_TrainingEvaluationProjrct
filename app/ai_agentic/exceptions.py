"""أنواع أخطاء Agentic Engine — رسائل عربية للمستخدم، بدون stack traces."""

from __future__ import annotations


class AgenticAIError(Exception):
    """قاعدة أخطاء الطبقة الوكيلة."""

    error_code = "agentic_error"
    user_message = "حدث خطأ في محرك الوكلاء."

    def __init__(self, message: str | None = None, *, error_code: str | None = None):
        self.user_message = (message or self.user_message).strip()
        if error_code:
            self.error_code = error_code
        super().__init__(self.user_message)


class OllamaConnectionError(AgenticAIError):
    error_code = "ollama_connection_error"
    user_message = "تعذر الاتصال بخدمة Ollama المحلية عبر AI Gateway."


class ModelNotAvailableError(AgenticAIError):
    error_code = "model_not_available"
    user_message = "النموذج المحلي المحدد غير متاح."


class AgentDisabledError(AgenticAIError):
    error_code = "agent_disabled"
    user_message = "الوكيل معطّل ولا يمكن تشغيله."


class AgentValidationError(AgenticAIError):
    error_code = "agent_validation_error"
    user_message = "مدخلات الوكيل غير صالحة."


class AgentExecutionError(AgenticAIError):
    error_code = "agent_execution_error"
    user_message = "فشل تنفيذ الوكيل."


class AgentOutputValidationError(AgenticAIError):
    error_code = "agent_output_validation_error"
    user_message = "مخرجات الوكيل لا تطابق الصيغة المتوقعة."


class WorkflowNotFoundError(AgenticAIError):
    error_code = "workflow_not_found"
    user_message = "تشغيل سير العمل غير موجود."


class WorkflowStateError(AgenticAIError):
    error_code = "workflow_state_error"
    user_message = "حالة سير العمل لا تسمح بهذه العملية."


class RetryLimitExceededError(AgenticAIError):
    error_code = "retry_limit_exceeded"
    user_message = "تم تجاوز الحد الأقصى لإعادة المحاولة."


class MigrationSafetyError(AgenticAIError):
    error_code = "migration_safety_error"
    user_message = "فشلت عملية الترحيل الآمنة لقاعدة البيانات."


class AgenticDisabledError(AgenticAIError):
    error_code = "agentic_disabled"
    user_message = "محرك الوكلاء معطّل من الإعدادات."


class DuplicateAgentKeyError(AgenticAIError):
    error_code = "duplicate_agent_key"
    user_message = "مفتاح الوكيل موجود مسبقاً."
