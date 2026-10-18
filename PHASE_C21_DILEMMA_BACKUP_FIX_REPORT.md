# C.2.1 — إصلاح قوائم تقييم المعاضل والصور في النسخة الاحتياطية

**Version:** 2.7.39+53  
**Date:** 2026-10-17  
**APK:** `dist/judge-tablet-v2.7.39.apk`  
**APK Installed:** NO  
**Production Tablet Accessed:** NO

---

## المشكلة

قوائم المعاضل والصور تظهر في التطبيق، بينما مجلد `قوائم التقييم/قوائم تقييم المعاضل` في Backup يبقى فارغاً.

السبب: `assembleEvalBackup` كان يسقط `action_eval_detail` عند غياب `exercise_id` من JSON ما لم يكن المعرّف في كتالوج `action_eval_lists`. استجابة الإنتاج لا ترسل `exercise_id`. ربط الصور البشرية كان يعتمد فقط على `bundle_action_eval_id`.

---

## الإصلاح

1. قوائم المعاضل تُستخرج من كاش `u{userId}:action_eval_detail:{slot}` للمستخدم المحدد. غياب `exercise_id` أو الكتالوج لا يسقط القائمة.
2. المعرّف: `slot_id` ثم `id` ثم الجزء الأخير من مفتاح الكاش.
3. الإسقاط يبقى إذا `exercise_id` موجود ويخالف التمرين الحالي، أو إذا مفتاح الكاش لمستخدم آخر.
4. ربط الوسائط: `bundle_action_eval_id` أو `sheet_cache_key` المطابق أو `local_media` في JSON الورقة. نسخ فقط، بلا نقل/حذف المصدر.
5. السيرفر يضيف `exercise_id` و`id` (= `slot_id`) إلى تفاصيل المعاضل، و`exercise_id` إلى قائمة المعاضل. بلا تغيير مخطط.

قوائم الإجراءات ما زالت تتطلب عضوية الكتالوج عند غياب `exercise_id`.

---

## الملفات المعدّلة

| ملف | التغيير |
|---|---|
| `flutter_app/lib/services/eval_backup_assembler.dart` | عدم إسقاط معاضل بلا `exercise_id`/كتالوج؛ معرّف `slot_id`؛ ربط `sheet_cache_key` |
| `flutter_app/lib/services/scoped_backup_excel.dart` | ربط bundle / sheet_cache_key / local_media ونسخ بثّي |
| `flutter_app/lib/services/local_recovery_parser.dart` | `_idsFromCacheKey` يستخرج رقم الـ slot من `action_eval_detail` |
| `app/tablet_api.py` | `exercise_id` + `id` في `tablet_action_eval_detail`؛ `exercise_id` في قوائم المعاضل |
| `flutter_app/test/eval_backup_assembler_test.dart` | اختبار إنتاجي بلا `exercise_id`/كتالوج مع عزل مستخدم/تمرين |
| `flutter_app/test/phase_c21_evaluation_excel_backup_test.dart` | Excel + صور sheet_cache_key + فيديو + بلا وسائط + عزل |
| `flutter_app/pubspec.yaml` | 2.7.39+53 |
| `flutter_app/lib/theme/device_layout.dart` | 2.7.39 / 53 |
| `BUILD_TABLET.bat` | بناء 2.7.39+53 |

لم يُغيَّر: مخطط SQLite، الواجهات، المزامنة، `pending_ops`، بيانات التقييم الأصلية.

---

## الاختبارات

كلها PASS:

- `eval_backup_assembler_test.dart` — بما فيه معاضلة بلا `exercise_id` وكتالوج، واستبعاد محكم/تمرين آخر
- `phase_c21_evaluation_excel_backup_test.dart` — Excel + صورة عبر `sheet_cache_key` + فيديو عبر `bundle_action_eval_id` + `local_media` + قائمة بلا وسائط + عزل + عدم تغيير الملف الأصلي
- `phase_c_scoped_backup_test.dart` — Restore وC.1 بما فيه 256 MB
- `phase_c2_backup_storage_search_test.dart`
- `phase_b_network_sync_test.dart`
- `local_recovery_parser_test.dart`

Dilemma without exercise_id / catalog: **PASS**  
sheet_cache_key images: **PASS**  
Videos: **PASS**  
List with no media (Excel only): **PASS**  
Cross-user / cross-exercise isolation: **PASS**  
Original media unchanged: **PASS**  
Technical restore regression: **PASS**

---

لا تثبيت على الجهاز الإنتاجي. لا مرحلة D.
