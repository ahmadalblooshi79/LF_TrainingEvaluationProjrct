# خطة المرحلة الثانية — مكتبة التقارير الذكية

تاريخ الإعداد: 2026-07-22  
الحالة: جاهزة للتنفيذ بعد المراجعة  
المحرك الفعلي: **Ollama فقط** — النموذج المستهدف `qwen3:8b` (أو الاسم المحفوظ في الإعدادات)  
غير مفعّل: LM Studio، llama.cpp، Embeddings، Vector DB، إنشاء تقارير، RAG

---

## 1. وصف بنية المرحلة الأولى الحالية

| العنصر | الواقع |
|--------|--------|
| الحزمة | `app/ai_local_engine/` — Providers + AIService + Health + أمان عناوين |
| الصفحة | `/ai-center` → `ai_center.html` (إعدادات، نماذج، اختبار Prompt) |
| البطاقة | «مركز الذكاء الاصطناعي» في `/dashboard` لـ `system_admin` |
| الجدول | `ai_settings` عبر `AiSettings` + `ensure_ai_settings_table()` |
| API | `/api/ai/settings|models|test-connection|test-prompt|health` |
| الصلاحيات | دوال `can_access_ai_*` / `can_edit_ai_*` = إدارة النظام |
| التخزين | `data_dir()/instance/...` عبر `config.py` + `paths.ensure_data_directories` |
| الهجرات | بدون Alembic — `create_all` + `ensure_*` |
| مكتبات PDF/Word | `pypdf` موجود؛ **لا** `python-docx` / PyMuPDF بعد — ستُضاف |

المرحلة 1 تبقى كما هي؛ المكتبة تُضاف كقسم/صفحة فرعية دون كسر الإعدادات أو اختبار Prompt.

---

## 2. موقع المرحلة الثانية في الواجهة

داخل `/ai-center` يُضاف بطاقة/قسم:

**مكتبة التقارير الذكية** → يفتح `/ai-center/report-library`

صفحات فرعية:

| المسار | الغرض |
|--------|--------|
| `/ai-center/report-library` | قائمة المكتبة + بحث/تصفية |
| `/ai-center/report-library/upload` | إضافة تقرير |
| `/ai-center/report-library/bulk-upload` | رفع جماعي |
| `/ai-center/report-library/<id>` | تفاصيل التقرير (Tabs) |
| `/ai-center/report-library/<id>/review` | مراجعة النقاط |

نفس تصميم البطاقات/الأزرار/RTL الحالي.

---

## 3. الملفات الجديدة المطلوبة

### حزمة التقارير

```
app/ai_report_library/
  __init__.py
  models.py                 # جداول SQLAlchemy
  constants.py              # حالات، أنواع أقسام، مستويات وحدات
  paths.py                  # مسارات originals/extracted/failed/archived/temp
  security_upload.py        # امتداد، MIME، حجم، path traversal، checksum
  services/
    storage_service.py
    checksum_service.py
    text_cleaning_service.py
    docx_parser.py
    pdf_parser.py
    section_detection_service.py
    unit_detection_service.py
    table_extraction_service.py
    finding_extraction_service.py
    finding_unit_link_service.py
    processing_pipeline.py  # تنسيق الخطوات + سجل المعالجة
    qwen_assist_service.py  # مساعد منخفض الثقة عبر AIService فقط
  schemas/
    report_dto.py
```

### قوالب

```
app/templates/ai_report_library.html
app/templates/ai_report_upload.html
app/templates/ai_report_bulk_upload.html
app/templates/ai_report_detail.html
app/templates/ai_report_review.html
app/templates/partials/ai_report_findings_by_unit.html
```

### اختبارات

```
tests/test_ai_report_checksum.py
tests/test_ai_report_upload_security.py
tests/test_ai_report_docx_parser.py
tests/test_ai_report_pdf_parser.py
tests/test_ai_report_text_cleaning.py
tests/test_ai_report_section_detection.py
tests/test_ai_report_unit_detection.py
tests/test_ai_report_findings.py
tests/test_ai_report_permissions.py
tests/test_ai_report_pipeline_mock.py
```

### توثيق

```
docs/AI_REPORT_LIBRARY_OVERVIEW.md
docs/AI_REPORT_LIBRARY_INSTALLATION.md
docs/AI_REPORT_LIBRARY_USER_GUIDE_AR.md
docs/AI_REPORT_LIBRARY_ADMIN_GUIDE_AR.md
docs/AI_REPORT_LIBRARY_SECURITY.md
docs/AI_REPORT_LIBRARY_TROUBLESHOOTING.md
docs/AI_REPORT_LIBRARY_DATABASE_SCHEMA.md
docs/AI_REPORT_LIBRARY_PROCESSING_FLOW.md
```

---

## 4. الملفات التي سيتم تعديلها

