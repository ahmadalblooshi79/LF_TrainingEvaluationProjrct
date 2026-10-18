import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';

import '../models/eval_sheet.dart';
import 'api_client.dart';
import 'device_eval_manager_models.dart';
import 'device_eval_manager_paths.dart';
import 'health_service.dart';
import 'offline_store.dart';
import 'scoped_backup_inventory.dart';
import 'scoped_backup_io.dart';
import 'scoped_backup_models.dart';
import 'scoped_backup_service.dart';

class DeviceEvalDownloadProgress {
  final String currentFile;
  final int copiedFiles;
  final int totalFiles;
  final int copiedBytes;
  final String message;

  const DeviceEvalDownloadProgress({
    required this.currentFile,
    required this.copiedFiles,
    required this.totalFiles,
    this.copiedBytes = 0,
    this.message = '',
  });
}

class DeviceEvalDownloadResult {
  final bool ok;
  final String message;
  final String? displayPath;
  final int fileCount;
  final List<String> warnings;

  const DeviceEvalDownloadResult({
    required this.ok,
    required this.message,
    this.displayPath,
    this.fileCount = 0,
    this.warnings = const [],
  });
}

class DeviceEvalReopenResult {
  final bool ok;
  final String message;
  final Map<String, dynamic>? serverPayload;

  const DeviceEvalReopenResult({
    required this.ok,
    required this.message,
    this.serverPayload,
  });
}

class DeviceEvalInspectData {
  final DeviceEvalListSummary summary;
  final DeviceEvalUser user;
  final String exerciseName;
  final EvalSheetDetail? detail;
  final List<EvalRowInput> rows;
  final List<DeviceEvalMediaRef> media;
  final Map<String, dynamic>? rawCache;

  const DeviceEvalInspectData({
    required this.summary,
    required this.user,
    required this.exerciseName,
    this.detail,
    this.rows = const [],
    this.media = const [],
    this.rawCache,
  });
}

class DeviceEvalManagerService {
  DeviceEvalManagerService._();
  static final DeviceEvalManagerService instance = DeviceEvalManagerService._();

  static const _channel = MethodChannel('lf.training/recovery_export');

  bool _cancelled = false;
  bool get isCancelled => _cancelled;
  void requestCancel() => _cancelled = true;
  void resetCancel() => _cancelled = false;

  Future<ScopedBackupExercise?> currentExercise() {
    return ScopedBackupService.instance.currentExercise();
  }

  Future<List<Map<String, dynamic>>> provisionedUsers() {
    return ScopedBackupService.instance.provisionedUsersSafe();
  }

  Future<DeviceEvalListsLoad> loadListsForUser({
    required int userId,
    required DeviceEvalKind kind,
    required int exerciseId,
  }) async {
    await OfflineStore.instance.init();
    final keys = await OfflineStore.instance.cacheKeysLike('u$userId:');
    final mine = [
      for (final k in keys)
        if (cacheKeyUserId(k) == userId) k,
    ];
    final available = userHasLocalListCache(
      cacheKeys: mine,
      userId: userId,
      kind: kind,
    );
    if (!available) {
      return const DeviceEvalListsLoad(dataAvailable: false, lists: []);
    }

    final byId = <int, DeviceEvalListSummary>{};
    for (final key in mine) {
      final bare = cacheKeyBare(key);
      final isList = kind == DeviceEvalKind.procedure
          ? cacheKeyIsProcedureLists(bare)
          : cacheKeyIsDilemmaLists(bare);
      if (!isList) continue;
      final payload = await OfflineStore.instance.cacheGet(key);
      if (payload == null) continue;
      for (final row in summariesFromListPayload(
        payload: payload,
        kind: kind,
        userId: userId,
        exerciseId: exerciseId,
      )) {
        byId.putIfAbsent(row.listId, () => row);
      }
    }

    if (byId.isEmpty) {
      for (final key in mine) {
        final bare = cacheKeyBare(key);
        final isDetail = kind == DeviceEvalKind.procedure
            ? cacheKeyIsProcedureDetail(bare)
            : cacheKeyIsDilemmaDetail(bare);
        if (!isDetail) continue;
        final payload = await OfflineStore.instance.cacheGet(key);
        if (payload == null || !payloadMatchesExercise(payload, exerciseId)) {
          continue;
        }
        final summary = _summaryFromDetail(payload, kind, userId, exerciseId);
        if (summary != null) {
          byId.putIfAbsent(summary.listId, () => summary);
        }
      }
    }

    final mediaRows = await OfflineStore.instance
        .backupSelectMediaMetadataForUserExercise(
      userId: userId,
      exerciseId: exerciseId,
    );
    final media = [
      for (final row in mediaRows) DeviceEvalMediaRef.fromRow(row),
    ];

    final lists = byId.values.map((row) {
      final attached = mediaForManagedList(
        all: media,
        kind: kind,
        userId: userId,
        exerciseId: exerciseId,
        listId: row.listId,
      );
      final counts = mediaCounts(attached);
      return DeviceEvalListSummary(
        kind: row.kind,
        userId: row.userId,
        exerciseId: row.exerciseId,
        listId: row.listId,
        unitKey: row.unitKey,
        unitLabel: row.unitLabel,
        phaseKey: row.phaseKey,
        title: row.title,
        statusLabel: row.statusLabel,
        workflowLabel: row.workflowLabel,
        lastUpdated: row.lastUpdated,
        imageCount: counts.images,
        videoCount: counts.videos,
      );
    }).toList()
      ..sort((a, b) => a.title.compareTo(b.title));

    return DeviceEvalListsLoad(dataAvailable: true, lists: lists);
  }

