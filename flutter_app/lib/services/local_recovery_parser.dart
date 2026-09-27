import 'dart:convert';

/// Recovery format written into export packages. Independent of DB schema.
const String kRecoveryFormatVersion = '1';

/// Every SQL issued by Local Recovery. Tests assert these are SELECT-only.
const List<String> kRecoverySelectOnlySql = [
  'SELECT * FROM pending_ops ORDER BY created_at ASC',
  'SELECT * FROM cache ORDER BY cache_key ASC',
  'SELECT * FROM media_files ORDER BY created_at ASC',
  'SELECT * FROM device_meta',
  'SELECT * FROM local_users',
];

final _writeSql = RegExp(
  r'\b(UPDATE|DELETE|INSERT|DROP|ALTER|REPLACE)\b',
  caseSensitive: false,
);

bool recoverySqlIsReadOnly(String sql) => !_writeSql.hasMatch(sql);

int? recoveryAsInt(dynamic v) {
  if (v == null) return null;
  if (v is int) return v;
  if (v is num) return v.toInt();
  return int.tryParse('$v'.trim());
}

String recoveryAsString(dynamic v) {
  if (v == null) return '';
  return '$v';
}

bool recoveryIsEvaluationCacheKey(String key) {
  return key.contains('evaluation_list_detail') ||
      key.contains('action_eval_detail');
}

bool recoveryIsSignatureCacheKey(String key) {
  return key.contains('judge_signature');
}

String recoveryPendingBodyRaw(Map<String, dynamic> row) {
  final b = row['body'];
  if (b is String) return b;
  if (b == null) return '';
  try {
    return jsonEncode(b);
  } catch (_) {
    return '$b';
  }
}

class RecoveredEvalRow {
  final String rowKind;
  final String element;
  final String maxVal;
  final String acquired;
  final String notes;

  const RecoveredEvalRow({
    required this.rowKind,
    required this.element,
    required this.maxVal,
    required this.acquired,
    required this.notes,
  });

  bool get hasScore => acquired.trim().isNotEmpty;
  bool get hasNotes => notes.trim().isNotEmpty;

  Map<String, dynamic> toJson() => {
        'row_kind': rowKind,
        'element': element,
        'max_val': maxVal,
        'acquired': acquired,
        'notes': notes,
      };

  String fingerprint() =>
      '${rowKind.trim()}|${element.trim()}|${maxVal.trim()}|${acquired.trim()}|${notes.trim()}';

  factory RecoveredEvalRow.fromMap(Map<String, dynamic> m) {
    return RecoveredEvalRow(
      rowKind: recoveryAsString(m['row_kind']),
      element: recoveryAsString(m['element']),
      maxVal: recoveryAsString(m['max_val']),
      acquired: recoveryAsString(m['acquired']),
      notes: recoveryAsString(m['notes']),
    );
  }
}

class ParsedPendingBody {
  final bool parseSuccessful;
  final String rawBody;
  final String clientOpId;
  final List<RecoveredEvalRow> rows;
  final Map<String, dynamic>? decoded;

  const ParsedPendingBody({
    required this.parseSuccessful,
    required this.rawBody,
    required this.clientOpId,
    required this.rows,
    this.decoded,
  });

  int get rowsWithScores => rows.where((r) => r.hasScore).length;
  int get rowsWithNotes => rows.where((r) => r.hasNotes).length;
}

