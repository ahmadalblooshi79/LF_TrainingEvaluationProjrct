/// One row of a structured evaluation sheet (rubric layout parsed from the
/// original Excel template on the server).
class EvalRow {
  final String rowKind; // 'score' | 'section'
  final String element;
  final String elementPrefixKind;
  final String elementPrefix;
  final String elementRest;
  final int elementIndent;
  final String maxVal;
  final double? maxNum;
  final String acquiredRaw;
  final String acquiredInitial;
  final String notesInitial;

  const EvalRow({
    required this.rowKind,
    required this.element,
    required this.elementPrefixKind,
    required this.elementPrefix,
    required this.elementRest,
    required this.elementIndent,
    required this.maxVal,
    required this.maxNum,
    required this.acquiredRaw,
    required this.acquiredInitial,
    required this.notesInitial,
  });

  bool get isSection => rowKind == 'section';

  factory EvalRow.fromJson(Map<String, dynamic> json) {
    double? maxNum;
    final rawMax = json['max_num'];
    if (rawMax is num && rawMax.isFinite) maxNum = rawMax.toDouble();
    return EvalRow(
      rowKind: (json['row_kind'] ?? 'score').toString(),
      element: (json['element'] ?? '').toString(),
      elementPrefixKind: (json['element_prefix_kind'] ?? 'plain').toString(),
      elementPrefix: (json['element_prefix'] ?? '').toString(),
      elementRest: (json['element_rest'] ?? '').toString(),
      elementIndent: (json['element_indent'] as num?)?.toInt() ?? 0,
      maxVal: (json['max_val'] ?? '').toString(),
      maxNum: maxNum,
      acquiredRaw: (json['acquired_raw'] ?? '').toString(),
      acquiredInitial: (json['acquired_initial'] ?? '').toString(),
      notesInitial: (json['notes_initial'] ?? '').toString(),
    );
  }
}

class AcquiredOption {
  final String value;
  final String label;

  const AcquiredOption(this.value, this.label);

  factory AcquiredOption.fromJson(dynamic json) {
    if (json is List && json.length >= 2) {
      return AcquiredOption(json[0].toString(), json[1].toString());
    }
    if (json is Map) {
      return AcquiredOption(
        (json['value'] ?? '').toString(),
        (json['label'] ?? json['value'] ?? '').toString(),
      );
    }
    return const AcquiredOption('', '—');
  }
}

/// A single editable row kept in memory while the judge fills the sheet.
class EvalRowInput {
  String rowKind;
  String element;
  String maxVal;
  String acquired;
  String notes;
  final List<String> localMediaPaths;

  EvalRowInput({
    required this.rowKind,
    required this.element,
    required this.maxVal,
    required this.acquired,
    required this.notes,
    List<String>? localMediaPaths,
  }) : localMediaPaths = localMediaPaths ?? [];

  factory EvalRowInput.fromEvalRow(EvalRow row) {
    return EvalRowInput(
      rowKind: row.rowKind,
      element: row.element,
      maxVal: row.maxVal,
      acquired: row.acquiredInitial,
      notes: row.notesInitial,
    );
  }

  factory EvalRowInput.fromSaved(Map<String, dynamic> json) {
    return EvalRowInput(
      rowKind: (json['row_kind'] ?? 'score').toString(),
      element: (json['element'] ?? '').toString(),
      maxVal: (json['max_val'] ?? '').toString(),
      acquired: (json['acquired'] ?? '').toString(),
      notes: (json['notes'] ?? '').toString(),
    );
  }

  Map<String, dynamic> toJson() => {
        'row_kind': rowKind,
        'element': element,
        'max_val': maxVal,
        'acquired': acquired,
        'notes': notes,
      };
}

class EvalWorkflow {
  final String label;
  final bool reopened;

  const EvalWorkflow({required this.label, required this.reopened});

  factory EvalWorkflow.fromJson(Map<String, dynamic>? json) {
    if (json == null) return const EvalWorkflow(label: '', reopened: false);
    return EvalWorkflow(
      label: (json['label'] ?? '').toString(),
      reopened: json['reopened'] == true,
    );
  }
}

List<Map<String, dynamic>> _mapsFrom(dynamic raw) {
  if (raw is! List) return const [];
  final out = <Map<String, dynamic>>[];
  for (final e in raw) {
    if (e is Map) out.add(Map<String, dynamic>.from(e));
  }
  return out;
}

