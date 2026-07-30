class FlowDay {
  final String id;
  final String label;
  final String note;
  final String phaseKey;

  const FlowDay({
    required this.id,
    required this.label,
    required this.note,
    required this.phaseKey,
  });

  factory FlowDay.fromJson(Map<String, dynamic> json) {
    return FlowDay(
      id: (json['id'] ?? '').toString(),
      label: (json['label'] ?? '').toString(),
      note: (json['note'] ?? '').toString(),
      phaseKey: (json['phase_key'] ?? '').toString(),
    );
  }
}

class FlowRow {
  final int seq;
  final String kind;
  final String time;
  final String text;
  final String assignee;
  final String method;
  final String expected;
  final String tone; // event | dilemma | row

  const FlowRow({
    required this.seq,
    required this.kind,
    required this.time,
    required this.text,
    required this.assignee,
    required this.method,
    required this.expected,
    required this.tone,
  });

  factory FlowRow.fromJson(Map<String, dynamic> json) {
    return FlowRow(
      seq: (json['seq'] as num?)?.toInt() ?? 0,
      kind: (json['kind'] ?? '').toString(),
      time: (json['time'] ?? '').toString(),
      text: (json['text'] ?? '').toString(),
      assignee: (json['assignee'] ?? '').toString(),
      method: (json['method'] ?? '').toString(),
      expected: (json['expected'] ?? '').toString(),
      tone: (json['tone'] ?? 'row').toString(),
    );
  }
}

class FlowData {
  final int exerciseId;
  final String unitKey;
  final String unitLabel;
  final String title;
  final String activeDayId;
  final List<FlowDay> days;
  final List<FlowRow> rows;
  final bool readonly;

  const FlowData({
    required this.exerciseId,
    required this.unitKey,
    required this.unitLabel,
    required this.title,
    required this.activeDayId,
    required this.days,
    required this.rows,
    required this.readonly,
  });

  factory FlowData.fromJson(Map<String, dynamic> json) {
    return FlowData(
      exerciseId: (json['exercise_id'] as num?)?.toInt() ?? 0,
      unitKey: (json['unit_key'] ?? '').toString(),
      unitLabel: (json['unit_label'] ?? '').toString(),
      title: (json['title'] ?? '').toString(),
      activeDayId: (json['active_day_id'] ?? '').toString(),
      days: ((json['days'] as List?) ?? [])
          .whereType<Map>()
          .map((e) => FlowDay.fromJson(e.cast<String, dynamic>()))
          .toList(),
      rows: ((json['rows'] as List?) ?? [])
          .whereType<Map>()
          .map((e) => FlowRow.fromJson(e.cast<String, dynamic>()))
          .toList(),
      readonly: json['readonly'] != false,
    );
  }
}
