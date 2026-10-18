# تشخيص C.2.1 — عدم ظهور قوائم تقييم المعاضل والصور في النسخة الاحتياطية

**التاريخ:** 2026-10-17  
**الإصدار المفحوص:** 2.7.38+52  
**نطاق الفحص:** تشخيص فقط — لم يُعدَّل كود ولا قاعدة بيانات ولا تصميم.

---

## الخلاصة

المشكلة ليست أن البيانات غير موجودة على التابلت. قوائم المعاضل والصور موجودة محلياً وتظهر في التطبيق. النسخة الاحتياطية **تنشئ مجلد «قوائم تقييم المعاضل» فارغاً** لأن مولّد Excel البشري **يسقط قوائم المعاضل قبل كتابة أي ملف**.

السبب الجذري:

1. استجابة السيرفر لتفاصيل قائمة المعاضل **لا تحتوي `exercise_id`**.
2. `assembleEvalBackup` عند غياب `exercise_id` **يشترط** أن يكون معرّف القائمة موجوداً في كاش كتالوج `action_eval_lists`.
3. اختبارات C.2.1 لا تكشف ذلك لأنها تضيف `exercise_id` يدوياً (عكس بيانات الإنتاج).
4. الصور تظهر في التطبيق عبر `sheet_cache_key` / `local_media`، بينما مجلد القائمة في النسخة الاحتياطية يربط الوسائط فقط بـ `bundle_action_eval_id`.

النتيجة المرئية: هيكل مجلدات بلا ملفات Excel/صور داخل «قوائم تقييم المعاضل».

---

## 1) أين تُخزَّن قوائم تقييم المعاضل والصور على التابلت

### قوائم تقييم المعاضل (بيانات الورقة)

| الطبقة | المكان | المفتاح / الجدول |
|---|---|---|
| SQLite | `cache.json_body` | `u{userId}:action_eval_detail:{slot}` |
| SQLite | كتالوج القوائم | `u{userId}:action_eval_lists:` و `u{userId}:action_eval_lists:{day}` |
| ليست ملفاً مستقلاً | لا يوجد `.xlsx` عسكري على الجهاز | القالب يُفسَّر على السيرفر ويُخزَّن كـ JSON (`eval_rows` + `saved_payload`) |

الدوال:

- `TabletRepository.fetchActionEvalLists` / `fetchActionEvalDetail` — `flutter_app/lib/services/tablet_repository.dart`
- `TabletRepository._scoped` → `u{userId}:` + المفتاح
- `OfflineStore.cacheSet` / جدول `cache` — `flutter_app/lib/services/offline_store.dart`
- مصدر السيرفر: `tablet_action_eval_lists` و `tablet_action_eval_detail` — `app/tablet_api.py`

واجهة التطبيق تقرأ الكاش نفسه، لذلك القوائم تظهر طبيعياً حتى لو فشل مولّد النسخة الاحتياطية.

### الصور / الفيديو

| الطبقة | المكان |
|---|---|
| ملف القرص | تخزين التطبيق الخاص: `{app_documents}/media/pending/images/` أو `.../videos/` |
| SQLite بيانات وصفية | جدول `media_files` (مسار، `user_id`, `exercise_id`, `bundle_action_eval_id`, `row_index`, `sheet_cache_key`) |
| JSON داخل ورقة المعاضلة | `cache.json_body.local_media[]` (إن كُتب) |

الدوال:

- `EvalSheetScreen` (وضع `actionEval`) → `TabletRepository.queueCriterionMedia`
- `OfflineStore.persistMediaFile` ينسخ الملف إلى التخزين الخاص (لا يُنقل المصدر)
- `OfflineStore.upsertMedia` يكتب صف `media_files`

هذه الملفات **غير ظاهرة** عند نسخ وحدة التخزين عبر USB/MTP. النسخة الاحتياطية هي المسار المقصود لإخراجها.

### قوائم تقييم الإجراءات (للمقارنة)

- كاش: `u{userId}:evaluation_list_detail:{unitKey}:{itemId}`
- كتالوج: `u{userId}:evaluation_lists...`
- وسائط: `evaluation_list_item_id` في `media_files`

---

## 2) SQLite أم JSON أم ملفات مستقلة؟

الخليط التالي:

