import 'dart:convert';
import 'dart:io';

import 'package:archive/archive.dart';
import 'package:crypto/crypto.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';

import '../models/user.dart';
import '../theme/device_layout.dart';
import 'auth_service.dart';
import 'device_presence_service.dart';
import 'local_recovery_parser.dart';
import 'local_recovery_xlsx.dart';
import 'offline_store.dart';

class RecoveryExportResult {
  final bool ok;
  final String zipName;
  final String zipPath;
  final int zipBytes;
  final String? excelError;
  final List<String> warnings;
  final Uint8List? zipBytesData;

  const RecoveryExportResult({
    required this.ok,
    required this.zipName,
    required this.zipPath,
    required this.zipBytes,
    this.excelError,
    this.warnings = const [],
    this.zipBytesData,
  });
}

/// Read-only local recovery: inspects tablet_offline.db and copies user-generated
/// evidence into a new ZIP. Never calls the network or mutates source tables.
class LocalRecoveryService {
  LocalRecoveryService._();
  static final LocalRecoveryService instance = LocalRecoveryService._();

  Future<LocalRecoveryScan> scan() async {
    await OfflineStore.instance.init();
    try {
      await DevicePresenceService.instance.init();
    } catch (_) {}

    final pending = await OfflineStore.instance.recoverySelectPendingOps();
    final cache = await OfflineStore.instance.recoverySelectCache();
    final media = await OfflineStore.instance.recoverySelectMedia();
    final ctx = await _buildContext(pending);

    RecoveryFileStat fileStat(String path) {
      if (kIsWeb || path.isEmpty) {
        return const RecoveryFileStat(exists: false, size: 0);
      }
      try {
        final f = File(path);
        if (!f.existsSync()) {
          return const RecoveryFileStat(exists: false, size: 0);
        }
        return RecoveryFileStat(exists: true, size: f.lengthSync());
      } catch (_) {
        return const RecoveryFileStat(exists: false, size: 0);
      }
    }

    final orphans = await _listOrphanPendingMedia(media);

    return assembleRecoveryScan(
      context: ctx,
      pendingRows: pending,
      cacheRows: cache,
      mediaRows: media,
      fileStat: kIsWeb ? null : fileStat,
      orphanMediaPaths: orphans,
    );
  }

