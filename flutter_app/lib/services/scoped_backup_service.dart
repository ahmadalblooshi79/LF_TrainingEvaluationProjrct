import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';

import '../theme/device_layout.dart';
import 'auth_service.dart';
import 'device_presence_service.dart';
import 'media_upload_service.dart';
import 'offline_store.dart';
import 'scoped_backup_excel.dart';
import 'scoped_backup_inventory.dart';
import 'scoped_backup_io.dart';
import 'scoped_backup_models.dart';
import 'scoped_backup_paths.dart';
import 'sync_service.dart';

class SourceFingerprint {
  final String cache;
  final String pending;
  final String media;
  final String users;
  final String deviceMeta;
  final Map<String, String> mediaFiles;

  const SourceFingerprint({
    required this.cache,
    required this.pending,
    required this.media,
    required this.users,
    required this.deviceMeta,
    required this.mediaFiles,
  });

  bool sameAs(SourceFingerprint other) {
    if (cache != other.cache) return false;
    if (pending != other.pending) return false;
    if (media != other.media) return false;
    if (users != other.users) return false;
    if (deviceMeta != other.deviceMeta) return false;
    if (mediaFiles.length != other.mediaFiles.length) return false;
    for (final e in mediaFiles.entries) {
      if (other.mediaFiles[e.key] != e.value) return false;
    }
    return true;
  }
}

class ScopedBackupResult {
  final ScopedBackupStatus status;
  final String? error;
  final String? packagePath;
  final ScopedBackupManifest? manifest;
  final List<String> warnings;
  final String? publicDisplayPath;
  final String? publicRelativeDir;
  final int procedureExcelCount;
  final int dilemmaExcelCount;
  final int evaluationImageCount;
  final int evaluationVideoCount;

  const ScopedBackupResult({
    required this.status,
    this.error,
    this.packagePath,
    this.manifest,
    this.warnings = const [],
    this.publicDisplayPath,
    this.publicRelativeDir,
    this.procedureExcelCount = 0,
    this.dilemmaExcelCount = 0,
    this.evaluationImageCount = 0,
    this.evaluationVideoCount = 0,
  });

  bool get verified => status == ScopedBackupStatus.verified;

  bool get savedToPublicDownloads =>
      verified &&
      publicDisplayPath != null &&
      publicDisplayPath!.isNotEmpty;
}

class ScopedRestoreResult {
  final bool ok;
  final String? error;
  final bool rolledBack;
  final bool rollbackFailed;
  final List<String> warnings;

  const ScopedRestoreResult({
    required this.ok,
    this.error,
    this.rolledBack = false,
    this.rollbackFailed = false,
    this.warnings = const [],
  });
}

class ScopedBackupService {
  ScopedBackupService._();
  static final ScopedBackupService instance = ScopedBackupService._();

  static const _channel = MethodChannel('lf.training/recovery_export');

  bool _cancelled = false;
  bool get isCancelled => _cancelled;

  void requestCancel() => _cancelled = true;

  void resetCancel() => _cancelled = false;

  Future<ScopedBackupExercise?> currentExercise() async {
    await OfflineStore.instance.init();
    final cached = await OfflineStore.instance.cacheGet('device_exercise');
    if (cached != null) {
      final id = rowAsInt(cached['id'] ?? cached['exercise_id']) ?? 0;
      if (id > 0) {
        return ScopedBackupExercise(
          exerciseId: id,
          name: '${cached['name'] ?? ''}',
          code: '${cached['code'] ?? ''}',
        );
      }
    }
    final session = AuthService.instance.session;
    final sid = session?.exercise?.id ?? 0;
    if (sid > 0) {
      return ScopedBackupExercise(
        exerciseId: sid,
        name: session?.exercise?.name ?? '',
        code: session?.exercise?.code ?? '',
      );
    }
    return null;
  }

  Future<List<Map<String, dynamic>>> provisionedUsersSafe() async {
    await OfflineStore.instance.init();
    final rows = await OfflineStore.instance.allLocalUsers();
    return rows.map(safeLocalUserDisplay).where((e) => (e['user_id'] as int) > 0).toList();
  }

  Future<SourceFingerprint> captureSourceFingerprint() async {
    await OfflineStore.instance.init();
    final cache = await OfflineStore.instance.recoverySelectCache();
    final pending = await OfflineStore.instance.recoverySelectPendingOps();
    final media = await OfflineStore.instance.recoverySelectMedia();
    final users = await OfflineStore.instance.allLocalUsers();
    final meta = await OfflineStore.instance.recoverySelectDeviceMeta();
    final mediaFiles = kIsWeb
        ? <String, String>{}
        : await hashExistingMediaFiles(media);
    return SourceFingerprint(
      cache: fingerprintPayload(cache, ['cache_key', 'json_body', 'updated_at', 'sync_status']),
      pending: fingerprintPayload(pending, [
        'id',
        'method',
        'path',
        'body',
        'op_type',
        'sync_status',
        'attempts',
        'user_id',
        'exercise_id',
      ]),
      media: fingerprintPayload(media, [
        'id',
        'local_path',
        'sync_status',
        'user_id',
        'exercise_id',
        'checksum',
        'file_size',
        'server_confirmed',
      ]),
      users: fingerprintPayload(users, [
        'user_id',
        'username',
        'military_number',
        'password_hash',
        'session_json',
        'updated_at',
      ]),
      deviceMeta: fingerprintPayload(meta, ['meta_key', 'meta_value']),
      mediaFiles: mediaFiles,
    );
  }

