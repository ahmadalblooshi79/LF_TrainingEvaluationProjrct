import 'dart:convert';
import 'dart:io';

import 'package:path/path.dart' as p;

import 'eval_backup_assembler.dart';
import 'scoped_backup_inventory.dart';
import 'scoped_backup_io.dart';
import 'scoped_backup_models.dart';
import 'scoped_backup_paths.dart';

const String kBackupEvalListsRoot = 'قوائم التقييم';
const String kBackupExcelRoot = kBackupEvalListsRoot;
const String kBackupExcelProcedureFolder = 'قوائم تقييم الإجراءات';
const String kBackupExcelDilemmaFolder = 'قوائم تقييم المعاضل';
const String kProcedureExcelKind = 'procedure_evaluation_excel';
const String kDilemmaExcelKind = 'dilemma_evaluation_excel';
const String kProcedureImageKind = 'procedure_evaluation_image';
const String kProcedureVideoKind = 'procedure_evaluation_video';
const String kDilemmaImageKind = 'dilemma_evaluation_image';
const String kDilemmaVideoKind = 'dilemma_evaluation_video';

class HumanReadableBackupMeta {
  final String kind;
  final int evaluationListId;
  final String evaluationType;
  final int exerciseId;
  final int userId;
  final String displayName;
  final int? evaluationItemId;
  final String? mediaId;
  final String? mediaType;
  final String? sourceLocalPath;

  const HumanReadableBackupMeta({
    required this.kind,
    required this.evaluationListId,
    required this.evaluationType,
    required this.exerciseId,
    required this.userId,
    required this.displayName,
    this.evaluationItemId,
    this.mediaId,
    this.mediaType,
    this.sourceLocalPath,
  });
}

class ScopedExcelWriteResult {
  final int procedureCount;
  final int dilemmaCount;
  final int imageCount;
  final int videoCount;
  final Map<String, int> evaluationListIdByRel;
  final Map<String, String> kindByRel;
  final Map<String, HumanReadableBackupMeta> metaByRel;

  const ScopedExcelWriteResult({
    required this.procedureCount,
    required this.dilemmaCount,
    required this.imageCount,
    required this.videoCount,
    required this.evaluationListIdByRel,
    required this.kindByRel,
    required this.metaByRel,
  });
}

bool sheetCacheKeyMatchesDilemma(String sheetKey, int slotId) {
  if (sheetKey.isEmpty || slotId <= 0) return false;
  final bare = cacheKeyBare(sheetKey);
  if (!bare.startsWith('action_eval_detail:')) return false;
  final n = int.tryParse(bare.split(':').last);
  return n != null && n == slotId;
}

bool mediaBelongsToEvaluationList({
  required Map<String, dynamic> row,
  required EvalBackupList list,
  required int userId,
  required int exerciseId,
  Set<String> localMediaPaths = const {},
}) {
  final owner = rowAsInt(row['user_id']);
  if (owner != null && owner > 0 && owner != userId) return false;
  final ex = rowAsInt(row['exercise_id']);
  if (ex != null && ex > 0 && ex != exerciseId) return false;
  final evalId = rowAsInt(row['evaluation_list_item_id']);
  final slotId = rowAsInt(row['bundle_action_eval_id']);
  if (list.kind == EvalBackupKind.action) {
    return evalId != null && evalId == list.evalItemId;
  }
  if (slotId != null && slotId == list.evalItemId) return true;
  if (sheetCacheKeyMatchesDilemma(
    '${row['sheet_cache_key'] ?? ''}',
    list.evalItemId,
  )) {
    return true;
  }
  final path = '${row['local_path'] ?? ''}'.trim();
  if (path.isNotEmpty && localMediaPaths.contains(path)) return true;
  return false;
}

Set<String> localMediaPathsForList({
  required List<Map<String, dynamic>> cacheRows,
  required EvalBackupList list,
}) {
  final paths = <String>{};
  if (list.kind != EvalBackupKind.dilemma) return paths;
  for (final row in cacheRows) {
    final key = '${row['cache_key'] ?? ''}';
    final bare = cacheKeyBare(key);
    if (!bare.startsWith('action_eval_detail:')) continue;
    Map<String, dynamic>? decoded;
    try {
      final raw = jsonDecode('${row['json_body'] ?? ''}');
      if (raw is Map) decoded = Map<String, dynamic>.from(raw);
    } catch (_) {}
    if (decoded == null) continue;
    final slot = rowAsInt(decoded['slot_id']) ??
        rowAsInt(decoded['id']) ??
        int.tryParse(bare.split(':').last);
    if (slot != list.evalItemId) continue;
    final media = decoded['local_media'];
    if (media is! List) continue;
    for (final item in media) {
      if (item is! Map) continue;
      final path = '${item['local_path'] ?? ''}'.trim();
      if (path.isNotEmpty) paths.add(path);
    }
  }
  return paths;
}

