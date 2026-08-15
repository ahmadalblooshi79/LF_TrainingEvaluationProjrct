import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:path/path.dart' as p;

import 'api_client.dart';
import 'offline_store.dart';

/// حجم الجزء الافتراضي للرفع المجزّأ (10 MB).
const int kDefaultMediaChunkSize = 10 * 1024 * 1024;

/// حالات وسائط موسّعة (فوق SyncStatuses العامة).
class MediaSyncStatuses {
  static const pending = 'pending';
  static const readyToUpload = 'ready_to_upload';
  static const uploading = 'uploading';
  static const paused = 'paused';
  static const pausedNetwork = 'paused_network';
  static const synced = 'synced';
  static const failed = 'failed';
  static const cancelled = 'cancelled';
}

class MediaUploadProgress {
  final String mediaId;
  final String label;
  final int uploadedBytes;
  final int totalBytes;
  final String status;
  final String? error;

  const MediaUploadProgress({
    required this.mediaId,
    required this.label,
    required this.uploadedBytes,
    required this.totalBytes,
    required this.status,
    this.error,
  });

  double get fraction =>
      totalBytes <= 0 ? 0 : (uploadedBytes / totalBytes).clamp(0.0, 1.0);
}

/// رفع مجزّأ قابل للاستئناف + إدارة Pause/Resume.
class MediaUploadService extends ChangeNotifier {
  MediaUploadService._();
  static final MediaUploadService instance = MediaUploadService._();

  static const _channel = MethodChannel('lf.training/storage');

  bool _pauseRequested = false;
  bool _cancelRequested = false;
  bool uploading = false;

  final ValueNotifier<List<MediaUploadProgress>> fileProgress =
      ValueNotifier<List<MediaUploadProgress>>([]);
  final ValueNotifier<int> overallUploaded = ValueNotifier<int>(0);
  final ValueNotifier<int> overallTotal = ValueNotifier<int>(0);

  void pause() {
    _pauseRequested = true;
    notifyListeners();
  }

  void requestCancel() {
    _cancelRequested = true;
    _pauseRequested = true;
    notifyListeners();
  }

  void clearPauseFlags() {
    _pauseRequested = false;
    _cancelRequested = false;
  }

  Future<int?> freeDiskBytes() async {
    if (kIsWeb) return null;
    try {
      final v = await _channel.invokeMethod<dynamic>('getFreeSpace');
      if (v is int) return v;
      if (v is num) return v.toInt();
    } catch (_) {}
    return null;
  }

  Future<void> ensureStorageFor(int fileBytes) async {
    final free = await freeDiskBytes();
    if (free != null && free < fileBytes + (50 * 1024 * 1024)) {
      throw ApiException('لا توجد مساحة تخزين كافية على الجهاز.');
    }
  }

  Future<String> sha256File(String path) async {
    final file = File(path);
    final digest = await sha256.bind(file.openRead()).first;
    return digest.toString();
  }

  String guessMime(String path, String mediaKind) {
    final ext = p.extension(path).toLowerCase();
    switch (ext) {
      case '.jpg':
      case '.jpeg':
        return 'image/jpeg';
      case '.png':
        return 'image/png';
      case '.webp':
        return 'image/webp';
      case '.heic':
      case '.heif':
        return 'image/heic';
      case '.mp4':
      case '.m4v':
        return 'video/mp4';
      case '.mov':
        return 'video/quicktime';
      case '.webm':
        return 'video/webm';
      case '.mpg':
      case '.mpeg':
        return 'video/mpeg';
      case '.3gp':
        return 'video/3gpp';
      default:
        return mediaKind == 'video' ? 'video/mp4' : 'image/jpeg';
    }
  }

  Future<String> sha256Chunk(List<int> bytes) async {
    return sha256.convert(bytes).toString();
  }

  void _setProgress(MediaUploadProgress item) {
    final list = List<MediaUploadProgress>.from(fileProgress.value);
    final i = list.indexWhere((e) => e.mediaId == item.mediaId);
    if (i >= 0) {
      list[i] = item;
    } else {
      list.add(item);
    }
    fileProgress.value = list;
  }

