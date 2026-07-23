# Changelog

## 2026-07-22 — المرحلة الثانية: مكتبة التقارير الذكية

### أُضيف
- حزمة `app/ai_report_library/` (تخزين، parsers، اكتشاف أقسام/وحدات/نقاط، pipeline).
- جداول `ai_report_*` ومسارات `/ai-center/report-library*`.
- بطاقة مكتبة التقارير داخل مركز الذكاء الاصطناعي.
- صلاحيات `can_*_ai_reports_*` (إدارة النظام).
- اختبارات `tests/test_ai_report_library.py` وتوثيق `docs/AI_REPORT_LIBRARY_*.md`.
- اعتمادية `python-docx`.

### خارج النطاق (متعمد)
- Embeddings / Vector / RAG / إنشاء تقارير مولَّدة.
- تفعيل LM Studio أو llama.cpp.
- OCR تلقائي لـ PDF المصور.

## 2026-07-22 — المرحلة الأولى: محرك الذكاء الاصطناعي المحلي

### أُضيف
- حزمة `app/ai_local_engine/` (Ollama فعلي + هياكل LM Studio وllama.cpp).
- جدول `ai_settings` وإعدادات من `.env`.
- صفحة `/ai-center` وبطاقة **مركز الذكاء الاصطناعي** في الصفحة الرئيسية (لإدارة النظام).
- واجهات API: `/api/ai/settings`, `/api/ai/test-connection`, `/api/ai/models`, `/api/ai/test-prompt`, `/api/ai/health`.
- صلاحيات `can_access_ai_center` وما يتبعها.
- اختبارات unittest وتوثيق تحت `docs/AI_LOCAL_ENGINE_*.md` وخطة `AI_LOCAL_ENGINE_PLAN.md`.