List<Map<String, dynamic>> localMediaRowsFromCache({
  required List<Map<String, dynamic>> cacheRows,
  required EvalBackupList list,
  required int userId,
  required int exerciseId,
}) {
  final out = <Map<String, dynamic>>[];
  if (list.kind != EvalBackupKind.dilemma) return out;
  for (final row in cacheRows) {
    final key = '${row['cache_key'] ?? ''}';
    final bare = cacheKeyBare(key);
    if (!bare.startsWith('action_eval_detail:')) continue;
    Map<String, dynamic>? decoded;
    try {
      final raw = jsonDecode('${row['json_body'] ?? ''}');
      if (raw is Map) decoded = Map<String, dynamic>.from(raw);
    } catch (_) {}
    if (decoded == null) continue;
    final slot = rowAsInt(decoded['slot_id']) ??
        rowAsInt(decoded['id']) ??
        int.tryParse(bare.split(':').last);
    if (slot != list.evalItemId) continue;
    final media = decoded['local_media'];
    if (media is! List) continue;
    for (final item in media) {
      if (item is! Map) continue;
      final m = Map<String, dynamic>.from(item);
      final path = '${m['local_path'] ?? ''}'.trim();
      if (path.isEmpty) continue;
      out.add({
        ...m,
        'local_path': path,
        'user_id': m['user_id'] ?? userId,
        'exercise_id': m['exercise_id'] ?? exerciseId,
        'bundle_action_eval_id':
            m['bundle_action_eval_id'] ?? list.evalItemId,
        'sheet_cache_key': m['sheet_cache_key'] ?? bare,
        'media_kind': m['media_kind'] ?? 'photo',
      });
    }
  }
  return out;
}

String evaluationListFolderName({
  required String displayName,
  required int listId,
  required Set<String> usedFolders,
}) {
  final base = sanitizeBackupFolderName(
    displayName,
    fallback: 'قائمة $listId',
  );
  if (!usedFolders.contains(base)) return base;
  return sanitizeBackupFolderName(
    '$base (L$listId)',
    fallback: 'list_$listId',
  );
}

String scopedBackupFileKind(
  String rel, {
  Map<String, String> excelKinds = const {},
}) {
  final kind = excelKinds[rel];
  if (kind != null && kind.isNotEmpty) return kind;
  if (rel.startsWith('$kBackupEvalListsRoot/$kBackupExcelProcedureFolder/') &&
      rel.toLowerCase().endsWith('.xlsx')) {
    return kProcedureExcelKind;
  }
  if (rel.startsWith('$kBackupEvalListsRoot/$kBackupExcelDilemmaFolder/') &&
      rel.toLowerCase().endsWith('.xlsx')) {
    return kDilemmaExcelKind;
  }
  if (rel.startsWith('media/')) return 'media';
  if (rel.startsWith('signatures/')) return 'signature';
  return 'record';
}

bool isUnrelatedExcelSourceKey(String cacheKey) {
  final lower = cacheKey.toLowerCase();
  if (lower.contains('evaluation_list_detail') ||
      lower.contains('action_eval_detail') ||
      lower.contains('evaluation_lists') ||
      lower.contains('action_eval_lists')) {
    return false;
  }
  return lower.contains('library') ||
      lower.contains('information_bank') ||
      lower.contains('ibank') ||
      lower.contains('unit_designation') ||
      lower.contains('unit_allocation') ||
      lower.contains('objectives') ||
      lower.contains('bootstrap') ||
      lower.contains('planner') ||
      lower.contains('config');
}

Future<List<Map<String, dynamic>>> hydrateCacheRowsForExcel(
  List<Map<String, dynamic>> cacheRows,
) async {
  final out = <Map<String, dynamic>>[];
  for (final row in cacheRows) {
    final copy = Map<String, dynamic>.from(row);
    final path = '${copy['json_body_file'] ?? ''}';
    if (path.isNotEmpty) {
      final f = File(path);
      if (f.existsSync()) {
        copy['json_body'] = await f.readAsString();
      }
    }
    out.add(copy);
  }
  return out;
}

EvalBackupScope excelScopeFromBackup({
  required ScopedBackupExercise exercise,
  required ScopedBackupIdentity identity,
  required String deviceId,
  required String appVersion,
}) {
  final judge = identity.displayName.trim().isNotEmpty
      ? identity.displayName
      : identity.username;
  return EvalBackupScope(
    exerciseId: exercise.exerciseId,
    exerciseName: exercise.name,
    userId: identity.userId,
    judgeId: identity.userId,
    judgeName: judge,
    unitKey: '',
    unitName: '',
    deviceId: deviceId,
    appVersion: appVersion,
    createdAt: DateTime.now().toUtc().toIso8601String(),
  );
}

