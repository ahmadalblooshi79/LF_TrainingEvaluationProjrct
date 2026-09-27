import 'dart:convert';

import 'local_recovery_parser.dart';
import 'local_recovery_xlsx.dart';

const String kEvalBackupFormatVersion = '1';

const String kEvalBackupListsRoot = 'Evaluation_Lists';
const String kEvalBackupActionFolder = 'Action_Evaluation_Lists';
const String kEvalBackupDilemmaFolder = 'Dilemma_Evaluation_Lists';
const String kEvalBackupImagesRoot = 'Images';
const String kEvalBackupVideosRoot = 'Videos';

enum EvalBackupKind { action, dilemma }

class EvalBackupScope {
  final int exerciseId;
  final String exerciseName;
  final int userId;
  final int? judgeId;
  final String judgeName;
  final String unitKey;
  final String unitName;
  final String deviceId;
  final String appVersion;
  final String createdAt;

  const EvalBackupScope({
    required this.exerciseId,
    required this.exerciseName,
    required this.userId,
    this.judgeId,
    required this.judgeName,
    required this.unitKey,
    required this.unitName,
    required this.deviceId,
    required this.appVersion,
    required this.createdAt,
  });
}

class EvalBackupRow {
  final String rowKind;
  final String element;
  final String maxVal;
  final String acquired;
  final String notes;

  const EvalBackupRow({
    required this.rowKind,
    required this.element,
    required this.maxVal,
    required this.acquired,
    required this.notes,
  });

  Map<String, dynamic> toJson() => {
        'row_kind': rowKind,
        'element': element,
        'max_val': maxVal,
        'acquired': acquired,
        'notes': notes,
      };
}

class EvalBackupMediaRef {
  final String id;
  final String localPath;
  final String mediaKind;
  final String zipPath;
  final int? exerciseId;
  final int? evalItemId;
  final bool isImage;
  final bool isVideo;
  final bool fileExists;

  const EvalBackupMediaRef({
    required this.id,
    required this.localPath,
    required this.mediaKind,
    required this.zipPath,
    this.exerciseId,
    this.evalItemId,
    required this.isImage,
    required this.isVideo,
    required this.fileExists,
  });

  Map<String, dynamic> toJson() => {
        'id': id,
        'zip_path': zipPath,
        'media_kind': mediaKind,
        'eval_item_id': evalItemId,
        'exercise_id': exerciseId,
        'file_exists': fileExists,
      };
}

class EvalBackupList {
  final int evalItemId;
  final int exerciseId;
  final EvalBackupKind kind;
  final String listName;
  final String unitId;
  final String unitName;
  final String stageId;
  final String stageName;
  final String dilemmaName;
  final int? dilemmaId;
  final String savedAt;
  final String saveStatus;
  final bool approved;
  final String excelRelPath;
  final List<EvalBackupRow> rows;
  final List<EvalBackupMediaRef> media;
  final List<int> xlsxBytes;

  const EvalBackupList({
    required this.evalItemId,
    required this.exerciseId,
    required this.kind,
    required this.listName,
    required this.unitId,
    required this.unitName,
    required this.stageId,
    required this.stageName,
    required this.dilemmaName,
    this.dilemmaId,
    required this.savedAt,
    required this.saveStatus,
    required this.approved,
    required this.excelRelPath,
    required this.rows,
    required this.media,
    required this.xlsxBytes,
  });

  String get kindFolder => kind == EvalBackupKind.action
      ? kEvalBackupActionFolder
      : kEvalBackupDilemmaFolder;

  String get kindLabel => kind == EvalBackupKind.action
      ? 'قائمة تقييم الإجراءات'
      : 'قائمة تقييم المعاضل';

  Map<String, dynamic> toManifestEntry() => {
        'evaluation_list_id': evalItemId,
        'eval_item_id': evalItemId,
        'evaluation_list_name': listName,
        'evaluation_type': kind == EvalBackupKind.action
            ? 'action_evaluation_list'
            : 'dilemma_evaluation_list',
        'exercise_id': exerciseId,
        'stage_id': stageId,
        'stage_name': stageName,
        'dilemma_id': dilemmaId,
        'dilemma_name': dilemmaName,
        'saved_at': savedAt,
        'approval_status': approved ? 'approved' : 'not_approved',
        'save_status': saveStatus,
        'excel_file': excelRelPath,
        'media': media.map((m) => m.toJson()).toList(),
      };
}

