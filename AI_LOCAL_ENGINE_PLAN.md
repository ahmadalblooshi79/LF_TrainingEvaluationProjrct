# خطة المرحلة الأولى — محرك الذكاء الاصطناعي المحلي

تاريخ الإعداد: 2026-07-22  
الحالة: جاهزة للتنفيذ بعد المراجعة

---

## 1. ملخص بنية المشروع الحالية

| العنصر | الواقع في المشروع |
|--------|-------------------|
| Backend | Flask 3.x — مصنع `create_app()` في `app/__init__.py` — Blueprint واحد `views` في `app/views.py` |
| Frontend | قوالب Jinja2 + CSS محلي (`style.css`, `ui-refine.css`, …) — Font Awesome 6.5.1 محلي — RTL |
| قاعدة البيانات | SQLite (`exercises.db`) + SQLAlchemy 2 — ترحيل يدوي عبر `ensure_*` في `app/database.py` (لا Alembic) |
| التشغيل | `.venv` (Python 3.14) عبر `run.bat` / `run.py` — المنفذ الافتراضي 8005 |
| الصفحة الرئيسية | `GET /dashboard` → `app/templates/dashboard.html` — شبكة بطاقات أدوار `.role-grid.role-grid--pyramid` |
| الصلاحيات | دور واحد لكل مستخدم (`RoleKey`) + دوال `can_*` في `app/permissions.py` — لا صلاحيات granular منفصلة حالياً |
| الإعدادات | `.env` + `app/config.py` — لا صفحة إعدادات عامة |
| الرسائل | `form-ok-banner` / `form-error-banner` عبر متغيرات القالب (لا Flask flash) |
| AI الحالي | `app/ai_service.py` و`positives_negatives_ai.py` يعتمدان OpenAI عبر HTTP — **منفصل** عن المحرك المحلي الجديد |
| الاختبارات | `unittest` في مجلد `tests/` |
| CHANGELOG | غير موجود — سيُنشأ |

### هيكل المجلدات ذات الصلة

```
app/
  __init__.py, config.py, database.py, views.py, permissions.py
  models/          # نماذج SQLAlchemy
  templates/       # Jinja بما فيها dashboard.html
  static/          # CSS + Font Awesome
tests/
docs/
run.py / run.bat / .env.example / AGENTS.md
```

---

## 2. أفضل مكان لإضافة محرك الذكاء الاصطناعي

### الحزمة البرمجية

حزمة جديدة تحت التطبيق (لتتوافق مع استيرادات المشروع):

```
app/ai_local_engine/
```

**لا** تُدمج في `app/ai_service.py` الحالي (مخصص لاقتراحات OpenAI السحابية) حتى لا تختلط المسؤوليات. المرحلة الأولى تبني طبقة محلية مستقلة؛ أي ربط لاحق مع المساعد السحابي اختياري وخارج النطاق.

### الواجهة والدخول

- **بطاقة جديدة** في الصفحة الرئيسية (`/dashboard`) باسم **مركز الذكاء الاصطناعي**.
- المسار: **`/ai-center`** → صفحة `ai_center.html`.
- البطاقة **ليست** `RoleDef` جديداً؛ تُضاف بعد بطاقات الأدوار عند توفر الصلاحية.

### مكان البطاقة في الصفحة الرئيسية

في `dashboard.html` داخل `.role-grid.role-grid--pyramid`:

1. الإبقاء على حلقة `{% for c in dashboard_cards %}` كما هي.
2. بعد الحلقة (أو عبر عنصر إضافي في `dashboard_cards` من الـ view): بطاقة بنفس الأصناف:
   - `card card--tint dashboard-role-card`
3. أيقونة مقترحة (Font Awesome الموجود): `fa-solid fa-microchip` أو `fa-brain`.
4. النص الفرعي (tooltip / duties):  
   «إعداد وتشغيل الذكاء الاصطناعي المحلي وإدارة خصائص التقارير الذكية.»