- **SQLite** هو الحاوية (`cache`, `media_files`, `pending_ops`).
- **JSON داخل `cache.json_body`** هو محتوى قائمة المعاضل (الصفوف، المكتسبة، الملاحظات، `local_media`).
- **ملفات مستقلة للوسائط فقط** (jpg/mp4) تحت مجلد `media/` الخاص بالتطبيق.
- **لا يوجد** ملف Excel أصلي لقائمة المعاضل على التابلت. Excel النسخة الاحتياطية يُولَّد وقت الإنشاء من `assembleEvalBackup` + `buildSimpleXlsx`.

---

## 3) نقل البيانات من التابلت إلى الكمبيوتر

مساران منفصلان:

### أ) النسخ الاحتياطي داخل التطبيق (المسار المعتمد)

1. `ScopedBackupScreen` → `ScopedBackupService.createBackupForUser`
2. قراءة scoped من SQLite (كاش / pending / media metadata)
3. كتابة حزمة مجلدات محلية تحت `app_documents/scoped_backups/`
4. نسخ الحزمة إلى Downloads عبر القناة الأصلية `copyBackupToPublicDownloads` في `MainActivity.kt` (MediaStore)
5. المسار الظاهر: `Download/SmartArbitration_Backups/<التمرين>/<المحكم>/Backup_<timestamp>/`

### ب) نسخ الملفات يدوياً (USB / MTP / مستكشف الملفات)

- التخزين الخاص (`/data/data/.../app_flutter/media/...`) **لا يُنسخ** عبر USB العادي.
- مجلد Downloads يُنسخ، لكن MediaStore + MTP على ويندوز غالباً يُظهر شجرة مجلدات ناقصة أو مجلدات فارغة خصوصاً مع أسماء عربية متداخلة.
- لذلك «نسخ البيانات للكمبيوتر» بدون النسخة الاحتياطية لا يكفي لإخراج صور المعاضل.

---

## 4) آلية إنشاء النسخة الاحتياطية (الجزء البشري)

`writeBackupPackage` في `scoped_backup_service.dart`:

1. يكتب الحزمة التقنية: `records/` + `media/` + `backup_manifest.json` + `BACKUP_COMPLETE`
2. ثم يستدعي `writeEvaluationExcelIntoBackup` في `scoped_backup_excel.dart`
3. ذلك يستدعي `assembleEvalBackup` من `eval_backup_assembler.dart`
4. لكل قائمة ناجحة: مجلد باسم العرض + `.xlsx` + نسخ بثّي للوسائط المرتبطة

المجلدات تُنشأ **دائماً** حتى لو لم تُكتب ملفات:

```
قوائم التقييم/قوائم تقييم الإجراءات/
قوائم التقييم/قوائم تقييم المعاضل/
```

هذا يطابق العرض: هيكل موجود، محتوى ناقص.

الحزمة التقنية (`records/` و`media/`) تبقى منفصلة. الاستعادة لا تقرأ مجلدات Excel البشرية.

---

## 5) لماذا تُنشأ المجلدات بلا ملفات؟

### السبب 1 (الرئيسي) — إسقاط قوائم المعاضل في المجمّع

`tablet_action_eval_detail` في `app/tablet_api.py` يعيد مثلاً:

- `kind`, `slot`, `slot_id`, `title`, `eval_rows`, `saved_payload`, ...
- **لا يعيد `exercise_id`**
- **لا يعيد `id` ولا `item_id`**

`_draftFromCache` في `eval_backup_assembler.dart`:

- إذا وُجد `exercise_id` في JSON وطابق التمرين الحالي → تُدرج القائمة.
- إذا **غاب** `exercise_id` (حالة الإنتاج) → القائمة تُدرج فقط إذا كان معرّفها داخل `catalog.dilemmaIds` المستخرج من كاش `action_eval_lists`.
- وإلا: `skipped_cache_unknown_exercise:{id}` وتُهمل القائمة. لا Excel. لا مجلد قائمة.

قوائم الإجراءات تمرّ من البوابة نفسها، لكنها عادةً تنجح لأن كتالوج `evaluation_lists` موجود في الكاش ومفاتيحه تطابق `{itemId}` في `evaluation_list_detail`.

قوائم المعاضل تفشل إذا:

- كتالوج `action_eval_lists` غير موجود في صفوف كاش النسخة الاحتياطية، أو
- معرّف الكتالوج لا يطابق معرّف التفاصيل (انظر السبب 2).

ثم `writeEvaluationExcelIntoBackup` ينشئ مجلد النوع فارغاً لأن `pkg.lists` لا يحتوي أي `EvalBackupKind.dilemma`.

