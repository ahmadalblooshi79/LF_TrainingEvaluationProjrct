# LF Judge Tablet — Build APK

Requires Android SDK (API 34) and JDK 17.

## Quick build (Windows)

```bat
BUILD_JUDGE_APK.bat
```

Output: `android\judge-tablet\app\build\outputs\apk\release\app-release-unsigned.apk`

Copy/rename to: `dist\LF_Judge_Tablet.apk`

## Manual

```bat
cd android\judge-tablet
gradlew.bat assembleRelease
```

## Install guide

See `docs/JUDGE_TABLET_INSTALL.md`
