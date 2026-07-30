import 'dart:async';

import '../models/action_eval.dart';
import '../models/eval_sheet.dart';
import '../models/evaluation_lists.dart';
import '../models/flow.dart';
import '../models/home_data.dart';
import '../models/list_row.dart';
import '../models/objective.dart';
import 'api_client.dart';
import 'offline_store.dart';
import 'sync_service.dart';

/// Wraps a value with a flag telling the UI whether it came from the local
/// offline cache (server unreachable) rather than a live network response.
class Fetched<T> {
  final T data;
  final bool fromCache;
  const Fetched(this.data, this.fromCache);
}

int _opSeq = 0;
String _newOpId() {
  _opSeq += 1;
  return '${DateTime.now().microsecondsSinceEpoch}-$_opSeq';
}

/// Offline-first repository for `/api/tablet/*`.
class TabletRepository {
  TabletRepository._internal();
  static final TabletRepository instance = TabletRepository._internal();

  Future<Fetched<Map<String, dynamic>>> _getCached(
    String path,
    String cacheKey, {
    Map<String, dynamic>? query,
  }) async {
    try {
      final data = await ApiClient.instance.get(path, query: query);
      // Never let offline cache quota/write failures discard a live response —
      // that previously left the eval sheet with headers but no rows.
      try {
        await OfflineStore.instance.cacheSet(cacheKey, data);
      } catch (_) {}
      return Fetched(data, false);
    } catch (e) {
      final cached = await OfflineStore.instance.cacheGet(cacheKey);
      if (cached != null) return Fetched(cached, true);
      if (e is ApiException) rethrow;
      throw ApiOfflineException();
    }
  }

  /// After login: warm local cache so the tablet keeps working without Wi‑Fi.
  Future<void> prefetchForOffline() async {
    try {
      await fetchBootstrap();
    } catch (_) {}
    try {
      await fetchHome();
    } catch (_) {}
    try {
      final flow = await fetchFlow();
      for (final d in flow.data.days.take(5)) {
        try {
          await fetchFlow(day: d.id);
        } catch (_) {}
      }
    } catch (_) {}
    try {
      final lists = await fetchActionEvalLists();
      for (final d in lists.data.dayTabs.take(5)) {
        try {
          final dayLists = await fetchActionEvalLists(day: d.id);
          await _prefetchActionDetails(dayLists.data.lists);
        } catch (_) {}
      }
      await _prefetchActionDetails(lists.data.lists);
    } catch (_) {}
    try {
      final ev = await fetchEvaluationLists();
      await _prefetchEvalDetails(ev.data.lists, ev.data.unitKey);
    } catch (_) {}
    try {
      await fetchObjectives();
    } catch (_) {}
    try {
      await fetchIncomplete();
    } catch (_) {}
  }

  Future<void> _prefetchActionDetails(List<ListRow> lists) async {
    var n = 0;
    for (final row in lists) {
      final slot = row.slotIndex ?? row.slotId;
      if (slot == null) continue;
      try {
        await fetchActionEvalDetail(slot);
      } catch (_) {}
      n += 1;
      if (n >= 12) break;
    }
  }

  Future<void> _prefetchEvalDetails(List<ListRow> lists, String unitKey) async {
    var n = 0;
    for (final row in lists) {
      final id = row.itemId ?? (row.id is int ? row.id as int : int.tryParse('${row.id}'));
      if (id == null) continue;
      final uk = row.unitKey.isNotEmpty ? row.unitKey : unitKey;
      if (uk.isEmpty) continue;
      try {
        await fetchEvaluationListDetail(uk, id);
      } catch (_) {}
      n += 1;
      if (n >= 12) break;
    }
  }

  Future<Fetched<HomeData>> fetchHome() async {
    final r = await _getCached('/api/tablet/home', 'home');
    return Fetched(HomeData.fromJson(r.data), r.fromCache);
  }

  Future<Fetched<FlowData>> fetchFlow({String? day}) async {
    final key = 'flow:${day ?? ''}';
    final r = await _getCached(
      '/api/tablet/flow',
      key,
      query: day != null && day.isNotEmpty ? {'day': day} : null,
    );
    // Also mirror under empty-day key when server returns active day.
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
    final r = await _getCached(
      '/api/tablet/action-eval',
      key,
      query: day != null && day.isNotEmpty ? {'day': day} : null,
    );
    if (!r.fromCache) {
      unawaited(_prefetchActionDetails(
        ((r.data['lists'] as List?) ?? [])
            .whereType<Map>()
            .map((e) => ListRow.fromJson(e.cast<String, dynamic>()))
            .toList(),
      ));
    }
    return Fetched(ActionEvalListsData.fromJson(r.data), r.fromCache);
  }