### السبب 2 — هشاشة معرّف قائمة المعاضل

`_idsFromCacheKey` في `local_recovery_parser.dart`:

- لـ `evaluation_list_detail` يستخرج الرقم الأخير كـ `evalItemId`.
- لـ `action_eval_detail` يعيد `evalItemId = null` عمداً.

المجمّع يعوّض بالجزء الأخير من مفتاح الكاش (`slot` في المسار). الكتالوج يأخذ `item_id ?? slot_id ?? eval_item_id ?? id`.

أي اختلاف بين `slot_id` (مفتاح قاعدة `ExercisePlannerFlowBundleActionEval.id`) و`slot_index` أو `node_id` يُخرج المعرّف من الكتالوج → إسقاط القائمة.

واجهة التطبيق لا تستخدم هذه المطابقة؛ تفتح الورقة بـ `slotId ?? slotIndex` وتعرض الكاش مباشرة.

### السبب 3 — الاختبارات لا تمثّل الإنتاج

`phase_c21_evaluation_excel_backup_test.dart` يضع `'exercise_id': exerciseId` داخل JSON المعاضلة. استجابة السيرفر الحقيقية لا تفعل ذلك. لذلك الاختبارات نجحت بينما الجهاز يُنتج مجلداً فارغاً.

---

## 6) ارتباط الصور بالقوائم

### لماذا تظهر في التطبيق؟

`overlayLocalMediaOnRows` في `tablet_repository.dart` يجلب الوسائط من:

1. `cache.local_media` تحت مفتاح الورقة `action_eval_detail:{slot}` أو `u{userId}:action_eval_detail:{slot}`
2. صفوف `media_files` حيث `sheet_cache_key` يطابق مفتاح الورقة

لا يشترط نجاح مطابقة الكتالوج المستخدمة في النسخة الاحتياطية.

عند الالتقاط:

```
bundleActionEvalId = detail.slotId   // من JSON slot_id
sheetCacheKey     = action_eval_detail:{widget.slot}
```

### لماذا لا تُنسخ إلى مجلد القائمة في Backup؟

`mediaBelongsToEvaluationList` في `scoped_backup_excel.dart` لقائمة معاضلة يشترط فقط:

`bundle_action_eval_id == list.evalItemId`

مع تصفية `user_id` + `exercise_id`.

لا يستخدم:

- `sheet_cache_key`
- `local_media` داخل JSON الورقة
- اسم الملف أو المجلد

إذا لم تُولَّد قائمة المعاضلة أصلاً (السبب 1) فلن يوجد مجلد تُنسخ إليه الصور.  
إذا وُلدت القائمة بمعرّف مختلف عن `bundle_action_eval_id` فالصور تُستبعد من المجلد البشري.

قد تبقى نسخ تقنية تحت `media/` داخل الحزمة إذا مرّت `selectUserExerciseMedia` عبر `user_id` + `exercise_id`. ذلك لا يظهر داخل «قوائم تقييم المعاضل».

ملفات المصدر الأصلية لا تُنقل ولا تُحذف (`persistMediaFile` ينسخ فقط).

---

## 7) الملفات والدوال المسؤولة

