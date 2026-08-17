import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'auth_service.dart';
import 'offline_store.dart';

const String kDeviceAdminUserPref = 'device_admin_username';
const String kDeviceAdminHashPref = 'device_admin_password_hash';
const String kDeviceReadyMeta = 'device_ready';
const String kDeviceLastPackageAt = 'last_package_at';
const String kDefaultDeviceAdminUser = 'device_admin';
const String kDefaultDeviceAdminPass = 'Admin@Device1';

/// مدير الجهاز المحلي — صلاحيات تقنية فقط (ليس محكماً).
class DeviceAdminService extends ChangeNotifier {
  DeviceAdminService._();
  static final DeviceAdminService instance = DeviceAdminService._();

  bool _ready = false;
  bool _isLocalAdminSession = false;
  String? _lastError;

  bool get isDeviceReady => _ready;
  bool get isLocalAdminSession => _isLocalAdminSession;
  String? get lastError => _lastError;

  Future<void> init() async {
    await ensureDefaultAdmin();
    final v = await OfflineStore.instance.getDeviceMeta(kDeviceReadyMeta);
    _ready = v == '1';
    notifyListeners();
  }

  Future<void> ensureDefaultAdmin() async {
    final prefs = await SharedPreferences.getInstance();
    if ((prefs.getString(kDeviceAdminHashPref) ?? '').isNotEmpty) return;
    final hash = await credentialDigest(
      kDefaultDeviceAdminUser,
      kDefaultDeviceAdminPass,
    );
    await prefs.setString(kDeviceAdminUserPref, kDefaultDeviceAdminUser);
    await prefs.setString(kDeviceAdminHashPref, hash);
  }

  Future<bool> login(String username, String password) async {
    _lastError = null;
    final prefs = await SharedPreferences.getInstance();
    final storedUser =
        (prefs.getString(kDeviceAdminUserPref) ?? kDefaultDeviceAdminUser)
            .trim()
            .toLowerCase();
    final storedHash = prefs.getString(kDeviceAdminHashPref) ?? '';
    if (username.trim().toLowerCase() != storedUser) {
      _lastError = 'بيانات مدير الجهاز غير صحيحة';
      return false;
    }
    final hash = await credentialDigest(username, password);
    if (hash != storedHash) {
      _lastError = 'بيانات مدير الجهاز غير صحيحة';
      return false;
    }
    _isLocalAdminSession = true;
    notifyListeners();
    return true;
  }

  Future<void> logout() async {
    _isLocalAdminSession = false;
    notifyListeners();
  }

  Future<void> markDeviceReady() async {
    await OfflineStore.instance.setDeviceMeta(kDeviceReadyMeta, '1');
    await OfflineStore.instance.setDeviceMeta(
      kDeviceLastPackageAt,
      DateTime.now().toIso8601String(),
    );
    _ready = true;
    notifyListeners();
  }

  Future<void> clearDeviceReady() async {
    await OfflineStore.instance.setDeviceMeta(kDeviceReadyMeta, '0');
    _ready = false;
    notifyListeners();
  }

  Future<String?> lastPackageAt() =>
      OfflineStore.instance.getDeviceMeta(kDeviceLastPackageAt);

  Future<bool> changePassword(String oldPass, String newPass) async {
    final prefs = await SharedPreferences.getInstance();
    final user = prefs.getString(kDeviceAdminUserPref) ?? kDefaultDeviceAdminUser;
    final ok = await login(user, oldPass);
    if (!ok) return false;
    final hash = await credentialDigest(user, newPass);
    await prefs.setString(kDeviceAdminHashPref, hash);
    return true;
  }
}
