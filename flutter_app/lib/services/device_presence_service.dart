import 'dart:async';
import 'dart:math';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api_client.dart';
import 'auth_service.dart';
import 'health_service.dart';
import 'sync_service.dart';

const String kDeviceIdPrefKey = 'lf_device_id';
const String kDeviceNamePrefKey = 'lf_device_name';

/// تسجيل الجهاز ونبضات النشاط لصفحة «إدارة الخادم».
class DevicePresenceService {
  DevicePresenceService._();
  static final DevicePresenceService instance = DevicePresenceService._();

  Timer? _timer;
  bool _started = false;
  String _deviceId = '';
  String _deviceName = '';

  String get deviceId => _deviceId;
  String get deviceName => _deviceName;

  Future<void> init() async {
    final prefs = await SharedPreferences.getInstance();
    var id = (prefs.getString(kDeviceIdPrefKey) ?? '').trim();
    if (id.isEmpty) {
      final rnd = Random.secure().nextInt(0xFFFFFF).toRadixString(16).padLeft(6, '0');
      id = 'tablet-${DateTime.now().millisecondsSinceEpoch.toRadixString(16)}-$rnd';
      await prefs.setString(kDeviceIdPrefKey, id);
    }
    _deviceId = id;

    var name = (prefs.getString(kDeviceNamePrefKey) ?? '').trim();
    if (name.isEmpty) {
      name = kIsWeb ? 'تابلت PWA' : 'تابلت محكم';
      await prefs.setString(kDeviceNamePrefKey, name);
    }
    _deviceName = name;
  }

  Future<void> start() async {
    if (_started) return;
    _started = true;
    await init();
    HealthService.instance.serverReachable.addListener(_onReachable);
    AuthService.instance.addListener(_onAuthChanged);
    _timer = Timer.periodic(const Duration(seconds: 25), (_) {
      unawaited(heartbeat());
    });
    if (AuthService.instance.isLoggedIn) {
      unawaited(register(isLogin: false));
    }
  }

  void stop() {
    _timer?.cancel();
    _timer = null;
    HealthService.instance.serverReachable.removeListener(_onReachable);
    AuthService.instance.removeListener(_onAuthChanged);
    _started = false;
  }

  void _onReachable() {
    if (HealthService.instance.serverReachable.value &&
        AuthService.instance.isLoggedIn) {
      unawaited(heartbeat());
    }
  }

  void _onAuthChanged() {
    if (AuthService.instance.isLoggedIn) {
      unawaited(register(isLogin: true));
    }
  }

  Future<void> register({bool isLogin = false}) async {
    await init();
    if (!AuthService.instance.isLoggedIn) return;
    if (!ApiClient.instance.isConfigured) return;
    if (!HealthService.instance.serverReachable.value) {
      // محاولة سريعة — قد يكون السيرفر متاحاً قبل تحديث الـ notifier
      final ok = await HealthService.instance.check();
      if (!ok) return;
    }
    try {
      final pending = SyncService.instance.pendingCount.value;
      await ApiClient.instance.post(
        '/api/device/register',
        body: {
          'device_id': _deviceId,
          'device_name': _deviceName,
          'is_login': isLogin,
          'sync_status': pending > 0 ? 'pending' : 'idle',
          'pending_sync_count': pending,
        },
        timeout: const Duration(seconds: 8),
      );
    } catch (_) {
      // لا نمنع عمل التطبيق إذا فشل التسجيل
    }
  }

  Future<void> heartbeat() async {
    await init();
    if (!AuthService.instance.isLoggedIn) return;
    if (!ApiClient.instance.isConfigured) return;
    if (!HealthService.instance.serverReachable.value) return;
    try {
      final pending = SyncService.instance.pendingCount.value;
      await ApiClient.instance.post(
        '/api/device/heartbeat',
        body: {
          'device_id': _deviceId,
          'device_name': _deviceName,
          'sync_status': SyncService.instance.syncing.value
              ? 'syncing'
              : (pending > 0 ? 'pending' : 'idle'),
          'pending_sync_count': pending,
        },
        timeout: const Duration(seconds: 6),
      );
    } catch (_) {}
  }
}