ParsedPendingBody parsePendingBody(String rawBody) {
  if (rawBody.trim().isEmpty) {
    return ParsedPendingBody(
      parseSuccessful: false,
      rawBody: rawBody,
      clientOpId: '',
      rows: const [],
    );
  }
  try {
    final decoded = jsonDecode(rawBody);
    if (decoded is! Map) {
      return ParsedPendingBody(
        parseSuccessful: false,
        rawBody: rawBody,
        clientOpId: '',
        rows: const [],
      );
    }
    final root = Map<String, dynamic>.from(decoded);
    final clientOpId = recoveryAsString(
      root['client_op_id'] ?? root['clientOpId'],
    );
    Map<String, dynamic> payload = root;
    final p = root['payload'];
    if (p is Map) payload = Map<String, dynamic>.from(p);
    final rawRows = payload['rows'];
    final rows = <RecoveredEvalRow>[];
    if (rawRows is List) {
      for (final item in rawRows) {
        if (item is Map) {
          rows.add(RecoveredEvalRow.fromMap(Map<String, dynamic>.from(item)));
        }
      }
    }
    return ParsedPendingBody(
      parseSuccessful: true,
      rawBody: rawBody,
      clientOpId: clientOpId,
      rows: rows,
      decoded: root,
    );
  } catch (_) {
    return ParsedPendingBody(
      parseSuccessful: false,
      rawBody: rawBody,
      clientOpId: '',
      rows: const [],
    );
  }
}

class ParsedCacheEvaluation {
  final String cacheKey;
  final String syncStatus;
  final String updatedAt;
  final String jsonBodyRaw;
  final bool locallyModified;
  final bool savedPayloadExists;
  final List<RecoveredEvalRow> savedRows;
  final int? userId;
  final int? evalItemId;
  final String? listId;
  final bool parseSuccessful;

  const ParsedCacheEvaluation({
    required this.cacheKey,
    required this.syncStatus,
    required this.updatedAt,
    required this.jsonBodyRaw,
    required this.locallyModified,
    required this.savedPayloadExists,
    required this.savedRows,
    this.userId,
    this.evalItemId,
    this.listId,
    required this.parseSuccessful,
  });

  String identity() {
    if ((evalItemId ?? 0) > 0) return 'eval:$evalItemId';
    if ((listId ?? '').isNotEmpty) return 'list:$listId';
    return 'cache:$cacheKey';
  }
}

ParsedCacheEvaluation parseCacheEvaluationRow(Map<String, dynamic> row) {
  final key = recoveryAsString(row['cache_key']);
  final jsonBody = recoveryAsString(row['json_body']);
  final syncStatus = recoveryAsString(row['sync_status']);
  final updatedAt = recoveryAsString(row['updated_at']);
  final userId = _userIdFromCacheKey(key);
  final ids = _idsFromCacheKey(key);

  if (jsonBody.trim().isEmpty) {
    return ParsedCacheEvaluation(
      cacheKey: key,
      syncStatus: syncStatus,
      updatedAt: updatedAt,
      jsonBodyRaw: jsonBody,
      locallyModified: false,
      savedPayloadExists: false,
      savedRows: const [],
      userId: userId,
      evalItemId: ids.evalItemId,
      listId: ids.listId,
      parseSuccessful: false,
    );
  }

  try {
    final decoded = jsonDecode(jsonBody);
    if (decoded is! Map) {
      return ParsedCacheEvaluation(
        cacheKey: key,
        syncStatus: syncStatus,
        updatedAt: updatedAt,
        jsonBodyRaw: jsonBody,
        locallyModified: false,
        savedPayloadExists: false,
        savedRows: const [],
        userId: userId,
        evalItemId: ids.evalItemId,
        listId: ids.listId,
        parseSuccessful: false,
      );
    }
    final root = Map<String, dynamic>.from(decoded);
    final locallyModified = root['locally_modified'] == true ||
        recoveryAsString(root['locally_modified']).toLowerCase() == 'true';
    final savedPayload = root['saved_payload'];
    final savedPayloadExists = savedPayload is Map || savedPayload is List;
    final rows = _rowsFromCacheMap(root);
    return ParsedCacheEvaluation(
      cacheKey: key,
      syncStatus: syncStatus,
      updatedAt: updatedAt,
      jsonBodyRaw: jsonBody,
      locallyModified: locallyModified,
      savedPayloadExists: savedPayloadExists,
      savedRows: rows,
      userId: userId,
      evalItemId: ids.evalItemId ?? recoveryAsInt(root['id']),
      listId: ids.listId,
      parseSuccessful: true,
    );
  } catch (_) {
    return ParsedCacheEvaluation(
      cacheKey: key,
      syncStatus: syncStatus,
      updatedAt: updatedAt,
      jsonBodyRaw: jsonBody,
      locallyModified: false,
      savedPayloadExists: false,
      savedRows: const [],
      userId: userId,
      evalItemId: ids.evalItemId,
      listId: ids.listId,
      parseSuccessful: false,
    );
  }
}

