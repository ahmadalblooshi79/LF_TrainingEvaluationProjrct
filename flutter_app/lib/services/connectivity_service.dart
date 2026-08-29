import 'dart:async';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter/foundation.dart';

/// Tracks whether the device currently has *some* network interface up.
/// This is a hint only — actual reachability of the LAN server is confirmed
/// by [ApiClient] request outcomes (see [ApiClient.online]).
class ConnectivityService {
  ConnectivityService._internal();
  static final ConnectivityService instance = ConnectivityService._internal();

  final ValueNotifier<bool> hasNetwork = ValueNotifier<bool>(true);

  /// Wi‑Fi أو Ethernet — شبكة محلية LAN (لا يشمل بيانات الجوال).
  final ValueNotifier<bool> isLocalNetwork = ValueNotifier<bool>(false);

  StreamSubscription<List<ConnectivityResult>>? _sub;

  static bool _isLocalNetwork(List<ConnectivityResult> results) {
    if (results.contains(ConnectivityResult.none)) return false;
    return results.contains(ConnectivityResult.wifi) ||
        results.contains(ConnectivityResult.ethernet);
  }

  void _applyResults(List<ConnectivityResult> results) {
    hasNetwork.value = !results.contains(ConnectivityResult.none);
    isLocalNetwork.value = _isLocalNetwork(results);
  }

  Future<void> init() async {
    try {
      final result = await Connectivity().checkConnectivity();
      _applyResults(result);
    } catch (_) {
      hasNetwork.value = true;
      isLocalNetwork.value = !kIsWeb;
    }
    _sub = Connectivity().onConnectivityChanged.listen(_applyResults);
  }

  void dispose() {
    _sub?.cancel();
  }
}
