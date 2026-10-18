# إصلاح ظهور ملفات Backup في Windows عبر USB/MTP

**Version:** 2.7.40+54  
**Date:** 2026-10-17  
**APK:** `dist/judge-tablet-v2.7.40.apk`  
**APK Installed:** NO  
**Production Tablet Accessed:** NO

---

## السبب الجذري (بالأدلة)

Excel يُفتح على التابلت من الحزمة **الخاصة** `app_documents/scoped_backups/` التي يكتبها `writeBackupPackage`. هذا المسار لا يمر بـ MediaStore ولا بـ MTP.

النسخة التي يراها ويندوز هي النسخة العامة عبر `copyBackupToPublicDownloads` في `MainActivity.kt`. قبل الإصلاح كانت تُدرج كل الملفات في:

`MediaStore.Downloads.EXTERNAL_CONTENT_URI`

مع MIME حقيقي (`image/jpeg`, `video/mp4`, `application/vnd...xlsx`).

الأدلة في الكود السابق:

1. الإدراج في مجموعة Downloads وليس `MediaStore.Files`. ويندوز/MTP يعدد عادة ملفات التخزين الأساسي (`/storage/emulated/0/Download/...`) عبر Documents provider، بينما مجموعة Downloads افتراضية وقد لا تُظهر الشجرة المتداخلة.
2. الصور/الفيديو بـ MIME وسائط تُفهرس في Images/Video فتظهر في المعرض أو لا تظهر داخل مجلد Backup.
3. `IS_PENDING=0` كان يُستدعى دون التحقق من عدد الصفوف المحدَّثة. إن فشل التحديث تبقى الملفات معلّقة وغير مرئية لـ MTP وFile Manager.
4. لم يُضبط `SIZE` / `DATE_MODIFIED` بعد الكتابة. بعض طبقات MTP تتجاهل ملفاً بحجم 0 أو غير ممسوح.
5. لم يُستدعَ `MediaScannerConnection.scanFile`. فهرس MTP لا يتحدّث إلا بعد إعادة توصيل/إعادة تشغيل.
6. `OutputStream` كان يُغلق عبر `.use` ويُعمل `flush` — هذا الجزء كان صحيحاً.

لذلك نجاح الفتح على التابلت لا يثبت ظهور الملفات في مستكشف ويندوز.

---

## التعديل المحدود

فقط مسار التصدير العام. بلا تغيير واجهة، مخطط، مزامنة، أو الملفات الأصلية.

| ملف | التغيير |
|---|---|
| `MainActivity.kt` | إدراج عبر `MediaStore.Files` + `RELATIVE_PATH` تحت `Download/`؛ `IS_PENDING` 1 ثم 0 مع التحقق؛ `SIZE`/`DATE_MODIFIED`؛ إغلاق التيار بـ `use`+`flush`؛ `MediaScannerConnection.scanFile`؛ سجل `LFBackupExport` بعدد الملفات والحجم |
| `scoped_backup_service.dart` | رفض التصدير إن `fileCount <= 0`؛ `debugPrint` للعدد والحجم |
| اختبارات C.2 | عقد MediaStore/Files/pending/scanner + نسخة `test.xlsx` / `test.jpg` / مجلد فرعي |

---

## الاختبارات

PASS محلياً:

- `phase_c2_backup_storage_search_test.dart` — عقد MTP + `test.xlsx`/`test.jpg` تحت `مجلد_فرعي` تُقرأ بعد النسخ
- `phase_c21_evaluation_excel_backup_test.dart`
- `phase_c_scoped_backup_test.dart` بما فيه 256 MB

التحقق عبر USB/Windows Explorer **مطلوب على جهاز تطوير** بعد تثبيت 2.7.40 (غير الجهاز الإنتاجي):

1. إنشاء Backup.
2. فصل التابلت ثم إعادة توصيله (أو انتظر المسح).
3. فتح `Download/SmartArbitration_Backups/<التمرين>/<المحكم>/Backup_.../`
4. التأكد أن `test.xlsx`/`*.xlsx` و`test.jpg`/الصور تُفتح من ويندوز.

Physical USB test: **REQUIRED / NOT PERFORMED HERE**

---

لا تثبيت على الجهاز الإنتاجي. لا حذف/نقل للنسخ الأصلية الخاصة.