class EvalBackupPackage {
  final EvalBackupScope scope;
  final List<EvalBackupList> lists;
  final List<String> warnings;

  const EvalBackupPackage({
    required this.scope,
    required this.lists,
    this.warnings = const [],
  });

  List<EvalBackupList> get actionLists =>
      lists.where((e) => e.kind == EvalBackupKind.action).toList();

  List<EvalBackupList> get dilemmaLists =>
      lists.where((e) => e.kind == EvalBackupKind.dilemma).toList();

  List<EvalBackupMediaRef> get media =>
      [for (final l in lists) ...l.media];

  int get imageCount => media.where((m) => m.isImage && m.fileExists).length;

  int get videoCount => media.where((m) => m.isVideo && m.fileExists).length;

  Map<String, dynamic> toManifest() => {
        'backup_format_version': kEvalBackupFormatVersion,
        'created_at': scope.createdAt,
        'device_id': scope.deviceId,
        'app_version': scope.appVersion,
        'exercise_id': scope.exerciseId,
        'exercise_name': scope.exerciseName,
        'judge_id': scope.judgeId,
        'judge_name': scope.judgeName,
        'user_id': scope.userId,
        'unit_id': scope.unitKey,
        'unit_name': scope.unitName,
        'action_evaluation_list_count': actionLists.length,
        'dilemma_evaluation_list_count': dilemmaLists.length,
        'total_evaluation_list_count': lists.length,
        'image_count': imageCount,
        'video_count': videoCount,
        'action_evaluation_lists':
            actionLists.map((e) => e.toManifestEntry()).toList(),
        'dilemma_evaluation_lists':
            dilemmaLists.map((e) => e.toManifestEntry()).toList(),
        'warnings': warnings,
      };
}

class _OpenCatalog {
  final Set<int> actionIds;
  final Set<int> dilemmaIds;
  final Map<int, String> titles;
  const _OpenCatalog({
    required this.actionIds,
    required this.dilemmaIds,
    required this.titles,
  });
}

/// Pure current-exercise backup assembly. No I/O. No recovery-scanner calls.
EvalBackupPackage assembleEvalBackup({
  required EvalBackupScope scope,
  required List<Map<String, dynamic>> pendingRows,
  required List<Map<String, dynamic>> cacheRows,
  required List<Map<String, dynamic>> mediaRows,
  Set<String> existingFilePaths = const {},
}) {
  final warnings = <String>[];
  if (scope.exerciseId <= 0) {
    return EvalBackupPackage(scope: scope, lists: const [], warnings: [
      'current_exercise_id_missing',
    ]);
  }

  final catalog = _openCatalogIds(
    cacheRows,
    userId: scope.userId,
    unitKey: scope.unitKey,
    exerciseId: scope.exerciseId,
  );

  final byId = <int, _Draft>{};
  for (final row in pendingRows) {
    final draft = _draftFromPending(row, scope, catalog, warnings);
    if (draft == null) continue;
    byId[draft.evalItemId] = draft;
  }
  for (final row in cacheRows) {
    final draft = _draftFromCache(row, scope, catalog, warnings);
    if (draft == null) continue;
    final existing = byId[draft.evalItemId];
    if (existing != null) {
      if (_isGenericListName(existing.listName, existing.evalItemId) &&
          !_isGenericListName(draft.listName, draft.evalItemId)) {
        byId[draft.evalItemId] = existing.copyWith(listName: draft.listName);
      }
      continue;
    }
    byId[draft.evalItemId] = draft;
  }
  for (final e in byId.entries.toList()) {
    final named = catalog.titles[e.key];
    if (named == null || named.trim().isEmpty) continue;
    if (_isGenericListName(e.value.listName, e.key)) {
      byId[e.key] = e.value.copyWith(listName: named.trim());
    }
  }

  final lists = <EvalBackupList>[];
  for (final draft in byId.values) {
    if (draft.exerciseId != scope.exerciseId) {
      warnings.add('skipped_other_exercise:${draft.evalItemId}');
      continue;
    }
    if (draft.rows.isEmpty) continue;
    final usedNames = {for (final l in lists) l.excelRelPath};
    final excelRel = _excelRelPath(draft, usedNames);
    final media = _mediaForList(
      draft,
      mediaRows,
      scope,
      existingFilePaths,
      warnings,
    );
    lists.add(
      EvalBackupList(
        evalItemId: draft.evalItemId,
        exerciseId: draft.exerciseId,
        kind: draft.kind,
        listName: draft.listName,
        unitId: draft.unitId,
        unitName: draft.unitName,
        stageId: draft.stageId,
        stageName: draft.stageName,
        dilemmaName: draft.dilemmaName,
        dilemmaId: draft.dilemmaId,
        savedAt: draft.savedAt,
        saveStatus: draft.saveStatus,
        approved: draft.approved,
        excelRelPath: excelRel,
        rows: draft.rows,
        media: media,
        xlsxBytes: _buildListXlsx(draft, scope),
      ),
    );
  }
  lists.sort((a, b) {
    final k = a.kind.index.compareTo(b.kind.index);
    if (k != 0) return k;
    return a.evalItemId.compareTo(b.evalItemId);
  });
  return EvalBackupPackage(scope: scope, lists: lists, warnings: warnings);
}

