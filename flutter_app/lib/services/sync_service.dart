import 'dart:async';

import 'package:flutter/foundation.dart';

import 'api_client.dart';
import 'auth_service.dart';
import 'connectivity_service.dart';
import 'health_service.dart';
import 'media_upload_service.dart';
import 'notifications_badge_service.dart';
import 'offline_store.dart';
import 'package_sync_service.dart';
import 'sync_preferences.dart';

/// حالة مؤشر المزامنة الظاهر في الواجهة.
enum SyncUiState {
  online,
  offline,
  pending,
  syncing,
  synced,
  failed,
}

/// محرك المزامنة: طابور دائم + إرسال مرتب + Idempotency عبر client_op_id.
class SyncService {
  SyncService._internal();
  static final SyncService instance = SyncService._internal();

  /// يُعيَّن من [TabletRepository] بعد الاعتماد المتزامن.
  static Future<void> Function(PendingOp op)? onApproveSyncedHandler;

  final ValueNotifier<int> pendingCount = ValueNotifier<int>(0);
  final ValueNotifier<bool> syncing = ValueNotifier<bool>(false);
  final ValueNotifier<SyncUiState> uiState = ValueNotifier<SyncUiState>(SyncUiState.offline);
  final ValueNotifier<String?> lastError = ValueNotifier<String?>(null);
  final ValueNotifier<DateTime?> lastSuccessAt = ValueNotifier<DateTime?>(null);

  Timer? _retryTimer;
  bool _started = false;
  bool _wasReachable = false;
  bool _wasLocalNetwork = false;
  bool _autoFullSyncRunning = false;
  DateTime? _lastAutoFullSyncAt;
  static const _autoFullSyncCooldown = Duration(minutes: 3);

  Future<void> start() async {
    if (_started) return;
    _started = true;
    await SyncPreferences.instance.init();
    await HealthService.instance.start();
    await refreshPendingCount();
    final saved = await AuthService.loadLastSyncAt();
    if (saved != null) lastSuccessAt.value = saved;
    _wasLocalNetwork = ConnectivityService.instance.isLocalNetwork.value;
    _updateUiState();
    HealthService.instance.serverReachable.addListener(_onConnectivityChanged);
    ConnectivityService.instance.isLocalNetwork
        .addListener(_onConnectivityChanged);
    _retryTimer = Timer.periodic(const Duration(seconds: 20), (_) {
      unawaited(HealthService.instance.check());
      unawaited(refreshPendingCount());
      if (_shouldAutoUpload() &&
          HealthService.instance.serverReachable.value &&
          pendingCount.value > 0 &&
          !syncing.value) {
        unawaited(flush());
      }
    });
    if (_shouldAutoUpload() &&
        HealthService.instance.serverReachable.value &&
        pendingCount.value > 0) {
      unawaited(flush());
    }
    unawaited(_maybeAutoFullSync(force: false));
  }

  void dispose() {
    HealthService.instance.serverReachable.removeListener(_onConnectivityChanged);
    ConnectivityService.instance.isLocalNetwork
        .removeListener(_onConnectivityChanged);
    _retryTimer?.cancel();
  }

  bool _shouldAutoUpload() => SyncPreferences.instance.isAutomatic;

  void _onConnectivityChanged() {
    final online = HealthService.instance.serverReachable.value;
    final local = ConnectivityService.instance.isLocalNetwork.value;
    _updateUiState();

    if (_shouldAutoUpload()) {
      if (online && !_wasReachable && pendingCount.value > 0 && !syncing.value) {
        unawaited(flush());
      }
      if (local && online && AuthService.instance.isLoggedIn) {
        final justJoined =
            (!_wasLocalNetwork && local) || (!_wasReachable && online);
        if (justJoined) {
          unawaited(_maybeAutoFullSync(force: false));
        }
      }
    }

    _wasReachable = online;
    _wasLocalNetwork = local;
  }

