import 'dart:async';

import '../models/action_eval.dart';
import '../models/eval_sheet.dart';
import '../models/evaluation_lists.dart';
import '../models/flow.dart';
import '../models/home_data.dart';
import '../models/list_row.dart';
import '../models/objective.dart';
import 'api_client.dart';
import 'auth_service.dart';
import 'health_service.dart';
import 'offline_store.dart';
import 'sync_service.dart';

/// يغلّف قيمة مع علم يوضح إن كانت من القاعدة المحلية أم بعد مزامنة حيّة.
class Fetched<T> {
  final T data;
  final bool fromCache;
  const Fetched(this.data, this.fromCache);
}

int _opSeq = 0;
String newClientOpId([String prefix = 'op']) {
  _opSeq += 1;
  return '$prefix-${DateTime.now().microsecondsSinceEpoch}-$_opSeq';
}

/// Offline-first: UI → Local DB → Sync Engine → Server API.
class TabletRepository {
  TabletRepository._internal();
  static final TabletRepository instance = TabletRepository._internal();

  /// عند توفر السيرفر: جلب حيّ أولاً (لتوافق الإشعارات وإعادة القوائم).
  /// عند الانقطاع فقط: إرجاع الكاش المحلي.
  Future<Fetched<Map<String, dynamic>>> _readLocalFirst(
    String path,
    String cacheKey, {
    Map<String, dynamic>? query,
  }) async {
    final local = await OfflineStore.instance.cacheGet(cacheKey);
    final reachable = await HealthService.instance.check();

    if (reachable) {
      try {
        final data = await ApiClient.instance.get(path, query: query);
        final status = await OfflineStore.instance.cacheSyncStatus(cacheKey);
        final existing = await OfflineStore.instance.cacheGet(cacheKey);
        final serverReopened = _sheetReopenedOnServer(data);
        // إعادة كبير المحكمين من السيرفر تلغي قفل الاعتماد المحلي القديم
        if (serverReopened && existing != null) {
          final merged = Map<String, dynamic>.from(data);
          merged['locally_approved'] = false;
          merged['locally_modified'] = existing['locally_modified'] == true;
          if (existing['locally_modified'] == true &&
              existing['saved_payload'] is Map) {
            // أبقِ تعديلات الصفوف المحلية غير المتزامنة فوق حمولة السيرفر
            merged['saved_payload'] = existing['saved_payload'];
            if (existing['saved_rows'] != null) {
              merged['saved_rows'] = existing['saved_rows'];
            }
          }
          await OfflineStore.instance.cacheSet(
            cacheKey,
            merged,
            syncStatus: existing['locally_modified'] == true
                ? SyncStatuses.pending
                : SyncStatuses.synced,
          );
          return Fetched(merged, false);
        }
        final hasLocalEdits = status == SyncStatuses.pending ||
            status == SyncStatuses.failed ||
            (existing != null &&
                (existing['locally_modified'] == true ||
                    existing['locally_approved'] == true));
        if (!hasLocalEdits) {
          await OfflineStore.instance.cacheSet(cacheKey, data);
          return Fetched(Map<String, dynamic>.from(data), false);
        }
        // تعديلات معلّقة محلياً: أبقِ الكاش لكن لا تُظهر بانر «بدون اتصال»
        return Fetched(
          Map<String, dynamic>.from(existing ?? data),
          false,
        );
      } catch (_) {
        if (local != null) {
          return Fetched(Map<String, dynamic>.from(local), true);
        }
        rethrow;
      }
    }

    if (local != null) {
      return Fetched(Map<String, dynamic>.from(local), true);
    }
    throw ApiOfflineException(
      'لا توجد بيانات محلية لهذه الشاشة — اتصل بالخادم مرة واحدة للتنزيل',
    );
  }

  /// هل أعلن السيرفر إعادة القائمة للمحكم؟
  bool _sheetReopenedOnServer(Map<String, dynamic> data) {
    final wf = data['workflow'];
    if (wf is Map && wf['reopened'] == true) return true;
    return false;
  }

