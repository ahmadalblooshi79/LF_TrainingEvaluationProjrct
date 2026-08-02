import 'dart:async';

import 'package:flutter/foundation.dart';

import 'api_client.dart';
import 'connectivity_service.dart';

/// فحص وصول حقيقي للسيرفر — لا يعتمد على وجود Wi‑Fi وحده.
class HealthService {
  HealthService._internal();
  static final HealthService instance = HealthService._internal();

  final ValueNotifier<bool> serverReachable = ValueNotifier<bool>(false);
  final ValueNotifier<DateTime?> lastCheckedAt = ValueNotifier<DateTime?>(null);

  Timer? _timer;
  bool _started = false;
  bool _checking = false;

  Future<void> start() async {
    if (_started) return;
    _started = true;
    ConnectivityService.instance.hasNetwork.addListener(_onNetChanged);
    await check(force: true);
    _timer = Timer.periodic(const Duration(seconds: 12), (_) => check());
  }

  void dispose() {
    ConnectivityService.instance.hasNetwork.removeListener(_onNetChanged);
    _timer?.cancel();
  }

  void _onNetChanged() {
    if (!ConnectivityService.instance.hasNetwork.value) {
      serverReachable.value = false;
      ApiClient.instance.online.value = false;
      return;
    }
    unawaited(check(force: true));
  }

  /// مهلة قصيرة: إن لم يرد السيرفر ننتقل فوراً لوضع Offline.
  Future<bool> check({bool force = false}) async {
    if (_checking && !force) return serverReachable.value;
    _checking = true;
    try {
      if (!ConnectivityService.instance.hasNetwork.value) {
        serverReachable.value = false;
        ApiClient.instance.online.value = false;
        lastCheckedAt.value = DateTime.now();
        return false;
      }
      final ok = await ApiClient.instance.ping(timeout: const Duration(seconds: 3));
      serverReachable.value = ok;
      ApiClient.instance.online.value = ok;
      lastCheckedAt.value = DateTime.now();
      return ok;
    } finally {
      _checking = false;
    }
  }
}