  Future<void> refreshOverallFromDb() async {
    final all = await OfflineStore.instance.mediaRecords();
    final pending = all.where((m) => !m.serverConfirmed &&
        m.syncStatus != MediaSyncStatuses.synced &&
        m.syncStatus != MediaSyncStatuses.cancelled);
    var up = 0;
    var tot = 0;
    for (final m in pending) {
      tot += m.totalBytes > 0 ? m.totalBytes : m.fileSize;
      up += m.uploadedBytes;
    }
    overallUploaded.value = up;
    overallTotal.value = tot;
  }

  /// رفع سجل وسائط واحد بشكل مجزّأ مع استئناف.
  Future<void> uploadOne(LocalMediaRecord rec) async {
    clearPauseFlags();
    final path = rec.localPath;
    final file = File(path);
    if (!await file.exists()) {
      throw ApiException('الملف المحلي غير موجود');
    }
    final size = await file.length();
    await ensureStorageFor(0); // فحص خفيف؛ الحجم على السيرفر أهم عند init

    var checksum = rec.checksum;
    if (checksum == null || checksum.isEmpty) {
      checksum = await sha256File(path);
    }
    final mime = (rec.mimeType != null && rec.mimeType!.isNotEmpty)
        ? rec.mimeType!
        : guessMime(path, rec.mediaKind);

    var sessionId = rec.uploadSessionId;
    var chunkSize = kDefaultMediaChunkSize;
    var nextChunk = 0;
    var totalChunks = (size + chunkSize - 1) ~/ chunkSize;
    if (totalChunks < 1) totalChunks = 1;

    final label = rec.mediaKind == 'video' ? 'فيديو' : 'صورة';

    // استعلام حالة إن وُجدت جلسة
    if (sessionId != null && sessionId.isNotEmpty) {
      try {
        final st = await ApiClient.instance.get(
          '/api/tablet/media/upload/status',
          query: {'upload_session_id': sessionId},
          timeout: const Duration(seconds: 30),
        );
        nextChunk = (st['next_chunk'] as num?)?.toInt() ?? 0;
        chunkSize = (st['chunk_size'] as num?)?.toInt() ?? chunkSize;
        totalChunks = (st['total_chunks'] as num?)?.toInt() ?? totalChunks;
        if (st['status'] == 'completed' && st['server_media_id'] != null) {
          await OfflineStore.instance.markMediaSynced(
            rec.id,
            serverMediaId: (st['server_media_id'] as num).toInt(),
          );
          return;
        }
      } catch (_) {
        sessionId = null;
      }
    }

    if (sessionId == null || sessionId.isEmpty) {
      final init = await ApiClient.instance.post(
        '/api/tablet/media/upload/init',
        body: {
          'client_uuid': rec.id,
          'media_kind': rec.mediaKind,
          'mime_type': mime,
          'file_size': size,
          'checksum': checksum,
          'original_filename': rec.originalFilename ?? p.basename(path),
          'row_index': rec.rowIndex,
          'chunk_size': kDefaultMediaChunkSize,
          if (rec.evaluationListItemId != null)
            'evaluation_list_item_id': rec.evaluationListItemId,
          if (rec.bundleActionEvalId != null)
            'bundle_action_eval_id': rec.bundleActionEvalId,
        },
        timeout: const Duration(seconds: 60),
      );
      if (init['already_received'] == true) {
        await OfflineStore.instance.markMediaSynced(
          rec.id,
          serverMediaId: (init['server_media_id'] as num?)?.toInt(),
        );
        return;
      }
      if (init['error'] == 'INSUFFICIENT_SERVER_STORAGE' ||
          init['code'] == 'INSUFFICIENT_SERVER_STORAGE') {
        throw ApiException('لا توجد مساحة كافية على السيرفر.');
      }
      sessionId = (init['upload_session_id'] ?? '').toString();
      if (sessionId.isEmpty) {
        throw ApiException('تعذر إنشاء جلسة الرفع');
      }
      chunkSize = (init['chunk_size'] as num?)?.toInt() ?? chunkSize;
      nextChunk = (init['next_chunk'] as num?)?.toInt() ?? 0;
      totalChunks = (init['total_chunks'] as num?)?.toInt() ?? totalChunks;
    }

    await OfflineStore.instance.patchMedia(
      rec.id,
      uploadSessionId: sessionId,
      checksum: checksum,
      mimeType: mime,
      fileSize: size,
      totalBytes: size,
      syncStatus: MediaSyncStatuses.uploading,
      uploadedBytes: nextChunk * chunkSize > size ? size : nextChunk * chunkSize,
    );

    while (nextChunk < totalChunks) {
      if (_cancelRequested) {
        await OfflineStore.instance.patchMedia(
          rec.id,
          syncStatus: MediaSyncStatuses.cancelled,
          lastError: 'أُلغي الرفع',
        );
        throw ApiException('أُلغي الرفع');
      }
      if (_pauseRequested) {
        await OfflineStore.instance.patchMedia(
          rec.id,
          syncStatus: MediaSyncStatuses.paused,
          uploadSessionId: sessionId,
          uploadedBytes:
              nextChunk * chunkSize > size ? size : nextChunk * chunkSize,
        );
        throw ApiOfflineException('تم إيقاف الرفع مؤقتاً');
      }

      final start = nextChunk * chunkSize;
      final end = (start + chunkSize > size) ? size : start + chunkSize;
      final length = end - start;
      final stream = file.openRead(start, end);
      final chunkBytes = await stream.fold<List<int>>(
        <int>[],
        (prev, el) => prev..addAll(el),
      );
      // للمقاطع الكبيرة نفضّل streaming في الطلب؛ نحسب checksum من البايتات
      final chunkCs = sha256.convert(chunkBytes).toString();

      try {
        final resp = await ApiClient.instance.uploadMediaChunk(
          uploadSessionId: sessionId!,
          clientUuid: rec.id,
          chunkNumber: nextChunk,
          totalChunks: totalChunks,
          chunkChecksum: chunkCs,
          chunkBytes: chunkBytes,
        );
        nextChunk = (resp['next_chunk'] as num?)?.toInt() ?? (nextChunk + 1);
        final uploaded = nextChunk * chunkSize > size ? size : nextChunk * chunkSize;
        await OfflineStore.instance.patchMedia(
          rec.id,
          uploadedBytes: uploaded,
          uploadSessionId: sessionId,
          syncStatus: MediaSyncStatuses.uploading,
          attemptCount: (rec.attemptCount) + 0,
        );
        _setProgress(MediaUploadProgress(
          mediaId: rec.id,
          label: '$label ${p.basename(path)}',
          uploadedBytes: uploaded,
          totalBytes: size,
          status: MediaSyncStatuses.uploading,
        ));
        await refreshOverallFromDb();
      } on ApiOfflineException {
        await OfflineStore.instance.patchMedia(
          rec.id,
          syncStatus: MediaSyncStatuses.pausedNetwork,
          uploadSessionId: sessionId,
          lastError: 'انقطع الاتصال — يمكن الاستئناف لاحقاً',
          uploadedBytes:
              nextChunk * chunkSize > size ? size : nextChunk * chunkSize,
        );
        rethrow;
      }
    }

    final done = await ApiClient.instance.post(
      '/api/tablet/media/upload/complete',
      body: {'upload_session_id': sessionId, 'client_uuid': rec.id},
      timeout: const Duration(seconds: 120),
    );
    if (done['ok'] != true && done['already_received'] != true) {
      throw ApiException((done['error'] ?? 'فشل إكمال الرفع').toString());
    }
    await OfflineStore.instance.markMediaSynced(
      rec.id,
      serverMediaId: (done['server_media_id'] as num?)?.toInt(),
    );
    _setProgress(MediaUploadProgress(
      mediaId: rec.id,
      label: '$label ${p.basename(path)}',
      uploadedBytes: size,
      totalBytes: size,
      status: MediaSyncStatuses.synced,
    ));
  }
}