| ملف | التغيير |
|-----|---------|
| `requirements.txt` | إضافة `python-docx`؛ `pymupdf` (أو الاعتماد على `pypdf` أولاً مع دعم نصي) |
| `app/paths.py` | مجلدات `instance/ai_reports/{originals,extracted,failed,archived,temp}` |
| `app/config.py` | `AI_REPORTS_DIR`, حد الحجم، عدد الدفعة |
| `.env.example` | متغيرات التقارير |
| `app/database.py` + `app/__init__.py` | `ensure_ai_report_library_tables()` |
| `app/models/__init__.py` | تصدير نماذج التقارير |
| `app/permissions.py` | دوال `can_*_ai_reports_*` |
| `app/views.py` | مسارات المكتبة + API تحت `/api/ai/reports` |
| `app/templates/ai_center.html` | بطاقة/رابط مكتبة التقارير |
| `CHANGELOG.md` | سجل المرحلة 2 |

**لن يُعدَّل:** تصميم الصفحة الرئيسية، مزودو LM Studio/llama.cpp (يبقون stub)، وظائف المرحلة 1 الأساسية.

---

## 5. الجداول الجديدة (Models)

أسماء الجداول SQL (snake_case):

1. `ai_report_sources` — التقرير الأصلي + بيانات التصنيف + حالة المعالجة  
2. `ai_report_sections` — أقسام  
3. `ai_report_tables` — جداول مستخرجة  
4. `ai_report_units` — وحدات + هيكل  
5. `ai_report_findings` — قوة/ضعف/ملاحظة/…  
6. `ai_report_finding_units` — ربط many-to-many  
7. `ai_report_processing_logs` — سجل الخطوات  
8. `ai_report_corrections` — تعديلات يدوية  

حالات المعالجة:  
`uploaded | queued | processing | ready | needs_review | failed | excluded | archived`

حالات المراجعة:  
`auto_detected | needs_review | reviewed | approved | rejected`

---

## 6. Migrations

- نماذج Declarative + استيراد في `create_app`  
- `ensure_ai_report_library_tables()` = `CREATE TABLE IF NOT EXISTS` لكل جدول (نمط SQLite الحالي)  
- لا Alembic  
- Backup/checkpoint قبل التشغيل على قاعدة حقيقية

---

## 7. طريقة حفظ الملفات

الجذر: `AI_REPORTS_DIR` = `data_dir()/instance/ai_reports`

```
ai_reports/
  originals/<uuid>/
    original.docx|pdf
    meta.json
  extracted/<uuid>/
    extracted.json
    sections.json
    tables.json
    processing.log
  failed/
  archived/<uuid>/
  temp/
```

- UUID للمجلد وليس اسم الملف وحده  
- SHA-256 checksum  
- اسم ملف مُعقَّم (sanitize)  
- `version` للسماح بنسخة جديدة مؤكدة  
- المسار الكامل لا يُعرض للمستخدم العادي (خدمة تنزيل عبر مسار محمي)

---

## 8. قراءة Word وPDF

| النوع | الأداة | المخرج |
|-------|--------|--------|
| DOCX | `python-docx` | عناصر مرتبة: heading/paragraph/list/table + styles |
| PDF نصي | `pypdf` أولاً؛ `pymupdf` إن لزم لتحسين الكتل | نص لكل صفحة + جداول تقديرية |
| PDF مصور | كشف عبر قلة النص | حالة `needs_ocr` — **بدون OCR تلقائي** |

تمثيل موحّد: قائمة `DocumentElement` (`element_type`, `text`, `style`, `heading_level`, `order`, `page_hint`, `parent_heading`, `table_ref`).

---

## 9. استخراج الجداول

- Word: عبر `python-docx` Table API → `headers_json` / `rows_json`  
- PDF: محاولة جداول بسيطة بـ pypdf/pymupdf؛ عند الفشل تسجيل تحذير دون إسقاط التقرير  
- FindingExtraction يقرأ خلايا أعمدة القوة/الضعف ويقسّم النقاط المتعددة

---

## 10. اكتشاف الوحدات

قواعد أولاً (عناوين، جداول، كلمات مفتاحية: لواء، كتيبة، سرية، …) ثم Qwen عبر `AIService.generate_text` عند ثقة منخفضة فقط (مقاطع قصيرة).

حقول: `original_unit_name`, `normalized_unit_name`, `unit_level`, `parent_unit_id`, `detection_source`, `confidence_score`.

هيكل شجري قابل للتعديل من الواجهة.

---

## 11. ربط القوة/الضعف بالوحدات

- تقسيم كل نقطة إلى `AIReportFinding`  
- ربط عبر `AIReportFindingUnit` (`primary|shared|affected|brigade_level`)  
- `scope_type`: `single_unit|multiple_units|brigade|general|unknown`  
- استفادة من عنوان الوحدة الأب قبل عنوان وحدة جديدة  
- Qwen فقط عند غموض التصنيف/النطاق