class _Draft {
  final int evalItemId;
  final int exerciseId;
  final EvalBackupKind kind;
  final String listName;
  final String unitId;
  final String unitName;
  final String stageId;
  final String stageName;
  final String dilemmaName;
  final int? dilemmaId;
  final String savedAt;
  final String saveStatus;
  final bool approved;
  final List<EvalBackupRow> rows;

  const _Draft({
    required this.evalItemId,
    required this.exerciseId,
    required this.kind,
    required this.listName,
    required this.unitId,
    required this.unitName,
    required this.stageId,
    required this.stageName,
    required this.dilemmaName,
    this.dilemmaId,
    required this.savedAt,
    required this.saveStatus,
    required this.approved,
    required this.rows,
  });

  _Draft copyWith({String? listName}) {
    return _Draft(
      evalItemId: evalItemId,
      exerciseId: exerciseId,
      kind: kind,
      listName: listName ?? this.listName,
      unitId: unitId,
      unitName: unitName,
      stageId: stageId,
      stageName: stageName,
      dilemmaName: dilemmaName,
      dilemmaId: dilemmaId,
      savedAt: savedAt,
      saveStatus: saveStatus,
      approved: approved,
      rows: rows,
    );
  }
}

_OpenCatalog _openCatalogIds(
  List<Map<String, dynamic>> cacheRows, {
  required int userId,
  required String unitKey,
  required int exerciseId,
}) {
  final action = <int>{};
  final dilemma = <int>{};
  final titles = <int, String>{};
  final uk = unitKey.trim();
  for (final row in cacheRows) {
    final key = recoveryAsString(row['cache_key']);
    final keyUser = _userIdFromKey(key);
    if (keyUser != null && keyUser != userId) continue;
    final bare = _bareKey(key);
    final isActionCatalog = bare.startsWith('evaluation_lists') &&
        !bare.contains('evaluation_list_detail');
    final isDilemmaCatalog = bare.startsWith('action_eval_lists') &&
        !bare.contains('action_eval_detail');
    if (!isActionCatalog && !isDilemmaCatalog) continue;
    if (isActionCatalog && uk.isNotEmpty) {
      final parts = bare.split(':');
      final keyUnit = parts.length >= 2 ? parts[1] : '';
      if (keyUnit.isNotEmpty && keyUnit != uk) continue;
    }
    final map = _decodeMap(row['json_body']);
    if (map == null) continue;
    final jsonEx = recoveryAsInt(map['exercise_id']);
    if (jsonEx != null && jsonEx != exerciseId) continue;
    final jsonUnit = recoveryAsString(map['unit_key']);
    if (uk.isNotEmpty && jsonUnit.isNotEmpty && jsonUnit != uk) continue;
    final target = isDilemmaCatalog ? dilemma : action;
    for (final listKey in const ['lists', 'rows']) {
      final arr = map[listKey];
      if (arr is! List) continue;
      for (final item in arr) {
        if (item is! Map) continue;
        final m = Map<String, dynamic>.from(item);
        final itemUnit = recoveryAsString(m['unit_key']);
        if (uk.isNotEmpty && itemUnit.isNotEmpty && itemUnit != uk) continue;
        final id = recoveryAsInt(
          m['item_id'] ?? m['slot_id'] ?? m['eval_item_id'] ?? m['id'],
        );
        if (id != null && id > 0) {
          target.add(id);
          final t = _titleFrom(m, id);
          if (!_isGenericListName(t, id)) titles[id] = t;
        }
      }
    }
  }
  for (final row in cacheRows) {
    final key = recoveryAsString(row['cache_key']);
    final keyUser = _userIdFromKey(key);
    if (keyUser != null && keyUser != userId) continue;
    final bare = _bareKey(key);
    if (!bare.contains('evaluation_list_detail') &&
        !bare.contains('action_eval_detail')) {
      continue;
    }
    final map = _decodeMap(row['json_body']);
    if (map == null) continue;
    final jsonEx = recoveryAsInt(map['exercise_id']);
    if (jsonEx != null && jsonEx != exerciseId) continue;
    final id = int.tryParse(bare.split(':').last) ?? 0;
    if (id <= 0) continue;
    final existing = titles[id];
    if (existing != null && !_isGenericListName(existing, id)) continue;
    final t = _titleFrom(map, id);
    if (!_isGenericListName(t, id)) titles[id] = t;
  }
  return _OpenCatalog(actionIds: action, dilemmaIds: dilemma, titles: titles);
}