bool _isImageRow(Map<String, dynamic> row) {
  final kind = '${row['media_kind'] ?? ''}'.toLowerCase();
  if (kind.contains('video')) return false;
  if (kind.contains('photo') || kind.contains('image') || kind.contains('pic')) {
    return true;
  }
  final blob =
      '${row['local_path'] ?? ''} ${row['original_filename'] ?? ''}'.toLowerCase();
  return blob.contains('.jpg') ||
      blob.contains('.jpeg') ||
      blob.contains('.png') ||
      blob.contains('.webp');
}

bool _isVideoRow(Map<String, dynamic> row) {
  final kind = '${row['media_kind'] ?? ''}'.toLowerCase();
  if (kind.contains('video')) return true;
  final blob =
      '${row['local_path'] ?? ''} ${row['original_filename'] ?? ''}'.toLowerCase();
  return blob.contains('.mp4') ||
      blob.contains('.mov') ||
      blob.contains('.webm');
}

String _extOf(Map<String, dynamic> row, {required bool isVideo}) {
  for (final raw in [
    '${row['original_filename'] ?? ''}',
    '${row['local_filename'] ?? ''}',
    '${row['local_path'] ?? ''}',
  ]) {
    final base = p.basename(raw.replaceAll('\\', '/'));
    final dot = base.lastIndexOf('.');
    if (dot > 0 && dot < base.length - 1) {
      final ext = base.substring(dot).toLowerCase();
      if (RegExp(r'^\.[a-z0-9]{1,8}$').hasMatch(ext)) return ext;
    }
  }
  return isVideo ? '.mp4' : '.jpg';
}

bool _isSafeMediaFileName(String name) {
  if (name.isEmpty || name == '.' || name == '..') return false;
  if (name.contains('/') || name.contains('\\') || name.contains('\u0000')) {
    return false;
  }
  if (RegExp(r'[<>:"|?*]').hasMatch(name)) return false;
  return true;
}

String _uniqueInFolder(String wanted, Set<String> used) {
  var name = wanted;
  if (!used.contains(name.toLowerCase())) {
    used.add(name.toLowerCase());
    return name;
  }
  final dot = wanted.lastIndexOf('.');
  final stem = dot > 0 ? wanted.substring(0, dot) : wanted;
  final ext = dot > 0 ? wanted.substring(dot) : '';
  var i = 2;
  while (used.contains('$stem\_$i$ext'.toLowerCase())) {
    i++;
  }
  name = '$stem\_$i$ext';
  used.add(name.toLowerCase());
  return name;
}

String _humanMediaFileName({
  required Map<String, dynamic> row,
  required bool isVideo,
  required int seq,
  required Set<String> used,
}) {
  final original = p.basename(
    '${row['original_filename'] ?? row['local_filename'] ?? ''}'
        .replaceAll('\\', '/'),
  );
  if (_isSafeMediaFileName(original) && original.contains('.')) {
    return _uniqueInFolder(original, used);
  }
  final ext = _extOf(row, isVideo: isVideo);
  final fallback =
      '${isVideo ? 'فيديو' : 'صورة'}_${seq.toString().padLeft(2, '0')}$ext';
  return _uniqueInFolder(fallback, used);
}