---

## 12. مراجعة النتائج

- Tabs في صفحة التفاصيل + شاشة `/review`  
- كل تعديل يُسجَّل في `ai_report_corrections`  
- نتائج ثقة منخفضة → `needs_review` تلقائياً  
- اعتماد/استبعاد/تقسيم/دمج/تغيير نوع أو وحدة

---

## 13. الصلاحيات (دوال can_*)

| منطقي | دالة | افتراضي |
|-------|------|---------|
| ai.reports.view | `can_view_ai_reports` | system_admin |
| ai.reports.upload | `can_upload_ai_reports` | system_admin |
| ai.reports.edit | `can_edit_ai_reports` | system_admin |
| ai.reports.process | `can_process_ai_reports` | system_admin |
| ai.reports.review | `can_review_ai_reports` | system_admin |
| ai.reports.approve | `can_approve_ai_reports` | system_admin |
| ai.reports.exclude | `can_exclude_ai_reports` | system_admin |
| ai.reports.archive | `can_archive_ai_reports` | system_admin |
| ai.reports.delete | `can_delete_ai_reports` | system_admin |
| ai.reports.view_extracted_text | `can_view_ai_report_text` | system_admin |
| ai.reports.review_units | `can_review_ai_report_units` | system_admin |
| ai.reports.review_findings | `can_review_ai_report_findings` | system_admin |

المحكم العادي: لا يرى المكتبة ولا المسارات (`403`).

---

## 14. مخاطر التنفيذ

| خطر | تخفيف |
|-----|--------|
| حجم المرحلة كبير | تنفيذ على دفعات: تخزين→parsers→اكتشاف→UI→مراجعة |
| PDF معقد/مصور | تصنيف needs_ocr؛ لا OCR تلقائي |
| بطء Qwen | أجزاء قصيرة؛ قواعد أولاً؛ فشل Ollama لا يحذف التقرير |
| تكرار ملفات | checksum SHA-256 قبل الحفظ |
| كسر المرحلة 1 | عدم تعديل AIService إلا للاستهلاك؛ اختبارات المرحلة 1 تبقى |
| views.py ضخم | مسارات مجمّعة في نهاية قسم AI أو helper module مستورد من views |

---

## 15. خطة الاختبار

- Unit tests بملفات DOCX/PDF اصطناعية غير حساسة تحت `tests/fixtures/ai_reports/`  
- Mock لـ `AIService.generate_text`  
- اختبارات أمان الرفع والتكرار والصلاحيات  
- اختبار أن فشل ملف في الدفعة لا يوقف الباقي  
- إعادة تشغيل اختبارات المرحلة 1

---

## 16. طريقة الرجوع

```bat
git stash list
git checkout -- <files>
git clean -fd -- app/ai_report_library
```

أو العودة لـ commit/checkpoint قبل المرحلة 2.  
ملفات `instance/ai_reports` يمكن حذفها يدوياً دون المساس بـ `exercises.db` إن لزم (أو استعادة نسخة DB).

---

## 17. ترتيب التنفيذ المعتمد

**دفعة أ:** مسارات التخزين + Models + ensure_* + صلاحيات + بطاقة في ai_center  
**دفعة ب:** رفع فردي/جماعي + checksum + منع تكرار + حفظ الأصل  
**دفعة ج:** DOCX/PDF parsers + تنظيف النص  
**دفعة د:** اكتشاف أقسام/وحدات/جداول/نقاط + ربط + pipeline + log  
**دفعة هـ:** Qwen assist عند انخفاض الثقة  
**دفعة و:** صفحات المكتبة والتفاصيل والمراجعة + API  
**دفعة ز:** اختبارات + توثيق + CHANGELOG  

---

## 18. قرارات تقنية

1. المسار الأساسي: `/ai-center/report-library`  
2. الحزمة: `app/ai_report_library/` منفصلة عن `ai_local_engine`  
3. استدعاء النموذج فقط عبر `AIService` الموجود  
4. النموذج الافتراضي من إعدادات المحرك (المستخدم يستخدم `qwen3:8b` / `qwen2:8b` حسب المثبت)  
5. حد حجم مقترح: 25 MB للملف؛ دفعة حتى 20 ملفاً  
6. المعالجة المتزامنة في الطلب أولاً مع مؤشر تقدم؛ طابور خلفي لاحق إن لزم  
7. لا تغيير تصميم dashboard الرئيسي  

---

## 19. خارج النطاق (تأكيد)

- Embeddings / Vector / RAG / Fine-tuning  
- إنشاء أو تصدير تقارير مولَّدة  
- تحليل نتائج المحكمين الحالية  
- تفعيل LM Studio أو llama.cpp  

---

*بعد اعتماد هذه الخطة يبدأ التنفيذ بالدفعة أ.*