_Draft? _draftFromPending(
  Map<String, dynamic> row,
  EvalBackupScope scope,
  _OpenCatalog catalog,
  List<String> warnings,
) {
  final exerciseId = recoveryAsInt(row['exercise_id']);
  if (exerciseId == null || exerciseId != scope.exerciseId) {
    if (exerciseId != null) {
      warnings.add('skipped_pending_other_exercise:${row['eval_item_id']}');
    } else {
      warnings.add('skipped_pending_unknown_exercise:${row['id']}');
    }
    return null;
  }
  final userId = recoveryAsInt(row['user_id']);
  if (userId == null || userId != scope.userId) {
    warnings.add('skipped_pending_other_user:${row['id']}');
    return null;
  }
  final id = recoveryAsInt(row['eval_item_id']) ?? 0;
  if (id <= 0) return null;
  final path = recoveryAsString(row['path']);
  final kind = _kindFromPathOrKey(path, '');
  final parsed = parsePendingBody(recoveryPendingBodyRaw(row));
  Map<String, dynamic> payload = {};
  if (parsed.decoded is Map) {
    payload = Map<String, dynamic>.from(parsed.decoded!);
    if (payload['payload'] is Map) {
      payload = Map<String, dynamic>.from(payload['payload'] as Map);
    }
  }
  final payloadEx = recoveryAsInt(payload['exercise_id']);
  if (payloadEx != null && payloadEx != scope.exerciseId) return null;
  final unitId = recoveryAsString(payload['unit_key'] ?? payload['unit_id']);
  if (scope.unitKey.isNotEmpty &&
      unitId.isNotEmpty &&
      unitId != scope.unitKey) {
    warnings.add('skipped_pending_other_unit:$id');
    return null;
  }
  final rows = [
    for (final r in parsed.rows)
      EvalBackupRow(
        rowKind: r.rowKind,
        element: r.element,
        maxVal: r.maxVal,
        acquired: r.acquired,
        notes: r.notes,
      ),
  ];
  if (rows.isEmpty) return null;
  return _Draft(
    evalItemId: id,
    exerciseId: exerciseId,
    kind: kind,
    listName: _titleFrom(payload, id, catalogTitle: catalog.titles[id]),
    unitId: unitId,
    unitName: recoveryAsString(payload['unit_label'] ?? payload['unit_name']),
    stageId: recoveryAsString(payload['exercise_phase'] ?? payload['phase_key']),
    stageName: recoveryAsString(payload['phase_label'] ?? payload['exercise_phase']),
    dilemmaName: recoveryAsString(
      payload['dilemma_description'] ?? payload['eval_dilemma_description'],
    ),
    dilemmaId: recoveryAsInt(payload['dilemma_id']),
    savedAt: recoveryAsString(row['created_at']),
    saveStatus: recoveryAsString(row['sync_status']),
    approved: payload['is_approved'] == true ||
        recoveryAsString(payload['is_approved']).toLowerCase() == 'true',
    rows: rows,
  );
}