  Future<Fetched<EvalSheetDetail>> fetchActionEvalDetail(int slot) async {
    final key = 'action_eval_detail:$slot';
    final r = await _getCached('/api/tablet/action-eval/$slot', key);
    return Fetched(EvalSheetDetail.fromJson(r.data), r.fromCache);
  }

  Future<bool> saveActionEvalResults(int slot, List<EvalRowInput> rows) async {
    final sent = await SyncService.instance.enqueueOrSend(
      id: _newOpId(),
      method: 'PUT',
      path: '/api/tablet/action-eval/$slot/results',
      body: {
        'payload': {'rows': rows.map((r) => r.toJson()).toList()},
      },
      kind: 'حفظ نتائج تقييم إجراءات #$slot',
    );
    await _patchCachedSheet('action_eval_detail:$slot', rows);
    return sent;
  }

  Future<bool> approveActionEval(int slot) {
    return SyncService.instance.enqueueOrSend(
      id: _newOpId(),
      method: 'POST',
      path: '/api/tablet/action-eval/$slot/approve',
      body: const {},
      kind: 'اعتماد تقييم إجراءات #$slot',
    );
  }

  Future<Fetched<EvaluationListsData>> fetchEvaluationLists({
    String? unitKey,
    String? phase,
  }) async {
    final key = 'evaluation_lists:${unitKey ?? ''}:${phase ?? ''}';
    final query = <String, dynamic>{};
    if (unitKey != null && unitKey.isNotEmpty) query['unit_key'] = unitKey;
    if (phase != null && phase.isNotEmpty) query['phase'] = phase;
    final r = await _getCached(
      '/api/tablet/evaluation-lists',
      key,
      query: query.isEmpty ? null : query,
    );
    if (!r.fromCache) {
      final uk = (r.data['unit_key'] ?? unitKey ?? '').toString();
      unawaited(_prefetchEvalDetails(
        ((r.data['lists'] as List?) ?? [])
            .whereType<Map>()
            .map((e) => ListRow.fromJson(e.cast<String, dynamic>()))
            .toList(),
        uk,
      ));
    }
    return Fetched(EvaluationListsData.fromJson(r.data), r.fromCache);
  }

  Future<Fetched<EvalSheetDetail>> fetchEvaluationListDetail(
    String unitKey,
    int itemId,
  ) async {
    final key = 'evaluation_list_detail:$unitKey:$itemId';
    final r = await _getCached(
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
    final sent = await SyncService.instance.enqueueOrSend(
      id: _newOpId(),
      method: 'PUT',
      path: '/api/tablet/evaluation-lists/$unitKey/$itemId/results',
      body: {
        'payload': {'rows': rows.map((r) => r.toJson()).toList()},
      },
      kind: 'حفظ نتائج قائمة تقييم #$itemId',
    );
    await _patchCachedSheet('evaluation_list_detail:$unitKey:$itemId', rows);
    return sent;
  }

  Future<bool> approveEvaluationList(String unitKey, int itemId) {
    return SyncService.instance.enqueueOrSend(
      id: _newOpId(),
      method: 'POST',
      path: '/api/tablet/evaluation-lists/$unitKey/$itemId/approve',
      body: const {},
      kind: 'اعتماد قائمة تقييم #$itemId',
    );
  }

  Future<void> _patchCachedSheet(String cacheKey, List<EvalRowInput> rows) async {
    final cached = await OfflineStore.instance.cacheGet(cacheKey);
    if (cached == null) return;
    cached['saved_rows'] = rows.map((r) => r.toJson()).toList();
    cached['locally_modified'] = true;
    await OfflineStore.instance.cacheSet(cacheKey, cached);
  }

  Future<Fetched<ObjectivesData>> fetchObjectives() async {
    final r = await _getCached('/api/tablet/objectives', 'objectives');
    // Bootstrap may only have objectives array — normalize.
    if (!r.data.containsKey('objectives') && r.data['items'] is List) {
      r.data['objectives'] = r.data['items'];
    }
    return Fetched(ObjectivesData.fromJson(r.data), r.fromCache);
  }

  Future<Fetched<List<ListRow>>> fetchIncomplete() async {
    final r = await _getCached('/api/tablet/incomplete', 'incomplete');
    final tasks = ((r.data['tasks'] as List?) ?? r.data['incomplete_tasks'] as List? ?? [])
        .whereType<Map>()
        .map((e) => ListRow.fromJson(e.cast<String, dynamic>()))
        .toList();
    return Fetched(tasks, r.fromCache);
  }

  Future<Fetched<Map<String, dynamic>>> fetchBootstrap() async {
    final r = await _getCached('/api/tablet/bootstrap', 'bootstrap');
    if (!r.fromCache) {
      // Seed common keys from bootstrap payload.
      final data = r.data;
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
    }
    return r;
  }
}