class _CacheIds {
  final int? evalItemId;
  final String? listId;
  const _CacheIds(this.evalItemId, this.listId);
}

int? _userIdFromCacheKey(String key) {
  final m = RegExp(r'^u(\d+):').firstMatch(key);
  if (m == null) return null;
  return int.tryParse(m.group(1)!);
}

_CacheIds _idsFromCacheKey(String key) {
  final parts = key.split(':');
  if (parts.isEmpty) return const _CacheIds(null, null);
  final last = parts.last.trim();
  final asInt = int.tryParse(last);
  if (key.contains('evaluation_list_detail') && asInt != null) {
    return _CacheIds(asInt, last);
  }
  if (key.contains('action_eval_detail')) {
    return _CacheIds(null, 'action:$last');
  }
  return _CacheIds(asInt, last.isEmpty ? null : last);
}

List<RecoveredEvalRow> _rowsFromCacheMap(Map<String, dynamic> root) {
  final out = <RecoveredEvalRow>[];
  void addFrom(dynamic raw) {
    if (raw is! List) return;
    for (final item in raw) {
      if (item is Map) {
        out.add(RecoveredEvalRow.fromMap(Map<String, dynamic>.from(item)));
      }
    }
  }

  addFrom(root['saved_rows']);
  if (out.isNotEmpty) return out;
  final payload = root['saved_payload'];
  if (payload is Map) addFrom(payload['rows']);
  if (out.isNotEmpty) return out;
  addFrom(root['rows']);
  return out;
}

class RecoveredPendingOp {
  final String id;
  final String method;
  final String path;
  final String kind;
  final String opType;
  final String createdAt;
  final int attempts;
  final String lastError;
  final String syncStatus;
  final int? judgeId;
  final int? userId;
  final int? exerciseId;
  final String listId;
  final int? evalItemId;
  final String mediaLocalPath;
  final String rawBody;
  final ParsedPendingBody parsed;

  const RecoveredPendingOp({
    required this.id,
    required this.method,
    required this.path,
    required this.kind,
    required this.opType,
    required this.createdAt,
    required this.attempts,
    required this.lastError,
    required this.syncStatus,
    this.judgeId,
    this.userId,
    this.exerciseId,
    required this.listId,
    this.evalItemId,
    required this.mediaLocalPath,
    required this.rawBody,
    required this.parsed,
  });

  bool get isSaveResults =>
      opType == 'save_results' ||
      path.contains('save-results') ||
      path.contains('save_results');

  bool get isFailed =>
      syncStatus == 'failed' ||
      syncStatus == 'conflict' ||
      lastError.trim().isNotEmpty && syncStatus != 'synced';

  String identity() {
    if ((evalItemId ?? 0) > 0) return 'eval:$evalItemId';
    if (listId.isNotEmpty) return 'list:$listId';
    return 'op:$id';
  }