| الدور | الملف | الدالة / الموضع |
|---|---|---|
| JSON الإنتاج بلا `exercise_id` | `app/tablet_api.py` | `tablet_action_eval_detail` (~1045) — كذلك الكتالوج `tablet_action_eval_lists` بلا `exercise_id` |
| بوابة الإسقاط | `flutter_app/lib/services/eval_backup_assembler.dart` | `_draftFromCache` (jsonEx == null → catalog.dilemmaIds) ؛ `_openCatalogIds` |
| استخراج معرّف ناقص للمعاضلة | `flutter_app/lib/services/local_recovery_parser.dart` | `_idsFromCacheKey` (`action_eval_detail` → evalItemId null) |
| إنشاء المجلد الفارغ | `flutter_app/lib/services/scoped_backup_excel.dart` | `writeEvaluationExcelIntoBackup` ينشئ مجلدي النوع دائماً ؛ `mediaBelongsToEvaluationList` |
| مسار النسخة الاحتياطية | `flutter_app/lib/services/scoped_backup_service.dart` | `createBackupForUser` → `writeBackupPackage` → `exportVerifiedBackupToPublicDownloads` |
| اختيار الكاش/الوسائط | `flutter_app/lib/services/offline_store.dart` | `backupSelectScopedCacheForUser` ؛ `backupSelectMediaMetadataForUserExercise` |
| تصفية النطاق | `flutter_app/lib/services/scoped_backup_inventory.dart` | `selectUserExerciseCache` ؛ `selectUserExerciseMedia` |
| ظهور الصور في الواجهة | `flutter_app/lib/screens/eval_sheet_screen.dart` | `_pickAndQueue` |
|  | `flutter_app/lib/services/tablet_repository.dart` | `queueCriterionMedia` ؛ `overlayLocalMediaOnRows` |
| تخزين ملف الصورة | `flutter_app/lib/services/offline_store.dart` | `persistMediaFile` ؛ جدول `media_files` |
| النسخ إلى Downloads | `flutter_app/android/.../MainActivity.kt` | `copyBackupToPublicDownloads` (ينسخ ملفات فقط، ليس المجلدات الفارغة عبر MediaStore) |
| اختبار لا يحاكي الإنتاج | `flutter_app/test/phase_c21_evaluation_excel_backup_test.dart` | `dilemmaCache(... exercise_id: ...)` |

تسمية داخل المجمّع: `EvalBackupKind.action` = قوائم تقييم **الإجراءات**، و`EvalBackupKind.dilemma` = قوائم تقييم **المعاضل** (`action_eval_*`).

---

## ما الذي يعمل رغم العطل

- بيانات المعاضل ما زالت في SQLite (`records/cache.json` بعد النسخة إن وُجدت تفاصيل في الكاش).
- الاستعادة التقنية لا تعتمد على مجلد «قوائم تقييم المعاضل».
- قوائم الإجراءات غالباً تُكتب لأن الكتالوج ومفتاح `itemId` متوافقان.
- المخطط 4 و`pending_ops` والمزامنة لم تُكسر بهذا العطل.

---

## الحل المقترح (لم يُنفَّذ)

بدون تغيير مخطط SQLite وبدون نقل/حذف وسائط المصدر:

1. **اعتماد قائمة المعاضل من مفتاح الكاش `action_eval_detail:{slot}` داخل نطاق `user_id` + التمرين الحالي**، دون اشتراط `exercise_id` داخل JSON ولا عضوية الكتالوج. الكتالوج يبقى لتحسين الاسم فقط.
2. قراءة المعرّف المستقر من `slot_id` في JSON إن وُجد، وإلا الجزء الأخير من مفتاح الكاش. عدم استخدام `item_id`/`node_id` لمعاضلة.
3. إضافة `exercise_id` و`slot_id`/`id` إلى استجابة `tablet_action_eval_detail` وكتالوج `action_eval_lists` (متوافق، بلا ترحيل).
4. ربط الوسائط البشرية بـ: `bundle_action_eval_id` **أو** `sheet_cache_key` المطابق لورقة تلك القائمة **أو** `local_media` داخل JSON الورقة. عدم التخمين بالاسم/التاريخ.
5. عدم إنشاء مجلد نوع بلا قوائم، أو إنشاء مجلد القائمة حتى لو بلا وسائط (Excel فقط) بعد نجاح الإدراج.
6. اختبار إنتاجي: JSON معاضلة **بدون** `exercise_id`، وكتالوج ناقص، وصور مرتبطة بـ `sheet_cache_key` فقط — يجب أن يظهر Excel + الصور تحت مجلد القائمة.

بعد الإصلاح: بناء APK+PWA معاً. لا تثبيت على الجهاز الإنتاجي في هذه المرحلة.

---

## تحقق ميداني مقترح (غير منفَّذ)

على نسخة غير إنتاجية بعد إنشاء Backup:

1. هل `backup_manifest.json` يحتوي `kind = dilemma_evaluation_excel`؟ إن لا: الإسقاط في المجمّع مؤكد.
2. هل `records/cache.json` أو ملفات `json_body` تحتوي مفاتيح `action_eval_detail:`؟ إن نعم: البيانات موجودة والتقصير في التوليد البشري.
3. هل `records/media_files.json` فيه `bundle_action_eval_id` و/أو `sheet_cache_key` يبدأ بـ `action_eval_detail:`؟
4. هل مجلد `media/` التقني يحتوي الصور بينما «قوائم تقييم المعاضل» فارغ؟ يؤكد انفصال الربط البشري عن النسخ التقني.