  Future<RecoveryExportResult> exportScan(LocalRecoveryScan scan) async {
    final warnings = <String>[];
    final stamp = _stamp(scan.context.exportTimestamp);
    final devicePart = _safeName(
      scan.context.deviceId.isEmpty ? 'unknown' : scan.context.deviceId,
    );
    final zipName = 'Tablet_Recovery_${devicePart}_$stamp.zip';

    final files = <String, List<int>>{};
    final checksums = <String, String>{};

    void putFile(String rel, List<int> bytes) {
      files[rel.replaceAll('\\', '/')] = bytes;
      checksums[rel.replaceAll('\\', '/')] =
          sha256.convert(bytes).toString();
    }

    putFile(
      'data/pending_ops.json',
      utf8.encode(
        const JsonEncoder.withIndent('  ').convert({
          'note':
              'Canonical recovery source. body is the original pending_ops.body.',
          'operations': scan.pendingOps
              .map((o) => o.toJson(includeParsed: true))
              .toList(),
        }),
      ),
    );

    putFile(
      'data/cache_evaluations.json',
      utf8.encode(
        const JsonEncoder.withIndent('  ').convert({
          'entries': scan.cacheEvaluations
              .map(
                (c) => {
                  'cache_key': c.cacheKey,
                  'sync_status': c.syncStatus,
                  'updated_at': c.updatedAt,
                  'locally_modified': c.locallyModified,
                  'saved_payload_exists': c.savedPayloadExists,
                  'saved_rows_count': c.savedRows.length,
                  'eval_item_id': c.evalItemId,
                  'list_id': c.listId,
                  'user_id': c.userId,
                  'json_body': c.jsonBodyRaw,
                },
              )
              .toList(),
        }),
      ),
    );

    String? excelError;
    try {
      final xlsx = buildSimpleXlsx(_excelSheets(scan));
      if (xlsx.isEmpty) {
        excelError = 'xlsx encoder returned empty';
        warnings.add(excelError);
      } else {
        putFile('Recovery_Report.xlsx', xlsx);
      }
    } catch (e) {
      excelError = '$e';
      warnings.add('Excel generation failed: $e');
    }

    final mediaManifest = <Map<String, dynamic>>[];
    if (!kIsWeb) {
      for (final item in scan.media) {
        final rec = Map<String, dynamic>.from(item.toJson());
        rec['exported_path'] = '';
        rec['copy_ok'] = 'NO';
        final src = item.localPath;
        if (item.fileExists && src.isNotEmpty) {
          try {
            final bytes = await File(src).readAsBytes();
            final rel = _exportedMediaRel(item);
            putFile(rel, bytes);
            rec['exported_path'] = rel;
            rec['copy_ok'] = 'YES';
          } catch (e) {
            rec['copy_error'] = '$e';
            warnings.add('media copy failed ${item.id}: $e');
          }
        }
        mediaManifest.add(rec);
      }

      for (final orphan in scan.orphanMediaPaths) {
        try {
          final f = File(orphan);
          if (!await f.exists()) continue;
          final bytes = await f.readAsBytes();
          final kindDir = _orphanKindDir(orphan);
          final rel = '$kindDir/orphan_${p.basename(orphan)}';
          putFile(rel, bytes);
          mediaManifest.add({
            'id': '',
            'local_path': orphan,
            'exported_path': rel,
            'file_exists': 'YES',
            'actual_file_size': bytes.length,
            'orphan': true,
            'copy_ok': 'YES',
          });
        } catch (e) {
          warnings.add('orphan copy failed $orphan: $e');
        }
      }

      await _copySignatures(putFile, warnings);
    } else {
      for (final item in scan.media) {
        mediaManifest.add(item.toJson());
      }
    }

    putFile(
      'data/media_manifest.json',
      utf8.encode(
        const JsonEncoder.withIndent('  ').convert({
          'records': mediaManifest,
          'orphan_paths': scan.orphanMediaPaths,
        }),
      ),
    );

    if (scan.signatureCacheEntries.isNotEmpty) {
      putFile(
        'data/approvals.json',
        utf8.encode(
          const JsonEncoder.withIndent('  ').convert({
            'note': 'Local signature/approval cache only. Not invented.',
            'entries': scan.signatureCacheEntries
                .map((e) => Map<String, dynamic>.from(e))
                .toList(),
          }),
        ),
      );
    }

    final manifest = <String, dynamic>{
      'recovery_format_version': kRecoveryFormatVersion,
      'export_timestamp': scan.context.exportTimestamp,
      'app_version': scan.context.appVersion,
      'device_id': scan.context.deviceId,
      'exercise_id': scan.context.exerciseId,
      'judge_id': scan.context.judgeId,
      'user_id': scan.context.userId,
      'unit': scan.context.unit,
      'pending_operation_count': scan.counts['pending_operations'] ?? 0,
      'save_results_operation_count':
          scan.counts['save_results_operations'] ?? 0,
      'evaluation_count': scan.counts['evaluations_found'] ?? 0,
      'media_count': scan.counts['media_count'] ?? 0,
      'image_count': scan.counts['images_local'] ?? 0,
      'video_count': scan.counts['videos_local'] ?? 0,
      'failed_operation_count': scan.counts['failed_operations'] ?? 0,
      'file_checksums_sha256': checksums,
      'warnings': warnings,
      'network_calls': 'NONE',
    };
    putFile(
      'manifest.json',
      utf8.encode(const JsonEncoder.withIndent('  ').convert(manifest)),
    );

    final archive = Archive();
    files.forEach((name, bytes) {
      archive.addFile(ArchiveFile(name, bytes.length, bytes));
    });
    final zipBytes = ZipEncoder().encode(archive);
    if (zipBytes == null || zipBytes.isEmpty) {
      return RecoveryExportResult(
        ok: false,
        zipName: zipName,
        zipPath: '',
        zipBytes: 0,
        excelError: excelError,
        warnings: [...warnings, 'ZIP encoder returned empty'],
      );
    }
    final data = Uint8List.fromList(zipBytes);

    var savedPath = '';
    if (!kIsWeb) {
      try {
        final docs = await getApplicationDocumentsDirectory();
        final dir = Directory(p.join(docs.path, 'recovery_exports'));
        if (!await dir.exists()) {
          await dir.create(recursive: true);
        }
        final out = File(p.join(dir.path, zipName));
        await out.writeAsBytes(data, flush: true);
        savedPath = out.path;
      } catch (e) {
        warnings.add('could not persist zip locally: $e');
      }
    }

    return RecoveryExportResult(
      ok: true,
      zipName: zipName,
      zipPath: savedPath,
      zipBytes: data.length,
      excelError: excelError,
      warnings: warnings,
      zipBytesData: data,
    );
  }