  Future<void> _refreshIntoCache(
    String path,
    String cacheKey, {
    Map<String, dynamic>? query,
  }) async {
    try {
      final data = await ApiClient.instance.get(path, query: query);
      if (_sheetReopenedOnServer(data)) {
        final existing = await OfflineStore.instance.cacheGet(cacheKey);
        final merged = Map<String, dynamic>.from(data);
        merged['locally_approved'] = false;
        if (existing != null &&
            existing['locally_modified'] == true &&
            existing['saved_payload'] is Map) {
          merged['locally_modified'] = true;
          merged['saved_payload'] = existing['saved_payload'];
          if (existing['saved_rows'] != null) {
            merged['saved_rows'] = existing['saved_rows'];
          }
          await OfflineStore.instance.cacheSet(
            cacheKey,
            merged,
            syncStatus: SyncStatuses.pending,
          );
        } else {
          await OfflineStore.instance.cacheSet(cacheKey, merged);
        }
        return;
      }
      // لا تستبدل تعديلات محلية معلّقة بمزامنة
      final status = await OfflineStore.instance.cacheSyncStatus(cacheKey);
      if (status == SyncStatuses.pending || status == SyncStatuses.failed) {
        return;
      }
      final existing = await OfflineStore.instance.cacheGet(cacheKey);
      if (existing != null &&
          (existing['locally_modified'] == true ||
              existing['locally_approved'] == true)) {
        return;
      }
      await OfflineStore.instance.cacheSet(cacheKey, data);
    } catch (_) {}
  }

  /// بعد الدخول: تنزيل كامل لبيانات المحكم للعمل دون شبكة.
  Future<void> prefetchForOffline() async {
    try {
      await fetchBootstrap();
    } catch (_) {}
    try {
      await _downloadAndStore('/api/tablet/home', 'home');
    } catch (_) {}
    try {
      final flow = await _downloadAndStore('/api/tablet/flow', 'flow:');
      final days = ((flow['days'] as List?) ?? const [])
          .whereType<Map>()
          .map((e) => (e['id'] ?? '').toString())
          .where((id) => id.isNotEmpty);
      for (final d in days) {
        try {
          await _downloadAndStore(
            '/api/tablet/flow',
            'flow:$d',
            query: {'day': d},
          );
        } catch (_) {}
      }
    } catch (_) {}
    try {
      final lists = await _downloadAndStore(
        '/api/tablet/action-eval',
        'action_eval_lists:',
      );
      await _prefetchAllActionDetails(lists);
      final dayTabs = ((lists['day_tabs'] as List?) ?? const [])
          .whereType<Map>()
          .map((e) => (e['id'] ?? '').toString())
          .where((id) => id.isNotEmpty);
      for (final d in dayTabs) {
        try {
          final dayLists = await _downloadAndStore(
            '/api/tablet/action-eval',
            'action_eval_lists:$d',
            query: {'day': d},
          );
          await _prefetchAllActionDetails(dayLists);
        } catch (_) {}
      }
    } catch (_) {}
    try {
      final ev = await _downloadAndStore(
        '/api/tablet/evaluation-lists',
        'evaluation_lists::',
      );
      final uk = (ev['unit_key'] ?? '').toString();
      await _prefetchAllEvalDetails(ev, uk);
    } catch (_) {}
    try {
      await _downloadAndStore('/api/tablet/objectives', 'objectives');
    } catch (_) {}
    try {
      await _downloadAndStore('/api/tablet/incomplete', 'incomplete');
    } catch (_) {}
  }

  Future<Map<String, dynamic>> _downloadAndStore(
    String path,
    String cacheKey, {
    Map<String, dynamic>? query,
  }) async {
    final data = await ApiClient.instance.get(path, query: query);
    await OfflineStore.instance.cacheSet(cacheKey, data);
    if (cacheKey.startsWith('flow:')) {
      final active = (data['active_day_id'] ?? '').toString();
      if (active.isNotEmpty && cacheKey == 'flow:') {
        await OfflineStore.instance.cacheSet('flow:$active', data);
      }
    }
    return data;
  }

  Future<void> _prefetchAllActionDetails(Map<String, dynamic> listsPayload) async {
    final lists = ((listsPayload['lists'] as List?) ?? const [])
        .whereType<Map>()
        .map((e) => ListRow.fromJson(e.cast<String, dynamic>()))
        .toList();
    for (final row in lists) {
      final slot = row.slotIndex ?? row.slotId;
      if (slot == null) continue;
      try {
        await _downloadAndStore(
          '/api/tablet/action-eval/$slot',
          'action_eval_detail:$slot',
        );
      } catch (_) {}
    }
  }