  Map<String, dynamic> toJson({bool includeParsed = true}) {
    final m = <String, dynamic>{
      'id': id,
      'method': method,
      'path': path,
      'kind': kind,
      'op_type': opType,
      'created_at': createdAt,
      'attempts': attempts,
      'last_error': lastError,
      'sync_status': syncStatus,
      'judge_id': judgeId,
      'user_id': userId,
      'exercise_id': exerciseId,
      'list_id': listId,
      'eval_item_id': evalItemId,
      'media_local_path': mediaLocalPath,
      'body': rawBody,
      'body_parse_successful': parsed.parseSuccessful ? 'YES' : 'NO',
      'rows_found': parsed.rows.length,
      'rows_with_scores': parsed.rowsWithScores,
      'rows_with_notes': parsed.rowsWithNotes,
      'client_op_id': parsed.clientOpId,
    };
    if (includeParsed && parsed.parseSuccessful) {
      m['parsed_rows'] = parsed.rows.map((r) => r.toJson()).toList();
    }
    return m;
  }

  factory RecoveredPendingOp.fromRow(Map<String, dynamic> row) {
    final raw = recoveryPendingBodyRaw(row);
    final parsed = parsePendingBody(raw);
    return RecoveredPendingOp(
      id: recoveryAsString(row['id']),
      method: recoveryAsString(row['method']),
      path: recoveryAsString(row['path']),
      kind: recoveryAsString(row['kind']),
      opType: recoveryAsString(row['op_type']),
      createdAt: recoveryAsString(row['created_at']),
      attempts: recoveryAsInt(row['attempts']) ?? 0,
      lastError: recoveryAsString(row['last_error']),
      syncStatus: recoveryAsString(row['sync_status']),
      judgeId: recoveryAsInt(row['judge_id']),
      userId: recoveryAsInt(row['user_id']),
      exerciseId: recoveryAsInt(row['exercise_id']),
      listId: recoveryAsString(row['list_id']),
      evalItemId: recoveryAsInt(row['eval_item_id']),
      mediaLocalPath: recoveryAsString(row['media_local_path']),
      rawBody: raw,
      parsed: parsed,
    );
  }
}

class RecoveredMediaItem {
  final Map<String, dynamic> fields;
  final bool fileExists;
  final int actualFileSize;
  final String copyError;

  const RecoveredMediaItem({
    required this.fields,
    required this.fileExists,
    required this.actualFileSize,
    this.copyError = '',
  });

  String get id => recoveryAsString(fields['id']);
  String get localPath => recoveryAsString(fields['local_path']);
  String get mediaKind => recoveryAsString(fields['media_kind']);
  int? get evaluationListItemId =>
      recoveryAsInt(fields['evaluation_list_item_id']);
  int? get bundleActionEvalId => recoveryAsInt(fields['bundle_action_eval_id']);

  bool get isImage {
    final k = mediaKind.toLowerCase();
    return k.contains('photo') ||
        k.contains('image') ||
        k.contains('pic') ||
        k.contains('jpg') ||
        k.contains('png');
  }

  bool get isVideo {
    final k = mediaKind.toLowerCase();
    return k.contains('video') || k.contains('mp4') || k.contains('mov');
  }

  Map<String, dynamic> toJson() {
    final m = Map<String, dynamic>.from(fields);
    m['file_exists'] = fileExists ? 'YES' : 'NO';
    m['actual_file_size'] = actualFileSize;
    if (copyError.isNotEmpty) m['copy_error'] = copyError;
    return m;
  }
}

class RecoveryIdentityStatus {
  final String identity;
  final bool pendingCopyExists;
  final bool cacheCopyExists;
  final bool sourceMismatch;
  final int? evalItemId;

  const RecoveryIdentityStatus({
    required this.identity,
    required this.pendingCopyExists,
    required this.cacheCopyExists,
    required this.sourceMismatch,
    this.evalItemId,
  });

  String get recoveryStatus {
    if (sourceMismatch) return 'SOURCE MISMATCH';
    if (pendingCopyExists && cacheCopyExists) return 'BOTH';
    if (pendingCopyExists) return 'PENDING_ONLY';
    if (cacheCopyExists) return 'CACHE_ONLY';
    return 'NONE';
  }
}