5. الرابط: `/ai-center`.

في `dashboard()` داخل `views.py`: إن `can_access_ai_center(user)` أُلحق عنصراً إلى `dashboard_cards` بمفتاح `role_key: "ai_center"` (مفتاح عرض فقط، ليس دوراً في DB).

---

## 3. الملفات الجديدة المطلوبة

### محرك AI

| مسار | الغرض |
|------|--------|
| `app/ai_local_engine/__init__.py` | تصدير عام |
| `app/ai_local_engine/config.py` | قراءة إعدادات env + دمج مع DB |
| `app/ai_local_engine/exceptions.py` | استثناءات عربية واضحة |
| `app/ai_local_engine/models.py` | نموذج SQLAlchemy `AiSettings` (+ حالة صحة اختيارية) |
| `app/ai_local_engine/security.py` | التحقق من `base_url` (محلي / شبكة داخلية) |
| `app/ai_local_engine/providers/__init__.py` | مصنع المزودين |
| `app/ai_local_engine/providers/base_provider.py` | `BaseAIProvider` |
| `app/ai_local_engine/providers/ollama_provider.py` | تنفيذ فعلي |
| `app/ai_local_engine/providers/lmstudio_provider.py` | هيكل مبدئي |
| `app/ai_local_engine/providers/llamacpp_provider.py` | هيكل مبدئي |
| `app/ai_local_engine/services/ai_service.py` | `AIService` المركزية |
| `app/ai_local_engine/services/health_service.py` | فحص الصحة |
| `app/ai_local_engine/schemas/request_schema.py` | مخططات طلب |
| `app/ai_local_engine/schemas/response_schema.py` | استجابة موحدة |

### واجهة

| مسار | الغرض |
|------|--------|
| `app/templates/ai_center.html` | مركز الذكاء الاصطناعي المحلي |

### اختبارات

| مسار | الغرض |
|------|--------|
| `tests/test_ai_local_engine_service.py` | AIService + أمان + إعدادات |
| `tests/test_ai_local_ollama_provider.py` | Ollama مع Mock |
| `tests/test_ai_local_health_service.py` | Health |
| `tests/test_ai_local_permissions_api.py` | صلاحيات + مسارات API/صفحة |

### توثيق

| مسار | الغرض |
|------|--------|
| `docs/AI_LOCAL_ENGINE_OVERVIEW.md` | نظرة عامة |
| `docs/AI_LOCAL_ENGINE_INSTALLATION.md` | التثبيت وOllama |
| `docs/AI_LOCAL_ENGINE_CONFIGURATION.md` | الإعدادات |
| `docs/AI_LOCAL_ENGINE_TROUBLESHOOTING.md` | استكشاف الأخطاء |
| `docs/AI_LOCAL_ENGINE_SECURITY.md` | الأمان |
| `docs/AI_LOCAL_ENGINE_USER_GUIDE_AR.md` | دليل المستخدم عربي |
| `CHANGELOG.md` | سجل التغييرات (جديد) |

---

## 4. الملفات التي سيتم تعديلها

| ملف | التغيير |
|-----|---------|
| `app/permissions.py` | دوال `can_access_ai_center`, `can_view_ai_settings`, `can_edit_ai_settings`, `can_test_ai_connection`, `can_view_ai_models` |
| `app/views.py` | بطاقة dashboard + مسارات `/ai-center` وواجهات API تحت `/api/ai/...` |
| `app/templates/dashboard.html` | فرع أيقونة `ai_center` |
| `app/models/__init__.py` | تصدير `AiSettings` |
| `app/database.py` + `app/__init__.py` | `ensure_ai_settings_table()` عند الإقلاع |
| `app/config.py` | مفاتيح `AI_*` الافتراضية من البيئة |
| `.env.example` | توثيق متغيرات AI |
| `AGENTS.md` | إشارة مختصرة لمحرك AI المحلي (إن لزم) |

