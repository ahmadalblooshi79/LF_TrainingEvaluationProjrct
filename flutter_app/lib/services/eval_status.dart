/// حالات موقف التقييم المعتمدة في التطبيق (ليست تسميات واجهة فقط).
const String kEvalStatusWaiting = 'بإنتظار الإعتماد';
const String kEvalStatusApproved = 'معتمد';
const String kEvalStatusReopened = 'معاد للتقييم';
const String kEvalStatusNotDone = 'لم ينجز';
const String kEvalStatusNa = 'لا ينطبق';

bool evalStatusIsApprovedLabel(String raw) {
  final s = raw.trim();
  return s == kEvalStatusApproved || s == 'منجز' || s == 'ينجز';
}

bool evalStatusIsWaitingLabel(String raw) {
  final s = raw.trim();
  return s.contains('بإنتظار') || s.contains('بانتظار');
}

bool evalStatusIsReopenedLabel(String raw) {
  return raw.contains('معاد');
}

bool evalStatusIsComplete({
  required String statusLabel,
  bool statusDone = false,
}) {
  if (evalStatusIsReopenedLabel(statusLabel)) return false;
  if (evalStatusIsWaitingLabel(statusLabel)) return false;
  return statusDone || evalStatusIsApprovedLabel(statusLabel);
}

bool evalStatusIsIncomplete({
  required String statusLabel,
  bool statusDone = false,
}) {
  return !evalStatusIsComplete(
    statusLabel: statusLabel,
    statusDone: statusDone,
  );
}

String evalListIdentity({
  required String kind,
  int? itemId,
  int? slotId,
  int? slotIndex,
  dynamic id,
}) {
  if (kind == 'dilemma') {
    final n = slotId ?? slotIndex ?? _asInt(id);
    return 'd:${n ?? 0}';
  }
  final n = itemId ?? _asInt(id);
  return 'p:${n ?? 0}';
}

String evalListIdentityFromRow(Map<String, dynamic> row) {
  final listType = '${row['list_type'] ?? row['list_type_kind'] ?? ''}'.toLowerCase();
  final hasSlot = row.containsKey('slot_id') ||
      row.containsKey('slot_index') ||
      listType.contains('action') ||
      listType.contains('planner');
  if (hasSlot &&
      (row['item_id'] == null ||
          listType.contains('action') ||
          listType.contains('planner'))) {
    return evalListIdentity(
      kind: 'dilemma',
      slotId: _asInt(row['slot_id']),
      slotIndex: _asInt(row['slot_index']),
      id: row['id'],
    );
  }
  return evalListIdentity(
    kind: 'procedure',
    itemId: _asInt(row['item_id'] ?? row['id']),
    id: row['id'],
  );
}

/// حالة الورقة من كاش التفاصيل المحلي.
String evalStatusFromSheet(Map<String, dynamic> sheet) {
  final wf = sheet['workflow'];
  final reopened = (wf is Map && wf['reopened'] == true) ||
      sheet['device_manager_reopened'] == true;
  if (reopened) return kEvalStatusReopened;
  if (sheet['locally_approved'] == true ||
      (sheet['is_approved'] == true && sheet['can_edit'] != true)) {
    if (_sheetAllNa(sheet)) return kEvalStatusNa;
    return kEvalStatusApproved;
  }
  if (sheet['locally_modified'] == true || _sheetHasSavedWork(sheet)) {
    if (_sheetAllNa(sheet)) return kEvalStatusNa;
    return kEvalStatusWaiting;
  }
  final labeled = '${sheet['status_label'] ?? ''}'.trim();
  if (labeled.isNotEmpty) return labeled;
  return kEvalStatusNotDone;
}

bool _sheetHasSavedWork(Map<String, dynamic> sheet) {
  if (sheet['saved_rows'] is List && (sheet['saved_rows'] as List).isNotEmpty) {
    return true;
  }
  final payload = sheet['saved_payload'];
  if (payload is Map) {
    final rows = payload['rows'];
    return rows is List && rows.isNotEmpty;
  }
  return false;
}

bool _sheetAllNa(Map<String, dynamic> sheet) {
  final payload = sheet['saved_payload'];
  List<dynamic>? rows;
  if (payload is Map && payload['rows'] is List) {
    rows = payload['rows'] as List;
  } else if (sheet['saved_rows'] is List) {
    rows = sheet['saved_rows'] as List;
  }
  if (rows == null || rows.isEmpty) return false;
  final scores = rows.whereType<Map>().where((r) {
    return '${r['row_kind'] ?? 'score'}' != 'section';
  });
  if (scores.isEmpty) return false;
  return scores.every((r) {
    final a = '${r['acquired'] ?? ''}'.trim().toLowerCase();
    return a == 'na' || a == 'n/a' || a == 'لا ينطبق';
  });
}

int? _asInt(dynamic v) {
  if (v == null) return null;
  if (v is int) return v;
  if (v is num) return v.toInt();
  return int.tryParse('$v'.trim());
}
