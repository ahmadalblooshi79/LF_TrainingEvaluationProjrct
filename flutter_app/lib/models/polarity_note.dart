class PolarityNote {
  final int? id;
  final String clientUuid;
  final String polarity; // positive | negative
  final String body;
  final String sourceKind; // general | criterion | action_eval
  final int? evaluationListItemId;
  final int? bundleActionEvalId;
  final int? rowIndex;
  final String criterionLabel;
  final String unitLevelKey;
  final String syncStatus;
  final String createdAt;
  final String updatedAt;

  const PolarityNote({
    this.id,
    required this.clientUuid,
    required this.polarity,
    required this.body,
    this.sourceKind = 'general',
    this.evaluationListItemId,
    this.bundleActionEvalId,
    this.rowIndex,
    this.criterionLabel = '',
    this.unitLevelKey = '',
    this.syncStatus = 'synced',
    this.createdAt = '',
    this.updatedAt = '',
  });

  bool get isPositive => polarity == 'positive';

  factory PolarityNote.fromJson(Map<String, dynamic> json) {
    return PolarityNote(
      id: (json['id'] as num?)?.toInt(),
      clientUuid: (json['client_uuid'] ?? '').toString(),
      polarity: (json['polarity'] ?? 'positive').toString(),
      body: (json['body'] ?? '').toString(),
      sourceKind: (json['source_kind'] ?? 'general').toString(),
      evaluationListItemId: (json['evaluation_list_item_id'] as num?)?.toInt(),
      bundleActionEvalId: (json['bundle_action_eval_id'] as num?)?.toInt(),
      rowIndex: (json['row_index'] as num?)?.toInt(),
      criterionLabel: (json['criterion_label'] ?? '').toString(),
      unitLevelKey: (json['unit_level_key'] ?? '').toString(),
      syncStatus: (json['sync_status'] ?? 'synced').toString(),
      createdAt: (json['created_at'] ?? '').toString(),
      updatedAt: (json['updated_at'] ?? '').toString(),
    );
  }

  Map<String, dynamic> toJson() => {
        if (id != null) 'id': id,
        'client_uuid': clientUuid,
        'polarity': polarity,
        'body': body,
        'source_kind': sourceKind,
        if (evaluationListItemId != null)
          'evaluation_list_item_id': evaluationListItemId,
        if (bundleActionEvalId != null)
          'bundle_action_eval_id': bundleActionEvalId,
        if (rowIndex != null) 'row_index': rowIndex,
        'criterion_label': criterionLabel,
        'unit_level_key': unitLevelKey,
        'sync_status': syncStatus,
        'created_at': createdAt,
        'updated_at': updatedAt,
      };

  PolarityNote copyWith({
    int? id,
    String? body,
    String? polarity,
    String? syncStatus,
    String? updatedAt,
  }) {
    return PolarityNote(
      id: id ?? this.id,
      clientUuid: clientUuid,
      polarity: polarity ?? this.polarity,
      body: body ?? this.body,
      sourceKind: sourceKind,
      evaluationListItemId: evaluationListItemId,
      bundleActionEvalId: bundleActionEvalId,
      rowIndex: rowIndex,
      criterionLabel: criterionLabel,
      unitLevelKey: unitLevelKey,
      syncStatus: syncStatus ?? this.syncStatus,
      createdAt: createdAt,
      updatedAt: updatedAt ?? this.updatedAt,
    );
  }
}

class PolarityNotesBundle {
  final List<PolarityNote> notes;
  final String unitKey;
  final String unitLabel;
  final int posCount;
  final int negCount;

  const PolarityNotesBundle({
    required this.notes,
    this.unitKey = '',
    this.unitLabel = '',
    this.posCount = 0,
    this.negCount = 0,
  });

  factory PolarityNotesBundle.fromJson(Map<String, dynamic> json) {
    final notes = ((json['notes'] as List?) ?? [])
        .whereType<Map>()
        .map((e) => PolarityNote.fromJson(e.cast<String, dynamic>()))
        .toList();
    final pos = (json['notes_pos_count'] as num?)?.toInt() ??
        notes.where((n) => n.isPositive).length;
    final neg = (json['notes_neg_count'] as num?)?.toInt() ??
        notes.where((n) => !n.isPositive).length;
    return PolarityNotesBundle(
      notes: notes,
      unitKey: (json['unit_key'] ?? '').toString(),
      unitLabel: (json['unit_label'] ?? '').toString(),
      posCount: pos,
      negCount: neg,
    );
  }
}