**لن يُعدَّل:** تصميم الألوان/الشبكة العامة، بطاقات الأدوار الحالية، `ai_service.py` السحابي (يبقى كما هو).

---

## 5. التغييرات في قاعدة البيانات

جدول جديد `ai_settings` (صف واحد للإعدادات الفعّالة):

| عمود | نوع تقريبي |
|------|------------|
| id | Integer PK |
| enabled | Boolean |
| provider | String (ollama / lmstudio / llamacpp) |
| base_url | String |
| model_name | String |
| temperature | Float |
| max_tokens | Integer |
| timeout_seconds | Integer |
| retry_count | Integer |
| context_window | Integer |
| response_language | String |
| structured_output | Boolean |
| allow_internal_network | Boolean |
| last_connection_ok | Boolean nullable |
| last_connection_at | DateTime nullable |
| last_response_ms | Integer nullable |
| last_error | String nullable |
| created_at / updated_at | DateTime |
| updated_by | Integer nullable (user id) |

الترحيل: `Base.metadata.create_all` + `ensure_ai_settings_table()` بأسلوب المشروع (بدون Alembic).  
قيم أولية من `.env` عند أول إنشاء للصف.

**لا** تُخزَّن مفاتيح سرية أو كلمات مرور.

---

## 6. طريقة إضافة زر/بطاقة مركز الذكاء الاصطناعي

1. في `dashboard()`: إذا `can_access_ai_center(user)` أضف dict إلى `dashboard_cards`:
   - `role_key`: `"ai_center"`
   - `title_ar`: `"مركز الذكاء الاصطناعي"`
   - `duties_ar`: النص الفرعي أعلاه
   - `href`: `"/ai-center"`
2. في `dashboard.html`: شرط أيقونة لـ `ai_center` → `fa-microchip` (أو `fa-brain`).
3. لا إعادة ترتيب بطاقات الأدوار؛ البطاقة تُلحق في النهاية (أو تُدرج بعد السيطرة إن رُغب لاحقاً — الافتراضي: النهاية).

---

## 7. مسار التنقل

```
الصفحة الرئيسية (/dashboard)
  → بطاقة «مركز الذكاء الاصطناعي»
    → /ai-center
      → صفحة «مركز الذكاء الاصطناعي المحلي»
        أقسام المرحلة 1 فقط:
          1) حالة المحرك
          2) إعدادات الاتصال
          3) النماذج المحلية
          4) اختبار Prompt
          5) معلومات المحرك
```

الرجوع: `partials/subpage_close.html` كما في بقية الصفحات (إلى الرئيسية/السابق).

---

## 8. الصلاحيات (مواءمة مع نظام الأدوار الحالي)

المشروع لا يستخدم مفاتيح مثل `ai.center.view` كسجلات DB.  
**الخطة:** تعريف دوال `can_*` مع توثيق المكافئ المنطقي:

| مفتاح منطقي | دالة | افتراضي |
|-------------|------|---------|
| ai.center.view | `can_access_ai_center` | `system_admin` فقط |
| ai.settings.view | `can_view_ai_settings` | نفس المركز |
| ai.settings.edit | `can_edit_ai_settings` | `system_admin` فقط |
| ai.connection.test | `can_test_ai_connection` | `system_admin` فقط |
| ai.models.view | `can_view_ai_models` | نفس المركز |

المحكم العادي **لا** يرى البطاقة ولا يصل للمسار (`abort(403)`).

---

## 9. واجهات API المقترحة

| Method | Path | صلاحية |
|--------|------|--------|
| GET | `/api/ai/settings` | view settings |
| PUT | `/api/ai/settings` | edit settings |
| POST | `/api/ai/test-connection` | test connection |
| GET | `/api/ai/models` | view models |
| POST | `/api/ai/test-prompt` | test connection (أو edit) |
| GET | `/api/ai/health` | view center |