  Future<ScopedBackupResult> createBackupForUser({
    required int userId,
    Directory? destinationParent,
    void Function(ScopedBackupProgress progress)? onProgress,
    int? freeBytes,
  }) async {
    resetCancel();
    await OfflineStore.instance.init();
    final exercise = await currentExercise();
    if (exercise == null || exercise.exerciseId <= 0) {
      return const ScopedBackupResult(
        status: ScopedBackupStatus.failed,
        error: 'لا يوجد تمرين حالي',
      );
    }
    final userRow = await OfflineStore.instance.localUserById(userId);
    if (userRow == null) {
      return const ScopedBackupResult(
        status: ScopedBackupStatus.failed,
        error: 'المستخدم غير مُهيأ على هذا الجهاز',
      );
    }
    final identity = identityFromLocalUser(userRow);
    onProgress?.call(const ScopedBackupProgress(stage: 'جارٍ إنشاء النسخة الاحتياطية'));
    Directory? largeCacheDir;
    if (!kIsWeb) {
      final tmp = await getTemporaryDirectory();
      largeCacheDir = Directory(
        p.join(tmp.path, 'scoped_backup_cachebody_$userId'),
      );
      if (largeCacheDir.existsSync()) {
        await largeCacheDir.delete(recursive: true);
      }
      await largeCacheDir.create(recursive: true);
    }
    final scopedCache = await OfflineStore.instance.backupSelectScopedCacheForUser(
      userId: userId,
      exerciseId: exercise.exerciseId,
      largeBodyDir: largeCacheDir,
    );
    final cacheRows = selectUserExerciseCache(
      allCache: scopedCache,
      userId: userId,
      exerciseId: exercise.exerciseId,
    );
    final pendingRows = await OfflineStore.instance.backupSelectPendingForUserExercise(
      exerciseId: exercise.exerciseId,
      userId: userId,
    );
    final evalIds = evalIdsFromCacheAndPending(
      cacheRows: cacheRows,
      pendingRows: pendingRows,
    );
    final scopedMedia =
        await OfflineStore.instance.backupSelectMediaMetadataForUserExercise(
      userId: userId,
      exerciseId: exercise.exerciseId,
    );
    final mediaRows = selectUserExerciseMedia(
      allMedia: scopedMedia,
      userId: userId,
      exerciseId: exercise.exerciseId,
      selectedEvalIds: evalIds,
    );
    File? signature;
    if (!kIsWeb) {
      try {
        final docs = await getApplicationDocumentsDirectory();
        final sig = File(p.join(docs.path, 'judge_signatures', '$userId.png'));
        if (sig.existsSync()) signature = sig;
      } catch (_) {}
    }
    Directory parent;
    if (destinationParent != null) {
      parent = destinationParent;
    } else if (kIsWeb) {
      return const ScopedBackupResult(
        status: ScopedBackupStatus.failed,
        error: 'النسخ الاحتياطي الآمن غير متاح على الويب',
      );
    } else {
      final docs = await getApplicationDocumentsDirectory();
      parent = Directory(p.join(docs.path, 'scoped_backups'));
    }
    final resolvedFree = freeBytes ?? await MediaUploadService.instance.freeDiskBytes();
    final written = await writeBackupPackage(
      destinationParent: parent,
      identity: identity,
      exercise: exercise,
      cacheRows: cacheRows,
      pendingRows: pendingRows,
      mediaRows: mediaRows,
      signatureFile: signature,
      freeBytes: resolvedFree,
      onProgress: onProgress,
      isCancelled: () => _cancelled,
    );
    if (!written.verified) return written;
    if (destinationParent != null || kIsWeb) return written;
    return exportVerifiedBackupToPublicDownloads(
      result: written,
      exercise: exercise,
      identity: identity,
      onProgress: onProgress,
    );
  }

