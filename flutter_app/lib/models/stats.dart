class StatsModel {
  final int completionPct;
  final int completedCount;
  final int totalCount;
  final int incompleteCount;
  final int completedLists;
  final int incompleteLists;

  const StatsModel({
    this.completionPct = 0,
    this.completedCount = 0,
    this.totalCount = 0,
    this.incompleteCount = 0,
    this.completedLists = 0,
    this.incompleteLists = 0,
  });

  factory StatsModel.fromJson(Map<String, dynamic>? json) {
    if (json == null) return const StatsModel();
    int i(String k) => (json[k] as num?)?.toInt() ?? 0;
    return StatsModel(
      completionPct: i('completion_pct'),
      completedCount: i('completed_count'),
      totalCount: i('total_count'),
      incompleteCount: i('incomplete_count'),
      completedLists: i('completed_lists'),
      incompleteLists: i('incomplete_lists'),
    );
  }

  Map<String, dynamic> toJson() => {
    'completion_pct': completionPct,
    'completed_count': completedCount,
    'total_count': totalCount,
    'incomplete_count': incompleteCount,
    'completed_lists': completedLists,
    'incomplete_lists': incompleteLists,
  };
}