  Future<void> _prefetchAllEvalDetails(
    Map<String, dynamic> payload,
    String unitKey,
  ) async {
    final lists = ((payload['lists'] as List?) ?? const [])
        .whereType<Map>()
        .map((e) => ListRow.fromJson(e.cast<String, dynamic>()))
        .toList();
    for (final row in lists) {
      final id =
          row.itemId ?? (row.id is int ? row.id as int : int.tryParse('${row.id}'));
      if (id == null) continue;
      final uk = row.unitKey.isNotEmpty ? row.unitKey : unitKey;
      if (uk.isEmpty) continue;
      try {
        await _downloadAndStore(
          '/api/tablet/evaluation-lists/$uk/$id',
          'evaluation_list_detail:$uk:$id',
        );
      } catch (_) {}
    }
  }

  Future<Fetched<HomeData>> fetchHome() async {
    final r = await _readLocalFirst('/api/tablet/home', 'home');
    return Fetched(HomeData.fromJson(r.data), r.fromCache);
  }

  Future<Fetched<FlowData>> fetchFlow({String? day}) async {
    final key = 'flow:${day ?? ''}';
    final r = await _readLocalFirst(
      '/api/tablet/flow',
      key,
      query: day != null && day.isNotEmpty ? {'day': day} : null,
    );
    if (day == null || day.isEmpty) {
      final active = (r.data['active_day_id'] ?? '').toString();
      if (active.isNotEmpty) {
        await OfflineStore.instance.cacheSet('flow:$active', r.data);
      }
    }
    return Fetched(FlowData.fromJson(r.data), r.fromCache);
  }

  Future<Fetched<ActionEvalListsData>> fetchActionEvalLists({String? day}) async {
    final key = 'action_eval_lists:${day ?? ''}';
    final r = await _readLocalFirst(
      '/api/tablet/action-eval',
      key,
      query: day != null && day.isNotEmpty ? {'day': day} : null,
    );
    return Fetched(ActionEvalListsData.fromJson(r.data), r.fromCache);
  }

  Future<Fetched<EvalSheetDetail>> fetchActionEvalDetail(int slot) async {
    final key = 'action_eval_detail:$slot';
    final r = await _readLocalFirst('/api/tablet/action-eval/$slot', key);
    return Fetched(EvalSheetDetail.fromJson(r.data), r.fromCache);
  }

  Future<bool> saveActionEvalResults(int slot, List<EvalRowInput> rows) async {
    final key = 'action_eval_detail:$slot';
    await _patchCachedSheet(key, rows, syncStatus: SyncStatuses.pending);
    await SyncService.instance.enqueueLocalFirst(
      id: newClientOpId('save-ae-$slot'),
      method: 'PUT',
      path: '/api/tablet/action-eval/$slot/results',
      body: {
        'payload': {'rows': rows.map((r) => r.toJson()).toList()},
      },
      kind: 'حفظ نتائج تقييم إجراءات #$slot',
      opType: 'save_results',
      listId: key,
      evalItemId: slot,
    );
    return false;
  }

  Future<bool> approveActionEval(int slot) async {
    final key = 'action_eval_detail:$slot';
    await _markLocallyApproved(key);
    await SyncService.instance.enqueueLocalFirst(
      id: newClientOpId('approve-ae-$slot'),
      method: 'POST',
      path: '/api/tablet/action-eval/$slot/approve',
      body: const {},
      kind: 'اعتماد تقييم إجراءات #$slot',
      opType: 'approve',
      listId: key,
      evalItemId: slot,
    );
    return false;
  }

  Future<Fetched<EvaluationListsData>> fetchEvaluationLists({
    String? unitKey,
    String? phase,
  }) async {
    final key = 'evaluation_lists:${unitKey ?? ''}:${phase ?? ''}';
    final query = <String, dynamic>{};
    if (unitKey != null && unitKey.isNotEmpty) query['unit_key'] = unitKey;
    if (phase != null && phase.isNotEmpty) query['phase'] = phase;
    final r = await _readLocalFirst(
      '/api/tablet/evaluation-lists',
      key,
      query: query.isEmpty ? null : query,
    );
    return Fetched(EvaluationListsData.fromJson(r.data), r.fromCache);
  }