_Draft? _draftFromCache(
  Map<String, dynamic> row,
  EvalBackupScope scope,
  _OpenCatalog catalog,
  List<String> warnings,
) {
  final key = recoveryAsString(row['cache_key']);
  final bare = _bareKey(key);
  if (!bare.contains('evaluation_list_detail') &&
      !bare.contains('action_eval_detail')) {
    return null;
  }
  final keyUser = _userIdFromKey(key);
  if (keyUser != null && keyUser != scope.userId) return null;
  final parsed = parseCacheEvaluationRow(row);
  final id = parsed.evalItemId ??
      (bare.startsWith('action_eval_detail:')
          ? int.tryParse(bare.split(':').last)
          : null) ??
      0;
  if (id <= 0) return null;
  final kind = _kindFromPathOrKey('', key);
  final decoded = _decodeMap(parsed.jsonBodyRaw) ?? {};
  final jsonEx = recoveryAsInt(decoded['exercise_id']);
  if (jsonEx != null && jsonEx != scope.exerciseId) {
    warnings.add('skipped_cache_other_exercise:$id');
    return null;
  }
  if (jsonEx == null) {
    final open = kind == EvalBackupKind.action
        ? catalog.actionIds
        : catalog.dilemmaIds;
    if (!open.contains(id)) {
      warnings.add('skipped_cache_unknown_exercise:$id');
      return null;
    }
  }
  if (kind == EvalBackupKind.action && scope.unitKey.isNotEmpty) {
    final keyUnit = _unitFromEvalDetailKey(key);
    if (keyUnit.isNotEmpty && keyUnit != scope.unitKey) {
      warnings.add('skipped_cache_other_unit:$id');
      return null;
    }
  }
  if (!parsed.savedPayloadExists && parsed.savedRows.isEmpty) return null;
  final rows = [
    for (final r in parsed.savedRows)
      EvalBackupRow(
        rowKind: r.rowKind,
        element: r.element,
        maxVal: r.maxVal,
        acquired: r.acquired,
        notes: r.notes,
      ),
  ];
  if (rows.isEmpty) return null;
  return _Draft(
    evalItemId: id,
    exerciseId: jsonEx ?? scope.exerciseId,
    kind: kind,
    listName: _titleFrom(decoded, id, catalogTitle: catalog.titles[id]),
    unitId: recoveryAsString(decoded['unit_key'] ?? decoded['unit_id']).isNotEmpty
        ? recoveryAsString(decoded['unit_key'] ?? decoded['unit_id'])
        : _unitFromEvalDetailKey(key),
    unitName: recoveryAsString(decoded['unit_label'] ?? decoded['unit_name']),
    stageId: recoveryAsString(decoded['phase_key'] ?? decoded['exercise_phase']),
    stageName: recoveryAsString(decoded['phase_label'] ?? decoded['exercise_phase']),
    dilemmaName: recoveryAsString(
      decoded['eval_dilemma_description'] ?? decoded['dilemma_description'],
    ),
    dilemmaId: recoveryAsInt(decoded['dilemma_id']),
    savedAt: parsed.updatedAt,
    saveStatus: parsed.syncStatus,
    approved: decoded['is_approved'] == true || decoded['locally_approved'] == true,
    rows: rows,
  );
}

EvalBackupKind _kindFromPathOrKey(String path, String cacheKey) {
  final blob = '$path $cacheKey'.toLowerCase();
  if (blob.contains('action-eval') || blob.contains('action_eval')) {
    return EvalBackupKind.dilemma;
  }
  return EvalBackupKind.action;
}