class EvalItemFocus {
  final int evalItemId;
  final bool pendingSaveFound;
  final int rowsFound;
  final int rowsWithScores;
  final int rowsWithNotes;
  final int associatedMedia;
  final String syncStatus;
  final int attempts;
  final String lastError;

  const EvalItemFocus({
    required this.evalItemId,
    required this.pendingSaveFound,
    required this.rowsFound,
    required this.rowsWithScores,
    required this.rowsWithNotes,
    required this.associatedMedia,
    required this.syncStatus,
    required this.attempts,
    required this.lastError,
  });
}

class RecoveryContext {
  final String exportTimestamp;
  final String appVersion;
  final String deviceId;
  final int? exerciseId;
  final int? judgeId;
  final int? userId;
  final String judgeName;
  final String unit;
  final String databaseVersion;

  const RecoveryContext({
    required this.exportTimestamp,
    required this.appVersion,
    required this.deviceId,
    this.exerciseId,
    this.judgeId,
    this.userId,
    required this.judgeName,
    required this.unit,
    required this.databaseVersion,
  });

  Map<String, dynamic> toJson() => {
        'export_timestamp': exportTimestamp,
        'app_version': appVersion,
        'device_id': deviceId,
        'exercise_id': exerciseId,
        'judge_id': judgeId,
        'user_id': userId,
        'judge_name': judgeName,
        'unit': unit,
        'database_version': databaseVersion,
      };
}

class LocalRecoveryScan {
  final RecoveryContext context;
  final List<RecoveredPendingOp> pendingOps;
  final List<ParsedCacheEvaluation> cacheEvaluations;
  final List<Map<String, dynamic>> signatureCacheEntries;
  final List<RecoveredMediaItem> media;
  final List<String> orphanMediaPaths;
  final List<RecoveryIdentityStatus> identities;
  final Map<String, int> counts;

  const LocalRecoveryScan({
    required this.context,
    required this.pendingOps,
    required this.cacheEvaluations,
    required this.signatureCacheEntries,
    required this.media,
    required this.orphanMediaPaths,
    required this.identities,
    required this.counts,
  });

  List<RecoveredPendingOp> get saveResultsOps =>
      pendingOps.where((o) => o.isSaveResults).toList();

  EvalItemFocus focusEvalItem(int evalItemId) {
    final ops = saveResultsOps
        .where((o) => o.evalItemId == evalItemId)
        .toList();
    RecoveredPendingOp? first = ops.isEmpty ? null : ops.first;
    var rowsFound = 0;
    var rowsWithScores = 0;
    var rowsWithNotes = 0;
    for (final o in ops) {
      rowsFound += o.parsed.rows.length;
      rowsWithScores += o.parsed.rowsWithScores;
      rowsWithNotes += o.parsed.rowsWithNotes;
    }
    final mediaN = media.where((m) {
      return m.evaluationListItemId == evalItemId ||
          m.bundleActionEvalId == evalItemId;
    }).length;
    return EvalItemFocus(
      evalItemId: evalItemId,
      pendingSaveFound: ops.isNotEmpty,
      rowsFound: rowsFound,
      rowsWithScores: rowsWithScores,
      rowsWithNotes: rowsWithNotes,
      associatedMedia: mediaN,
      syncStatus: first?.syncStatus ?? '',
      attempts: first?.attempts ?? 0,
      lastError: first?.lastError ?? '',
    );
  }
}

class RecoveryFileStat {
  final bool exists;
  final int size;
  const RecoveryFileStat({required this.exists, required this.size});
}

typedef RecoveryFileStatFn = RecoveryFileStat Function(String path);

