import '../models/list_row.dart';
import '../models/stats.dart';
import 'eval_status.dart';

class HomeWorkEntry {
  final String identity;
  final String kind;
  final int listId;
  final String title;
  final String statusLabel;
  final bool statusDone;
  final String unitKey;
  final String listType;
  final String listTypeLabel;
  final Map<String, dynamic> row;

  const HomeWorkEntry({
    required this.identity,
    required this.kind,
    required this.listId,
    required this.title,
    required this.statusLabel,
    required this.statusDone,
    required this.unitKey,
    required this.listType,
    required this.listTypeLabel,
    required this.row,
  });

  bool get isComplete => evalStatusIsComplete(
        statusLabel: statusLabel,
        statusDone: statusDone,
      );

  bool get isIncomplete => !isComplete;

  ListRow toListRow() => ListRow.fromJson(row);
}

class HomeWorkSnapshot {
  final List<HomeWorkEntry> procedure;
  final List<HomeWorkEntry> dilemma;

  const HomeWorkSnapshot({
    required this.procedure,
    required this.dilemma,
  });

  List<HomeWorkEntry> get all => [...procedure, ...dilemma];

  int get procedureCount => procedure.length;
  int get dilemmaCount => dilemma.length;
  int get totalCount => procedureCount + dilemmaCount;
  int get completedCount => all.where((e) => e.isComplete).length;
  int get incompleteCount => totalCount - completedCount;

  List<HomeWorkEntry> get incomplete =>
      all.where((e) => e.isIncomplete).toList();

  StatsModel get stats {
    final total = totalCount;
    final done = completedCount;
    final pct = total == 0 ? 0 : ((done * 100.0 / total).round()).clamp(0, 100);
    return StatsModel(
      completionPct: pct,
      completedCount: done,
      totalCount: total,
      incompleteCount: total - done,
      completedLists: done,
      incompleteLists: total - done,
    );
  }
}

List<Map<String, dynamic>> uniqueEvalRows(Iterable<Map<String, dynamic>> rows) {
  final seen = <String>{};
  final out = <Map<String, dynamic>>[];
  for (final row in rows) {
    final id = evalListIdentityFromRow(row);
    if (id.endsWith(':0') || id.endsWith(':-1')) continue;
    if (!seen.add(id)) continue;
    out.add(row);
  }
  return out;
}

HomeWorkEntry? workEntryFromRow(Map<String, dynamic> row) {
  final identity = evalListIdentityFromRow(row);
  final kind = identity.startsWith('d:') ? 'dilemma' : 'procedure';
  final listId = int.tryParse(identity.split(':').last) ?? 0;
  if (listId <= 0) return null;
  final parsed = ListRow.fromJson(row);
  return HomeWorkEntry(
    identity: identity,
    kind: kind,
    listId: listId,
    title: parsed.title,
    statusLabel: parsed.statusLabel,
    statusDone: parsed.statusDone,
    unitKey: parsed.unitKey,
    listType: parsed.listType,
    listTypeLabel: parsed.listTypeLabel,
    row: row,
  );
}

HomeWorkSnapshot snapshotFromRows({
  required Iterable<Map<String, dynamic>> procedureRows,
  required Iterable<Map<String, dynamic>> dilemmaRows,
}) {
  final procedure = <HomeWorkEntry>[];
  final dilemma = <HomeWorkEntry>[];
  for (final row in uniqueEvalRows(procedureRows)) {
    final e = workEntryFromRow(row);
    if (e != null) procedure.add(e);
  }
  for (final row in uniqueEvalRows(dilemmaRows)) {
    final e = workEntryFromRow(row);
    if (e != null) dilemma.add(e);
  }
  return HomeWorkSnapshot(procedure: procedure, dilemma: dilemma);
}

Map<String, dynamic> applyStatsToHomePayload(
  Map<String, dynamic> payload,
  HomeWorkSnapshot snap,
) {
  final copy = Map<String, dynamic>.from(payload);
  copy['stats'] = snap.stats.toJson();
  copy['incomplete_tasks'] = [
    for (final e in snap.incomplete) e.row,
  ];
  return copy;
}

/// عناصر الصفحة الرئيسية بالترتيب المطلوب — بدون تكرار أنظمة موجودة.
class HomeFunctionSpec {
  final String id;
  final String title;
  final String route;
  final String? tab;

  const HomeFunctionSpec({
    required this.id,
    required this.title,
    required this.route,
    this.tab,
  });
}

const List<HomeFunctionSpec> kHomeFunctionsExact = [
  HomeFunctionSpec(
    id: 'evaluation_lists',
    title: 'قوائم تقييم الإجراءات',
    route: '/evaluation-lists',
  ),
  HomeFunctionSpec(
    id: 'action_eval',
    title: 'قوائم تقييم المعاضل',
    route: '/action-eval',
  ),
  HomeFunctionSpec(
    id: 'flow',
    title: 'مجرى الأحداث والمعاضل',
    route: '/flow',
  ),
  HomeFunctionSpec(
    id: 'positives_negatives',
    title: 'الإيجابيات والسلبيات',
    route: '/positives-negatives',
  ),
  HomeFunctionSpec(
    id: 'incomplete',
    title: 'المهام غير المكتملة',
    route: '/incomplete',
  ),
  HomeFunctionSpec(
    id: 'objectives',
    title: 'الأهداف التدريبية',
    route: '/objectives',
  ),
  HomeFunctionSpec(
    id: 'exercise_papers',
    title: 'كراسات الواجبات',
    route: '/exercise-papers',
  ),
  HomeFunctionSpec(
    id: 'program',
    title: 'برنامج التمرين',
    route: '/exercise-details',
    tab: 'program',
  ),
  HomeFunctionSpec(
    id: 'map',
    title: 'الخريطة',
    route: '/exercise-details',
    tab: 'map',
  ),
  HomeFunctionSpec(
    id: 'library',
    title: 'المكتبة',
    route: '/library',
  ),
];