  Future<void> _maybeAutoFullSync({required bool force}) async {
    if (!_shouldAutoUpload()) return;
    if (!AuthService.instance.isLoggedIn) return;
    if (!ConnectivityService.instance.isLocalNetwork.value) return;
    if (!HealthService.instance.serverReachable.value) return;
    if (!ApiClient.instance.isConfigured) return;
    if (_autoFullSyncRunning || syncing.value) return;
    if (!force && _lastAutoFullSyncAt != null) {
      final elapsed = DateTime.now().difference(_lastAutoFullSyncAt!);
      if (elapsed < _autoFullSyncCooldown) return;
    }

    _autoFullSyncRunning = true;
    try {
      final result = await runFullSync(silent: true);
      if (result.ok) {
        _lastAutoFullSyncAt = DateTime.now();
      }
    } finally {
      _autoFullSyncRunning = false;
    }
  }

  /// مزامنة كاملة: رفع المعلّق ثم تنزيل «تحديث بياناتي».
  Future<({bool ok, String? message})> runFullSync({bool silent = false}) async {
    await HealthService.instance.check(force: true);
    if (!HealthService.instance.serverReachable.value) {
      return (ok: false, message: 'السيرفر غير متاح — تحقق من الشبكة وعنوان الخادم');
    }

    await flush();
    final upErr = lastError.value;

    syncing.value = true;
    _updateUiState();
    var downOk = false;
    try {
      downOk = await PackageSyncService.instance.updateMyData();
    } finally {
      syncing.value = false;
      _updateUiState();
    }

    final ok = (upErr == null || upErr.isEmpty) && downOk;
    if (ok) {
      lastSuccessAt.value = DateTime.now();
      await AuthService.saveLastSyncAt(lastSuccessAt.value!);
      lastError.value = null;
      if (!silent) {
        await NotificationsBadgeService.instance.reportSyncEvent(
          kind: 'sync',
          detail: 'اكتملت المزامنة الكاملة (رفع وتنزيل).',
        );
      }
    }

    if (ok) {
      return (ok: true, message: null);
    }
    final parts = <String>[];
    if (upErr != null && upErr.isNotEmpty) parts.add('رفع: $upErr');
    if (!downOk) {
      parts.add('تنزيل: ${PackageSyncService.instance.lastError ?? 'فشل'}');
    }
    return (ok: false, message: parts.join('\n'));
  }

  Future<void> refreshPendingCount() async {
    pendingCount.value = await OfflineStore.instance.pendingOpsCount(
      userId: AuthService.instance.currentUserId,
    );
    _updateUiState();
  }

  void _updateUiState() {
    final online = HealthService.instance.serverReachable.value;
    final pending = pendingCount.value;
    if (syncing.value) {
      uiState.value = SyncUiState.syncing;
      return;
    }
    if (!online) {
      uiState.value = pending > 0 ? SyncUiState.pending : SyncUiState.offline;
      return;
    }
    if (pending > 0) {
      uiState.value =
          lastError.value != null ? SyncUiState.failed : SyncUiState.pending;
      return;
    }
    uiState.value = lastSuccessAt.value != null
        ? SyncUiState.synced
        : SyncUiState.online;
  }

  Map<String, dynamic> _sessionMeta() {
    final s = AuthService.instance.session;
    return {
      'judge_id': s?.user.id,
      'user_id': s?.user.id,
      'exercise_id': s?.exercise?.id,
    };
  }

  /// يحفظ العملية محلياً فوراً ثم يحاول الإرسال في الخلفية.
  /// يعيد false دائماً تقريباً لأن الواجهة لا تنتظر السيرفر.
  Future<bool> enqueueLocalFirst({
    required String id,
    required String method,
    required String path,
    required Map<String, dynamic> body,
    required String kind,
    required String opType,
    String? listId,
    int? evalItemId,
    String? mediaLocalPath,
  }) async {
    final meta = _sessionMeta();
    final enrichedBody = Map<String, dynamic>.from(body);
    enrichedBody['client_op_id'] = id;

    final op = PendingOp(
      id: id,
      method: method,
      path: path,
      body: enrichedBody,
      kind: kind,
      opType: opType,
      createdAt: DateTime.now().toIso8601String(),
      syncStatus: SyncStatuses.pending,
      judgeId: meta['judge_id'] as int?,
      userId: meta['user_id'] as int?,
      exerciseId: meta['exercise_id'] as int?,
      listId: listId,
      evalItemId: evalItemId,
      mediaLocalPath: mediaLocalPath,
    );
    await OfflineStore.instance.enqueueOp(op);
    await refreshPendingCount();
    if (_shouldAutoUpload() && HealthService.instance.serverReachable.value) {
      unawaited(flush());
    }
    return false;
  }