List<EvalBackupMediaRef> _mediaForList(
  _Draft draft,
  List<Map<String, dynamic>> mediaRows,
  EvalBackupScope scope,
  Set<String> existingFilePaths,
  List<String> warnings,
) {
  final out = <EvalBackupMediaRef>[];
  final folderName = _safeName(draft.listName);
  var imageI = 1;
  var videoI = 1;
  for (final row in mediaRows) {
    final evalId = recoveryAsInt(row['evaluation_list_item_id']);
    final slotId = recoveryAsInt(row['bundle_action_eval_id']);
    if (evalId != draft.evalItemId && slotId != draft.evalItemId) continue;
    final mediaEx = recoveryAsInt(row['exercise_id']);
    if (mediaEx != null && mediaEx != 0 && mediaEx != scope.exerciseId) {
      warnings.add('skipped_media_other_exercise:${row['id']}');
      continue;
    }
    if (mediaEx == null && evalId != draft.evalItemId && slotId != draft.evalItemId) {
      continue;
    }
    final kind = recoveryAsString(row['media_kind']);
    final path = recoveryAsString(row['local_path']);
    final isImage = _isImage(kind, path);
    final isVideo = _isVideo(kind, path);
    if (!isImage && !isVideo) continue;
    final exists = path.isNotEmpty &&
        (existingFilePaths.isEmpty || existingFilePaths.contains(path));
    if (!exists && existingFilePaths.isNotEmpty) {
      warnings.add('skipped_media_missing_file:${row['id']}');
      continue;
    }
    final root = isVideo ? kEvalBackupVideosRoot : kEvalBackupImagesRoot;
    final ext = _extOf(path, isVideo: isVideo);
    final seq = isVideo ? videoI++ : imageI++;
    final zipPath =
        '$root/${draft.kind == EvalBackupKind.action ? kEvalBackupActionFolder : kEvalBackupDilemmaFolder}/$folderName/${isVideo ? 'video' : 'image'}${seq.toString().padLeft(3, '0')}$ext';
    out.add(
      EvalBackupMediaRef(
        id: recoveryAsString(row['id']),
        localPath: path,
        mediaKind: kind,
        zipPath: zipPath,
        exerciseId: mediaEx ?? scope.exerciseId,
        evalItemId: draft.evalItemId,
        isImage: isImage,
        isVideo: isVideo,
        fileExists: exists || existingFilePaths.isEmpty,
      ),
    );
  }
  return out;
}

String _excelRelPath(_Draft draft, Set<String> used) {
  final folder = draft.kind == EvalBackupKind.action
      ? kEvalBackupActionFolder
      : kEvalBackupDilemmaFolder;
  final name = _safeName(draft.listName);
  final base = '$kEvalBackupListsRoot/$folder/$name.xlsx';
  if (!used.contains(base)) return base;
  return '$kEvalBackupListsRoot/$folder/${name}_${draft.evalItemId}.xlsx';
}

List<int> _buildListXlsx(_Draft draft, EvalBackupScope scope) {
  var totalMax = 0.0;
  var totalAcquired = 0.0;
  var i = 1;
  final table = <List<String>>[
    ['قائمة التقييم', draft.listName],
    ['النوع', draft.kind == EvalBackupKind.action
        ? 'قائمة تقييم الإجراءات'
        : 'قائمة تقييم المعاضل'],
    ['التمرين', scope.exerciseName],
    ['exercise_id', '${scope.exerciseId}'],
    ['eval_item_id', '${draft.evalItemId}'],
    ['الوحدة', draft.unitName.isNotEmpty ? draft.unitName : draft.unitId],
    ['المحكم', scope.judgeName],
    ['حالة الحفظ', draft.saveStatus],
    ['حالة الاعتماد', draft.approved ? 'معتمدة' : 'غير معتمدة'],
    ['تاريخ الحفظ', draft.savedAt],
    if (draft.dilemmaName.isNotEmpty) ['المعضلة', draft.dilemmaName],
    [],
    ['م', 'نوع الصف', 'عناصر التقييم', 'القصوى', 'المكتسبة', 'الملاحظات'],
  ];
  for (final row in draft.rows) {
    table.add([
      '$i',
      row.rowKind,
      row.element,
      row.maxVal,
      row.acquired,
      row.notes,
    ]);
    totalMax += _asNum(row.maxVal);
    totalAcquired += _asNum(row.acquired);
    i++;
  }
  final pct = totalMax <= 0 ? '' : ((totalAcquired / totalMax) * 100).toStringAsFixed(1);
  table.add(const []);
  table.add([
    'المجموع',
    '',
    '',
    totalMax.toStringAsFixed(totalMax % 1 == 0 ? 0 : 1),
    totalAcquired.toStringAsFixed(totalAcquired % 1 == 0 ? 0 : 1),
    '',
  ]);
  table.add(['النسبة %', '', '', '', pct, '']);
  final sheet = _safeName(draft.listName);
  return buildSimpleXlsx({
    sheet.length > 31 ? sheet.substring(0, 31) : (sheet.isEmpty ? 'Evaluation' : sheet): table,
  });
}

