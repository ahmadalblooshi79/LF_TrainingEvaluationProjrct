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
import 'library_pdf_cache.dart';
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
  TabletRepository._internal() {
    SyncService.onApproveSyncedHandler = notifyApproveSynced;
  }
  static final TabletRepository instance = TabletRepository._internal();

  String _scoped(String cacheKey) {
    final uid = AuthService.instance.currentUserId;
    if (uid == null || uid <= 0) return cacheKey;
    return OfflineStore.userKey(uid, cacheKey);
  }

  bool _isJudgePrivateKey(String cacheKey) {
    return cacheKey.startsWith('action_eval_detail:') ||
        cacheKey.startsWith('evaluation_list_detail:') ||
        cacheKey.startsWith('action_eval_lists');
  }

  Future<Map<String, dynamic>?> _cacheGetScoped(String cacheKey) async {
    final scoped = _scoped(cacheKey);
    final a = await OfflineStore.instance.cacheGet(scoped);
    if (a != null) return a;
    // لا تقرأ كاشاً غير معزول لتفاصيل القوائم — يخلط بيانات محكّمين مختلفين
    if (_isJudgePrivateKey(cacheKey)) {
      return null;
    }
    if (scoped != cacheKey) {
      final b = await OfflineStore.instance.cacheGet(cacheKey);
      if (b != null) return b;
    }
    try {
      final hits = await OfflineStore.instance.cacheKeysLike(cacheKey);
      for (final k in hits) {
        if (k == cacheKey || k.endsWith(':$cacheKey')) {
          final v = await OfflineStore.instance.cacheGet(k);
          if (v != null) return v;
        }
      }
    } catch (_) {}
    return null;
  }

  Future<void> _cacheSetScoped(
    String cacheKey,
    Map<String, dynamic> data, {
    String syncStatus = SyncStatuses.synced,
  }) async {
    await OfflineStore.instance.cacheSet(
      _scoped(cacheKey),
      data,
      syncStatus: syncStatus,
    );
    // نسخة دائمة غير معزولة لشاشات القراءة — تبقى بعد إعادة الفتح حتى لو تغيّر سياق المستخدم لحظياً
    if (!_isJudgePrivateKey(cacheKey) && _scoped(cacheKey) != cacheKey) {
      await OfflineStore.instance.cacheSet(
        cacheKey,
        data,
        syncStatus: syncStatus,
      );
    }
  }

  String _evalListsCacheKey({String? unitKey, String? phase}) =>
      'evaluation_lists:${unitKey ?? ''}:${phase ?? ''}';

  /// يبحث في مفاتيح الكاش المحتملة (prefetch قد يخزّن تحت مفتاح بدون unit/phase).
  Future<Map<String, dynamic>?> _readEvalListsCache({
    String? unitKey,
    String? phase,
  }) async {
    final candidates = <String>[
      _evalListsCacheKey(unitKey: unitKey, phase: phase),
      if (unitKey != null && unitKey.isNotEmpty)
        _evalListsCacheKey(unitKey: unitKey, phase: ''),
      _evalListsCacheKey(unitKey: '', phase: phase),
      _evalListsCacheKey(unitKey: '', phase: ''),
    ];
    Future<Map<String, dynamic>?> accept(Map<String, dynamic> local) async {
      final wantPhase = (phase ?? '').trim();
      if (wantPhase.isNotEmpty) {
        final cachedPhase = (local['phase_key'] ?? '').toString().trim();
        if (cachedPhase.isNotEmpty && cachedPhase != wantPhase) return null;
      }
      return local;
    }

    for (final k in candidates) {
      final local = await _cacheGetScoped(k);
      if (local == null) continue;
      final ok = await accept(local);
      if (ok != null) return ok;
    }

    try {
      final uid = AuthService.instance.currentUserId;
      final pattern =
          uid != null ? 'u$uid:evaluation_lists' : 'evaluation_lists';
      Map<String, dynamic>? any;
      for (final k in await OfflineStore.instance.cacheKeysLike(pattern)) {
        final local = await OfflineStore.instance.cacheGet(k);
        if (local == null) continue;
        any ??= local;
        final ok = await accept(local);
        if (ok != null) return ok;
      }
      if (any != null) return any;
    } catch (_) {}
    return null;
  }

  Future<void> _mirrorEvalListsCache(
    Map<String, dynamic> data, {
    String? unitKey,
    String? phase,
  }) async {
    final uk = (unitKey ?? data['unit_key'] ?? '').toString();
    final pk = (phase ?? data['phase_key'] ?? '').toString();
    final keys = <String>{
      _evalListsCacheKey(unitKey: uk, phase: pk),
      if (uk.isNotEmpty) _evalListsCacheKey(unitKey: uk, phase: ''),
      _evalListsCacheKey(unitKey: '', phase: pk),
      _evalListsCacheKey(unitKey: '', phase: ''),
    };
    for (final k in keys) {
      await _cacheSetScoped(k, data);
    }
  }

  /// Local-First: اعرض المحلي فوراً. السحب الحي فقط عبر Update My Data.
  Future<Fetched<Map<String, dynamic>>> _readLocalFirst(
    String path,
    String cacheKey, {
    Map<String, dynamic>? query,
  }) async {
    final local = await _cacheGetScoped(cacheKey);
    final reachable = await HealthService.instance.check();

    if (local != null) {
      return Fetched(Map<String, dynamic>.from(local), !reachable);
    }

    if (reachable) {
      try {
        final data = await ApiClient.instance.get(path, query: query);
        await _cacheSetScoped(cacheKey, data);
        return Fetched(Map<String, dynamic>.from(data), false);
      } catch (_) {
        final again = await _cacheGetScoped(cacheKey);
        if (again != null) {
          return Fetched(Map<String, dynamic>.from(again), true);
        }
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
      await _downloadAndStore('/api/tablet/exercise-details', 'exercise_details');
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
        try {
          await fetchFlowDayPdf(d);
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
      final defaultPhase = (ev['phase_key'] ?? '').toString();
      await _mirrorEvalListsCache(ev, unitKey: uk, phase: defaultPhase);
      await _prefetchAllEvalDetails(ev, uk);
      final phaseTabs = ((ev['phase_tabs'] as List?) ?? const [])
          .whereType<Map>()
          .map((e) => (e['key'] ?? '').toString())
          .where((id) => id.isNotEmpty);
      for (final pk in phaseTabs) {
        if (pk == defaultPhase) continue;
        try {
          final q = <String, dynamic>{'phase': pk};
          if (uk.isNotEmpty) q['unit_key'] = uk;
          final phaseEv = await _downloadAndStore(
            '/api/tablet/evaluation-lists',
            _evalListsCacheKey(unitKey: uk, phase: pk),
            query: q,
          );
          await _mirrorEvalListsCache(phaseEv, unitKey: uk, phase: pk);
          await _prefetchAllEvalDetails(phaseEv, uk);
        } catch (_) {}
      }
    } catch (_) {}
    try {
      await _downloadAndStore('/api/tablet/objectives', 'objectives');
    } catch (_) {}
    try {
      await _downloadAndStore('/api/tablet/incomplete', 'incomplete');
    } catch (_) {}
    await _prefetchAllLibraryPdfs();
  }

  Set<int> _collectPdfNodeIds(dynamic root) {
    final ids = <int>{};
    void walk(dynamic n) {
      if (n is List) {
        for (final x in n) {
          walk(x);
        }
        return;
      }
      if (n is! Map) return;
      if (n.containsKey('id') &&
          (n.containsKey('is_folder') ||
              n.containsKey('file_url') ||
              n.containsKey('name'))) {
        if (n['is_folder'] == true) {
          walk(n['children']);
          return;
        }
        final name = (n['name'] ?? '').toString().toLowerCase();
        final id = (n['id'] as num?)?.toInt() ?? 0;
        final looksPdf = name.endsWith('.pdf') || n['file_url'] == true;
        if (id > 0 && looksPdf && name.endsWith('.pdf')) ids.add(id);
        walk(n['children']);
        return;
      }
      for (final v in n.values) {
        walk(v);
      }
    }

    walk(root);
    return ids;
  }

  /// تنزيل كل ملفات PDF (المكتبة + أوراق التمرين) إلى الجهاز للعرض دون شبكة.
  Future<void> _prefetchAllLibraryPdfs() async {
    final ids = <int>{};
    var haveLibrary = false;
    var havePapers = false;
    try {
      final lib = await _downloadAndStore('/api/tablet/library', 'library');
      haveLibrary = true;
      ids.addAll(_collectPdfNodeIds(lib['trees']));
    } catch (_) {}
    try {
      final papers = await _downloadAndStore(
        '/api/tablet/exercise-papers',
        'exercise_papers',
      );
      havePapers = true;
      ids.addAll(_collectPdfNodeIds(papers['tree']));
    } catch (_) {}
    for (final id in ids) {
      try {
        final bytes = await ApiClient.instance.getBytes(
          '/api/tablet/library/nodes/$id/file',
          timeout: const Duration(seconds: 120),
        );
        if (bytes.isNotEmpty) {
          await LibraryPdfCache.put(id, bytes);
        }
      } catch (_) {}
    }
    if (haveLibrary && havePapers && ids.isNotEmpty) {
      await LibraryPdfCache.pruneExcept(ids);
    }
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
      final serverWf = data['workflow'];
      final serverReopened =
          serverWf is Map && serverWf['reopened'] == true;
      if (serverReopened) {
        // كبير المحكمين أعاد القائمة — ألغِ الاعتماد المحلي المتقادم
        merged['locally_approved'] = false;
        merged['locally_modified'] = existing['locally_modified'] == true;
        if (existing['locally_modified'] == true) {
          if (existing['saved_payload'] is Map) {
            merged['saved_payload'] = existing['saved_payload'];
          }
          if (existing['saved_rows'] != null) {
            merged['saved_rows'] = existing['saved_rows'];
          }
        }
      } else {
        merged['locally_modified'] = existing['locally_modified'] == true;
        merged['locally_approved'] = existing['locally_approved'] == true;
        if (existing['saved_payload'] is Map) {
          merged['saved_payload'] = existing['saved_payload'];
        }
        if (existing['saved_rows'] != null) {
          merged['saved_rows'] = existing['saved_rows'];
        }
      }
      await OfflineStore.instance.cacheSet(
        scopedKey,
        merged,
        syncStatus: serverReopened && existing['locally_modified'] != true
            ? SyncStatuses.synced
            : SyncStatuses.pending,
      );
    } else {
      var toStore = data;
      if (_isListAggregateCacheKey(cacheKey)) {
        toStore = await _overlayApprovedStatuses(Map<String, dynamic>.from(data));
      }
      await _cacheSetScoped(cacheKey, toStore);
    }
    if (cacheKey.startsWith('flow:')) {
      final active = (data['active_day_id'] ?? '').toString();
      if (active.isNotEmpty && cacheKey == 'flow:') {
        await _cacheSetScoped('flow:$active', data);
      }
    }
    return data;
  }

  /// مفتاح فتح قائمة الإجراءات: slot_id الفريد أولاً ثم slot_index.
  int? actionEvalOpenId(ListRow row) => row.slotId ?? row.slotIndex;

  Future<void> _prefetchAllActionDetails(Map<String, dynamic> listsPayload) async {
    final lists = ((listsPayload['lists'] as List?) ?? const [])
        .whereType<Map>()
        .map((e) => ListRow.fromJson(e.cast<String, dynamic>()))
        .toList();
    for (final row in lists) {
      final slot = actionEvalOpenId(row);
      if (slot == null) continue;
      final q = <String, dynamic>{};
      if (row.slotId != null) q['action_eval_id'] = row.slotId;
      try {
        await _downloadAndStore(
          '/api/tablet/action-eval/$slot',
          'action_eval_detail:$slot',
          query: q.isEmpty ? null : q,
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

  Future<Fetched<Map<String, dynamic>>> fetchLibrary() async {
    return _readLocalFirst('/api/tablet/library', 'library');
  }

  Future<Fetched<Map<String, dynamic>>> fetchExercisePapers() async {
    return _readLocalFirst('/api/tablet/exercise-papers', 'exercise_papers');
  }

  Future<Fetched<Map<String, dynamic>>> fetchExerciseDetails() async {
    return _readLocalFirst('/api/tablet/exercise-details', 'exercise_details');
  }

  /// عرض PDF من المخزون المحلي أولاً؛ التنزيل من السيرفر فقط إن لم يُحفظ بعد.
  Future<List<int>> fetchLibraryPdf(int nodeId) async {
    final cached = await LibraryPdfCache.get(nodeId);
    if (cached != null && cached.isNotEmpty) return cached;

    final reachable = await HealthService.instance.check();
    if (reachable) {
      final bytes = await ApiClient.instance.getBytes(
        '/api/tablet/library/nodes/$nodeId/file',
        timeout: const Duration(seconds: 120),
      );
      if (bytes.isNotEmpty) {
        await LibraryPdfCache.put(nodeId, bytes);
        return bytes;
      }
    }
    throw ApiOfflineException(
      'الملف غير متوفر محلياً — نفّذ «تحديث بياناتي» أثناء الاتصال بالنظام',
    );
  }

  /// PDF يوم المجرى من المخزون المحلي أولاً، ثم التنزيل إن وُجد اتصال.
  Future<List<int>> fetchFlowDayPdf(String dayId) async {
    final id = dayId.trim();
    if (id.isEmpty) {
      throw ApiException('اليوم غير صالح');
    }
    final cached = await LibraryPdfCache.getNamed(id);
    if (cached != null && cached.isNotEmpty) return cached;

    final reachable = await HealthService.instance.check();
    if (reachable) {
      final bytes = await ApiClient.instance.getBytes(
        '/api/tablet/flow/days/$id/file',
        timeout: const Duration(seconds: 120),
      );
      if (bytes.isNotEmpty) {
        await LibraryPdfCache.putNamed(id, bytes);
        return bytes;
      }
    }
    throw ApiOfflineException(
      'ملف PDF غير متوفر محلياً — نفّذ «تحديث بياناتي» أثناء الاتصال بالنظام',
    );
  }

  Future<Fetched<HomeData>> fetchHome() async {
    final reachable = await HealthService.instance.check();
    if (reachable) {
      try {
        final data = await _downloadAndStore('/api/tablet/home', 'home');
        final overlaid =
            await _overlayApprovedStatuses(Map<String, dynamic>.from(data));
        await _cacheSetScoped('home', overlaid);
        return Fetched(HomeData.fromJson(overlaid), false);
      } catch (_) {
        // fall through to local
      }
    }
    final r = await _readLocalFirst('/api/tablet/home', 'home');
    final overlaid =
        await _overlayApprovedStatuses(Map<String, dynamic>.from(r.data));
    return Fetched(HomeData.fromJson(overlaid), r.fromCache);
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
    final reachable = await HealthService.instance.check();
    if (reachable) {
      try {
        final data = await _downloadAndStore(
          '/api/tablet/action-eval',
          key,
          query: day != null && day.isNotEmpty ? {'day': day} : null,
        );
        final overlaid =
            await _overlayApprovedStatuses(Map<String, dynamic>.from(data));
        await _cacheSetScoped(key, overlaid);
        return Fetched(ActionEvalListsData.fromJson(overlaid), false);
      } catch (_) {}
    }
    final r = await _readLocalFirst(
      '/api/tablet/action-eval',
      key,
      query: day != null && day.isNotEmpty ? {'day': day} : null,
    );
    final overlaid =
        await _overlayApprovedStatuses(Map<String, dynamic>.from(r.data));
    return Fetched(ActionEvalListsData.fromJson(overlaid), r.fromCache);
  }

  Future<Fetched<EvalSheetDetail>> fetchActionEvalDetail(int slot, {int? actionEvalId}) async {
    final key = 'action_eval_detail:$slot';
    final q = <String, dynamic>{};
    final aid = actionEvalId ?? slot;
    q['action_eval_id'] = aid;

    final reachable = await HealthService.instance.check();
    if (reachable) {
      try {
        final data = await _downloadAndStore(
          '/api/tablet/action-eval/$slot',
          key,
          query: q,
        );
        return Fetched(EvalSheetDetail.fromJson(data), false);
      } catch (_) {
        // استخدم المحلي إن وُجد عند فشل الشبكة اللحظي
      }
    }
    final r = await _readLocalFirst(
      '/api/tablet/action-eval/$slot',
      key,
      query: q,
    );
    return Fetched(EvalSheetDetail.fromJson(r.data), r.fromCache);
  }

  Future<Fetched<EvalSheetDetail>> fetchEvaluationListDetail(
    String unitKey,
    int itemId,
  ) async {
    final key = 'evaluation_list_detail:$unitKey:$itemId';
    final reachable = await HealthService.instance.check();
    if (reachable) {
      try {
        final data = await _downloadAndStore(
          '/api/tablet/evaluation-lists/$unitKey/$itemId',
          key,
        );
        return Fetched(EvalSheetDetail.fromJson(data), false);
      } catch (_) {}
    }
    final r = await _readLocalFirst(
      '/api/tablet/evaluation-lists/$unitKey/$itemId',
      key,
    );
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

  Future<bool> approveActionEval(int slot, {String? gradeLabel}) async {
    final key = 'action_eval_detail:$slot';
    await _markLocallyApproved(key);
    await _propagateListRowStatus(
      matchActionSlot: slot,
      approved: true,
      gradeLabel: gradeLabel,
    );
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
    final sessionUk = AuthService.instance.session?.unitKey ?? '';
    final effectiveUk = (unitKey != null && unitKey.isNotEmpty)
        ? unitKey
        : sessionUk;
    final query = <String, dynamic>{};
    if (effectiveUk.isNotEmpty) query['unit_key'] = effectiveUk;
    if (phase != null && phase.isNotEmpty) query['phase'] = phase;

    final local = await _readEvalListsCache(
      unitKey: effectiveUk.isNotEmpty ? effectiveUk : null,
      phase: phase,
    );
    final reachable = await HealthService.instance.check();
    if (local != null && !reachable) {
      final overlaid =
          await _overlayApprovedStatuses(Map<String, dynamic>.from(local));
      return Fetched(EvaluationListsData.fromJson(overlaid), true);
    }
    if (reachable) {
      try {
        final data = await ApiClient.instance.get(
          '/api/tablet/evaluation-lists',
          query: query.isEmpty ? null : query,
        );
        final map = Map<String, dynamic>.from(data);
        await _mirrorEvalListsCache(
          map,
          unitKey: effectiveUk,
          phase: phase,
        );
        final overlaid = await _overlayApprovedStatuses(map);
        return Fetched(EvaluationListsData.fromJson(overlaid), false);
      } catch (_) {
        // fall through to local
      }
    }

    if (local != null) {
      final overlaid =
          await _overlayApprovedStatuses(Map<String, dynamic>.from(local));
      return Fetched(EvaluationListsData.fromJson(overlaid), true);
    }

    throw ApiOfflineException(
      'لا توجد بيانات محلية لهذه الشاشة — نفّذ «تحديث بياناتي» أو تهيئة الجهاز',
    );
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

  Future<bool> approveEvaluationList(
    String unitKey,
    int itemId, {
    String? gradeLabel,
  }) async {
    final key = 'evaluation_list_detail:$unitKey:$itemId';
    await _markLocallyApproved(key);
    await _propagateListRowStatus(
      matchItemId: itemId,
      matchUnitKey: unitKey,
      approved: true,
      gradeLabel: gradeLabel,
    );
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
    cached['can_approve'] = true;
    cached['can_edit'] = true;
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
    String? docSlot,
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
        'doc_slot': docSlot ?? '',
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

  /// يربط الوسائط المحلية المحفوظة بصفوف الورقة بعد إعادة فتحها.
  Future<void> overlayLocalMediaOnRows({
    required String sheetCacheKey,
    required List<EvalRowInput> rows,
  }) async {
    final keys = <String>{sheetCacheKey, _scoped(sheetCacheKey)};
    final seen = <String>{};

    Future<void> applyList(List<dynamic> media) async {
      for (final raw in media) {
        if (raw is! Map) continue;
        final path = (raw['local_path'] ?? '').toString();
        final idx = int.tryParse('${raw['row_index']}') ?? -1;
        if (path.isEmpty || idx < 0 || idx >= rows.length) continue;
        if (!seen.add('$idx|$path')) continue;
        var slot = (raw['doc_slot'] ?? '').toString().trim();
        if (slot.isEmpty) {
          slot = docSlotFromMediaKind((raw['media_kind'] ?? 'photo').toString());
        }
        rows[idx].addMedia(slot, path);
      }
    }

    for (final key in keys) {
      final cached = await OfflineStore.instance.cacheGet(key);
      if (cached == null || cached['local_media'] is! List) continue;
      await applyList(cached['local_media'] as List);
    }

    try {
      final recs = await OfflineStore.instance.mediaRecords();
      for (final rec in recs) {
        final sk = rec.sheetCacheKey ?? '';
        if (sk.isEmpty || !keys.contains(sk)) continue;
        if (rec.localPath.isEmpty) continue;
        final idx = rec.rowIndex;
        if (idx < 0 || idx >= rows.length) continue;
        if (!seen.add('$idx|${rec.localPath}')) continue;
        rows[idx].addMedia(docSlotFromMediaKind(rec.mediaKind), rec.localPath);
      }
    } catch (_) {}
  }

  /// حذف آخر توثيق محلي للبند (الملف + الطابور + كاش الورقة).
  Future<void> removeLastCriterionMedia({
    required String sheetCacheKey,
    required int rowIndex,
    required String localPath,
  }) async {
    if (localPath.isEmpty) return;
    final all = await OfflineStore.instance.mediaRecords();
    LocalMediaRecord? rec;
    for (final m in all) {
      if (m.localPath == localPath) {
        rec = m;
        break;
      }
    }
    if (rec != null) {
      try {
        await OfflineStore.instance.removeOp(rec.id);
      } catch (_) {}
      try {
        await OfflineStore.instance.deleteMediaRecord(rec.id);
      } catch (_) {}
    }
    try {
      await File(localPath).delete();
    } catch (_) {}

    Future<void> stripCache(String key) async {
      final cached = await OfflineStore.instance.cacheGet(key);
      if (cached == null) return;
      final media = (cached['local_media'] is List)
          ? List<Map<String, dynamic>>.from(
              (cached['local_media'] as List).whereType<Map>().map(
                    (e) => Map<String, dynamic>.from(e),
                  ),
            )
          : <Map<String, dynamic>>[];
      media.removeWhere((e) => (e['local_path'] ?? '').toString() == localPath);
      cached['local_media'] = media;
      await OfflineStore.instance.cacheSet(
        key,
        cached,
        syncStatus: SyncStatuses.pending,
      );
    }

    await stripCache(sheetCacheKey);
    final scoped = _scoped(sheetCacheKey);
    if (scoped != sheetCacheKey) {
      await stripCache(scoped);
    }
  }

  Future<Fetched<ObjectivesData>> fetchObjectives() async {
    final r = await _readLocalFirst('/api/tablet/objectives', 'objectives');
    if (!r.data.containsKey('objectives') && r.data['items'] is List) {
      r.data['objectives'] = r.data['items'];
    }
    return Fetched(ObjectivesData.fromJson(r.data), r.fromCache);
  }

  Future<Fetched<List<ListRow>>> fetchIncomplete() async {
    final reachable = await HealthService.instance.check();
    if (reachable) {
      try {
        final data = await _downloadAndStore('/api/tablet/incomplete', 'incomplete');
        final overlaid =
            await _overlayApprovedStatuses(Map<String, dynamic>.from(data));
        await _cacheSetScoped('incomplete', overlaid);
        final tasks = ((overlaid['tasks'] as List?) ??
                overlaid['incomplete_tasks'] as List? ??
                [])
            .whereType<Map>()
            .map((e) => ListRow.fromJson(e.cast<String, dynamic>()))
            .toList();
        return Fetched(tasks, false);
      } catch (_) {}
    }
    final r = await _readLocalFirst('/api/tablet/incomplete', 'incomplete');
    final overlaid =
        await _overlayApprovedStatuses(Map<String, dynamic>.from(r.data));
    final tasks =
        ((overlaid['tasks'] as List?) ?? overlaid['incomplete_tasks'] as List? ?? [])
            .whereType<Map>()
            .map((e) => ListRow.fromJson(e.cast<String, dynamic>()))
            .toList();
    return Fetched(tasks, r.fromCache);
  }

  /// بعد نجاح مزامنة الاعتماد — تأكيد تحديث صفوف القوائم والرئيسية.
  Future<void> notifyApproveSynced(PendingOp op) async {
    final path = op.path;
    if (path.contains('/action-eval/')) {
      final slot = op.evalItemId;
      if (slot != null) {
        await _propagateListRowStatus(
          matchActionSlot: slot,
          approved: true,
        );
      }
      return;
    }
    if (path.contains('/evaluation-lists/')) {
      final itemId = op.evalItemId;
      if (itemId == null) return;
      final parts = path.split('/');
      final ukIdx = parts.indexOf('evaluation-lists');
      final uk = ukIdx >= 0 && ukIdx + 1 < parts.length ? parts[ukIdx + 1] : '';
      await _propagateListRowStatus(
        matchItemId: itemId,
        matchUnitKey: uk == '_' ? null : uk,
        approved: true,
      );
    }
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

  bool _isListAggregateCacheKey(String cacheKey) {
    return cacheKey == 'home' ||
        cacheKey == 'incomplete' ||
        cacheKey.startsWith('action_eval_lists') ||
        cacheKey.startsWith('evaluation_lists');
  }

  String _stripUserScope(String fullKey) {
    final uid = AuthService.instance.currentUserId;
    if (uid == null) return fullKey;
    final prefix = 'u$uid:';
    if (fullKey.startsWith(prefix)) return fullKey.substring(prefix.length);
    return fullKey;
  }

  /// يدمج حالة «معتمد» من أوراق التقييم المخزّنة محلياً في صفوف القوائم.
  Future<Map<String, dynamic>> _overlayApprovedStatuses(
    Map<String, dynamic> payload,
  ) async {
    final copy = Map<String, dynamic>.from(payload);
    final field = copy.containsKey('lists')
        ? 'lists'
        : copy.containsKey('incomplete_tasks')
            ? 'incomplete_tasks'
            : copy.containsKey('tasks')
                ? 'tasks'
                : null;
    if (field == null) return copy;
    final raw = copy[field];
    if (raw is! List) return copy;

    final approvedSlots = <int, String>{};
    final approvedItems = <String, String>{};

    for (final pattern in ['action_eval_detail:', 'evaluation_list_detail:']) {
      for (final fullKey in await OfflineStore.instance.cacheKeysLike(pattern)) {
        final localKey = _stripUserScope(fullKey);
        if (!localKey.startsWith(pattern)) continue;
        final sheet = await _cacheGetScoped(localKey);
        if (sheet == null) continue;
        final wf = sheet['workflow'];
        final reopened = wf is Map && wf['reopened'] == true;
        if (reopened) continue;
        final approved = sheet['is_approved'] == true ||
            sheet['locally_approved'] == true;
        if (!approved) continue;
        final grade = (sheet['grade_label'] ??
                (sheet['summary'] is Map
                    ? (sheet['summary'] as Map)['grade_label']
                    : '') ??
                '')
            .toString();
        if (pattern.startsWith('action_eval_detail')) {
          final slot = int.tryParse(localKey.split(':').last);
          if (slot != null) approvedSlots[slot] = grade;
        } else {
          final rest = localKey.substring('evaluation_list_detail:'.length);
          approvedItems[rest] = grade;
        }
      }
    }

    final isIncompleteList =
        field == 'incomplete_tasks' || field == 'tasks';

    bool rowIsReturned(Map row) {
      final label = (row['status_label'] ?? '').toString();
      final tone = (row['row_tone'] ?? '').toString();
      final wf = (row['workflow_label'] ?? row['dispatch_label'] ?? '').toString();
      return tone == 'returned' ||
          label.contains('معاد') ||
          wf.contains('معاد');
    }

    bool rowIsTrulyDone(Map row) {
      if (rowIsReturned(row)) return false;
      final label = (row['status_label'] ?? '').toString().trim();
      return row['status_done'] == true ||
          label == 'معتمد' ||
          label == 'منجز' ||
          label == 'ينجز';
    }

    final lists = List<dynamic>.from(raw);
    var changed = false;
    final kept = <dynamic>[];
    for (final rawRow in lists) {
      if (rawRow is! Map) {
        kept.add(rawRow);
        continue;
      }
      final row = Map<String, dynamic>.from(rawRow);
      final returned = rowIsReturned(row);
      final alreadyDone = rowIsTrulyDone(row);

      String? grade;
      var matched = false;
      if (!returned) {
        final slot = row['slot_index'] ?? row['slot_id'] ?? row['id'];
        final slotInt = int.tryParse('$slot');
        if (slotInt != null && approvedSlots.containsKey(slotInt)) {
          grade = approvedSlots[slotInt];
          matched = true;
        } else {
          final itemId = row['item_id'] ?? row['id'];
          final uk = (row['unit_key'] ?? '').toString();
          if (itemId != null) {
            final keys = <String>[
              if (uk.isNotEmpty) '$uk:$itemId',
              '_:$itemId',
              '$itemId',
            ];
            for (final k in keys) {
              if (approvedItems.containsKey(k)) {
                grade = approvedItems[k];
                matched = true;
                break;
              }
            }
          }
        }
      }

      if (isIncompleteList && alreadyDone && !returned) {
        changed = true;
        continue;
      }
      if (isIncompleteList && matched && !returned) {
        changed = true;
        continue;
      }
      if (!matched || alreadyDone || returned) {
        if (returned) {
          row['status_done'] = false;
          if (!(row['status_label'] ?? '').toString().contains('معاد')) {
            row['status_label'] = 'معاد للتقييم';
          }
          row['row_tone'] = 'returned';
          changed = true;
        }
        kept.add(row);
        continue;
      }
      row['status_done'] = true;
      row['status_label'] = 'معتمد';
      row['row_tone'] = 'sent';
      if (grade != null && grade.isNotEmpty) {
        row['grade_label'] = grade;
      }
      if ((row['delivery_dt'] ?? '').toString().isEmpty) {
        row['delivery_dt'] = DateTime.now().toIso8601String();
      }
      if (isIncompleteList) {
        changed = true;
        continue;
      }
      kept.add(row);
      changed = true;
    }
    if (changed) copy[field] = kept;

    // مواءمة مؤشر الإنجاز مع المهام غير المكتملة الفعلية
    if (copy.containsKey('stats') && copy.containsKey('incomplete_tasks')) {
      final stats = Map<String, dynamic>.from(copy['stats'] as Map? ?? {});
      final total = (stats['total_count'] as num?)?.toInt() ?? 0;
      final incompleteLen =
          ((copy['incomplete_tasks'] as List?) ?? const []).length;
      if (total > 0) {
        final completed = (total - incompleteLen).clamp(0, total);
        stats['completed_count'] = completed;
        stats['incomplete_count'] = incompleteLen;
        stats['completion_pct'] =
            ((completed * 100.0 / total).round()).clamp(0, 100);
        stats['completed_lists'] = completed;
        stats['incomplete_lists'] = incompleteLen;
        copy['stats'] = stats;
      }
    }
    return copy;
  }

  Future<void> _propagateListRowStatus({
    int? matchActionSlot,
    int? matchItemId,
    String? matchUnitKey,
    required bool approved,
    String? gradeLabel,
  }) async {
    final statusLabel = approved ? 'معتمد' : 'لم ينجز';
    final delivery = approved ? DateTime.now().toIso8601String() : '';

    bool patchRows(List<dynamic> lists) {
      var changed = false;
      for (var i = 0; i < lists.length; i++) {
        final raw = lists[i];
        if (raw is! Map) continue;
        final m = Map<String, dynamic>.from(raw);
        if (!_listRowMatches(
          m,
          matchActionSlot: matchActionSlot,
          matchItemId: matchItemId,
          matchUnitKey: matchUnitKey,
        )) {
          continue;
        }
        m['status_done'] = approved;
        m['status_label'] = statusLabel;
        if (gradeLabel != null && gradeLabel.isNotEmpty) {
          m['grade_label'] = gradeLabel;
        }
        if (approved) {
          m['delivery_dt'] = delivery;
          m['row_tone'] = 'sent';
        }
        lists[i] = m;
        changed = true;
      }
      return changed;
    }

    Future<void> patchPayload(String cacheKey) async {
      final data = await _cacheGetScoped(cacheKey);
      if (data == null) return;
      final copy = Map<String, dynamic>.from(data);
      final keyName = copy.containsKey('lists') ? 'lists' : 'rows';
      final rawLists = copy[keyName];
      if (rawLists is! List) return;
      final lists = List<dynamic>.from(rawLists);
      if (!patchRows(lists)) return;
      copy[keyName] = lists;
      await _cacheSetScoped(cacheKey, copy);
    }

    final uid = AuthService.instance.currentUserId;
    final patterns = <String>[
      if (uid != null) 'u$uid:evaluation_lists' else 'evaluation_lists',
      if (uid != null) 'u$uid:action_eval_lists' else 'action_eval_lists',
    ];
    for (final pattern in patterns) {
      for (final fullKey in await OfflineStore.instance.cacheKeysLike(pattern)) {
        final localKey = (uid != null && fullKey.startsWith('u$uid:'))
            ? fullKey.substring('u$uid:'.length)
            : fullKey;
        await patchPayload(localKey);
      }
    }

    for (final cacheKey in ['home', 'incomplete']) {
      final data = await _cacheGetScoped(cacheKey);
      if (data == null) continue;
      final copy = Map<String, dynamic>.from(data);
      final field = cacheKey == 'home' ? 'incomplete_tasks' : 'tasks';
      final raw = copy[field];
      if (raw is! List) continue;
      final lists = List<dynamic>.from(raw);
      if (approved) {
        final before = lists.length;
        lists.removeWhere((rawRow) {
          if (rawRow is! Map) return false;
          return _listRowMatches(
            Map<String, dynamic>.from(rawRow),
            matchActionSlot: matchActionSlot,
            matchItemId: matchItemId,
            matchUnitKey: matchUnitKey,
          );
        });
        if (lists.length == before) continue;
        copy[field] = lists;
        if (cacheKey == 'home') {
          final stats = Map<String, dynamic>.from((copy['stats'] as Map?) ?? {});
          final total = (stats['total_count'] as num?)?.toInt() ?? 0;
          final incompleteLen = lists.length;
          final completed =
              total > 0 ? (total - incompleteLen).clamp(0, total) : 0;
          stats['completed_count'] = completed;
          stats['incomplete_count'] = incompleteLen;
          if (total > 0) {
            stats['completion_pct'] =
                ((completed * 100.0 / total).round()).clamp(0, 100);
          }
          stats['completed_lists'] = completed;
          stats['incomplete_lists'] = incompleteLen;
          copy['stats'] = stats;
        }
      } else {
        if (!patchRows(lists)) continue;
        copy[field] = lists;
      }
      await _cacheSetScoped(cacheKey, copy);
    }
  }

  bool _listRowMatches(
    Map<String, dynamic> row, {
    int? matchActionSlot,
    int? matchItemId,
    String? matchUnitKey,
  }) {
    if (matchActionSlot != null) {
      final slot = row['slot_id'] ?? row['slot_index'] ?? row['id'];
      return int.tryParse('$slot') == matchActionSlot;
    }
    if (matchItemId != null) {
      final id = row['item_id'] ?? row['id'];
      if (int.tryParse('$id') != matchItemId) return false;
      if (matchUnitKey != null && matchUnitKey.isNotEmpty) {
        final uk = (row['unit_key'] ?? '').toString();
        return uk.isEmpty || uk == matchUnitKey;
      }
      return true;
    }
    return false;
  }
}
