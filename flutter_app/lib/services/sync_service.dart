import 'dart:async';

import 'package:flutter/foundation.dart';

import 'api_client.dart';
import 'connectivity_service.dart';
import 'offline_store.dart';

/// Flushes queued offline writes (save results / approve) once the tablet
/// regains connectivity to the server.
class SyncService {
  SyncService._internal();
  static final SyncService instance = SyncService._internal();

  final ValueNotifier<int> pendingCount = ValueNotifier<int>(0);
  final ValueNotifier<bool> syncing = ValueNotifier<bool>(false);

  Timer? _retryTimer;
  bool _started = false;

  Future<void> start() async {
    if (_started) return;
    _started = true;
    await refreshPendingCount();
    ConnectivityService.instance.hasNetwork.addListener(_onConnectivityTick);
    _retryTimer = Timer.periodic(const Duration(seconds: 45), (_) => flush());
    if (ConnectivityService.instance.hasNetwork.value) {
      unawaited(flush());
    }
  }

  void dispose() {
    ConnectivityService.instance.hasNetwork.removeListener(_onConnectivityTick);
    _retryTimer?.cancel();
  }

  void _onConnectivityTick() {
    if (ConnectivityService.instance.hasNetwork.value) {
      unawaited(flush());
    }
  }

  Future<void> refreshPendingCount() async {
    pendingCount.value = await OfflineStore.instance.pendingOpsCount();
  }

  /// Try live send first; on any network failure queue locally for replay.
  /// Returns true if it was sent synchronously.
  Future<bool> enqueueOrSend({
    required String id,
    required String method,
    required String path,
    required Map<String, dynamic> body,
    required String kind,
  }) async {
    try {
      if (method == 'PUT') {
        await ApiClient.instance.put(path, body: body);
      } else {
        await ApiClient.instance.post(path, body: body);
      }
      return true;
    } on ApiOfflineException {
      // fall through to queue
    } on ApiException catch (e) {
      // 5xx / unreachable-style — queue. Auth errors should surface.
      if (e.status == 401 || e.status == 403) rethrow;
    } catch (_) {
      // fall through to queue
    }
    await OfflineStore.instance.enqueueOp(
      PendingOp(
        id: id,
        method: method,
        path: path,
        body: body,
        kind: kind,
        createdAt: DateTime.now().toIso8601String(),
      ),
    );
    await refreshPendingCount();
    return false;
  }

  Future<void> flush() async {
    if (syncing.value) return;
    syncing.value = true;
    try {
      final ops = await OfflineStore.instance.pendingOps();
      if (ops.isEmpty) return;
      final reachable = await ApiClient.instance.ping();
      if (!reachable) return;
      for (final op in ops) {
        try {
          if (op.method == 'PUT') {
            await ApiClient.instance.put(op.path, body: op.body);
          } else {
            await ApiClient.instance.post(op.path, body: op.body);
          }
          await OfflineStore.instance.removeOp(op.id);
        } on ApiOfflineException {
          break; // connection dropped mid-flush, retry later
        } catch (e) {
          await OfflineStore.instance.markOpFailed(op.id, e.toString());
        }
      }
      await refreshPendingCount();
    } finally {
      syncing.value = false;
    }
  }
}