  Future<DeviceEvalInspectData> loadInspect({
    required DeviceEvalUser user,
    required DeviceEvalListSummary summary,
    required String exerciseName,
  }) async {
    await OfflineStore.instance.init();
    final raw = await _detailCache(summary);
    EvalSheetDetail? detail;
    var rows = <EvalRowInput>[];
    if (raw != null && payloadMatchesExercise(raw, summary.exerciseId)) {
      detail = inspectOnlyDetail(EvalSheetDetail.fromJson(raw));
      rows = detail.savedRows.isNotEmpty
          ? List<EvalRowInput>.from(detail.savedRows)
          : detail.evalRows.map(EvalRowInput.fromEvalRow).toList();
    }
    final mediaRows = await OfflineStore.instance
        .backupSelectMediaMetadataForUserExercise(
      userId: summary.userId,
      exerciseId: summary.exerciseId,
    );
    final media = mediaForManagedList(
      all: [for (final row in mediaRows) DeviceEvalMediaRef.fromRow(row)],
      kind: summary.kind,
      userId: summary.userId,
      exerciseId: summary.exerciseId,
      listId: summary.listId,
    );
    _overlayMediaOnRows(rows, media);
    return DeviceEvalInspectData(
      summary: summary,
      user: user,
      exerciseName: exerciseName,
      detail: detail,
      rows: rows,
      media: media,
      rawCache: raw == null ? null : Map<String, dynamic>.from(raw),
    );
  }

  Future<DeviceEvalDownloadResult> downloadExcel({
    required DeviceEvalUser user,
    required DeviceEvalListSummary summary,
    required String exerciseName,
    required bool online,
    void Function(DeviceEvalDownloadProgress progress)? onProgress,
  }) async {
    if (!online) {
      return const DeviceEvalDownloadResult(
        ok: false,
        message: kDeviceEvalExcelOffline,
      );
    }
    resetCancel();
    final staging = await _prepareStaging(user, summary, exerciseName);
    final xlsxName = uniqueDownloadFileName(
      '${summary.title}.xlsx',
      <String>{},
    );
    final dest = File(p.join(staging.path, xlsxName));
    onProgress?.call(DeviceEvalDownloadProgress(
      currentFile: xlsxName,
      copiedFiles: 0,
      totalFiles: 1,
      message: 'جارٍ تنزيل Excel',
    ));
    final ok = await _downloadExcelTo(dest, summary);
    if (!ok || !dest.existsSync()) {
      return const DeviceEvalDownloadResult(
        ok: false,
        message: kDeviceEvalExcelUnsupported,
      );
    }
    return _publishStaging(staging: staging, summary: summary, user: user);
  }

  Future<DeviceEvalDownloadResult> downloadAttachments({
    required DeviceEvalUser user,
    required DeviceEvalListSummary summary,
    required String exerciseName,
    void Function(DeviceEvalDownloadProgress progress)? onProgress,
  }) async {
    resetCancel();
    final inspect = await loadInspect(
      user: user,
      summary: summary,
      exerciseName: exerciseName,
    );
    if (inspect.media.isEmpty) {
      return const DeviceEvalDownloadResult(
        ok: false,
        message: 'لا توجد مرفقات متوفرة على الجهاز لهذه القائمة',
      );
    }
    final staging = await _prepareStaging(user, summary, exerciseName);
    final copied = await _copyMediaToStaging(
      staging: staging,
      media: inspect.media,
      intoAttachments: true,
      onProgress: onProgress,
    );
    if (copied <= 0) {
      return const DeviceEvalDownloadResult(
        ok: false,
        message: kDeviceEvalDownloadFailed,
      );
    }
    return _publishStaging(staging: staging, summary: summary, user: user);
  }

