PHASE D — DEVICE MANAGER

Starting Version:
2.7.40+54

Final Version:
2.7.41+55

Version note:
Spec expected accepted baseline 2.7.36+50 then Phase D as 2.7.37+51. The repository already contained deferred C.2.1 work at 2.7.37–2.7.40. Those C.2.1 files were not reverted and were not extended. Phase D was versioned to the next safe pair: 2.7.41+55.

Current Exercise Isolation:
PASS

All Provisioned Users Accessible:
PASS

User Search:
PASS

Stable user_id:
PASS

Procedure Evaluation Lists:
PASS

Dilemma Evaluation Lists:
PASS

Procedure/Dilemma Isolation:
PASS

List View:
PASS

Results View:
PASS

Notes View:
PASS

Status View:
PASS

Media Association:
PASS

Image Download:
PASS

Video Download:
PASS

Large Video Streaming:
PASS

Excel Architecture Reused:
PASS

Excel Download:
PASS (online via existing server export of the original workbook). Offline local original workbook is not stored on the tablet; Device Manager does not fabricate a new Excel engine. Offline message: تنزيل Excel غير متوفر على الجهاز ويتطلب الاتصال بالسيرفر

Download List With Attachments:
PASS (Excel when online + locally available attachments). Separate from Phase C Backup.

Public Download Location:
Download/SmartArbitration/<اسم التمرين>/<اسم المحكم>/<اسم قائمة التقييم>/
Attachments: Download/SmartArbitration/<اسم التمرين>/<اسم المحكم>/<اسم قائمة التقييم>/المرفقات/

Approved List View:
PASS

Chief Judge Reopen Architecture Reused:
PASS

Authorized Reopen:
PASS (device_setup session AND can_chief_reopen_evaluation_for_judge: system_admin or chief_judge; calls apply_chief_reopen)

Unauthorized Reopen Blocked:
PASS (normal judge / planner / control / no device_setup / unauthenticated)

Offline Reopen Safe:
PASS (يتطلب إعادة فتح القائمة الاتصال بالسيرفر — no queued privileged reopen)

Normal Judge Permissions Unchanged:
PASS

Phase B Regression:
PASS

Phase C Regression:
PASS

C.2.1 Implemented:
NO

Database Schema Changed:
NO

Migration Created:
NO

New Dependency:
NO

Operational Data Preserved:
PASS

Automated Tests:
- flutter test test/phase_d_device_manager_test.dart: All tests passed (12 tests)
- flutter test test/phase_b_network_sync_test.dart: All tests passed
- flutter test test/phase_c_scoped_backup_test.dart: All tests passed (prior run)
- flutter test test/phase_c2_backup_storage_search_test.dart: All tests passed (prior run)
- flutter test test/phase_c21_evaluation_excel_backup_test.dart: All tests passed (existing deferred C.2.1 tests unchanged)
- .venv python -m unittest tests.test_tablet_device_eval_manager: 8 tests OK
- .venv python -m unittest tests.test_tablet_reconnect: 6 tests OK

APK:
dist/judge-tablet-v2.7.41.apk
applicationId: ae.lf.training.lf_training_evaluation
SQLite schema: 4
PWA: dist/tablet_pwa

APK Installed:
NO

Production Tablet Accessed:
NO

Physical Test Required:
YES

Files Modified:
- BUILD_TABLET.bat
- app/tablet_api.py
- flutter_app/pubspec.yaml
- flutter_app/lib/app.dart
- flutter_app/lib/theme/device_layout.dart
- flutter_app/lib/screens/device_admin_hub_screen.dart
- flutter_app/android/app/src/main/kotlin/ae/lf/training/lf_training_evaluation/MainActivity.kt

New Files:
- flutter_app/lib/services/device_eval_manager_models.dart
- flutter_app/lib/services/device_eval_manager_paths.dart
- flutter_app/lib/services/device_eval_manager_service.dart
- flutter_app/lib/screens/device_eval_manager_screen.dart
- flutter_app/lib/screens/device_eval_inspect_screen.dart
- flutter_app/test/phase_d_device_manager_test.dart
- tests/test_tablet_device_eval_manager.py
- PHASE_D_DEVICE_MANAGER_REPORT.md

Architecture trace (before implementation):
A. Device Manager: existing DeviceAdminHubScreen + DeviceAdminService local admin. New card «إدارة قوائم التقييم» only from this hub. Admin router allowlist extended for /device-eval-manager and /device-eval-inspect.
B. Users: OfflineStore.local_users via ScopedBackupService.provisionedUsersSafe(). Identity is user_id.
C. Procedure lists: cache keys u{userId}:evaluation_lists:: and evaluation_list_detail:{unit}:{itemId}.
D. Dilemma lists: cache keys u{userId}:action_eval_lists: and action_eval_detail:{slot}.
E. Excel: tablet does not store the original military workbook. Reused existing server export _send_evaluation_list_export_xlsx / _send_eval_xlsx_file over device_setup session. Streamed with downloadToFile (.part then rename).
F. Media: media_files user_id + exercise_id + evaluation_list_item_id / bundle_action_eval_id. Copy via streamCopyFile; public copy copyExportToPublicDownloads under SmartArbitration/ (not SmartArbitration_Backups/).
G. Reopen: POST /api/tablet/device/eval/chief-reopen reuses can_chief_reopen_evaluation_for_judge + eval_chief_can_reopen + apply_chief_reopen + notify_evaluation_reopened_by_chief_judge.
H. Phase B: HealthService / SyncService / ApiClient.withDeviceAuth reused. No second network monitor.

STOP. Waiting for review and physical testing of Phase D.
Do not start Phase E, Phase F, or Phase C.2.1.