  Future<ScopedBackupResult> exportVerifiedBackupToPublicDownloads({
    required ScopedBackupResult result,
    required ScopedBackupExercise exercise,
    required ScopedBackupIdentity identity,
    void Function(ScopedBackupProgress progress)? onProgress,
  }) async {
    if (!result.verified || result.packagePath == null || kIsWeb) {
      return result;
    }
    onProgress?.call(const ScopedBackupProgress(
      stage: 'جارٍ حفظ النسخة الاحتياطية في التنزيلات',
    ));
    List<Map<String, dynamic>> users = const [];
    try {
      users = await provisionedUsersSafe();
    } catch (_) {}
    final location = buildPublicBackupLocation(
      exercise: exercise,
      identity: identity,
      siblingDisplayNames: users.map((u) => '${u['display_name'] ?? ''}'),
    );
    if (!isSafePublicRelativeDir(location.relativeDir)) {
      return ScopedBackupResult(
        status: ScopedBackupStatus.failed,
        error: 'مسار مجلد التنزيلات غير آمن',
        packagePath: result.packagePath,
        manifest: result.manifest,
        warnings: result.warnings,
      );
    }
    try {
      final raw = await _channel.invokeMethod<dynamic>(
        'copyBackupToPublicDownloads',
        {
          'sourceDir': result.packagePath,
          'relativeDir': location.relativeDir,
        },
      );
      if (raw is! Map) {
        return ScopedBackupResult(
          status: ScopedBackupStatus.failed,
          error: 'تعذر حفظ النسخة الاحتياطية في مجلد التنزيلات',
          packagePath: result.packagePath,
          manifest: result.manifest,
          warnings: result.warnings,
          procedureExcelCount: result.procedureExcelCount,
          dilemmaExcelCount: result.dilemmaExcelCount,
          evaluationImageCount: result.evaluationImageCount,
          evaluationVideoCount: result.evaluationVideoCount,
        );
      }
      final displayPath = '${raw['displayPath'] ?? ''}'.trim();
      final relativeDir = '${raw['relativeDir'] ?? location.relativeDir}'.trim();
      final fileCount = int.tryParse('${raw['fileCount'] ?? '0'}') ?? 0;
      final totalBytes = int.tryParse('${raw['totalBytes'] ?? '0'}') ?? 0;
      if (displayPath.isEmpty ||
          !isSafePublicRelativeDir(relativeDir) ||
          fileCount <= 0) {
        return ScopedBackupResult(
          status: ScopedBackupStatus.failed,
          error: 'تعذر حفظ النسخة الاحتياطية في مجلد التنزيلات',
          packagePath: result.packagePath,
          manifest: result.manifest,
          warnings: result.warnings,
          procedureExcelCount: result.procedureExcelCount,
          dilemmaExcelCount: result.dilemmaExcelCount,
          evaluationImageCount: result.evaluationImageCount,
          evaluationVideoCount: result.evaluationVideoCount,
        );
      }
      debugPrint(
        'LFBackupExport public files=$fileCount bytes=$totalBytes path=$displayPath',
      );
      return ScopedBackupResult(
        status: ScopedBackupStatus.verified,
        packagePath: result.packagePath,
        manifest: result.manifest,
        warnings: result.warnings,
        publicDisplayPath: displayPath,
        publicRelativeDir: relativeDir,
        procedureExcelCount: result.procedureExcelCount,
        dilemmaExcelCount: result.dilemmaExcelCount,
        evaluationImageCount: result.evaluationImageCount,
        evaluationVideoCount: result.evaluationVideoCount,
      );
    } catch (e) {
      return ScopedBackupResult(
        status: ScopedBackupStatus.failed,
        error: 'تعذر حفظ النسخة الاحتياطية في مجلد التنزيلات',
        packagePath: result.packagePath,
        manifest: result.manifest,
        warnings: result.warnings,
      );
    }
  }

  Future<bool> openPublicBackupFolder(String relativeDir) async {
    if (kIsWeb || !isSafePublicRelativeDir(relativeDir)) return false;
    try {
      final raw = await _channel.invokeMethod<dynamic>(
        'openPublicBackupFolder',
        {'relativeDir': relativeDir},
      );
      return raw == true;
    } catch (_) {
      return false;
    }
  }