حماية: جلسة مستخدم + `can_*` + تحقق `base_url` + حد أقصى لطول Prompt التجريبي.

---

## 10. خطة التنفيذ (ترتيب)

1. ✅ فحص المشروع والصفحة الرئيسية (هذا الملف).
2. إنشاء حزمة `app/ai_local_engine` (config, exceptions, security, schemas).
3. `BaseAIProvider` + `OllamaProvider` + هياكل LM Studio / llama.cpp.
4. `AIService` + `HealthService`.
5. نموذج `AiSettings` + `ensure_ai_settings_table`.
6. صلاحيات في `permissions.py`.
7. مسارات API + صفحة `/ai-center` + قالب.
8. بطاقة الصفحة الرئيسية.
9. اختبارات unittest مع Mock.
10. توثيق `docs/` + `CHANGELOG.md`.
11. تشغيل المشروع والاختبارات وإصلاح الأخطاء.

**خارج النطاق صراحةً:** تقارير، Word/PDF، embeddings، قاعدة معرفة، تحليل أسلوب عسكري، تحليل محكمين.

---

## 11. خطة الاختبار

- Unit tests مع Mock لـ httpx/Ollama — **بدون** تشغيل Ollama فعلياً.
- تغطية: إعدادات، اختيار مزود، اتصال ناجح/فاشل، timeout، نموذج مفقود، استجابة فارغة، منع URL خارجي، السماح بـ localhost، صلاحيات، API، عدم تسجيل الـ Prompt في اللوجات.
- اختبار اختياري يدوي عند توفر Ollama محلياً.

---

## 12. المخاطر المحتملة

| خطر | تخفيف |
|-----|--------|
| تعارض اسم `ai_service` | حزمة منفصلة `ai_local_engine` |
| تسرب بطاقة بدون صلاحية | فلترة في `dashboard()` + `abort(403)` على المسار |
| عنوان خارجي في الإعدادات | `security.py` يمنع قبل أي طلب |
| تعطل النظام عند توقف Ollama | معالجة أخطاء؛ الصفحة تعمل وتعرض حالة الفشل |
| كسر تخطيط الهرم في dashboard | إلحاق البطاقة بنفس الأصناف؛ مراجعة CSS pyramid إن لزم |
| تسجيل بيانات حساسة | `AI_LOG_PROMPTS=false` افتراضياً؛ لا تسجيل محتوى |

---

## 13. طريقة الرجوع عن التعديلات

```bat
git status
git checkout -- <files>
git clean -fd -- app/ai_local_engine docs/AI_LOCAL_* CHANGELOG.md
```

أو إعادة تعيين الفرع إلى commit ما قبل المرحلة إن وُجد checkpoint:

```bat
git stash push -u -m "ai-local-engine-phase1"
```

قبل التعديلات الكبيرة يُفضَّل commit/checkpoint على الفرع الحالي.

---

## 14. قرارات تقنية معتمدة في هذه الخطة

1. المسار: `/ai-center`.
2. الحزمة: `app/ai_local_engine/`.
3. الإعدادات: جدول `ai_settings` + قيم افتراضية من `.env`.
4. المزود الافتراضي: Ollama على `http://127.0.0.1:11434`.
5. البطاقة: نهاية شبكة الأدوار، ظاهرة لـ `system_admin` فقط افتراضياً.
6. عدم المساس بـ OpenAI الحالي في `ai_service.py`.
7. لا `ollama pull` ولا اتصال سحابي من المحرك المحلي.

---

## 15. معايير اكتمال المرحلة الأولى

راجع البنود 1–22 في مواصفات المستخدم (زر، صفحة، Providers، AIService، إعدادات، اختبار اتصال/Prompt، أمان، اختبارات، توثيق، بدون وظائف التقارير).

---

*بعد اعتماد هذه الخطة يبدأ التنفيذ وفق القسم 10.*
