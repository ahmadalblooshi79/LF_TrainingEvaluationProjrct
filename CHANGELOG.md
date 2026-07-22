# Changelog

## 2026-07-22 — المرحلة الأولى: محرك الذكاء الاصطناعي المحلي

### أُضيف
- حزمة `app/ai_local_engine/` (Ollama فعلي + هياكل LM Studio وllama.cpp).
- جدول `ai_settings` وإعدادات من `.env`.
- صفحة `/ai-center` وبطاقة **مركز الذكاء الاصطناعي** في الصفحة الرئيسية (لإدارة النظام).
- واجهات API: `/api/ai/settings`, `/api/ai/test-connection`, `/api/ai/models`, `/api/ai/test-prompt`, `/api/ai/health`.
- صلاحيات `can_access_ai_center` وما يتبعها.
- اختبارات unittest وتوثيق تحت `docs/AI_LOCAL_ENGINE_*.md` وخطة `AI_LOCAL_ENGINE_PLAN.md`.

### خارج النطاق (متعمد)
- تقارير عسكرية، Word/PDF، Embeddings، قاعدة معرفة، تحليل محكمين.