  Future<ScopedBackupResult> writeBackupPackage({
    required Directory destinationParent,
    required ScopedBackupIdentity identity,
    required ScopedBackupExercise exercise,
    required List<Map<String, dynamic>> cacheRows,
    required List<Map<String, dynamic>> pendingRows,
    required List<Map<String, dynamic>> mediaRows,
    File? signatureFile,
    int? freeBytes,
    void Function(ScopedBackupProgress progress)? onProgress,
    BackupCancelCheck? isCancelled,
    int chunkSize = kScopedBackupChunkSize,
  }) async {
    final warnings = <String>[];
    for (final row in cacheRows) {
      try {
        final body = jsonDecode('${row['json_body'] ?? '{}'}');
        if (jsonContainsSecretField(body)) {
          warnings.add('secret_stripped:${row['cache_key']}');
        }
      } catch (_) {}
    }
    Directory? inProgress;
    try {
      onProgress?.call(const ScopedBackupProgress(
        stage: 'جارٍ إنشاء النسخة الاحتياطية',
      ));
      final mediaPlan = <_MediaCopyPlan>[];
      var mediaBytes = 0;
      for (final row in mediaRows) {
        final srcPath = '${row['local_path'] ?? ''}';
        final rel = mediaBackupRelPath(row);
        if (!isSafeRelativeBackupPath(rel)) {
          return const ScopedBackupResult(
            status: ScopedBackupStatus.failed,
            error: 'مسار وسائط غير آمن',
          );
        }
        if (srcPath.isEmpty || kIsWeb) {
          warnings.add('media_missing_path:${row['id']}');
          continue;
        }
        final src = File(srcPath);
        if (!src.existsSync()) {
          return ScopedBackupResult(
            status: ScopedBackupStatus.failed,
            error: 'ملف الوسائط مفقود: ${row['id']}',
          );
        }
        onProgress?.call(ScopedBackupProgress(
          stage: 'جارٍ إنشاء النسخة الاحتياطية',
          currentFile: p.basename(srcPath),
        ));
        final hashed = await streamHashFile(
          src,
          chunkSize: chunkSize,
          isCancelled: isCancelled,
        );
        mediaBytes += hashed.bytes;
        mediaPlan.add(_MediaCopyPlan(
          source: src,
          relativePath: rel,
          size: hashed.bytes,
          sha256: hashed.sha256,
          row: portableMediaRow(row, rel)
            ..['file_size'] = hashed.bytes
            ..['checksum'] = hashed.sha256,
        ));
      }
      if (signatureFile != null && signatureFile.existsSync()) {
        final hashed = await streamHashFile(
          signatureFile,
          chunkSize: chunkSize,
          isCancelled: isCancelled,
        );
        mediaBytes += hashed.bytes;
        mediaPlan.add(_MediaCopyPlan(
          source: signatureFile,
          relativePath: 'signatures/${identity.userId}.png',
          size: hashed.bytes,
          sha256: hashed.sha256,
          row: const {},
        ));
      }
      const jsonEstimate = 8 * 1024 * 1024;
      final needed = mediaBytes + jsonEstimate + kScopedBackupOverheadBytes;
      if (freeBytes != null && freeBytes < needed) {
        return const ScopedBackupResult(
          status: ScopedBackupStatus.failed,
          error: 'لا توجد مساحة تخزين كافية على الجهاز.',
        );
      }
      await destinationParent.create(recursive: true);
      final stamp = DateTime.now().toUtc().toIso8601String().replaceAll(':', '');
      final folderName =
          'LF_SCOPED_BACKUP_${exercise.exerciseId}_u${identity.userId}_$stamp';
      inProgress = Directory(p.join(destinationParent.path, '$folderName.inprogress'));
      await deleteDirIfExists(inProgress);
      await inProgress.create(recursive: true);

      Future<void> putJson(String rel, Object data) async {
        if (isCancelled?.call() == true) {
          throw const ScopedBackupIoException('cancelled');
        }
        await writeUtf8File(
          File(p.join(inProgress!.path, rel)),
          const JsonEncoder.withIndent('  ').convert(data),
        );
      }

      await putJson('records/identity.json', identity.toJson());
      await putJson('records/exercise.json', exercise.toJson());
      final cacheForPackage = <Map<String, dynamic>>[];
      for (final row in cacheRows) {
        final copy = Map<String, dynamic>.from(row);
        final srcPath = '${copy['json_body_file'] ?? ''}';
        copy.remove('json_body_file');
        if (srcPath.isNotEmpty && !kIsWeb) {
          final src = File(srcPath);
          if (src.existsSync()) {
            final rel = 'records/cache_files/${p.basename(src.path)}';
            if (!isSafeRelativeBackupPath(rel)) {
              throw ScopedBackupIoException('unsafe_path:$rel');
            }
            final size = await src.length();
            await streamCopyFile(
              source: src,
              dest: File(p.join(inProgress.path, rel)),
              expectedSize: size,
              chunkSize: chunkSize,
              isCancelled: isCancelled,
            );
            copy['json_body_rel'] = rel;
            copy['json_body'] = '{}';
          }
        }
        cacheForPackage.add(copy);
      }
      await putJson('records/cache.json', cacheForPackage);
      await putJson('records/pending_ops.json', pendingRows);
      await putJson(
        'records/media_files.json',
        [for (final m in mediaPlan.where((e) => e.row.isNotEmpty)) m.row],
      );

      var copied = 0;
      for (final item in mediaPlan) {
        if (isCancelled?.call() == true) {
          throw const ScopedBackupIoException('cancelled');
        }
        onProgress?.call(ScopedBackupProgress(
          stage: 'جارٍ إنشاء النسخة الاحتياطية',
          currentFile: item.relativePath,
          bytesProcessed: copied,
          totalBytes: mediaBytes,
          percent: mediaBytes == 0 ? 0 : ((copied * 100) / mediaBytes).round(),
        ));
        final dest = File(p.join(inProgress.path, item.relativePath));
        await streamCopyFile(
          source: item.source,
          dest: dest,
          expectedSize: item.size,
          expectedSha256: item.sha256,
          chunkSize: chunkSize,
          isCancelled: isCancelled,
          onBytes: (n) {
            copied += n;
            onProgress?.call(ScopedBackupProgress(
              stage: 'جارٍ إنشاء النسخة الاحتياطية',
              currentFile: item.relativePath,
              bytesProcessed: copied,
              totalBytes: mediaBytes,
              percent: mediaBytes == 0 ? 0 : ((copied * 100) / mediaBytes).round(),
            ));
          },
        );
      }

      onProgress?.call(const ScopedBackupProgress(
        stage: 'جارٍ إضافة ملفات Excel لقوائم التقييم',
      ));
      final excel = await writeEvaluationExcelIntoBackup(
        packageDir: inProgress,
        scope: excelScopeFromBackup(
          exercise: exercise,
          identity: identity,
          deviceId: DevicePresenceService.instance.deviceId,
          appVersion: DeviceLayout.appVersion,
        ),
        cacheRows: cacheRows,
        pendingRows: pendingRows,
        mediaRows: mediaRows,
        chunkSize: chunkSize,
        isCancelled: isCancelled,
      );

      final inventory = <ScopedBackupFileEntry>[];
      await for (final entity in inProgress.list(recursive: true, followLinks: false)) {
        if (entity is! File) continue;
        final rel = p.relative(entity.path, from: inProgress.path).replaceAll('\\', '/');
        if (!isSafeRelativeBackupPath(rel)) {
          throw ScopedBackupIoException('unsafe_path:$rel');
        }
        final hashed = await streamHashFile(entity, chunkSize: chunkSize);
        final meta = excel.metaByRel[rel];
        inventory.add(ScopedBackupFileEntry(
          relativePath: rel,
          size: hashed.bytes,
          sha256: hashed.sha256,
          kind: scopedBackupFileKind(rel, excelKinds: excel.kindByRel),
          evaluationListId: meta?.evaluationListId ??
              excel.evaluationListIdByRel[rel],
          evaluationType: meta?.evaluationType,
          exerciseId: meta?.exerciseId,
          userId: meta?.userId,
          displayName: meta?.displayName,
          evaluationItemId: meta?.evaluationItemId,
          mediaId: meta?.mediaId,
          mediaType: meta?.mediaType,
          sourceLocalPath: meta?.sourceLocalPath,
        ));
      }

      final pendingByStatus = <String, int>{};
      for (final row in pendingRows) {
        final st = '${row['sync_status'] ?? 'pending'}';
        pendingByStatus[st] = (pendingByStatus[st] ?? 0) + 1;
      }
      var manifest = ScopedBackupManifest(
        backupFormatVersion: kScopedBackupFormatVersion,
        applicationId: kTabletApplicationId,
        applicationVersion: DeviceLayout.appVersion,
        applicationVersionCode: DeviceLayout.appVersionCode,
        schemaVersion: OfflineStore.databaseSchemaVersion,
        createdAt: DateTime.now().toUtc().toIso8601String(),
        exercise: exercise,
        user: identity,
        deviceId: DevicePresenceService.instance.deviceId,
        recordCounts: {
          'cache': cacheRows.length,
          'pending_ops': pendingRows.length,
          'media_files': mediaPlan.where((e) => e.row.isNotEmpty).length,
          'procedure_evaluation_excel': excel.procedureCount,
          'dilemma_evaluation_excel': excel.dilemmaCount,
          'evaluation_list_images': excel.imageCount,
          'evaluation_list_videos': excel.videoCount,
        },
        pendingCountsByStatus: pendingByStatus,
        mediaCount: mediaPlan.where((e) => e.relativePath.startsWith('media/')).length,
        totalMediaBytes: mediaBytes,
        fileInventory: inventory,
        completionStatus: 'complete',
        warnings: warnings,
      );
      await putJson(kScopedBackupManifestName, manifest.toJson());
      await writeUtf8File(
        File(p.join(inProgress.path, kScopedBackupCompleteName)),
        'complete\n',
      );

      onProgress?.call(const ScopedBackupProgress(
        stage: 'جارٍ التحقق من النسخة الاحتياطية',
      ));
      final issues = await validateBackupPackage(
        inProgress,
        chunkSize: chunkSize,
        isCancelled: isCancelled,
      );
      if (issues.isNotEmpty) {
        await deleteDirIfExists(inProgress);
        return ScopedBackupResult(
          status: issues.any((e) => e.code == 'manifest_corrupt')
              ? ScopedBackupStatus.corrupt
              : ScopedBackupStatus.failed,
          error: 'النسخة الاحتياطية غير صالحة: ${issues.first.code}',
          warnings: warnings,
        );
      }
      manifest = manifest.copyWith(
        completionStatus: 'verified',
        verifiedAt: DateTime.now().toUtc().toIso8601String(),
      );
      await putJson(kScopedBackupManifestName, manifest.toJson());
      final finalDir = Directory(p.join(destinationParent.path, folderName));
      await renameDirCommitted(inProgress, finalDir);
      inProgress = null;
      final reopen = await validateBackupPackage(finalDir, chunkSize: chunkSize);
      if (reopen.isNotEmpty) {
        await deleteDirIfExists(finalDir);
        return ScopedBackupResult(
          status: ScopedBackupStatus.corrupt,
          error: 'النسخة الاحتياطية غير صالحة: ${reopen.first.code}',
          warnings: warnings,
        );
      }
      return ScopedBackupResult(
        status: ScopedBackupStatus.verified,
        packagePath: finalDir.path,
        manifest: manifest,
        warnings: warnings,
        procedureExcelCount: excel.procedureCount,
        dilemmaExcelCount: excel.dilemmaCount,
        evaluationImageCount: excel.imageCount,
        evaluationVideoCount: excel.videoCount,
      );
    } on ScopedBackupIoException catch (e) {
      if (inProgress != null) {
        await deleteDirIfExists(inProgress);
      }
      if (e.message == 'cancelled') {
        return ScopedBackupResult(
          status: ScopedBackupStatus.cancelled,
          error: 'تم إلغاء النسخة الاحتياطية',
          warnings: warnings,
        );
      }
      return ScopedBackupResult(
        status: ScopedBackupStatus.failed,
        error: e.message,
        warnings: warnings,
      );
    } catch (e) {
      if (inProgress != null) {
        await deleteDirIfExists(inProgress);
      }
      return ScopedBackupResult(
        status: ScopedBackupStatus.failed,
        error: '$e',
        warnings: warnings,
      );
    }
  }