/// Pure assembly from already-read storage rows. No I/O, no SQL writes.
LocalRecoveryScan assembleRecoveryScan({
  required RecoveryContext context,
  required List<Map<String, dynamic>> pendingRows,
  required List<Map<String, dynamic>> cacheRows,
  required List<Map<String, dynamic>> mediaRows,
  RecoveryFileStatFn? fileStat,
  List<String> orphanMediaPaths = const [],
}) {
  final pending = pendingRows.map(RecoveredPendingOp.fromRow).toList();
  final cacheEvals = <ParsedCacheEvaluation>[];
  final signatures = <Map<String, dynamic>>[];
  for (final row in cacheRows) {
    final key = recoveryAsString(row['cache_key']);
    if (recoveryIsSignatureCacheKey(key)) {
      signatures.add(Map<String, dynamic>.from(row));
      continue;
    }
    if (!recoveryIsEvaluationCacheKey(key)) continue;
    cacheEvals.add(parseCacheEvaluationRow(row));
  }

  final media = <RecoveredMediaItem>[];
  for (final row in mediaRows) {
    final fields = Map<String, dynamic>.from(row);
    final path = recoveryAsString(fields['local_path']);
    var exists = false;
    var size = 0;
    if (path.isNotEmpty && fileStat != null) {
      final st = fileStat(path);
      exists = st.exists;
      size = st.size;
    }
    media.add(
      RecoveredMediaItem(
        fields: fields,
        fileExists: exists,
        actualFileSize: size,
      ),
    );
  }

  final identities = _buildIdentities(pending, cacheEvals);
  final listsWithSaved = <String>{};
  for (final o in pending.where((e) => e.isSaveResults)) {
    if (o.parsed.rows.isNotEmpty) listsWithSaved.add(o.identity());
  }
  for (final c in cacheEvals) {
    if (c.savedRows.isNotEmpty || c.locallyModified) {
      listsWithSaved.add(c.identity());
    }
  }

  var evalsWithScores = 0;
  var evalsWithNotes = 0;
  for (final o in pending.where((e) => e.isSaveResults)) {
    if (o.parsed.rowsWithScores > 0) evalsWithScores++;
    if (o.parsed.rowsWithNotes > 0) evalsWithNotes++;
  }
  for (final c in cacheEvals) {
    if (c.savedRows.any((r) => r.hasScore)) evalsWithScores++;
    if (c.savedRows.any((r) => r.hasNotes)) evalsWithNotes++;
  }

  final counts = <String, int>{
    'lists_with_saved_results': listsWithSaved.length,
    'pending_operations': pending.length,
    'save_results_operations': pending.where((o) => o.isSaveResults).length,
    'images_local': media.where((m) => m.isImage).length,
    'videos_local': media.where((m) => m.isVideo).length,
    'failed_operations': pending.where((o) => o.syncStatus == 'failed').length,
    'evaluations_found': listsWithSaved.length,
    'evaluations_with_scores': evalsWithScores,
    'evaluations_with_notes': evalsWithNotes,
    'missing_physical_media': media.where((m) => !m.fileExists).length,
    'source_mismatches': identities.where((i) => i.sourceMismatch).length,
    'recoverable_evaluation_items': identities.length,
    'media_count': media.length,
    'orphan_media_files': orphanMediaPaths.length,
    'signature_cache_entries': signatures.length,
  };

  return LocalRecoveryScan(
    context: context,
    pendingOps: pending,
    cacheEvaluations: cacheEvals,
    signatureCacheEntries: signatures,
    media: media,
    orphanMediaPaths: orphanMediaPaths,
    identities: identities,
    counts: counts,
  );
}

