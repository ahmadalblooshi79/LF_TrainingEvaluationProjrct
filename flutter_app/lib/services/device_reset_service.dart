import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api_client.dart';
import 'auth_service.dart';
import 'device_admin_service.dart';
import 'offline_store.dart';
import 'sync_service.dart';

class DeviceResetPreview {
  final int pendingOps;
  final int localUsers;
  final bool hasUnsyncedWork;

  const DeviceResetPreview({
    required this.pendingOps,
    required this.localUsers,
    required this.hasUnsyncedWork,
  });
}

class DeviceResetResult {
  final bool ok;
  final String message;

  const DeviceResetResult({required this.ok, required this.message});
}

/// إعادة ضبط محلية فقط — لا تحذف بيانات السيرفر ولا ملفات Downloads العامة.
class DeviceResetService {
  DeviceResetService._();
  static final DeviceResetService instance = DeviceResetService._();

  bool _running = false;
  bool get isRunning => _running;

  Future<DeviceResetPreview> preview() async {
    await OfflineStore.instance.init();
    final pending = await OfflineStore.instance.pendingOpsCount();
    final users = await OfflineStore.instance.allLocalUsers();
    return DeviceResetPreview(
      pendingOps: pending,
      localUsers: users.length,
      hasUnsyncedWork: pending > 0,
    );
  }

  Future<DeviceResetResult> resetLocalDevice() async {
    if (_running) {
      return const DeviceResetResult(
        ok: false,
        message: 'إعادة الضبط قيد التنفيذ',
      );
    }
    _running = true;
    SyncService.instance.beginRestoreHold();
    try {
      await OfflineStore.instance.init();
      await _deleteAppOwnedMediaTree();
      await OfflineStore.instance.clearAll();
      await DeviceAdminService.instance.clearDeviceReady();
      await DeviceAdminService.instance.logout();
      await DeviceAdminService.instance.ensureDefaultAdmin();
      await _clearLocalSessionPrefs();
      try {
        await ApiClient.instance.clearCookies();
        await ApiClient.instance.clearCookies(device: true);
      } catch (_) {}
      AuthService.instance.forgetLocalSession();
      await SyncService.instance.refreshPendingCount();
      final leftover = await OfflineStore.instance.pendingOpsCount();
      final leftoverUsers = (await OfflineStore.instance.allLocalUsers()).length;
      if (leftover > 0 || leftoverUsers > 0) {
        return const DeviceResetResult(
          ok: false,
          message: 'تعذر إكمال إعادة ضبط بيانات الجهاز',
        );
      }
      return const DeviceResetResult(
        ok: true,
        message: 'تم إعادة ضبط بيانات الجهاز',
      );
    } catch (_) {
      return const DeviceResetResult(
        ok: false,
        message: 'تعذر إكمال إعادة ضبط بيانات الجهاز',
      );
    } finally {
      SyncService.instance.endRestoreHold();
      _running = false;
    }
  }

  Future<void> _deleteAppOwnedMediaTree() async {
    if (kIsWeb) return;
    try {
      final root = await OfflineStore.instance.mediaRoot();
      if (await root.exists()) {
        await root.delete(recursive: true);
      }
    } catch (_) {}
  }

  Future<void> _clearLocalSessionPrefs() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(kWasLoggedInPrefKey, false);
    await prefs.remove(kLastSyncAtPrefKey);
    for (final k in prefs.getKeys().toList()) {
      if (k.startsWith('reconnect_ticket_u')) {
        await prefs.remove(k);
      }
    }
  }
}
