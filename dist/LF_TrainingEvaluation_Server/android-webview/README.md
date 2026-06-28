# تطبيق Android WebView — نظام إدارة التمارين

تطبيق **حاوية WebView** يعرض نفس نظام الويب (Flask) على الكمبيوتر عبر شبكة Wi‑Fi المحلية.  
لا يوجد قاعدة بيانات داخل التطبيق — كل البيانات على السيرفر.

## محتويات المجلد

| المسار | الوصف |
|--------|--------|
| `app/` | كود Android (Kotlin + WebView) |
| `server.defaults.properties` | القيم الافتراضية لـ IP والمنفذ (قبل البناء) |
| `app/src/main/assets/default_server.properties` | نفس القيم داخل APK |
| `build-debug-apk.bat` | بناء APK تجريبي |
| `app/build/outputs/apk/debug/app-debug.apk` | ملف التثبيت بعد البناء |

## 1) تشغيل Flask على الكمبيوتر

من جذر المشروع:

```bat
run-tablet.bat
```

أو يدوياً:

```bat
set PORT=4000
set HOST=0.0.0.0
set LF_OPEN_BROWSER=0
.venv\Scripts\python.exe run.py
```

- `HOST=0.0.0.0` يسمح بالوصول من التابلت على نفس الشبكة.
- المنفذ الافتراضي في `run-tablet.bat` هو **4000** (يمكن تغييره).

عند التشغيل تظهر في الطرفية عناوين LAN، مثل:

```text
http://192.168.1.100:4000/
```

## 2) معرفة IP الكمبيوتر

في PowerShell أو CMD:

```bat
ipconfig
```

ابحث عن **IPv4 Address** لمحول **Wi‑Fi** (مثل `192.168.1.100`).

## 3) ربط التابلت بنفس Wi‑Fi

1. على Samsung Tablet: **الإعدادات → الاتصالات → Wi‑Fi**.
2. اختر **نفس شبكة** الكمبيوتر.
3. تأكد أن الكمبيوتر ليس على VPN يعزل الشبكة المحلية.

## 4) اختبار الاتصال (متصفح التابلت أولاً)

قبل فتح APK، افتح Chrome/Samsung Internet على التابلت:

```text
http://SERVER_IP:4000
```

مثال: `http://192.168.1.100:4000`

إذا ظهرت صفحة تسجيل الدخول، الاتصال سليم.

### جدار الحماية (Windows)

إذا لم يفتح من التابلت، اسمح لـ Python عبر جدار Windows للشبكة الخاصة (Private).

## 5) بناء APK

### المتطلبات

- [Android Studio](https://developer.android.com/studio) (يُثبّت Android SDK و JDK)
- أو JDK 17 + Android SDK مع `ANDROID_HOME`

### البناء السريع

```bat
cd android-webview
powershell -ExecutionPolicy Bypass -File scripts\fetch-gradle-wrapper.ps1
build-debug-apk.bat
```

أو من Android Studio: **File → Open → android-webview** ثم **Build → Build APK(s)**.

### تعديل IP الافتراضي قبل البناء

عدّل:

- `server.defaults.properties`
- `app/src/main/assets/default_server.properties`

```properties
server.host=192.168.1.100
server.port=4000
```

## 6) تثبيت APK على Samsung Tablet

1. انسخ `app-debug.apk` إلى التابلت (USB / Google Drive / البريد).
2. على التابلت: **الإعدادات → الأمان → تثبيت تطبيقات غير معروفة** (اسمح للملفات/Chrome).
3. افتح ملف APK وثبّت **نظام إدارة التمارين**.

أو عبر USB مع تفعيل **USB debugging**:

```bat
adb install -r app\build\outputs\apk\debug\app-debug.apk
```

## 7) إعداد عنوان السيرفر داخل التطبيق

بعد التثبيت:

1. افتح التطبيق.
2. من شريط الأدوات: **إعدادات السيرفر** (أيقونة الترس).
3. أدخل IP الكمبيوتر والمنفذ (مثل `192.168.1.100` و `4000`).
4. **اختبار الاتصال** ثم **حفظ وفتح النظام**.

## 8) خطوات الاختبار الكاملة

1. شغّل `run-tablet.bat` على الكمبيوتر.
2. `ipconfig` → خذ IPv4.
3. التابلت والكمبيوتر على نفس Wi‑Fi.
4. متصفح التابلت: `http://IP:4000`.
5. افتح APK — يجب أن يظهر نفس التصميم.
6. سجّل الدخول.
7. أدخل تقييماً أو عدّل بياناً من التابلت.
8. تحقق على الكمبيوتر أن البيانات ظهرت في النظام.

## ميزات WebView

- JavaScript، Local Storage، Session Cookies
- رفع وتحميل الملفات
- دعم RTL العربية
- سحب للتحديث (Pull to refresh)
- شاشة ترحيب (Splash)
- صفحة إعدادات IP/Port

## ملاحظات

- التطبيق يتصل **فقط** بسيرفر Flask المحلي — لا مزامنة Offline.
- تصميم الويب لم يُغيّر؛ أُضيف `tablet.css` فقط لتحسين اللمس والتمرير على التابلت.
- إذا غيّرت منفذ السيرفر، حدّثه في إعدادات التطبيق أيضاً.