  Future<ScopedBackupManifest?> readManifest(Directory packageDir) async {
    final f = File(p.join(packageDir.path, kScopedBackupManifestName));
    if (!f.existsSync()) return null;
    try {
      final json = jsonDecode(await f.readAsString());
      if (json is Map) {
        return ScopedBackupManifest.fromJson(Map<String, dynamic>.from(json));
      }
    } catch (_) {}
    return null;
  }

  RestorePreview buildRestorePreview({
    required ScopedBackupManifest manifest,
    required List<BackupValidationIssue> validationIssues,
    required int currentExerciseId,
    required int selectedUserId,
    required bool userProvisioned,
    required Map<String, Map<String, dynamic>> localCacheByKey,
    required Map<String, String> localCacheStatus,
    required Map<String, DateTime?> localCacheUpdated,
    required Set<String> existingPendingIds,
    required Set<String> livePendingIds,
    required List<Map<String, dynamic>> backupCache,
    required List<Map<String, dynamic>> backupPending,
    required List<Map<String, dynamic>> backupMedia,
    int currentSchema = kScopedBackupSupportedSchema,
  }) {
    final blockers = <String>[];
    final warnings = <String>[];
    final items = <RestorePreviewItem>[];

    if (validationIssues.isNotEmpty) {
      blockers.add('النسخة الاحتياطية غير صالحة');
    }
    if (manifest.backupFormatVersion != kScopedBackupFormatVersion) {
      blockers.add('إصدار النسخة الاحتياطية غير مدعوم');
    }
    if (manifest.schemaVersion != currentSchema) {
      blockers.add('إصدار قاعدة البيانات غير متوافق');
    }
    if (manifest.exercise.exerciseId != currentExerciseId) {
      blockers.add('التمرين في النسخة الاحتياطية لا يطابق التمرين الحالي');
    }
    if (manifest.user.userId != selectedUserId) {
      blockers.add('المستخدم في النسخة الاحتياطية لا يطابق المستخدم المحدد');
    }
    if (!userProvisioned) {
      blockers.add('المستخدم غير مُهيأ على هذا الجهاز');
    }

    for (final row in backupCache) {
      final key = '${row['cache_key'] ?? ''}';
      if (!cacheKeyBelongsToUser(key, selectedUserId)) {
        blockers.add('مفتاح كاش خارج النطاق: $key');
        continue;
      }
      Map<String, dynamic>? body;
      try {
        final decoded = jsonDecode('${row['json_body'] ?? '{}'}');
        if (decoded is Map) body = Map<String, dynamic>.from(decoded);
      } catch (_) {}
      Map<String, dynamic>? localBody;
      final localRaw = localCacheByKey[key];
      if (localRaw != null) {
        try {
          final decoded = jsonDecode('${localRaw['json_body'] ?? '{}'}');
          if (decoded is Map) localBody = Map<String, dynamic>.from(decoded);
        } catch (_) {}
      }
      final classification = classifyRestoreCache(
        localBody: localBody,
        localStatus: localCacheStatus[key],
        localUpdatedAt: localCacheUpdated[key],
        backupBody: body,
        backupStatus: '${row['sync_status'] ?? ''}',
        backupUpdatedAt: DateTime.tryParse('${row['updated_at'] ?? ''}'),
        hasLivePending: livePendingIds.contains(key),
      );
      items.add(RestorePreviewItem(
        kind: 'cache',
        id: key,
        classification: classification,
      ));
      if (classification == RestoreConflictClass.localUnsynced ||
          classification == RestoreConflictClass.conflict) {
        blockers.add('تعارض مع بيانات محلية غير متزامنة');
      }
    }

    for (final row in backupPending) {
      final id = '${row['id'] ?? ''}';
      final opType = '${row['op_type'] ?? ''}';
      if (!kKnownPendingOpTypes.contains(opType)) {
        warnings.add('unknown_op_type:$opType:$id');
      }
      if (!pendingBelongsToScope(
        row,
        userId: selectedUserId,
        exerciseId: currentExerciseId,
      )) {
        blockers.add('عملية معلّقة خارج النطاق: $id');
        continue;
      }
      if (existingPendingIds.contains(id)) {
        items.add(RestorePreviewItem(
          kind: 'pending',
          id: id,
          classification: RestoreConflictClass.same,
          detail: 'exists',
        ));
      } else {
        items.add(RestorePreviewItem(
          kind: 'pending',
          id: id,
          classification: RestoreConflictClass.missingLocally,
        ));
      }
    }

    for (final row in backupMedia) {
      final id = '${row['id'] ?? ''}';
      items.add(RestorePreviewItem(
        kind: 'media',
        id: id,
        classification: RestoreConflictClass.missingLocally,
      ));
    }

    return RestorePreview(
      manifest: manifest,
      items: items,
      blockers: blockers.toSet().toList(),
      warnings: warnings,
      canRestore: blockers.isEmpty,
    );
  }