  Future<void> shareExport(RecoveryExportResult result) async {
    if (result.zipBytesData == null) return;
    if (!kIsWeb && result.zipPath.isNotEmpty) {
      await Share.shareXFiles(
        [XFile(result.zipPath, mimeType: 'application/zip')],
        text: result.zipName,
      );
      return;
    }
    await Share.shareXFiles(
      [
        XFile.fromData(
          result.zipBytesData!,
          name: result.zipName,
          mimeType: 'application/zip',
        ),
      ],
      text: result.zipName,
    );
  }

  static const _saveChannel = MethodChannel('lf.training/recovery_export');

  /// Copies the already-written private ZIP to a user-chosen public location
  /// (Android ACTION_CREATE_DOCUMENT). Does not move or delete the original.
  /// Returns null if the operator cancelled the picker.
  Future<Map<String, String>?> copyExportToUserLocation(
    RecoveryExportResult result,
  ) async {
    if (kIsWeb) {
      await shareExport(result);
      return {'name': result.zipName, 'uri': result.zipName};
    }
    final src = result.zipPath;
    if (src.isEmpty) {
      throw StateError('private zip path is empty');
    }
    final file = File(src);
    if (!await file.exists()) {
      throw StateError('private zip is missing');
    }
    final raw = await _saveChannel.invokeMethod<dynamic>(
      'saveZipCopy',
      {
        'sourcePath': src,
        'suggestedName': result.zipName,
      },
    );
    if (raw == null) return null;
    if (raw is Map) {
      return {
        'name': '${raw['name'] ?? result.zipName}',
        'uri': '${raw['uri'] ?? ''}',
      };
    }
    return {'name': result.zipName, 'uri': '$raw'};
  }

  Future<RecoveryContext> _buildContext(
    List<Map<String, dynamic>> pending,
  ) async {
    final session = AuthService.instance.session;
    String judgeName = '';
    String unit = '';
    int? userId;
    int? judgeId;
    int? exerciseId;

    if (session != null) {
      judgeName = session.user.judgeDisplayName;
      if (judgeName.isEmpty) judgeName = session.user.fullName;
      unit = session.unitLabel;
      userId = session.user.id;
      judgeId = session.user.id;
      exerciseId = session.exercise?.id;
    } else {
      final users = await OfflineStore.instance.allLocalUsers();
      if (users.isNotEmpty) {
        Map<String, dynamic> pick = users.first;
        final counts = <int, int>{};
        for (final row in pending) {
          final uid = recoveryAsInt(row['user_id']);
          if (uid == null) continue;
          counts[uid] = (counts[uid] ?? 0) + 1;
        }
        if (counts.isNotEmpty) {
          final top = counts.entries.reduce((a, b) => a.value >= b.value ? a : b).key;
          for (final u in users) {
            if (recoveryAsInt(u['user_id']) == top) {
              pick = u;
              break;
            }
          }
        }
        userId = recoveryAsInt(pick['user_id']);
        judgeId = userId;
        try {
          final raw = pick['session_json'];
          if (raw is String && raw.isNotEmpty) {
            final decoded = jsonDecode(raw);
            if (decoded is Map) {
              final bundle = SessionBundle.fromJson(
                Map<String, dynamic>.from(decoded),
              );
              judgeName = bundle.user.judgeDisplayName;
              if (judgeName.isEmpty) judgeName = bundle.user.fullName;
              unit = bundle.unitLabel;
              exerciseId = bundle.exercise?.id;
            }
          }
        } catch (_) {}
      }
    }

    if (exerciseId == null || exerciseId == 0) {
      for (final row in pending) {
        final ex = recoveryAsInt(row['exercise_id']);
        if (ex != null && ex > 0) {
          exerciseId = ex;
          break;
        }
      }
    }

    return RecoveryContext(
      exportTimestamp: DateTime.now().toIso8601String(),
      appVersion: DeviceLayout.appVersion,
      deviceId: DevicePresenceService.instance.deviceId,
      exerciseId: exerciseId,
      judgeId: judgeId,
      userId: userId,
      judgeName: judgeName,
      unit: unit,
      databaseVersion: '${OfflineStore.databaseSchemaVersion}',
    );
  }