  Future<DeviceEvalDownloadResult> downloadListWithAttachments({
    required DeviceEvalUser user,
    required DeviceEvalListSummary summary,
    required String exerciseName,
    required bool online,
    void Function(DeviceEvalDownloadProgress progress)? onProgress,
  }) async {
    resetCancel();
    final inspect = await loadInspect(
      user: user,
      summary: summary,
      exerciseName: exerciseName,
    );
    final staging = await _prepareStaging(user, summary, exerciseName);
    final warnings = <String>[];
    if (online) {
      final xlsxName = uniqueDownloadFileName(
        '${summary.title}.xlsx',
        <String>{},
      );
      final dest = File(p.join(staging.path, xlsxName));
      onProgress?.call(DeviceEvalDownloadProgress(
        currentFile: xlsxName,
        copiedFiles: 0,
        totalFiles: inspect.media.length + 1,
        message: 'جارٍ تنزيل Excel',
      ));
      final ok = await _downloadExcelTo(dest, summary);
      if (!ok) {
        warnings.add(kDeviceEvalExcelUnsupported);
      }
    } else {
      warnings.add(kDeviceEvalExcelOffline);
    }
    final copiedMedia = await _copyMediaToStaging(
      staging: staging,
      media: inspect.media,
      intoAttachments: true,
      onProgress: onProgress,
    );
    final hasExcel = Directory(staging.path)
        .listSync()
        .whereType<File>()
        .any((f) => f.path.toLowerCase().endsWith('.xlsx'));
    if (!hasExcel && copiedMedia <= 0) {
      return DeviceEvalDownloadResult(
        ok: false,
        message: kDeviceEvalDownloadFailed,
        warnings: warnings,
      );
    }
    final published = await _publishStaging(
      staging: staging,
      summary: summary,
      user: user,
    );
    return DeviceEvalDownloadResult(
      ok: published.ok,
      message: published.ok ? kDeviceEvalDownloadOk : published.message,
      displayPath: published.displayPath,
      fileCount: published.fileCount,
      warnings: [...warnings, ...published.warnings],
    );
  }

  Future<DeviceEvalReopenResult> reopenApprovedList({
    required DeviceEvalListSummary summary,
    required bool online,
  }) async {
    if (!online) {
      return const DeviceEvalReopenResult(
        ok: false,
        message: kDeviceEvalReopenNeedsServer,
      );
    }
    try {
      final payload = await ApiClient.instance.withDeviceAuth(() {
        return ApiClient.instance.post(
          '/api/tablet/device/eval/chief-reopen',
          body: {
            'kind': summary.kind == DeviceEvalKind.procedure
                ? 'procedure'
                : 'dilemma',
            'judge_id': summary.userId,
            'exercise_id': summary.exerciseId,
            'unit_key': summary.unitKey,
            'item_id': summary.kind == DeviceEvalKind.procedure
                ? summary.listId
                : null,
            'slot': summary.kind == DeviceEvalKind.dilemma
                ? summary.listId
                : null,
          },
        );
      });
      if (payload['ok'] != true) {
        return DeviceEvalReopenResult(
          ok: false,
          message: '${payload['error'] ?? 'رُفض طلب إعادة الفتح'}',
        );
      }
      await _applyServerReopenToCache(summary, payload);
      return DeviceEvalReopenResult(
        ok: true,
        message: 'تم إعادة فتح القائمة',
        serverPayload: payload,
      );
    } on ApiOfflineException {
      return const DeviceEvalReopenResult(
        ok: false,
        message: kDeviceEvalReopenNeedsServer,
      );
    } on ApiException catch (e) {
      if (e.status == 401 || e.status == 403) {
        return DeviceEvalReopenResult(
          ok: false,
          message: e.message.isNotEmpty
              ? e.message
              : 'لا صلاحية لإعادة فتح القائمة',
        );
      }
      return DeviceEvalReopenResult(
        ok: false,
        message: e.message.isNotEmpty ? e.message : 'تعذر إعادة فتح القائمة',
      );
    } catch (_) {
      return const DeviceEvalReopenResult(
        ok: false,
        message: 'تعذر إعادة فتح القائمة',
      );
    }
  }