  Future<RestorePreview> previewRestore({
    required Directory packageDir,
    required int selectedUserId,
  }) async {
    final issues = await validateBackupPackage(packageDir);
    final manifest = await readManifest(packageDir);
    if (manifest == null) {
      return RestorePreview(
        manifest: ScopedBackupManifest(
          backupFormatVersion: 0,
          applicationId: '',
          applicationVersion: '',
          applicationVersionCode: 0,
          schemaVersion: 0,
          createdAt: '',
          exercise: const ScopedBackupExercise(exerciseId: 0),
          user: const ScopedBackupIdentity(userId: 0, username: ''),
        ),
        blockers: const ['النسخة الاحتياطية غير صالحة'],
        canRestore: false,
      );
    }
    final exercise = await currentExercise();
    final userRow = await OfflineStore.instance.localUserById(selectedUserId);
    final backupCache = await _readJsonList(packageDir, 'records/cache.json');
    final backupPending = await _readJsonList(packageDir, 'records/pending_ops.json');
    final backupMedia = await _readJsonList(packageDir, 'records/media_files.json');
    final localCacheByKey = <String, Map<String, dynamic>>{};
    final localStatus = <String, String>{};
    final localUpdated = <String, DateTime?>{};
    for (final row in backupCache) {
      final key = '${row['cache_key'] ?? ''}';
      final raw = await OfflineStore.instance.cacheRowRaw(key);
      if (raw != null) localCacheByKey[key] = raw;
      localStatus[key] = await OfflineStore.instance.cacheSyncStatus(key) ?? '';
      localUpdated[key] = await OfflineStore.instance.cacheUpdatedAt(key);
    }
    final existingPending = <String>{};
    final livePending = <String>{};
    for (final row in backupPending) {
      final id = '${row['id'] ?? ''}';
      final existing = await OfflineStore.instance.pendingOpById(id);
      if (existing != null) {
        existingPending.add(id);
        if (existing.syncStatus != SyncStatuses.synced) {
          livePending.add(id);
        }
      }
    }
    return buildRestorePreview(
      manifest: manifest,
      validationIssues: issues,
      currentExerciseId: exercise?.exerciseId ?? 0,
      selectedUserId: selectedUserId,
      userProvisioned: userRow != null,
      localCacheByKey: localCacheByKey,
      localCacheStatus: localStatus,
      localCacheUpdated: localUpdated,
      existingPendingIds: existingPending,
      livePendingIds: livePending,
      backupCache: backupCache,
      backupPending: backupPending,
      backupMedia: backupMedia,
    );
  }

