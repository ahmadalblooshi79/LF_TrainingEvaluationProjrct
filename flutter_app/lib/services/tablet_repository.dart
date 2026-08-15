import 'dart:async';
import 'dart:io';

import 'package:path/path.dart' as p;

import '../models/action_eval.dart';
import '../models/eval_sheet.dart';
import '../models/evaluation_lists.dart';
import '../models/flow.dart';
import '../models/home_data.dart';
import '../models/list_row.dart';
import '../models/objective.dart';
import '../models/polarity_note.dart';
import 'api_client.dart';
import 'auth_service.dart';
import 'health_service.dart';
import 'media_upload_service.dart';
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

  String _scoped(String cacheKey) {
    final uid = AuthService.instance.currentUserId;
    if (uid == null || uid <= 0) return cacheKey;
    return OfflineStore.userKey(uid, cacheKey);
  }

  Future<Map<String, dynamic>?> _cacheGetScoped(String cacheKey) async {
    final scoped = _scoped(cacheKey);
    final a = await OfflineStore.instance.cacheGet(scoped);
    if (a != null) return a;
    if (scoped != cacheKey) {
      return OfflineStore.instance.cacheGet(cacheKey);
    }
    return null;
  }

  Future<void> _cacheSetScoped(
    String cacheKey,
    Map<String, dynamic> data, {
    String syncStatus = SyncStatuses.synced,
  }) {
    return OfflineStore.instance.cacheSet(
      _scoped(cacheKey),
      data,
      syncStatus: syncStatus,
    );
  }

  /// Local-First: اعرض المحلي فوراً. السحب الحي فقط عبر Update My Data.
  Future<Fetched<Map<String, dynamic>>> _readLocalFirst(
    String path,
    String cacheKey, {
    Map<String, dynamic>? query,
  }) async {
    final key = _scoped(cacheKey);
    final local = await _cacheGetScoped(cacheKey);
    final reachable = await HealthService.instance.check();

    if (local != null) {
      return Fetched(Map<String, dynamic>.from(local), !reachable);
    }

    if (reachable) {
      try {
        final data = await ApiClient.instance.get(path, query: query);
        await OfflineStore.instance.cacheSet(key, data);
        return Fetched(Map<String, dynamic>.from(data), false);
      } catch (_) {
        rethrow;
      }
    }

    throw ApiOfflineException(
      'لا توجد بيانات محلية لهذه الشاشة — نفّذ «تحديث بياناتي» أو تهيئة الجهاز',
    );
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
      await _downloadAndStore('/api/tablet/polarity-notes', 'polarity_notes');
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
    final scopedKey = _scoped(cacheKey);
    final status = await OfflineStore.instance.cacheSyncStatus(scopedKey);
    final existing = await _cacheGetScoped(cacheKey);
    final hasLocalEdits = status == SyncStatuses.pending ||
        status == SyncStatuses.failed ||
        (existing != null &&
            (existing['locally_modified'] == true ||
                existing['locally_approved'] == true));
    if (hasLocalEdits && existing != null) {
      // لا تمسح تعديلات معلّقة عند Update My Data
      final merged = Map<String, dynamic>.from(data);
      merged['locally_modified'] = existing['locally_modified'] == true;
      merged['locally_approved'] = existing['locally_approved'] == true;
      if (existing['saved_payload'] is Map) {
        merged['saved_payload'] = existing['saved_payload'];
      }
      if (existing['saved_rows'] != null) {
        merged['saved_rows'] = existing['saved_rows'];
      }
      await OfflineStore.instance.cacheSet(
        scopedKey,
        merged,
        syncStatus: SyncStatuses.pending,
      );
    } else {
      await _cacheSetScoped(cacheKey, data);
    }
    if (cacheKey.startsWith('flow:')) {
      final active = (data['active_day_id'] ?? '').toString();
      if (active.isNotEmpty && cacheKey == 'flow:') {
        await _cacheSetScoped('flow:$active', data);
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
        await _cacheSetScoped('flow:$active', r.data);
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
    final cached = await _cacheGetScoped(cacheKey) ??
        <String, dynamic>{};
    cached['saved_rows'] = rows.map((r) => r.toJson()).toList();
    cached['saved_payload'] = {
      'rows': rows.map((r) => r.toJson()).toList(),
    };
    cached['locally_modified'] = true;
    await _cacheSetScoped(
      cacheKey,
      cached,
      syncStatus: syncStatus,
    );
  }

  Future<void> _markLocallyApproved(String cacheKey) async {
    final cached = await _cacheGetScoped(cacheKey) ??
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
    await _cacheSetScoped(
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
    final src = sourcePath;
    // فحص المساحة قبل النسخ
    try {
      final len = await File(src).length();
      await MediaUploadService.instance.ensureStorageFor(len);
    } catch (e) {
      if (e is ApiException) rethrow;
      // إن فشل length نتابع — persist قد يفشل لاحقاً
    }

    final localPath = await OfflineStore.instance.persistMediaFile(
      src,
      id,
      mediaKind: mediaKind,
    );
    final file = File(localPath);
    final size = await file.length();
    final checksum = await MediaUploadService.instance.sha256File(localPath);
    final mime = MediaUploadService.instance.guessMime(localPath, mediaKind);
    final session = AuthService.instance.session;
    final rec = LocalMediaRecord(
      id: id,
      clientUuid: id,
      localPath: localPath,
      rowIndex: rowIndex,
      mediaKind: mediaKind,
      evaluationListItemId: evaluationListItemId,
      bundleActionEvalId: bundleActionEvalId,
      syncStatus: MediaSyncStatuses.pending,
      createdAt: DateTime.now().toIso8601String(),
      updatedAt: DateTime.now().toIso8601String(),
      sheetCacheKey: sheetCacheKey,
      userId: session?.user.id,
      exerciseId: session?.exercise?.id,
      originalFilename: p.basename(src),
      localFilename: p.basename(localPath),
      mimeType: mime,
      fileSize: size,
      totalBytes: size,
      checksum: checksum,
    );
    await OfflineStore.instance.upsertMedia(rec);

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
        'sync_status': MediaSyncStatuses.pending,
        'file_size': size,
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
      path: '/api/tablet/media/upload/init',
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
    await _cacheSetScoped('session_bundle', data);
    if (data['incomplete_tasks'] is List) {
      await _cacheSetScoped('incomplete', {
        'ok': true,
        'tasks': data['incomplete_tasks'],
      });
    }
    if (data['home'] is Map) {
      await _cacheSetScoped(
        'home',
        Map<String, dynamic>.from(data['home'] as Map),
      );
    }
    if (data['objectives'] is List) {
      await _cacheSetScoped('objectives', {
        'ok': true,
        'exercise_id': data['exercise'] is Map ? data['exercise']['id'] : 0,
        'exercise_name': data['exercise'] is Map ? data['exercise']['name'] : '',
        'objectives': data['objectives'],
      });
    }
    if (data['polarity_notes'] is Map) {
      await _cacheSetScoped(
        'polarity_notes',
        Map<String, dynamic>.from(data['polarity_notes'] as Map),
      );
    }
    final user = AuthService.instance.session?.user;
    if (user != null) {
      await _cacheSetScoped('judge_profile', {
        'user': user.toJson(),
        'exercise': AuthService.instance.session?.exercise?.toJson(),
        'unit_key': AuthService.instance.session?.unitKey,
        'unit_label': AuthService.instance.session?.unitLabel,
      });
    }
  }

  Future<Fetched<PolarityNotesBundle>> fetchPolarityBundle() async {
    final r = await _readLocalFirst(
      '/api/tablet/polarity-notes',
      'polarity_notes',
    );
    return Fetched(PolarityNotesBundle.fromJson(r.data), r.fromCache);
  }

  Future<Fetched<List<PolarityNote>>> fetchPolarityNotes() async {
    final r = await fetchPolarityBundle();
    return Fetched(r.data.notes, r.fromCache);
  }

  Future<PolarityNotesBundle> replaceGeneralPolarityNotes({
    required String polarity,
    required List<String> bodies,
    String? unitLevelKey,
  }) async {
    final uuid = newClientOpId('pn-bulk');
    final uk = (unitLevelKey ?? AuthService.instance.session?.unitKey ?? '')
        .trim();
    final cached = await _cacheGetScoped('polarity_notes') ??
        <String, dynamic>{
          'ok': true,
          'unit_key': uk,
          'unit_label': AuthService.instance.session?.unitLabel ?? '',
          'notes': <dynamic>[],
        };
    final other = ((cached['notes'] as List?) ?? [])
        .whereType<Map>()
        .map((e) => Map<String, dynamic>.from(e))
        .where((e) => (e['polarity'] ?? '').toString() != polarity)
        .toList();
    final now = DateTime.now().toIso8601String();
    final replaced = <Map<String, dynamic>>[];
    var i = 0;
    for (final raw in bodies) {
      final body = raw.trim();
      if (body.isEmpty) continue;
      replaced.add({
        'client_uuid': '$uuid-$i',
        'polarity': polarity,
        'body': body,
        'source_kind': 'general',
        'unit_level_key': uk,
        'row_index': i,
        'sync_status': SyncStatuses.pending,
        'created_at': now,
        'updated_at': now,
      });
      i++;
    }
    cached['notes'] = [...other, ...replaced];
    cached['unit_key'] = uk;
    cached['notes_pos_count'] = polarity == 'positive'
        ? replaced.length
        : other.where((e) => e['polarity'] == 'positive').length;
    cached['notes_neg_count'] = polarity == 'negative'
        ? replaced.length
        : other.where((e) => e['polarity'] == 'negative').length;
    await _cacheSetScoped(
      'polarity_notes',
      cached,
      syncStatus: SyncStatuses.pending,
    );

    await SyncService.instance.enqueueLocalFirst(
      id: uuid,
      method: 'POST',
      path: '/api/tablet/polarity-notes/bulk',
      body: {
        'client_op_id': uuid,
        'polarity': polarity,
        'unit_level_key': uk,
        'bodies': bodies,
      },
      kind: polarity == 'positive'
          ? 'حفظ قائمة الإيجابيات'
          : 'حفظ قائمة السلبيات',
      opType: 'polarity_notes_bulk',
    );
    return PolarityNotesBundle.fromJson(cached);
  }

  Future<void> savePolarityNote({
    PolarityNote? existing,
    required String polarity,
    required String body,
    String sourceKind = 'general',
    int? evaluationListItemId,
    int? bundleActionEvalId,
    int? rowIndex,
    String criterionLabel = '',
  }) async {
    final uuid = (existing?.clientUuid.isNotEmpty == true)
        ? existing!.clientUuid
        : newClientOpId('pn');
    final now = DateTime.now().toIso8601String();
    final note = PolarityNote(
      id: existing?.id,
      clientUuid: uuid,
      polarity: polarity,
      body: body.trim(),
      sourceKind: sourceKind,
      evaluationListItemId: evaluationListItemId,
      bundleActionEvalId: bundleActionEvalId,
      rowIndex: rowIndex,
      criterionLabel: criterionLabel,
      unitLevelKey: AuthService.instance.session?.unitKey ?? '',
      syncStatus: SyncStatuses.pending,
      createdAt: existing?.createdAt.isNotEmpty == true
          ? existing!.createdAt
          : now,
      updatedAt: now,
    );

    final cached = await _cacheGetScoped('polarity_notes') ??
        <String, dynamic>{'ok': true, 'notes': <dynamic>[]};
    final list = ((cached['notes'] as List?) ?? [])
        .whereType<Map>()
        .map((e) => Map<String, dynamic>.from(e))
        .toList();
    final idx = list.indexWhere(
      (e) => (e['client_uuid'] ?? '').toString() == uuid,
    );
    if (idx >= 0) {
      list[idx] = note.toJson();
    } else {
      list.insert(0, note.toJson());
    }
    cached['notes'] = list;
    await _cacheSetScoped(
      'polarity_notes',
      cached,
      syncStatus: SyncStatuses.pending,
    );

    await SyncService.instance.enqueueLocalFirst(
      id: uuid,
      method: 'POST',
      path: '/api/tablet/polarity-notes',
      body: note.toJson(),
      kind: polarity == 'positive' ? 'حفظ إيجابية' : 'حفظ سلبية',
      opType: 'polarity_note_save',
    );
  }

  Future<void> deletePolarityNote(PolarityNote note) async {
    final cached = await _cacheGetScoped('polarity_notes') ??
        <String, dynamic>{'ok': true, 'notes': <dynamic>[]};
    final list = ((cached['notes'] as List?) ?? [])
        .whereType<Map>()
        .map((e) => Map<String, dynamic>.from(e))
        .where((e) => (e['client_uuid'] ?? '') != note.clientUuid)
        .toList();
    cached['notes'] = list;
    await _cacheSetScoped('polarity_notes', cached);

    if (note.id != null && note.id! > 0) {
      await SyncService.instance.enqueueLocalFirst(
        id: newClientOpId('pn-del'),
        method: 'DELETE',
        path: '/api/tablet/polarity-notes/${note.id}',
        body: const {},
        kind: 'حذف ملاحظة قطبية',
        opType: 'polarity_note_delete',
      );
    }
  }
}
