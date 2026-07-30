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
  StreamSubscription<List<ConnectivityResult>>? _sub;

  Future<void> init() async {
    try {
      final result = await Connectivity().checkConnectivity();
      hasNetwork.value = !result.contains(ConnectivityResult.none);
    } catch (_) {
      hasNetwork.value = true;
    }
    _sub = Connectivity().onConnectivityChanged.listen((results) {
      hasNetwork.value = !results.contains(ConnectivityResult.none);
    });
  }

  void dispose() {
    _sub?.cancel();
  }
}