  Future<List<String>> _listOrphanPendingMedia(
    List<Map<String, dynamic>> mediaRows,
  ) async {
    if (kIsWeb) return const [];
    final known = <String>{};
    for (final row in mediaRows) {
      final path = recoveryAsString(row['local_path']);
      if (path.isNotEmpty) known.add(p.normalize(path));
    }
    final out = <String>[];
    try {
      final docs = await getApplicationDocumentsDirectory();
      final pendingRoot = Directory(p.join(docs.path, 'media', 'pending'));
      if (!await pendingRoot.exists()) return out;
      await for (final ent in pendingRoot.list(recursive: true, followLinks: false)) {
        if (ent is! File) continue;
        final n = p.normalize(ent.path);
        if (!known.contains(n)) out.add(ent.path);
      }
    } catch (_) {}
    return out;
  }

  Future<void> _copySignatures(
    void Function(String rel, List<int> bytes) putFile,
    List<String> warnings,
  ) async {
    try {
      final docs = await getApplicationDocumentsDirectory();
      final dir = Directory(p.join(docs.path, 'judge_signatures'));
      if (!await dir.exists()) return;
      await for (final ent in dir.list(followLinks: false)) {
        if (ent is! File) continue;
        try {
          final bytes = await ent.readAsBytes();
          putFile('signatures/${p.basename(ent.path)}', bytes);
        } catch (e) {
          warnings.add('signature copy failed ${ent.path}: $e');
        }
      }
    } catch (_) {}
  }
}

Map<String, List<List<String>>> _excelSheets(LocalRecoveryScan scan) {
  final ctx = scan.context;
  final c = scan.counts;
  final info = <List<String>>[
    ['Field', 'Value'],
    ['Export Date/Time', ctx.exportTimestamp],
    ['Application Version', ctx.appVersion],
    ['Device ID', ctx.deviceId],
    ['Exercise ID', '${ctx.exerciseId ?? ''}'],
    ['Judge ID', '${ctx.judgeId ?? ''}'],
    ['User ID', '${ctx.userId ?? ''}'],
    ['Judge Name', ctx.judgeName],
    ['Unit', ctx.unit],
    ['Database Version', ctx.databaseVersion],
    ['Recovery Format Version', kRecoveryFormatVersion],
  ];

  final evalRows = <List<String>>[
    [
      'Recovery Source',
      'pending_op_id',
      'client_op_id',
      'exercise_id',
      'judge_id',
      'user_id',
      'list_id',
      'eval_item_id',
      'element',
      'row_kind',
      'max_val',
      'acquired',
      'notes',
      'operation_status',
      'created_at',
    ],
  ];
  for (final r in flattenEvaluationResultRows(scan)) {
    evalRows.add([
      r.recoverySource,
      r.pendingOpId,
      r.clientOpId,
      '${r.exerciseId ?? ''}',
      '${r.judgeId ?? ''}',
      '${r.userId ?? ''}',
      r.listId,
      '${r.evalItemId ?? ''}',
      r.row.element,
      r.row.rowKind,
      r.row.maxVal,
      r.row.acquired,
      r.row.notes,
      r.operationStatus,
      r.createdAt,
    ]);
  }

  final pendingSheet = <List<String>>[
    [
      'id',
      'kind',
      'op_type',
      'method',
      'path',
      'exercise_id',
      'judge_id',
      'user_id',
      'list_id',
      'eval_item_id',
      'sync_status',
      'attempts',
      'last_error',
      'created_at',
      'client_op_id',
      'Body Parse Successful',
      'Rows Found',
      'Rows With Scores',
      'Rows With Notes',
    ],
  ];
  for (final o in scan.pendingOps) {
    pendingSheet.add([
      o.id,
      o.kind,
      o.opType,
      o.method,
      o.path,
      '${o.exerciseId ?? ''}',
      '${o.judgeId ?? ''}',
      '${o.userId ?? ''}',
      o.listId,
      '${o.evalItemId ?? ''}',
      o.syncStatus,
      '${o.attempts}',
      o.lastError,
      o.createdAt,
      o.parsed.clientOpId,
      o.parsed.parseSuccessful ? 'YES' : 'NO',
      '${o.parsed.rows.length}',
      '${o.parsed.rowsWithScores}',
      '${o.parsed.rowsWithNotes}',
    ]);
  }

  final cacheSheet = <List<String>>[
    [
      'cache_key',
      'sync_status',
      'updated_at',
      'locally_modified',
      'eval_item_id',
      'list_id',
      'user_id',
      'saved_rows_count',
      'saved_payload_exists',
    ],
  ];
  for (final e in scan.cacheEvaluations) {
    cacheSheet.add([
      e.cacheKey,
      e.syncStatus,
      e.updatedAt,
      e.locallyModified ? 'YES' : 'NO',
      '${e.evalItemId ?? ''}',
      e.listId ?? '',
      '${e.userId ?? ''}',
      '${e.savedRows.length}',
      e.savedPayloadExists ? 'YES' : 'NO',
    ]);
  }

  final mediaSheet = <List<String>>[
    [
      'media id',
      'client_uuid',
      'exercise_id',
      'user_id',
      'evaluation_list_item_id',
      'bundle_action_eval_id',
      'row_index',
      'media_kind',
      'local_path',
      'local_filename',
      'original_filename',
      'file_size',
      'actual_file_size',
      'file_exists',
      'sync_status',
      'server_confirmed',
      'attempt_count',
      'last_error',
      'sheet_cache_key',
    ],
  ];
  for (final m in scan.media) {
    final f = m.fields;
    mediaSheet.add([
      recoveryAsString(f['id']),
      recoveryAsString(f['client_uuid']),
      recoveryAsString(f['exercise_id']),
      recoveryAsString(f['user_id']),
      recoveryAsString(f['evaluation_list_item_id']),
      recoveryAsString(f['bundle_action_eval_id']),
      recoveryAsString(f['row_index']),
      recoveryAsString(f['media_kind']),
      recoveryAsString(f['local_path']),
      recoveryAsString(f['local_filename']),
      recoveryAsString(f['original_filename']),
      recoveryAsString(f['file_size']),
      '${m.actualFileSize}',
      m.fileExists ? 'YES' : 'NO',
      recoveryAsString(f['sync_status']),
      recoveryAsString(f['server_confirmed']),
      recoveryAsString(f['attempt_count']),
      recoveryAsString(f['last_error']),
      recoveryAsString(f['sheet_cache_key']),
    ]);
  }

  final summary = <List<String>>[
    ['Metric', 'Value'],
    ['Evaluations found', '${c['evaluations_found'] ?? 0}'],
    ['Evaluations with scores', '${c['evaluations_with_scores'] ?? 0}'],
    ['Evaluations with notes', '${c['evaluations_with_notes'] ?? 0}'],
    ['Pending operations', '${c['pending_operations'] ?? 0}'],
    ['Failed operations', '${c['failed_operations'] ?? 0}'],
    ['Images found', '${c['images_local'] ?? 0}'],
    ['Videos found', '${c['videos_local'] ?? 0}'],
    ['Missing physical media', '${c['missing_physical_media'] ?? 0}'],
    ['Source mismatches', '${c['source_mismatches'] ?? 0}'],
    ['Recoverable evaluation items', '${c['recoverable_evaluation_items'] ?? 0}'],
  ];

  return {
    '01_Export_Info': info,
    '02_Evaluation_Results': evalRows,
    '03_Pending_Operations': pendingSheet,
    '04_Cache_Evaluations': cacheSheet,
    '05_Media': mediaSheet,
    '06_Recovery_Summary': summary,
  };
}

