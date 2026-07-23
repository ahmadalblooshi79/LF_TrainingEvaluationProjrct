# أمان محرك الذكاء الاصطناعي المحلي

## مبادئ المرحلة الأولى

- لا إنترنت لمسار المحرك المحلي.
- لا مزودين سحابيين (OpenAI / Gemini / Anthropic…).
- العناوين المسموحة افتراضياً: `127.0.0.1` / `localhost` / `::1`.
- الشبكة الداخلية اختيارية وبقرار مدير النظام فقط (10/8، 172.16/12، 192.168/16).
- لا Telemetry.
- لا تسجيل محتوى Prompt أو Response افتراضياً.
- لا `ollama pull` من داخل النظام.
- لا تنفيذ أوامر Shell من صفحة الإعدادات.

## الصلاحيات

| منطقي | دالة | افتراضي |
|-------|------|---------|
| ai.center.view | can_access_ai_center | system_admin |
| ai.settings.edit | can_edit_ai_settings | system_admin |
| ai.connection.test | can_test_ai_connection | system_admin |
| ai.models.view | can_view_ai_models | system_admin |

المحكم العادي لا يرى البطاقة ويُرفض بـ 403 عند محاولة فتح المسار.