  Future<void> flush({bool mediaOnly = false}) async {
    if (syncing.value) return;
    final reachable = await HealthService.instance.check();
    if (!reachable) {
      _updateUiState();
      return;
    }
    final ops = await OfflineStore.instance.pendingOps(
      userId: AuthService.instance.currentUserId,
    );
    final filtered = mediaOnly
        ? ops.where((o) => o.opType == 'media_upload').toList()
        : ops;
    if (filtered.isEmpty) {
      lastError.value = null;
      _updateUiState();
      return;
    }

    syncing.value = true;
    MediaUploadService.instance.clearPauseFlags();
    _updateUiState();
    var successCount = 0;
    try {
      for (final op in filtered) {
        await OfflineStore.instance.markOpSyncing(op.id);
        try {
          if (op.opType == 'media_upload') {
            await _sendMedia(op);
          } else if (op.method == 'PUT') {
            await ApiClient.instance.put(
              op.path,
              body: op.body,
              idempotencyKey: op.id,
            );
          } else if (op.method == 'DELETE') {
            await ApiClient.instance.delete(
              op.path,
              idempotencyKey: op.id,
            );
          } else {
            await ApiClient.instance.post(
              op.path,
              body: op.body,
              idempotencyKey: op.id,
            );
          }
          await OfflineStore.instance.removeOp(op.id);
          successCount++;
          if (op.opType == 'approve') {
            await _markSheetSyncedAfterApprove(op);
          }
          lastSuccessAt.value = DateTime.now();
          lastError.value = null;
          await AuthService.saveLastSyncAt(lastSuccessAt.value!);
        } on ApiOfflineException {
          await OfflineStore.instance.updateOp(
            op.copyWith(syncStatus: SyncStatuses.pending),
          );
          break;
        } catch (e) {
          await OfflineStore.instance.markOpFailed(op.id, e.toString());
          lastError.value = e.toString();
          if (e is ApiException && (e.status == 401 || e.status == 403)) {
            break;
          }
        }
      }
      await refreshPendingCount();
      await MediaUploadService.instance.refreshOverallFromDb();
      if (successCount > 0) {
        await NotificationsBadgeService.instance.reportSyncEvent(
          kind: 'sync',
          detail: 'تم مزامنة $successCount عملية بنجاح.',
        );
      }
    } finally {
      syncing.value = false;
      _updateUiState();
    }
  }

  Future<void> _sendMedia(PendingOp op) async {
    final path = op.mediaLocalPath;
    if (path == null || path.isEmpty) {
      throw ApiException('مسار الوسائط مفقود');
    }
    var rec = await OfflineStore.instance.mediaById(op.id);
    rec ??= LocalMediaRecord(
      id: op.id,
      localPath: path,
      rowIndex: (op.body['row_index'] as num?)?.toInt() ?? 0,
      mediaKind: (op.body['media_kind'] ?? 'photo').toString(),
      evaluationListItemId:
          (op.body['evaluation_list_item_id'] as num?)?.toInt(),
      bundleActionEvalId: (op.body['bundle_action_eval_id'] as num?)?.toInt(),
      syncStatus: SyncStatuses.pending,
      createdAt: op.createdAt,
    );
    await MediaUploadService.instance.uploadOne(rec);
  }

  Future<void> _markSheetSyncedAfterApprove(PendingOp op) async {
    final key = op.listId;
    if (key == null || key.isEmpty) return;
    final cached = await OfflineStore.instance.cacheGet(key);
    if (cached == null) return;
    cached['is_approved'] = true;
    cached['can_edit'] = false;
    cached['can_approve'] = false;
    cached['locally_approved'] = false;
    cached['approval_sync_status'] = SyncStatuses.synced;
    cached['workflow'] = {
      ...(cached['workflow'] is Map
          ? Map<String, dynamic>.from(cached['workflow'] as Map)
          : <String, dynamic>{}),
      'label': 'معتمد ومتزامن',
    };
    await OfflineStore.instance.cacheSet(
      key,
      cached,
      syncStatus: SyncStatuses.synced,
    );
    await SyncService.onApproveSyncedHandler?.call(op);
  }
}
