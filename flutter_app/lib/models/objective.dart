class Objective {
  final int id;
  final int sortOrder;
  final String text;

  const Objective({
    required this.id,
    required this.sortOrder,
    required this.text,
  });

  factory Objective.fromJson(Map<String, dynamic> json) {
    return Objective(
      id: (json['id'] as num?)?.toInt() ?? 0,
      sortOrder: (json['sort_order'] as num?)?.toInt() ?? 0,
      text: (json['text'] ?? '').toString(),
    );
  }
}

class ObjectivesData {
  final int exerciseId;
  final String exerciseName;
  final List<Objective> objectives;

  const ObjectivesData({
    required this.exerciseId,
    required this.exerciseName,
    required this.objectives,
  });

  factory ObjectivesData.fromJson(Map<String, dynamic> json) {
    return ObjectivesData(
      exerciseId: (json['exercise_id'] as num?)?.toInt() ?? 0,
      exerciseName: (json['exercise_name'] ?? '').toString(),
      objectives: ((json['objectives'] as List?) ?? [])
          .whereType<Map>()
          .map((e) => Objective.fromJson(e.cast<String, dynamic>()))
          .toList(),
    );
  }
}