String _exportedMediaRel(RecoveredMediaItem item) {
  final name = _safeName(
    recoveryAsString(item.fields['local_filename']).isNotEmpty
        ? recoveryAsString(item.fields['local_filename'])
        : (recoveryAsString(item.fields['original_filename']).isNotEmpty
            ? recoveryAsString(item.fields['original_filename'])
            : p.basename(item.localPath)),
  );
  final id = _safeName(item.id.isEmpty ? 'media' : item.id);
  if (item.isVideo) return 'videos/${id}_$name';
  if (item.isImage) return 'images/${id}_$name';
  return 'files/${id}_$name';
}

String _orphanKindDir(String path) {
  final lower = path.replaceAll('\\', '/').toLowerCase();
  if (lower.contains('/videos/')) return 'videos';
  if (lower.contains('/images/')) return 'images';
  return 'files';
}

String _safeName(String raw) {
  final s = raw.replaceAll(RegExp(r'[^\w.\-]+'), '_');
  if (s.isEmpty) return 'x';
  return s.length > 80 ? s.substring(0, 80) : s;
}

String _stamp(String iso) {
  final dt = DateTime.tryParse(iso) ?? DateTime.now();
  String two(int n) => n.toString().padLeft(2, '0');
  return '${dt.year}${two(dt.month)}${two(dt.day)}_${two(dt.hour)}${two(dt.minute)}';
}