  Future<Fetched<EvalSheetDetail>> fetchEvaluationListDetail(
    String unitKey,
    int itemId,
  ) async {
    final key = 'evaluation_list_detail:$unitKey:$itemId';
    final r = await _readLocalFirst(
      '/api/tablet/evaluation-lists/$unitKey/$itemId',
      key,
    );
    return Fetched(EvalSheetDetail.fromJson(r.data), r.fromCache);
  }

  Future<bool> saveEvaluationListResults(
    String unitKey,
    int itemId,
    List<EvalRowInput> rows,
  ) async {
    final key = 'evaluation_list_detail:$unitKey:$itemId';
    await _patchCachedSheet(key, rows, syncStatus: SyncStatuses.pending);
    await SyncService.instance.enqueueLocalFirst(
      id: newClientOpId('save-el-$itemId'),
      method: 'PUT',
      path: '/api/tablet/evaluation-lists/$unitKey/$itemId/results',
      body: {
        'payload': {'rows': rows.map((r) => r.toJson()).toList()},
      },
      kind: 'حفظ نتائج قائمة تقييم #$itemId',
      opType: 'save_results',
      listId: key,
      evalItemId: itemId,
    );
    return false;
  }

  Future<bool> approveEvaluationList(String unitKey, int itemId) async {
    final key = 'evaluation_list_detail:$unitKey:$itemId';
    await _markLocallyApproved(key);
    await SyncService.instance.enqueueLocalFirst(
      id: newClientOpId('approve-el-$itemId'),
      method: 'POST',
      path: '/api/tablet/evaluation-lists/$unitKey/$itemId/approve',
      body: const {},
      kind: 'اعتماد قائمة تقييم #$itemId',
      opType: 'approve',
      listId: key,
      evalItemId: itemId,
    );
    return false;
  }

  Future<void> _patchCachedSheet(
    String cacheKey,
    List<EvalRowInput> rows, {
    String syncStatus = SyncStatuses.pending,
  }) async {
    final cached = await OfflineStore.instance.cacheGet(cacheKey) ??
        <String, dynamic>{};
    cached['saved_rows'] = rows.map((r) => r.toJson()).toList();
    cached['saved_payload'] = {
      'rows': rows.map((r) => r.toJson()).toList(),
    };
    cached['locally_modified'] = true;
    await OfflineStore.instance.cacheSet(
      cacheKey,
      cached,
      syncStatus: syncStatus,
    );
  }

  Future<void> _markLocallyApproved(String cacheKey) async {
    final cached = await OfflineStore.instance.cacheGet(cacheKey) ??
        <String, dynamic>{};
    cached['is_approved'] = true;
    cached['can_edit'] = false;
    cached['can_approve'] = false;
    cached['locally_approved'] = true;
    cached['approval_sync_status'] = SyncStatuses.pending;
    cached['workflow'] = {
      ...(cached['workflow'] is Map
          ? Map<String, dynamic>.from(cached['workflow'] as Map)
          : <String, dynamic>{}),
      'label': 'معتمد محلياً – بانتظار المزامنة',
    };
    await OfflineStore.instance.cacheSet(
      cacheKey,
      cached,
      syncStatus: SyncStatuses.pending,
    );
  }

