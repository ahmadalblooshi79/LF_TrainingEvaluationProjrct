import 'dart:convert';
import 'dart:io';

import 'package:archive/archive.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';

import '../theme/device_layout.dart';
import 'auth_service.dart';
import 'device_presence_service.dart';
import 'eval_backup_assembler.dart';
import 'offline_store.dart';

class EvalBackupResult {
  final bool ok;
  final String zipName;
  final String zipPath;
  final int zipBytes;
  final Uint8List? zipBytesData;
  final EvalBackupPackage? package;
  final String? error;

  const EvalBackupResult({
    required this.ok,
    required this.zipName,
    required this.zipPath,
    required this.zipBytes,
    this.zipBytesData,
    this.package,
    this.error,
  });
}

class EvalBackupService {
  EvalBackupService._();
  static final EvalBackupService instance = EvalBackupService._();

  static const _saveChannel = MethodChannel('lf.training/recovery_export');

  EvalBackupScope? currentScope() {
    final session = AuthService.instance.session;
    final exerciseId = session?.exercise?.id ?? 0;
    if (session == null || exerciseId <= 0) return null;
    final judge = session.user.judgeDisplayName.trim().isNotEmpty
        ? session.user.judgeDisplayName
        : session.user.fullName;
    return EvalBackupScope(
      exerciseId: exerciseId,
      exerciseName: session.exercise?.name ?? session.exercise?.code ?? '',
      userId: session.user.id,
      judgeId: session.user.id,
      judgeName: judge,
      unitKey: session.unitKey,
      unitName: session.unitLabel,
      deviceId: DevicePresenceService.instance.deviceId,
      appVersion: DeviceLayout.appVersion,
      createdAt: DateTime.now().toUtc().toIso8601String(),
    );
  }

  Future<EvalBackupPackage> preview() async {
    final scope = currentScope();
    if (scope == null) {
      throw StateError('لا يوجد تمرين حالي في الجلسة');
    }
    return _assemble(scope);
  }

  Future<EvalBackupResult> createBackup({EvalBackupPackage? preview}) async {
    final scope = currentScope();
    if (scope == null) {
      return const EvalBackupResult(
        ok: false,
        zipName: '',
        zipPath: '',
        zipBytes: 0,
        error: 'لا يوجد تمرين حالي في الجلسة',
      );
    }
    final pkg = preview ?? await _assemble(scope);
    for (final list in pkg.lists) {
      if (list.exerciseId != scope.exerciseId) {
        return const EvalBackupResult(
          ok: false,
          zipName: '',
          zipPath: '',
          zipBytes: 0,
          error: 'validation_failed_other_exercise',
        );
      }
    }
    for (final m in pkg.media) {
      if (m.exerciseId != null &&
          m.exerciseId != 0 &&
          m.exerciseId != scope.exerciseId) {
        return const EvalBackupResult(
          ok: false,
          zipName: '',
          zipPath: '',
          zipBytes: 0,
          error: 'validation_failed_media_other_exercise',
        );
      }
    }
    final zipName = suggestedEvalBackupZipName(scope);
    final files = <String, List<int>>{};
    for (final list in pkg.lists) {
      files[list.excelRelPath] = list.xlsxBytes;
    }
    for (final m in pkg.media) {
      if (!m.fileExists || m.localPath.isEmpty || kIsWeb) continue;
      try {
        final f = File(m.localPath);
        if (!f.existsSync()) continue;
        files[m.zipPath] = f.readAsBytesSync();
      } catch (_) {}
    }
    files['manifest.json'] = utf8.encode(
      const JsonEncoder.withIndent('  ').convert(pkg.toManifest()),
    );
    final archive = Archive();
    files.forEach((name, bytes) {
      archive.addFile(ArchiveFile(name, bytes.length, bytes));
    });
    final encoded = ZipEncoder().encode(archive) ?? <int>[];
    final data = Uint8List.fromList(encoded);
    var zipPath = '';
    if (!kIsWeb) {
      final dir = await getApplicationDocumentsDirectory();
      final outDir = Directory(p.join(dir.path, 'eval_backup'));
      if (!outDir.existsSync()) outDir.createSync(recursive: true);
      zipPath = p.join(outDir.path, zipName);
      File(zipPath).writeAsBytesSync(data);
    }
    return EvalBackupResult(
      ok: true,
      zipName: zipName,
      zipPath: zipPath,
      zipBytes: data.length,
      zipBytesData: data,
      package: pkg,
    );
  }

  Future<void> shareExport(EvalBackupResult result) async {
    if (!result.ok) return;
    if (!kIsWeb && result.zipPath.isNotEmpty && File(result.zipPath).existsSync()) {
      await Share.shareXFiles(
        [XFile(result.zipPath, mimeType: 'application/zip')],
        text: result.zipName,
      );
      return;
    }
    if (result.zipBytesData == null) return;
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

  Future<Map<String, String>?> copyExportToUserLocation(EvalBackupResult result) async {
    if (kIsWeb) {
      await shareExport(result);
      return {'name': result.zipName, 'uri': result.zipName};
    }
    final src = result.zipPath;
    if (src.isEmpty || !File(src).existsSync()) {
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

  Future<EvalBackupPackage> _assemble(EvalBackupScope scope) async {
    await OfflineStore.instance.init();
    final pending = await OfflineStore.instance.backupSelectPendingForExercise(
      exerciseId: scope.exerciseId,
      userId: scope.userId,
    );
    final cache = await OfflineStore.instance.backupSelectEvalCacheForUser(
      userId: scope.userId,
      unitKey: scope.unitKey,
    );
    final knownIds = <int>{};
    for (final row in pending) {
      final id = row['eval_item_id'];
      final n = id is int ? id : int.tryParse('${id ?? ''}');
      if (n != null && n > 0) knownIds.add(n);
    }
    final media = await OfflineStore.instance.backupSelectMediaForExercise(
      exerciseId: scope.exerciseId,
      evalItemIds: knownIds.toList(),
    );
    final existing = <String>{};
    if (!kIsWeb) {
      for (final row in media) {
        final path = '${row['local_path'] ?? ''}';
        if (path.isEmpty) continue;
        try {
          if (File(path).existsSync()) existing.add(path);
        } catch (_) {}
      }
    }
    var pkg = assembleEvalBackup(
      scope: scope,
      pendingRows: pending,
      cacheRows: cache,
      mediaRows: media,
      existingFilePaths: existing,
    );
    final extraIds = pkg.lists
        .map((e) => e.evalItemId)
        .where((id) => !knownIds.contains(id))
        .toList();
    if (extraIds.isNotEmpty) {
      final more = await OfflineStore.instance.backupSelectMediaForExercise(
        exerciseId: scope.exerciseId,
        evalItemIds: extraIds,
      );
      if (more.isNotEmpty) {
        for (final row in more) {
          final path = '${row['local_path'] ?? ''}';
          if (!kIsWeb && path.isNotEmpty) {
            try {
              if (File(path).existsSync()) existing.add(path);
            } catch (_) {}
          }
        }
        pkg = assembleEvalBackup(
          scope: scope,
          pendingRows: pending,
          cacheRows: cache,
          mediaRows: [...media, ...more],
          existingFilePaths: existing,
        );
      }
    }
    return pkg;
  }
}