List<RecoveryIdentityStatus> _buildIdentities(
  List<RecoveredPendingOp> pending,
  List<ParsedCacheEvaluation> cacheEvals,
) {
  final pendingBy = <String, List<RecoveredPendingOp>>{};
  for (final o in pending.where((e) => e.isSaveResults)) {
    pendingBy.putIfAbsent(o.identity(), () => []).add(o);
  }
  final cacheBy = <String, List<ParsedCacheEvaluation>>{};
  for (final c in cacheEvals) {
    cacheBy.putIfAbsent(c.identity(), () => []).add(c);
  }
  final keys = {...pendingBy.keys, ...cacheBy.keys};
  final out = <RecoveryIdentityStatus>[];
  for (final key in keys) {
    final pList = pendingBy[key] ?? const <RecoveredPendingOp>[];
    final cList = cacheBy[key] ?? const <ParsedCacheEvaluation>[];
    var mismatch = false;
    if (pList.isNotEmpty && cList.isNotEmpty) {
      final pFp = pList.first.parsed.rows.map((r) => r.fingerprint()).join('\n');
      final cFp = cList.first.savedRows.map((r) => r.fingerprint()).join('\n');
      mismatch = pFp != cFp;
    }
    int? evalId;
    if (key.startsWith('eval:')) {
      evalId = int.tryParse(key.substring(5));
    } else if (pList.isNotEmpty) {
      evalId = pList.first.evalItemId;
    } else if (cList.isNotEmpty) {
      evalId = cList.first.evalItemId;
    }
    out.add(
      RecoveryIdentityStatus(
        identity: key,
        pendingCopyExists: pList.isNotEmpty,
        cacheCopyExists: cList.isNotEmpty,
        sourceMismatch: mismatch,
        evalItemId: evalId,
      ),
    );
  }
  return out;
}

class EvaluationResultExportRow {
  final String recoverySource;
  final RecoveredEvalRow row;
  final String pendingOpId;
  final String clientOpId;
  final int? exerciseId;
  final int? judgeId;
  final int? userId;
  final String listId;
  final int? evalItemId;
  final String operationStatus;
  final String createdAt;

  const EvaluationResultExportRow({
    required this.recoverySource,
    required this.row,
    required this.pendingOpId,
    required this.clientOpId,
    this.exerciseId,
    this.judgeId,
    this.userId,
    required this.listId,
    this.evalItemId,
    required this.operationStatus,
    required this.createdAt,
  });
}

List<EvaluationResultExportRow> flattenEvaluationResultRows(
  LocalRecoveryScan scan,
) {
  final out = <EvaluationResultExportRow>[];
  for (final o in scan.saveResultsOps) {
    if (o.parsed.rows.isEmpty) {
      out.add(
        EvaluationResultExportRow(
          recoverySource: 'PENDING_OP',
          row: const RecoveredEvalRow(
            rowKind: '',
            element: '',
            maxVal: '',
            acquired: '',
            notes: '',
          ),
          pendingOpId: o.id,
          clientOpId: o.parsed.clientOpId,
          exerciseId: o.exerciseId,
          judgeId: o.judgeId,
          userId: o.userId,
          listId: o.listId,
          evalItemId: o.evalItemId,
          operationStatus: o.syncStatus,
          createdAt: o.createdAt,
        ),
      );
      continue;
    }
    for (final r in o.parsed.rows) {
      out.add(
        EvaluationResultExportRow(
          recoverySource: 'PENDING_OP',
          row: r,
          pendingOpId: o.id,
          clientOpId: o.parsed.clientOpId,
          exerciseId: o.exerciseId,
          judgeId: o.judgeId,
          userId: o.userId,
          listId: o.listId,
          evalItemId: o.evalItemId,
          operationStatus: o.syncStatus,
          createdAt: o.createdAt,
        ),
      );
    }
  }
  for (final c in scan.cacheEvaluations) {
    if (c.savedRows.isEmpty) continue;
    for (final r in c.savedRows) {
      out.add(
        EvaluationResultExportRow(
          recoverySource: 'CACHE',
          row: r,
          pendingOpId: '',
          clientOpId: '',
          exerciseId: scan.context.exerciseId,
          judgeId: c.userId ?? scan.context.judgeId,
          userId: c.userId ?? scan.context.userId,
          listId: c.listId ?? '',
          evalItemId: c.evalItemId,
          operationStatus: c.syncStatus,
          createdAt: c.updatedAt,
        ),
      );
    }
  }
  return out;
}
