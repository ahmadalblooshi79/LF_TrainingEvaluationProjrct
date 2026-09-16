import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';

import 'api_client.dart';
import 'auth_service.dart';
import 'offline_store.dart';
import 'sync_service.dart';
import 'tablet_repository.dart';

const kJudgeSignatureCacheKey = 'judge_signature';

class JudgeSignatureRecord {
  const JudgeSignatureRecord({
    required this.userId,
    required this.pngB64,
    required this.version,
    required this.status,
    required this.registeredAt,
    required this.updatedAt,
    required this.pendingSync,
  });

  final int userId;
  final String pngB64;
  final int version;
  final String status;
  final String registeredAt;
  final String updatedAt;
  final bool pendingSync;

  bool get isRegistered => pngB64.isNotEmpty && status == 'registered';

  Uint8List? get pngBytes {
    if (pngB64.isEmpty) return null;
    try {
      return base64Decode(pngB64);
    } catch (_) {
      return null;
    }
  }

  Map<String, dynamic> toJson() => {
        'user_id': userId,
        'png_b64': pngB64,
        'version': version,
        'status': status,
        'registered_at': registeredAt,
        'updated_at': updatedAt,
        'pending_sync': pendingSync,
      };

  factory JudgeSignatureRecord.fromJson(Map<String, dynamic> json) {
    return JudgeSignatureRecord(
      userId: (json['user_id'] as num?)?.toInt() ?? 0,
      pngB64: (json['png_b64'] ?? '').toString(),
      version: (json['version'] as num?)?.toInt() ?? 1,
      status: (json['status'] ?? '').toString(),
      registeredAt: (json['registered_at'] ?? '').toString(),
      updatedAt: (json['updated_at'] ?? '').toString(),
      pendingSync: json['pending_sync'] == true,
    );
  }
}

/// تخزين التوقيع معزول بـ user_id — لا يُحذف عند الخروج أو إعادة التشغيل.
class SignatureStore {
  SignatureStore._();
  static final SignatureStore instance = SignatureStore._();

  Future<JudgeSignatureRecord?> loadForUser(int userId) async {
    if (userId <= 0) return null;
    final cached = await OfflineStore.instance.cacheGetForUser(
      userId,
      kJudgeSignatureCacheKey,
    );
    if (cached != null) {
      final rec = JudgeSignatureRecord.fromJson(cached);
      if (rec.userId == userId && rec.pngB64.isNotEmpty) return rec;
    }
    final fileBytes = await _readNativeFile(userId);
    if (fileBytes == null || fileBytes.isEmpty) return null;
    final now = DateTime.now().toIso8601String();
    return JudgeSignatureRecord(
      userId: userId,
      pngB64: base64Encode(fileBytes),
      version: 1,
      status: 'registered',
      registeredAt: now,
      updatedAt: now,
      pendingSync: true,
    );
  }

  Future<JudgeSignatureRecord?> loadForCurrentUser() async {
    final uid = AuthService.instance.currentUserId;
    if (uid == null || uid <= 0) return null;
    return loadForUser(uid);
  }

  Future<JudgeSignatureRecord> saveApproved({
    required int userId,
    required Uint8List png,
    bool replace = false,
  }) async {
    if (userId <= 0) {
      throw StateError('invalid_user');
    }
    final currentUid = AuthService.instance.currentUserId;
    if (currentUid == null || currentUid != userId) {
      throw StateError('owner_mismatch');
    }
    final existing = await loadForUser(userId);
    if (existing != null && existing.isRegistered && !replace) {
      throw StateError('exists');
    }
    final now = DateTime.now().toUtc().toIso8601String();
    final version = existing == null ? 1 : existing.version + 1;
    final rec = JudgeSignatureRecord(
      userId: userId,
      pngB64: base64Encode(png),
      version: version,
      status: 'registered',
      registeredAt: existing?.registeredAt.isNotEmpty == true
          ? existing!.registeredAt
          : now,
      updatedAt: now,
      pendingSync: true,
    );
    await OfflineStore.instance.cacheSetForUser(
      userId,
      kJudgeSignatureCacheKey,
      rec.toJson(),
      syncStatus: SyncStatuses.pending,
    );
    await _writeNativeFile(userId, png);
    await SyncService.instance.enqueueLocalFirst(
      id: newClientOpId('sig-$userId-v$version'),
      method: 'POST',
      path: '/api/tablet/signature',
      body: {
        'user_id': userId,
        'png_b64': rec.pngB64,
        'replace': true,
        'version': version,
      },
      kind: 'حفظ التوقيع الإلكتروني',
      opType: 'save_signature',
    );
    return rec;
  }

  /// يسحب من السيرفر فقط إن لم يوجد توقيع محلي. لا يحذف المحلي عند الفشل.
  Future<void> pullIfMissing(int userId) async {
    if (userId <= 0) return;
    final local = await loadForUser(userId);
    if (local != null && local.isRegistered) return;
    try {
      final data = await ApiClient.instance.get('/api/tablet/signature');
      final pngB64 = (data['png_b64'] ?? '').toString();
      final owner = (data['user_id'] as num?)?.toInt() ?? 0;
      if (owner != userId || pngB64.isEmpty) return;
      final rec = JudgeSignatureRecord(
        userId: userId,
        pngB64: pngB64,
        version: (data['version'] as num?)?.toInt() ?? 1,
        status: 'registered',
        registeredAt: (data['registered_at'] ?? '').toString(),
        updatedAt: (data['updated_at'] ?? '').toString(),
        pendingSync: false,
      );
      await OfflineStore.instance.cacheSetForUser(
        userId,
        kJudgeSignatureCacheKey,
        rec.toJson(),
        syncStatus: SyncStatuses.synced,
      );
      final bytes = rec.pngBytes;
      if (bytes != null) await _writeNativeFile(userId, bytes);
    } catch (_) {
      // الإبقاء على المحلي — لا حذف.
    }
  }

  Future<void> _writeNativeFile(int userId, Uint8List png) async {
    if (kIsWeb) return;
    try {
      final dir = await _dir();
      final file = File(p.join(dir.path, 'u$userId.png'));
      await file.writeAsBytes(png, flush: true);
    } catch (_) {}
  }

  Future<Uint8List?> _readNativeFile(int userId) async {
    if (kIsWeb) return null;
    try {
      final dir = await _dir();
      final file = File(p.join(dir.path, 'u$userId.png'));
      if (!await file.exists()) return null;
      return await file.readAsBytes();
    } catch (_) {
      return null;
    }
  }

  Future<Directory> _dir() async {
    final root = await getApplicationDocumentsDirectory();
    final dir = Directory(p.join(root.path, 'judge_signatures'));
    if (!await dir.exists()) {
      await dir.create(recursive: true);
    }
    return dir;
  }
}
