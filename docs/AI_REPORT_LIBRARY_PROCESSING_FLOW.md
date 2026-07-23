# تدفق المعالجة

1. رفع + checksum + حفظ الأصل تحت `originals/<uuid>/`
2. parse DOCX أو PDF
3. تنظيف النص وحفظ extracted
4. اكتشاف الأقسام والجداول والوحدات
5. استخراج النقاط وربط الوحدات
6. سجل خطوات في `ai_report_processing_logs`
7. اختيارياً: مساعدة Qwen للأقسام unknown
8. حالة `ready` أو `needs_review` أو `failed`