  /// حفظ وسائط محلياً أولاً ثم طابور رفع.
  Future<String> queueCriterionMedia({
    required String sourcePath,
    required int rowIndex,
    required String mediaKind,
    required String sheetCacheKey,
    int? evaluationListItemId,
    int? bundleActionEvalId,
  }) async {
    final id = newClientOpId('media');
    final localPath =
        await OfflineStore.instance.persistMediaFile(sourcePath, id);
    final rec = LocalMediaRecord(
      id: id,
      localPath: localPath,
      rowIndex: rowIndex,
      mediaKind: mediaKind,
      evaluationListItemId: evaluationListItemId,
      bundleActionEvalId: bundleActionEvalId,
      syncStatus: SyncStatuses.pending,
      createdAt: DateTime.now().toIso8601String(),
      sheetCacheKey: sheetCacheKey,
    );
    await OfflineStore.instance.upsertMedia(rec);

    // أرفق المسار المحلي في ورقة التقييم المخزّنة
    final cached = await OfflineStore.instance.cacheGet(sheetCacheKey);
    if (cached != null) {
      final media = (cached['local_media'] is List)
          ? List<Map<String, dynamic>>.from(
              (cached['local_media'] as List).whereType<Map>().map(
                    (e) => Map<String, dynamic>.from(e),
                  ),
            )
          : <Map<String, dynamic>>[];
      media.add({
        'id': id,
        'row_index': rowIndex,
        'media_kind': mediaKind,
        'local_path': localPath,
        'sync_status': SyncStatuses.pending,
      });
      cached['local_media'] = media;
      await OfflineStore.instance.cacheSet(
        sheetCacheKey,
        cached,
        syncStatus: SyncStatuses.pending,
      );
    }

    await SyncService.instance.enqueueLocalFirst(
      id: id,
      method: 'POST',
      path: '/api/tablet/media/criterion',
      body: {
        'row_index': rowIndex,
        'media_kind': mediaKind,
        if (evaluationListItemId != null)
          'evaluation_list_item_id': evaluationListItemId,
        if (bundleActionEvalId != null)
          'bundle_action_eval_id': bundleActionEvalId,
      },
      kind: mediaKind == 'video' ? 'رفع فيديو' : 'رفع صورة',
      opType: 'media_upload',
      listId: sheetCacheKey,
      evalItemId: evaluationListItemId ?? bundleActionEvalId,
      mediaLocalPath: localPath,
    );
    return localPath;
  }

  Future<Fetched<ObjectivesData>> fetchObjectives() async {
    final r = await _readLocalFirst('/api/tablet/objectives', 'objectives');
    if (!r.data.containsKey('objectives') && r.data['items'] is List) {
      r.data['objectives'] = r.data['items'];
    }
    return Fetched(ObjectivesData.fromJson(r.data), r.fromCache);
  }

  Future<Fetched<List<ListRow>>> fetchIncomplete() async {
    final r = await _readLocalFirst('/api/tablet/incomplete', 'incomplete');
    final tasks =
        ((r.data['tasks'] as List?) ?? r.data['incomplete_tasks'] as List? ?? [])
            .whereType<Map>()
            .map((e) => ListRow.fromJson(e.cast<String, dynamic>()))
            .toList();
    return Fetched(tasks, r.fromCache);
  }

  Future<Fetched<Map<String, dynamic>>> fetchBootstrap() async {
    final r = await _readLocalFirst('/api/tablet/bootstrap', 'bootstrap');
    if (!r.fromCache) {
      await _seedFromBootstrap(r.data);
    }
    return r;
  }

  Future<void> _seedFromBootstrap(Map<String, dynamic> data) async {
    await OfflineStore.instance.cacheSet('session_bundle', data);
    if (data['incomplete_tasks'] is List) {
      await OfflineStore.instance.cacheSet('incomplete', {
        'ok': true,
        'tasks': data['incomplete_tasks'],
      });
    }
    if (data['home'] is Map) {
      await OfflineStore.instance.cacheSet(
        'home',
        Map<String, dynamic>.from(data['home'] as Map),
      );
    }
    if (data['objectives'] is List) {
      await OfflineStore.instance.cacheSet('objectives', {
        'ok': true,
        'exercise_id': data['exercise'] is Map ? data['exercise']['id'] : 0,
        'exercise_name': data['exercise'] is Map ? data['exercise']['name'] : '',
        'objectives': data['objectives'],
      });
    }
    final user = AuthService.instance.session?.user;
    if (user != null) {
      // احتفظ بهوية المحكم صراحةً في التخزين المحلي
      await OfflineStore.instance.cacheSet('judge_profile', {
        'user': user.toJson(),
        'exercise': AuthService.instance.session?.exercise?.toJson(),
        'unit_key': AuthService.instance.session?.unitKey,
        'unit_label': AuthService.instance.session?.unitLabel,
      });
    }
  }
}