  Future<ScopedRestoreResult> restorePackage({
    required Directory packageDir,
    required int selectedUserId,
    required RestorePreview preview,
    bool skipSafetySnapshot = false,
    Directory? safetyParent,
    void Function(ScopedBackupProgress progress)? onProgress,
  }) async {
    if (!preview.canRestore) {
      return ScopedRestoreResult(
        ok: false,
        error: preview.blockers.isEmpty
            ? 'تعارض مع بيانات محلية غير متزامنة'
            : preview.blockers.first,
      );
    }
    SyncService.instance.beginRestoreHold();
    Directory? staging;
    Directory? safetyDir;
    try {
      if (!skipSafetySnapshot) {
        onProgress?.call(const ScopedBackupProgress(
          stage: 'إنشاء لقطة أمان قبل الاستعادة',
        ));
        Directory parent;
        if (safetyParent != null) {
          parent = safetyParent;
        } else {
          final docs = await getApplicationDocumentsDirectory();
          parent = Directory(p.join(docs.path, 'restore_safety'));
        }
        final safety = await createBackupForUser(
          userId: selectedUserId,
          destinationParent: parent,
          onProgress: onProgress,
        );
        if (!safety.verified || safety.packagePath == null) {
          return ScopedRestoreResult(
            ok: false,
            error: 'تعذر إنشاء لقطة الأمان قبل الاستعادة',
            warnings: safety.warnings,
          );
        }
        safetyDir = Directory(safety.packagePath!);
      }

      final backupCache = await _readJsonList(packageDir, 'records/cache.json');
      final backupPending = await _readJsonList(packageDir, 'records/pending_ops.json');
      final backupMedia = await _readJsonList(packageDir, 'records/media_files.json');

      final cacheToWrite = <Map<String, dynamic>>[];
      for (final item in preview.items.where((e) => e.kind == 'cache')) {
        if (item.classification == RestoreConflictClass.same ||
            item.classification == RestoreConflictClass.backupOlder) {
          continue;
        }
        if (item.classification == RestoreConflictClass.localUnsynced ||
            item.classification == RestoreConflictClass.conflict) {
          return const ScopedRestoreResult(
            ok: false,
            error: 'تعارض مع بيانات محلية غير متزامنة',
          );
        }
        final row = backupCache.firstWhere(
          (e) => '${e['cache_key']}' == item.id,
          orElse: () => const {},
        );
        if (row.isEmpty) continue;
        cacheToWrite.add(Map<String, dynamic>.from(row));
      }

      final pendingToInsert = <PendingOp>[];
      for (final row in backupPending) {
        final id = '${row['id'] ?? ''}';
        if (id.isEmpty) continue;
        final existing = await OfflineStore.instance.pendingOpById(id);
        if (existing != null) continue;
        pendingToInsert.add(PendingOp.fromRow(row));
      }

      if (!kIsWeb) {
        final docs = await getApplicationDocumentsDirectory();
        staging = Directory(p.join(docs.path, 'media', 'restore_staging'));
        await staging.create(recursive: true);
      }

      final mediaToUpsert = <LocalMediaRecord>[];
      final committedFiles = <File>[];
      final stagedFiles = <File>[];
      try {
        for (final row in backupMedia) {
          final rel = '${row['backup_rel_path'] ?? ''}';
          if (!isSafeRelativeBackupPath(rel) || p.isAbsolute(rel)) {
            throw const ScopedBackupIoException('absolute_or_unsafe_path');
          }
          final src = File(p.join(packageDir.path, rel));
          if (!src.existsSync()) {
            throw const ScopedBackupIoException('backup_media_missing');
          }
          final expectedSha = '${row['checksum'] ?? row['sha256'] ?? ''}';
          final expectedSize = rowAsInt(row['file_size']) ?? await src.length();
          final hashed = await streamHashFile(src);
          if (expectedSha.isNotEmpty && hashed.sha256 != expectedSha) {
            throw const ScopedBackupIoException('backup_media_hash_mismatch');
          }
          if (kIsWeb) continue;
          final id = '${row['id'] ?? ''}';
          final existing = await OfflineStore.instance.mediaById(id);
          if (existing != null &&
              existing.checksum != null &&
              existing.checksum == hashed.sha256 &&
              existing.localPath.isNotEmpty &&
              File(existing.localPath).existsSync()) {
            mediaToUpsert.add(existing.copyWith(
              syncStatus: '${row['sync_status'] ?? existing.syncStatus}',
            ));
            continue;
          }
          if (existing != null &&
              existing.localPath.isNotEmpty &&
              File(existing.localPath).existsSync() &&
              existing.checksum != null &&
              existing.checksum != hashed.sha256) {
            throw const ScopedBackupIoException('media_exists_different_hash');
          }
          final staged = File(p.join(staging!.path, p.basename(rel)));
          await streamCopyFile(
            source: src,
            dest: staged,
            expectedSize: expectedSize,
            expectedSha256: hashed.sha256,
          );
          stagedFiles.add(staged);
          final stagedHash = await streamHashFile(staged);
          if (stagedHash.sha256 != hashed.sha256) {
            throw const ScopedBackupIoException('staged_hash_mismatch');
          }
          final kind = '${row['media_kind'] ?? 'photo'}';
          final destPath = await OfflineStore.instance.persistMediaFile(
            staged.path,
            id,
            mediaKind: kind == 'video' ? 'video' : kind,
          );
          committedFiles.add(File(destPath));
          final rec = LocalMediaRecord.fromRow({
            ...row,
            'local_path': destPath,
            'checksum': hashed.sha256,
            'file_size': hashed.bytes,
          });
          mediaToUpsert.add(rec);
        }

        final inlineCache = <Map<String, dynamic>>[];
        for (final row in cacheToWrite) {
          final rel = '${row['json_body_rel'] ?? ''}';
          if (rel.isNotEmpty) {
            if (!isSafeRelativeBackupPath(rel) || p.isAbsolute(rel)) {
              throw const ScopedBackupIoException('absolute_or_unsafe_path');
            }
            final src = File(p.join(packageDir.path, rel));
            if (!src.existsSync()) {
              throw const ScopedBackupIoException('cache_body_missing');
            }
            await OfflineStore.instance.cacheSetExactFromFile(
              key: '${row['cache_key'] ?? ''}',
              source: src,
              updatedAt: '${row['updated_at'] ?? ''}',
              syncStatus: '${row['sync_status'] ?? SyncStatuses.pending}',
            );
          } else {
            inlineCache.add(row);
          }
        }
        await OfflineStore.instance.restoreApplyScopedRows(
          cacheRows: inlineCache,
          pendingToInsert: pendingToInsert,
          mediaToUpsert: mediaToUpsert,
        );
      } catch (e) {
        for (final f in stagedFiles) {
          try {
            if (f.existsSync()) await f.delete();
          } catch (_) {}
        }
        for (final f in committedFiles) {
          try {
            if (f.existsSync()) await f.delete();
          } catch (_) {}
        }
        if (safetyDir != null) {
          final rb = await _rollbackFromSafety(
            safetyDir: safetyDir,
            selectedUserId: selectedUserId,
          );
          return ScopedRestoreResult(
            ok: false,
            error: '$e',
            rolledBack: rb.ok,
            rollbackFailed: !rb.ok,
            warnings: rb.warnings,
          );
        }
        return ScopedRestoreResult(ok: false, error: '$e');
      }
      return ScopedRestoreResult(ok: true, warnings: preview.warnings);
    } finally {
      if (staging != null) {
        try {
          await deleteDirIfExists(staging);
        } catch (_) {}
      }
      SyncService.instance.endRestoreHold();
    }
  }

