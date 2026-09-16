import 'dart:async';

import 'package:flutter/widgets.dart';

import 'api_client.dart';
import 'connectivity_service.dart';

/// فحص وصول حقيقي للسيرفر — لا يعتمد على وجود Wi‑Fi/Ethernet وحده.
class HealthService with WidgetsBindingObserver {
  HealthService._internal();
  static final HealthService instance = HealthService._internal();

  final ValueNotifier<bool> serverReachable = ValueNotifier<bool>(false);
  final ValueNotifier<DateTime?> lastCheckedAt = ValueNotifier<DateTime?>(null);

  Timer? _timer;
  bool _started = false;
  Completer<bool>? _inFlight;

  Future<void> start() async {
    if (_started) return;
    _started = true;
    WidgetsBinding.instance.addObserver(this);
    ConnectivityService.instance.hasNetwork.addListener(_onNetChanged);
    ConnectivityService.instance.isLocalNetwork.addListener(_onNetChanged);
    await check(force: true);
    _timer = Timer.periodic(const Duration(seconds: 12), (_) => check());
  }

  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    ConnectivityService.instance.hasNetwork.removeListener(_onNetChanged);
    ConnectivityService.instance.isLocalNetwork.removeListener(_onNetChanged);
    _timer?.cancel();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      unawaited(check(force: true));
    }
  }

  void _onNetChanged() {
    unawaited(check(force: true));
  }

  /// مهلة كافية لشبكة LAN؛ لا نمنع الفحص بسبب hasNetwork فقط.
  Future<bool> check({bool force = false}) async {
    if (_inFlight != null) {
      if (!force) return _inFlight!.future;
      return _inFlight!.future;
    }
    final pending = Completer<bool>();
    _inFlight = pending;
    try {
      if (!ApiClient.instance.isConfigured) {
        serverReachable.value = false;
        ApiClient.instance.online.value = false;
        lastCheckedAt.value = DateTime.now();
        pending.complete(false);
        return false;
      }
      final ok = await ApiClient.instance.ping(
        timeout: const Duration(seconds: 8),
      );
      serverReachable.value = ok;
      ApiClient.instance.online.value = ok;
      lastCheckedAt.value = DateTime.now();
      pending.complete(ok);
      return ok;
    } catch (_) {
      serverReachable.value = false;
      ApiClient.instance.online.value = false;
      lastCheckedAt.value = DateTime.now();
      pending.complete(false);
      return false;
    } finally {
      _inFlight = null;
    }
  }

  /// فحوصات وصول حقيقية قبل المزامنة: فوري ثم 2ث ثم 3ث ثم 5ث.
  Future<bool> ensureReachableForSync() async {
    const waits = <Duration>[
      Duration.zero,
      Duration(seconds: 2),
      Duration(seconds: 3),
      Duration(seconds: 5),
    ];
    for (final wait in waits) {
      if (wait > Duration.zero) {
        await Future<void>.delayed(wait);
      }
      final ok = await check(force: true);
      if (ok) return true;
    }
    serverReachable.value = false;
    ApiClient.instance.online.value = false;
    return false;
  }
}
