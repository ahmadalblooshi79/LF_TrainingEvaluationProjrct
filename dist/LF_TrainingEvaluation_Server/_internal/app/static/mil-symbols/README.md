# رموز PNG لتنظيم المعركة

1. انسخ ملفات الصور **PNG** إلى هذا المجلد (`app/static/mil-symbols/`) بنفس الأسماء المشار إليها في `manifest.json`، أو عدّل `manifest.json` ليربط مفاتيح `echelon:branch` بأسماء ملفاتك.
2. يمكن لأي عقدة في شجرة البيانات استخدام حقل اختياري `"image": "MyFile.png"` لتجاوز الربط التلقائي.
3. إذا لم يُعثر على الملف، تعرض الصفحة الرمز الاحتياطي (SVG) بدل الصورة.

## أسماء ملفات مقترحة (مطابقة للصور المرفقة سابقاً)

| الملف |
|------|
| `Mechanized_Infantry_Brigade.png` |
| `Mechanized_Infantry_Battalion.png` |
| `Mechanized_Infantry_Company.png` |
| `Mechanized_Infantry_Platoon.png` |
| `Mechanized_Infantry_Squad.png` |
| `Armor_Battalion.png` |
| `Armor_Company.png` |
| `Armor_Platoon.png` |
| `Armor_Squad.png` |

بعد إضافة الملفات أعد تحميل الصفحة؛ لا حاجة لإعادة تشغيل الخادم لتعديل `manifest.json` (يُقرأ في كل طلب).