  Future<ScopedRestoreResult> _rollbackFromSafety({
    required Directory safetyDir,
    required int selectedUserId,
  }) async {
    try {
      final preview = await previewRestore(
        packageDir: safetyDir,
        selectedUserId: selectedUserId,
      );
      final forced = RestorePreview(
        manifest: preview.manifest,
        items: [
          for (final i in preview.items)
            RestorePreviewItem(
              kind: i.kind,
              id: i.id,
              classification: i.classification == RestoreConflictClass.localUnsynced ||
                      i.classification == RestoreConflictClass.conflict
                  ? RestoreConflictClass.backupNewer
                  : i.classification,
              detail: i.detail,
            ),
        ],
        blockers: const [],
        warnings: preview.warnings,
        canRestore: true,
      );
      return restorePackage(
        packageDir: safetyDir,
        selectedUserId: selectedUserId,
        preview: forced,
        skipSafetySnapshot: true,
      );
    } catch (e) {
      return ScopedRestoreResult(
        ok: false,
        error: 'فشل التراجع: $e',
        rollbackFailed: true,
      );
    }
  }

  Future<Map<String, String>?> exportPackageToUserLocation(String packagePath) async {
    if (kIsWeb) return null;
    final raw = await _channel.invokeMethod<dynamic>(
      'exportBackupFolder',
      {
        'sourceDir': packagePath,
        'suggestedName': p.basename(packagePath),
      },
    );
    if (raw == null) return null;
    if (raw is Map) {
      return {
        'name': '${raw['name'] ?? p.basename(packagePath)}',
        'uri': '${raw['uri'] ?? ''}',
      };
    }
    return {'name': p.basename(packagePath), 'uri': '$raw'};
  }

  Future<String?> importPackageFromUserLocation() async {
    if (kIsWeb) return null;
    final raw = await _channel.invokeMethod<dynamic>('importBackupFolder');
    if (raw == null) return null;
    if (raw is Map) return '${raw['path'] ?? ''}';
    return '$raw';
  }

  Future<List<Map<String, dynamic>>> _readJsonList(
    Directory packageDir,
    String rel,
  ) async {
    if (!isSafeRelativeBackupPath(rel)) return [];
    final f = File(p.join(packageDir.path, rel));
    if (!f.existsSync()) return [];
    try {
      final decoded = jsonDecode(await f.readAsString());
      if (decoded is! List) return [];
      return [
        for (final e in decoded)
          if (e is Map) Map<String, dynamic>.from(e),
      ];
    } catch (_) {
      return [];
    }
  }
}

class _MediaCopyPlan {
  final File source;
  final String relativePath;
  final int size;
  final String sha256;
  final Map<String, dynamic> row;

  const _MediaCopyPlan({
    required this.source,
    required this.relativePath,
    required this.size,
    required this.sha256,
    required this.row,
  });
}
