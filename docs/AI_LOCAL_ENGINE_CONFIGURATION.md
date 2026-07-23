# إعدادات محرك الذكاء الاصطناعي المحلي

## مصادر الإعداد

1. قيم أولية من `.env` (انظر `.env.example`).
2. حفظ دائم في جدول SQLite: `ai_settings`.
3. التعديل من واجهة `/ai-center` أو `PUT /api/ai/settings`.

## الحقول الرئيسية

| المفتاح | الافتراضي | ملاحظة |
|---------|-----------|--------|
| AI_ENABLED | true | تفعيل المحرك |
| AI_PROVIDER | ollama | ollama / lmstudio / llamacpp |
| AI_BASE_URL | http://127.0.0.1:11434 | محلي فقط افتراضياً |
| AI_MODEL_NAME | (فارغ) | يُختار من القائمة |
| AI_TEMPERATURE | 0.2 | |
| AI_MAX_TOKENS | 4096 | |
| AI_TIMEOUT_SECONDS | 300 | |
| AI_RETRY_COUNT | 2 | |
| AI_ALLOW_INTERNET | false | مفروض متوقف |
| AI_ALLOW_INTERNAL_NETWORK | false | للشبكات الخاصة فقط عند التفعيل |
| AI_TELEMETRY | false | متوقف |
| AI_LOG_PROMPTS / AI_LOG_RESPONSES | false | لا يُسجَّل المحتوى |

## اختيار النموذج

من قسم «النماذج المحلية» اضغط اسم النموذج لحفظه، أو اكتبه يدوياً ثم احفظ الإعدادات.