  Future<bool> serverReachable() {
    return HealthService.instance.check(force: true);
  }

  DeviceEvalListSummary? _summaryFromDetail(
    Map<String, dynamic> payload,
    DeviceEvalKind kind,
    int userId,
    int exerciseId,
  ) {
    final id = kind == DeviceEvalKind.procedure
        ? rowAsInt(payload['item_id'] ?? payload['id'])
        : rowAsInt(payload['slot_id'] ?? payload['slot'] ?? payload['id']);
    if (id == null || id <= 0) return null;
    var status = '${payload['status_label'] ?? ''}'.trim();
    final wf = payload['workflow'];
    var workflow = '';
    if (wf is Map) {
      workflow = '${wf['label'] ?? ''}'.trim();
      if (status.isEmpty) status = workflow;
    }
    return DeviceEvalListSummary(
      kind: kind,
      userId: userId,
      exerciseId: exerciseId,
      listId: id,
      unitKey: '${payload['unit_key'] ?? ''}',
      unitLabel: '${payload['unit_label'] ?? ''}',
      phaseKey: '${payload['phase_key'] ?? ''}',
      title: '${payload['title'] ?? payload['eval_doc_title'] ?? 'قائمة $id'}',
      statusLabel: status,
      workflowLabel: workflow,
    );
  }

  Future<Map<String, dynamic>?> _detailCache(
    DeviceEvalListSummary summary,
  ) async {
    final key = summary.kind == DeviceEvalKind.procedure
        ? 'evaluation_list_detail:${summary.unitKey}:${summary.listId}'
        : 'action_eval_detail:${summary.listId}';
    final scoped = await OfflineStore.instance.cacheGetForUser(
      summary.userId,
      key,
    );
    if (scoped != null) return scoped;
    if (summary.kind == DeviceEvalKind.procedure &&
        summary.unitKey.isNotEmpty) {
      final alt = await OfflineStore.instance.cacheGetForUser(
        summary.userId,
        'evaluation_list_detail:_:${summary.listId}',
      );
      if (alt != null) return alt;
    }
    return null;
  }

  void _overlayMediaOnRows(
    List<EvalRowInput> rows,
    List<DeviceEvalMediaRef> media,
  ) {
    final seen = <String>{};
    for (final m in media) {
      if (m.localPath.isEmpty) continue;
      final idx = m.rowIndex;
      if (idx < 0 || idx >= rows.length) continue;
      if (!seen.add('$idx|${m.localPath}')) continue;
      rows[idx].addMedia(
        m.isVideo ? kDocSlotCameraVideo : kDocSlotCameraPhoto,
        m.localPath,
      );
    }
  }

  Future<Directory> _prepareStaging(
    DeviceEvalUser user,
    DeviceEvalListSummary summary,
    String exerciseName,
  ) async {
    final root = await getTemporaryDirectory();
    final loc = buildPublicExportLocation(
      exerciseName: exerciseName,
      exerciseId: summary.exerciseId,
      judgeName: user.displayName.isNotEmpty ? user.displayName : user.username,
      userId: user.userId,
      listTitle: summary.title,
      listId: summary.listId,
    );
    final dir = Directory(
      p.join(
        root.path,
        'smart_arbitration_export',
        '${DateTime.now().millisecondsSinceEpoch}',
        loc.exerciseFolder,
        loc.judgeFolder,
        loc.listFolder,
      ),
    );
    if (dir.existsSync()) {
      dir.deleteSync(recursive: true);
    }
    await dir.create(recursive: true);
    return dir;
  }

  Future<bool> _downloadExcelTo(
    File dest,
    DeviceEvalListSummary summary,
  ) async {
    final path = summary.kind == DeviceEvalKind.procedure
        ? '/api/tablet/device/judge/${summary.userId}/evaluation-lists/${summary.unitKey}/${summary.listId}/export.xlsx'
        : '/api/tablet/device/judge/${summary.userId}/action-eval/${summary.listId}/export.xlsx';
    try {
      return await ApiClient.instance.withDeviceAuth(() {
        return ApiClient.instance.downloadToFile(
          path,
          dest.path,
          timeout: const Duration(minutes: 3),
        );
      });
    } catch (_) {
      return false;
    }
  }