/// Detail of an action-eval slot or evaluation-list item (same shape).
class EvalSheetDetail {
  final String kind; // action_eval | evaluation_list
  final int? slot;
  final int? slotId;
  final int? itemId;
  final String title;
  final String unitKey;
  final String unitLabel;
  final String phaseKey;
  final List<EvalRow> evalRows;
  final bool evalStructured;
  final List<AcquiredOption> acquiredOptions;
  final List<EvalRowInput> savedRows;
  final bool canEdit;
  final bool canApprove;
  final bool isApproved;
  final bool locallyApproved;
  final String approvalSyncStatus;
  final EvalWorkflow workflow;

  const EvalSheetDetail({
    required this.kind,
    required this.slot,
    required this.slotId,
    required this.itemId,
    required this.title,
    required this.unitKey,
    required this.unitLabel,
    required this.phaseKey,
    required this.evalRows,
    required this.evalStructured,
    required this.acquiredOptions,
    required this.savedRows,
    required this.canEdit,
    required this.canApprove,
    required this.isApproved,
    this.locallyApproved = false,
    this.approvalSyncStatus = '',
    required this.workflow,
  });

  factory EvalSheetDetail.fromJson(Map<String, dynamic> json) {
    final evalRows = _mapsFrom(json['eval_rows']).map(EvalRow.fromJson).toList();

    final savedPayload = json['saved_payload'] is Map
        ? Map<String, dynamic>.from(json['saved_payload'] as Map)
        : <String, dynamic>{};
    final savedRowsRaw = _mapsFrom(
      savedPayload['rows'] ?? json['saved_rows'],
    );

    // Always seed from the Excel template so the sheet never renders empty
    // when eval_rows exist; overlay any previously saved acquired/notes.
    final editable = evalRows.map(EvalRowInput.fromEvalRow).toList();
    if (savedRowsRaw.isNotEmpty) {
      final n = editable.length < savedRowsRaw.length ? editable.length : savedRowsRaw.length;
      for (var i = 0; i < n; i++) {
        final m = savedRowsRaw[i];
        if (m.containsKey('acquired')) {
          editable[i].acquired = (m['acquired'] ?? '').toString();
        }
        if (m.containsKey('notes')) {
          editable[i].notes = (m['notes'] ?? '').toString();
        }
        if (m.containsKey('element') && (m['element'] ?? '').toString().trim().isNotEmpty) {
          editable[i].element = (m['element'] ?? '').toString();
        }
        if (m.containsKey('max_val') && (m['max_val'] ?? '').toString().trim().isNotEmpty) {
          editable[i].maxVal = (m['max_val'] ?? '').toString();
        }
        if (m.containsKey('row_kind') && (m['row_kind'] ?? '').toString().trim().isNotEmpty) {
          editable[i].rowKind = (m['row_kind'] ?? '').toString();
        }
      }
    }

    final workflow = EvalWorkflow.fromJson(
      json['workflow'] is Map
          ? Map<String, dynamic>.from(json['workflow'] as Map)
          : null,
    );
    // السيرفر بعد الإعادة يبقي is_approved=true مع can_edit=true حتى يحفظ المحكم.
    // نثق بأعلام can_edit/can_approve من السيرفر؛ الاعتماد المحلي فقط يقفل قبل الإعادة.
    final reopened = workflow.reopened;
    final locallyApproved =
        json['locally_approved'] == true && !reopened;
    final serverCanEdit = json['can_edit'] == true;
    final serverCanApprove = json['can_approve'] == true;
    final bool canEdit;
    final bool canApprove;
    final bool isApproved;
    if (locallyApproved) {
      canEdit = false;
      canApprove = false;
      isApproved = true;
    } else {
      canEdit = serverCanEdit;
      canApprove = serverCanApprove;
      // واجهة «معتمد ومقفول» فقط عندما لا يُسمح بالتعديل
      isApproved = json['is_approved'] == true && !canEdit;
    }
    return EvalSheetDetail(
      kind: (json['kind'] ?? '').toString(),
      slot: (json['slot'] as num?)?.toInt(),
      slotId: (json['slot_id'] as num?)?.toInt(),
      itemId: (json['item_id'] as num?)?.toInt(),
      title: (json['title'] ?? '').toString(),
      unitKey: (json['unit_key'] ?? '').toString(),
      unitLabel: (json['unit_label'] ?? '').toString(),
      phaseKey: (json['phase_key'] ?? '').toString(),
      evalRows: evalRows,
      evalStructured: json['eval_structured'] == true || evalRows.isNotEmpty,
      acquiredOptions: ((json['acquired_options'] as List?) ?? [])
          .map(AcquiredOption.fromJson)
          .toList(),
      savedRows: editable,
      canEdit: canEdit,
      canApprove: canApprove,
      isApproved: isApproved,
      locallyApproved: locallyApproved,
      approvalSyncStatus: (json['approval_sync_status'] ?? '').toString(),
      workflow: workflow,
    );
  }
}