Map<String, dynamic>? _decodeMap(dynamic raw) {
  try {
    final decoded = raw is String ? jsonDecode(raw) : raw;
    if (decoded is Map) return Map<String, dynamic>.from(decoded);
  } catch (_) {}
  return null;
}

String _titleFrom(Map<String, dynamic> payload, int id, {String? catalogTitle}) {
  for (final k in [
    'title',
    'item_title',
    'eval_doc_title',
    'list_name',
    'evaluation_list_name',
  ]) {
    final v = recoveryAsString(payload[k]).trim();
    if (v.isNotEmpty && !_isGenericListName(v, id)) return v;
  }
  final fromCatalog = (catalogTitle ?? '').trim();
  if (fromCatalog.isNotEmpty && !_isGenericListName(fromCatalog, id)) {
    return fromCatalog;
  }
  return 'Evaluation_$id';
}

bool _isGenericListName(String name, int id) {
  final t = name.trim();
  if (t.isEmpty) return true;
  if (t == '$id') return true;
  if (RegExp(r'^\d+$').hasMatch(t)) return true;
  if (RegExp(r'^Evaluation_\d+(_\d+)?$').hasMatch(t)) return true;
  return false;
}

String _bareKey(String key) {
  final m = RegExp(r'^u\d+:').firstMatch(key);
  if (m == null) return key;
  return key.substring(m.end);
}

int? _userIdFromKey(String key) {
  final m = RegExp(r'^u(\d+):').firstMatch(key);
  if (m == null) return null;
  return int.tryParse(m.group(1)!);
}

String _unitFromEvalDetailKey(String key) {
  final bare = _bareKey(key);
  if (!bare.startsWith('evaluation_list_detail:')) return '';
  final parts = bare.split(':');
  if (parts.length >= 3) return parts[1];
  return '';
}

String _safeName(String s) {
  var t = s.replaceAll(RegExp(r'[\\/:*?"<>|]'), '_').trim();
  t = t.replaceAll('..', '_');
  if (t.isEmpty) return 'list';
  if (t.length > 60) t = t.substring(0, 60);
  return t;
}

bool _isImage(String kind, String path) {
  final b = '${kind.toLowerCase()} ${path.toLowerCase()}';
  return b.contains('photo') ||
      b.contains('image') ||
      b.contains('pic') ||
      b.contains('.jpg') ||
      b.contains('.jpeg') ||
      b.contains('.png') ||
      b.contains('.webp');
}

bool _isVideo(String kind, String path) {
  final b = '${kind.toLowerCase()} ${path.toLowerCase()}';
  return b.contains('video') ||
      b.contains('.mp4') ||
      b.contains('.mov') ||
      b.contains('.webm');
}

String _extOf(String path, {required bool isVideo}) {
  final i = path.lastIndexOf('.');
  if (i >= 0 && i > path.lastIndexOf('/') && i > path.lastIndexOf('\\')) {
    return path.substring(i);
  }
  return isVideo ? '.mp4' : '.jpg';
}

double _asNum(String s) {
  final t = s.trim().replaceAll(',', '.');
  if (t.isEmpty) return 0;
  return double.tryParse(t) ?? 0;
}

String suggestedEvalBackupZipName(EvalBackupScope scope) {
  final stamp = scope.createdAt
      .replaceAll(':', '')
      .replaceAll('-', '')
      .replaceAll('T', '_')
      .replaceAll('Z', '');
  return 'Evaluation_Backup_${_safeName(scope.exerciseName)}_${_safeName(scope.judgeName)}_$stamp.zip';
}
