import 'dart:async';

import 'package:flutter/foundation.dart';

import 'api_client.dart';
import 'auth_service.dart';
import 'health_service.dart';
import 'offline_store.dart';

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

  final ValueNotifier<int> pendingCount = ValueNotifier<int>(0);
  final ValueNotifier<bool> syncing = ValueNotifier<bool>(false);
  final ValueNotifier<SyncUiState> uiState = ValueNotifier<SyncUiState>(SyncUiState.offline);
  final ValueNotifier<String?> lastError = ValueNotifier<String?>(null);
  final ValueNotifier<DateTime?> lastSuccessAt = ValueNotifier<DateTime?>(null);

  Timer? _retryTimer;
  bool _started = false;

  Future<void> start() async {
    if (_started) return;
    _started = true;
    await HealthService.instance.start();
    await refreshPendingCount();
    final saved = await AuthService.loadLastSyncAt();
    if (saved != null) lastSuccessAt.value = saved;
    _updateUiState();
    HealthService.instance.serverReachable.addListener(_onHealth);
    _retryTimer = Timer.periodic(const Duration(seconds: 20), (_) {
      if (HealthService.instance.serverReachable.value) {
        unawaited(flush());
      } else {
        unawaited(HealthService.instance.check());
      }
    });
    if (HealthService.instance.serverReachable.value) {
      unawaited(flush());
    }
  }

  void dispose() {
    HealthService.instance.serverReachable.removeListener(_onHealth);
    _retryTimer?.cancel();
  }

  void _onHealth() {
    _updateUiState();
    if (HealthService.instance.serverReachable.value) {
      unawaited(flush());
    }
  }

  Future<void> refreshPendingCount() async {
    pendingCount.value = await OfflineStore.instance.pendingOpsCount();
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
    unawaited(flush());
    return false;
  }

  Future<void> flush() async {
    if (syncing.value) return;
    final reachable = await HealthService.instance.check();
    if (!reachable) {
      _updateUiState();
      return;
    }
    final ops = await OfflineStore.instance.pendingOps();
    if (ops.isEmpty) {
      lastError.value = null;
      _updateUiState();
      return;
    }

    syncing.value = true;
    _updateUiState();
    try {
      for (final op in ops) {
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
          } else {
            await ApiClient.instance.post(
              op.path,
              body: op.body,
              idempotencyKey: op.id,
            );
          }
          await OfflineStore.instance.removeOp(op.id);
          if (op.opType == 'media_upload') {
            await OfflineStore.instance.markMediaConfirmed(op.id);
          }
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
          // تابع بقية الطابور إن أمكن؛ أخطاء التفويض تُترك ظاهرة
          if (e is ApiException && (e.status == 401 || e.status == 403)) {
            break;
          }
        }
      }
      await refreshPendingCount();
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
    final fields = op.body;
    await ApiClient.instance.uploadCriterionMedia(
      filePath: path,
      rowIndex: (fields['row_index'] as num?)?.toInt() ?? 0,
      mediaKind: (fields['media_kind'] ?? 'photo').toString(),
      evaluationListItemId: (fields['evaluation_list_item_id'] as num?)?.toInt(),
      bundleActionEvalId: (fields['bundle_action_eval_id'] as num?)?.toInt(),
      idempotencyKey: op.id,
    );
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
  }
}