Future<ScopedExcelWriteResult> writeEvaluationExcelIntoBackup({
  required Directory packageDir,
  required EvalBackupScope scope,
  required List<Map<String, dynamic>> cacheRows,
  required List<Map<String, dynamic>> pendingRows,
  List<Map<String, dynamic>> mediaRows = const [],
  int chunkSize = kScopedBackupChunkSize,
  BackupCancelCheck? isCancelled,
}) async {
  final procedureDir = Directory(
    p.join(packageDir.path, kBackupEvalListsRoot, kBackupExcelProcedureFolder),
  );
  final dilemmaDir = Directory(
    p.join(packageDir.path, kBackupEvalListsRoot, kBackupExcelDilemmaFolder),
  );
  await procedureDir.create(recursive: true);
  await dilemmaDir.create(recursive: true);

  final hydrated = await hydrateCacheRowsForExcel(cacheRows);
  final pkg = assembleEvalBackup(
    scope: scope,
    pendingRows: pendingRows,
    cacheRows: hydrated,
    mediaRows: const [],
    includeTemplateRowsIfUnsaved: true,
  );

  final kindByRel = <String, String>{};
  final idByRel = <String, int>{};
  final metaByRel = <String, HumanReadableBackupMeta>{};
  var procedure = 0;
  var dilemma = 0;
  var images = 0;
  var videos = 0;
  final usedFolders = <String>{};

  for (final list in pkg.lists) {
    if (isCancelled?.call() == true) {
      throw const ScopedBackupIoException('cancelled');
    }
    if (list.exerciseId != scope.exerciseId) continue;
    final typeFolder = list.kind == EvalBackupKind.action
        ? kBackupExcelProcedureFolder
        : kBackupExcelDilemmaFolder;
    final folderName = evaluationListFolderName(
      displayName: list.listName,
      listId: list.evalItemId,
      usedFolders: usedFolders,
    );
    usedFolders.add(folderName);
    final listDirRel = '$kBackupEvalListsRoot/$typeFolder/$folderName';
    final listDir = Directory(p.join(packageDir.path, listDirRel));
    await listDir.create(recursive: true);

    final excelRel = '$listDirRel/$folderName.xlsx';
    await writeBytesChunked(
      File(p.join(packageDir.path, excelRel)),
      list.xlsxBytes,
      chunkSize: chunkSize,
    );
    final evaluationType =
        list.kind == EvalBackupKind.action ? 'procedure' : 'dilemma';
    final excelKind = list.kind == EvalBackupKind.action
        ? kProcedureExcelKind
        : kDilemmaExcelKind;
    kindByRel[excelRel] = excelKind;
    idByRel[excelRel] = list.evalItemId;
    metaByRel[excelRel] = HumanReadableBackupMeta(
      kind: excelKind,
      evaluationListId: list.evalItemId,
      evaluationType: evaluationType,
      exerciseId: scope.exerciseId,
      userId: scope.userId,
      displayName: list.listName,
    );
    if (list.kind == EvalBackupKind.action) {
      procedure++;
    } else {
      dilemma++;
    }

    final usedNames = <String>{'$folderName.xlsx'.toLowerCase()};
    var imageSeq = 1;
    var videoSeq = 1;
    final localPaths = localMediaPathsForList(cacheRows: hydrated, list: list);
    final mergedMedia = <Map<String, dynamic>>[
      ...mediaRows,
      ...localMediaRowsFromCache(
        cacheRows: hydrated,
        list: list,
        userId: scope.userId,
        exerciseId: scope.exerciseId,
      ),
    ];
    final seenMediaPaths = <String>{};
    for (final row in mergedMedia) {
      if (!mediaBelongsToEvaluationList(
        row: row,
        list: list,
        userId: scope.userId,
        exerciseId: scope.exerciseId,
        localMediaPaths: localPaths,
      )) {
        continue;
      }
      final srcPath = '${row['local_path'] ?? ''}';
      if (srcPath.isEmpty) continue;
      if (!seenMediaPaths.add(srcPath)) continue;
      final src = File(srcPath);
      if (!src.existsSync()) continue;
      final isVideo = _isVideoRow(row);
      final isImage = !isVideo && _isImageRow(row);
      if (!isImage && !isVideo) continue;
      final fileName = _humanMediaFileName(
        row: row,
        isVideo: isVideo,
        seq: isVideo ? videoSeq : imageSeq,
        used: usedNames,
      );
      if (isVideo) {
        videoSeq++;
      } else {
        imageSeq++;
      }
      final rel = '$listDirRel/$fileName';
      if (!isSafeRelativeBackupPath(rel)) continue;
      final dest = File(p.join(packageDir.path, rel));
      final size = await src.length();
      await streamCopyFile(
        source: src,
        dest: dest,
        expectedSize: size,
        chunkSize: chunkSize,
        isCancelled: isCancelled,
      );
      final mediaKind = isVideo
          ? (list.kind == EvalBackupKind.action
              ? kProcedureVideoKind
              : kDilemmaVideoKind)
          : (list.kind == EvalBackupKind.action
              ? kProcedureImageKind
              : kDilemmaImageKind);
      kindByRel[rel] = mediaKind;
      idByRel[rel] = list.evalItemId;
      metaByRel[rel] = HumanReadableBackupMeta(
        kind: mediaKind,
        evaluationListId: list.evalItemId,
        evaluationType: evaluationType,
        exerciseId: scope.exerciseId,
        userId: scope.userId,
        displayName: list.listName,
        evaluationItemId: rowAsInt(row['row_index']),
        mediaId: '${row['id'] ?? ''}'.trim().isEmpty ? null : '${row['id']}',
        mediaType: isVideo ? 'video' : 'image',
        sourceLocalPath: srcPath,
      );
      if (isVideo) {
        videos++;
      } else {
        images++;
      }
    }
  }
  return ScopedExcelWriteResult(
    procedureCount: procedure,
    dilemmaCount: dilemma,
    imageCount: images,
    videoCount: videos,
    evaluationListIdByRel: idByRel,
    kindByRel: kindByRel,
    metaByRel: metaByRel,
  );
}