  Future<int> _copyMediaToStaging({
    required Directory staging,
    required List<DeviceEvalMediaRef> media,
    required bool intoAttachments,
    void Function(DeviceEvalDownloadProgress progress)? onProgress,
  }) async {
    final destDir = intoAttachments
        ? Directory(p.join(staging.path, kPublicExportAttachmentsFolder))
        : staging;
    await destDir.create(recursive: true);
    final used = <String>{};
    var copied = 0;
    for (var i = 0; i < media.length; i++) {
      if (_cancelled) break;
      final m = media[i];
      final source = File(m.localPath);
      if (!source.existsSync()) continue;
      final name = uniqueDownloadFileName(m.downloadName, used);
      onProgress?.call(DeviceEvalDownloadProgress(
        currentFile: name,
        copiedFiles: copied,
        totalFiles: media.length,
        message: 'جارٍ نسخ $name',
      ));
      final dest = File(p.join(destDir.path, '$name.part'));
      final finalDest = File(p.join(destDir.path, name));
      try {
        final size = await source.length();
        await streamCopyFile(
          source: source,
          dest: dest,
          expectedSize: size,
          isCancelled: () => _cancelled,
        );
        if (finalDest.existsSync()) {
          await finalDest.delete();
        }
        await dest.rename(finalDest.path);
        copied += 1;
      } catch (_) {
        if (dest.existsSync()) {
          try {
            await dest.delete();
          } catch (_) {}
        }
        if (_cancelled) break;
      }
    }
    return copied;
  }

  Future<DeviceEvalDownloadResult> _publishStaging({
    required Directory staging,
    required DeviceEvalListSummary summary,
    required DeviceEvalUser user,
  }) async {
    if (kIsWeb) {
      return const DeviceEvalDownloadResult(
        ok: false,
        message: 'التنزيل إلى مجلد التنزيلات متاح على تطبيق التابلت',
      );
    }
    final exercise = await currentExercise();
    final loc = buildPublicExportLocation(
      exerciseName: exercise?.name ?? '',
      exerciseId: summary.exerciseId,
      judgeName: user.displayName.isNotEmpty ? user.displayName : user.username,
      userId: user.userId,
      listTitle: summary.title,
      listId: summary.listId,
    );
    if (!isSafePublicExportRelativeDir(loc.relativeDir)) {
      return const DeviceEvalDownloadResult(
        ok: false,
        message: 'مسار التنزيل غير آمن',
      );
    }
    try {
      final raw = await _channel.invokeMethod<dynamic>(
        'copyExportToPublicDownloads',
        {
          'sourceDir': staging.path,
          'relativeDir': loc.relativeDir,
        },
      );
      if (raw is! Map) {
        return const DeviceEvalDownloadResult(
          ok: false,
          message: kDeviceEvalDownloadFailed,
        );
      }
      final display = '${raw['displayPath'] ?? loc.displayPath}';
      final count = int.tryParse('${raw['fileCount'] ?? '0'}') ?? 0;
      if (count <= 0) {
        return const DeviceEvalDownloadResult(
          ok: false,
          message: kDeviceEvalDownloadFailed,
        );
      }
      return DeviceEvalDownloadResult(
        ok: true,
        message: kDeviceEvalDownloadOk,
        displayPath: display,
        fileCount: count,
      );
    } on MissingPluginException {
      return DeviceEvalDownloadResult(
        ok: true,
        message: kDeviceEvalDownloadOk,
        displayPath: loc.displayPath,
        fileCount: staging.listSync(recursive: true).whereType<File>().length,
        warnings: const ['تم التجهيز محلياً — قناة التنزيل العام غير متاحة في هذا البناء'],
      );
    } catch (_) {
      return const DeviceEvalDownloadResult(
        ok: false,
        message: kDeviceEvalDownloadFailed,
      );
    }
  }

  Future<void> _applyServerReopenToCache(
    DeviceEvalListSummary summary,
    Map<String, dynamic> payload,
  ) async {
    final cached = await _detailCache(summary);
    if (cached == null) return;
    final next = Map<String, dynamic>.from(cached);
    if (payload['can_edit'] != null) next['can_edit'] = payload['can_edit'];
    if (payload['can_approve'] != null) {
      next['can_approve'] = payload['can_approve'];
    }
    if (payload['is_approved'] != null) {
      next['is_approved'] = payload['is_approved'];
    }
    if (payload['workflow'] is Map) {
      next['workflow'] = Map<String, dynamic>.from(payload['workflow'] as Map);
    }
    final key = summary.kind == DeviceEvalKind.procedure
        ? 'evaluation_list_detail:${summary.unitKey}:${summary.listId}'
        : 'action_eval_detail:${summary.listId}';
    await OfflineStore.instance.cacheSetForUser(summary.userId, key, next);
  }
}
