import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:sqflite/sqflite.dart';

/// حالات مزامنة سجل في الطابور المحلي.
class SyncStatuses {
  static const pending = 'pending';
  static const syncing = 'syncing';
  static const synced = 'synced';
  static const failed = 'failed';
  static const conflict = 'conflict';
}

/// عملية معلقة للإرسال إلى السيرفر (Idempotent عبر [id]).
class PendingOp {
  final String id;
  final String method;
  final String path;
  final Map<String, dynamic> body;
  final String kind;
  final String opType;
  final String createdAt;
  final int attempts;
  final String? lastError;
  final String syncStatus;
  final int? judgeId;
  final int? userId;
  final int? exerciseId;
  final String? listId;
  final int? evalItemId;
  final String? mediaLocalPath;

  const PendingOp({
    required this.id,
    required this.method,
    required this.path,
    required this.body,
    required this.kind,
    required this.opType,
    required this.createdAt,
    this.attempts = 0,
    this.lastError,
    this.syncStatus = SyncStatuses.pending,
    this.judgeId,
    this.userId,
    this.exerciseId,
    this.listId,
    this.evalItemId,
    this.mediaLocalPath,
  });

  PendingOp copyWith({
    int? attempts,
    String? lastError,
    String? syncStatus,
  }) {
    return PendingOp(
      id: id,
      method: method,
      path: path,
      body: body,
      kind: kind,
      opType: opType,
      createdAt: createdAt,
      attempts: attempts ?? this.attempts,
      lastError: lastError ?? this.lastError,
      syncStatus: syncStatus ?? this.syncStatus,
      judgeId: judgeId,
      userId: userId,
      exerciseId: exerciseId,
      listId: listId,
      evalItemId: evalItemId,
      mediaLocalPath: mediaLocalPath,
    );
  }

  Map<String, dynamic> toRow() => {
        'id': id,
        'method': method,
        'path': path,
        'body': jsonEncode(body),
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
      };

  factory PendingOp.fromRow(Map<String, dynamic> row) {
    Map<String, dynamic> body = {};
    try {
      final decoded = jsonDecode((row['body'] as String?) ?? '{}');
      if (decoded is Map) body = Map<String, dynamic>.from(decoded);
    } catch (_) {}
    return PendingOp(
      id: row['id'] as String,
      method: (row['method'] as String?) ?? 'POST',
      path: (row['path'] as String?) ?? '',
      body: body,
      kind: (row['kind'] as String?) ?? '',
      opType: (row['op_type'] as String?) ?? 'unknown',
      createdAt: (row['created_at'] as String?) ?? '',
      attempts: (row['attempts'] as int?) ?? 0,
      lastError: row['last_error'] as String?,
      syncStatus: (row['sync_status'] as String?) ?? SyncStatuses.pending,
      judgeId: row['judge_id'] as int?,
      userId: row['user_id'] as int?,
      exerciseId: row['exercise_id'] as int?,
      listId: row['list_id'] as String?,
      evalItemId: row['eval_item_id'] as int?,
      mediaLocalPath: row['media_local_path'] as String?,
    );
  }

  Map<String, dynamic> toJson() => toRow();

  factory PendingOp.fromJson(Map<String, dynamic> json) =>
      PendingOp.fromRow(json);
}

/// ملف وسائط محفوظ محلياً بانتظار الرفع (Metadata فقط — الملف على القرص).
class LocalMediaRecord {
  final String id;
  final String localPath;
  final int rowIndex;
  final String mediaKind;
  final int? evaluationListItemId;
  final int? bundleActionEvalId;
  final String syncStatus;
  final bool serverConfirmed;
  final String createdAt;
  final String? lastError;
  final String? sheetCacheKey;
  final String? clientUuid;
  final int? userId;
  final String? militaryNumber;
  final int? exerciseId;
  final String? originalFilename;
  final String? localFilename;
  final String? mimeType;
  final int fileSize;
  final String? checksum;
  final String? updatedAt;
  final int uploadedBytes;
  final int totalBytes;
  final String? uploadSessionId;
  final int attemptCount;
  final String? lastAttemptAt;
  final int? serverMediaId;

  const LocalMediaRecord({
    required this.id,
    required this.localPath,
    required this.rowIndex,
    required this.mediaKind,
    this.evaluationListItemId,
    this.bundleActionEvalId,
    this.syncStatus = SyncStatuses.pending,
    this.serverConfirmed = false,
    required this.createdAt,
    this.lastError,
    this.sheetCacheKey,
    this.clientUuid,
    this.userId,
    this.militaryNumber,
    this.exerciseId,
    this.originalFilename,
    this.localFilename,
    this.mimeType,
    this.fileSize = 0,
    this.checksum,
    this.updatedAt,
    this.uploadedBytes = 0,
    this.totalBytes = 0,
    this.uploadSessionId,
    this.attemptCount = 0,
    this.lastAttemptAt,
    this.serverMediaId,
  });

  LocalMediaRecord copyWith({
    String? localPath,
    String? syncStatus,
    bool? serverConfirmed,
    String? lastError,
    String? checksum,
    String? mimeType,
    int? fileSize,
    int? uploadedBytes,
    int? totalBytes,
    String? uploadSessionId,
    int? attemptCount,
    String? lastAttemptAt,
    int? serverMediaId,
    String? updatedAt,
  }) {
    return LocalMediaRecord(
      id: id,
      localPath: localPath ?? this.localPath,
      rowIndex: rowIndex,
      mediaKind: mediaKind,
      evaluationListItemId: evaluationListItemId,
      bundleActionEvalId: bundleActionEvalId,
      syncStatus: syncStatus ?? this.syncStatus,
      serverConfirmed: serverConfirmed ?? this.serverConfirmed,
      createdAt: createdAt,
      lastError: lastError ?? this.lastError,
      sheetCacheKey: sheetCacheKey,
      clientUuid: clientUuid,
      userId: userId,
      militaryNumber: militaryNumber,
      exerciseId: exerciseId,
      originalFilename: originalFilename,
      localFilename: localFilename,
      mimeType: mimeType ?? this.mimeType,
      fileSize: fileSize ?? this.fileSize,
      checksum: checksum ?? this.checksum,
      updatedAt: updatedAt ?? this.updatedAt,
      uploadedBytes: uploadedBytes ?? this.uploadedBytes,
      totalBytes: totalBytes ?? this.totalBytes,
      uploadSessionId: uploadSessionId ?? this.uploadSessionId,
      attemptCount: attemptCount ?? this.attemptCount,
      lastAttemptAt: lastAttemptAt ?? this.lastAttemptAt,
      serverMediaId: serverMediaId ?? this.serverMediaId,
    );
  }

  Map<String, dynamic> toRow() => {
        'id': id,
        'local_path': localPath,
        'row_index': rowIndex,
        'media_kind': mediaKind,
        'evaluation_list_item_id': evaluationListItemId,
        'bundle_action_eval_id': bundleActionEvalId,
        'sync_status': syncStatus,
        'server_confirmed': serverConfirmed ? 1 : 0,
        'created_at': createdAt,
        'last_error': lastError,
        'sheet_cache_key': sheetCacheKey,
        'client_uuid': clientUuid ?? id,
        'user_id': userId,
        'military_number': militaryNumber,
        'exercise_id': exerciseId,
        'original_filename': originalFilename,
        'local_filename': localFilename,
        'mime_type': mimeType,
        'file_size': fileSize,
        'checksum': checksum,
        'updated_at': updatedAt,
        'uploaded_bytes': uploadedBytes,
        'total_bytes': totalBytes,
        'upload_session_id': uploadSessionId,
        'attempt_count': attemptCount,
        'last_attempt_at': lastAttemptAt,
        'server_media_id': serverMediaId,
      };

  factory LocalMediaRecord.fromRow(Map<String, dynamic> row) {
    return LocalMediaRecord(
      id: row['id'] as String,
      localPath: (row['local_path'] as String?) ?? '',
      rowIndex: (row['row_index'] as int?) ?? 0,
      mediaKind: (row['media_kind'] as String?) ?? 'photo',
      evaluationListItemId: row['evaluation_list_item_id'] as int?,
      bundleActionEvalId: row['bundle_action_eval_id'] as int?,
      syncStatus: (row['sync_status'] as String?) ?? SyncStatuses.pending,
      serverConfirmed: (row['server_confirmed'] as int?) == 1,
      createdAt: (row['created_at'] as String?) ?? '',
      lastError: row['last_error'] as String?,
      sheetCacheKey: row['sheet_cache_key'] as String?,
      clientUuid: row['client_uuid'] as String?,
      userId: row['user_id'] as int?,
      militaryNumber: row['military_number'] as String?,
      exerciseId: row['exercise_id'] as int?,
      originalFilename: row['original_filename'] as String?,
      localFilename: row['local_filename'] as String?,
      mimeType: row['mime_type'] as String?,
      fileSize: (row['file_size'] as int?) ?? 0,
      checksum: row['checksum'] as String?,
      updatedAt: row['updated_at'] as String?,
      uploadedBytes: (row['uploaded_bytes'] as int?) ?? 0,
      totalBytes: (row['total_bytes'] as int?) ?? 0,
      uploadSessionId: row['upload_session_id'] as String?,
      attemptCount: (row['attempt_count'] as int?) ?? 0,
      lastAttemptAt: row['last_attempt_at'] as String?,
      serverMediaId: row['server_media_id'] as int?,
    );
  }
}

/// قاعدة محلية دائمة: نسخة تشغيلية للمحكم + طابور مزامنة + وسائط.
class OfflineStore {
  OfflineStore._internal();
  static final OfflineStore instance = OfflineStore._internal();

  Database? _db;
  SharedPreferences? _prefs;
  static const _cachePrefix = 'pwa_cache_';
  static const _opsKey = 'pwa_pending_ops_v2';
  static const _mediaKey = 'pwa_media_v2';

  Future<void> init() async {
    if (kIsWeb) {
      _prefs = await SharedPreferences.getInstance();
      return;
    }
    await _database;
  }

  Future<Database> get _database async {
    if (_db != null) return _db!;
    final dbPath = await getDatabasesPath();
    final path = p.join(dbPath, 'tablet_offline.db');
    _db = await openDatabase(
      path,
      version: 4,
      onCreate: (db, version) async {
        await _createV2(db);
        await _upgradeToV3(db);
        await _upgradeToV4(db);
      },
      onUpgrade: (db, oldVersion, newVersion) async {
        if (oldVersion < 2) {
          await _upgradeToV2(db);
        }
        if (oldVersion < 3) {
          await _upgradeToV3(db);
        }
        if (oldVersion < 4) {
          await _upgradeToV4(db);
        }
      },
    );
    return _db!;
  }

  Future<void> _createV2(Database db) async {
    await db.execute('''
      CREATE TABLE cache (
        cache_key TEXT PRIMARY KEY,
        json_body TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        sync_status TEXT NOT NULL DEFAULT 'synced'
      )
    ''');
    await db.execute('''
      CREATE TABLE pending_ops (
        id TEXT PRIMARY KEY,
        method TEXT NOT NULL,
        path TEXT NOT NULL,
        body TEXT NOT NULL,
        kind TEXT NOT NULL,
        op_type TEXT NOT NULL,
        created_at TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        last_error TEXT,
        sync_status TEXT NOT NULL DEFAULT 'pending',
        judge_id INTEGER,
        user_id INTEGER,
        exercise_id INTEGER,
        list_id TEXT,
        eval_item_id INTEGER,
        media_local_path TEXT
      )
    ''');
    await db.execute('''
      CREATE TABLE media_files (
        id TEXT PRIMARY KEY,
        local_path TEXT NOT NULL,
        row_index INTEGER NOT NULL,
        media_kind TEXT NOT NULL,
        evaluation_list_item_id INTEGER,
        bundle_action_eval_id INTEGER,
        sync_status TEXT NOT NULL DEFAULT 'pending',
        server_confirmed INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        last_error TEXT,
        sheet_cache_key TEXT
      )
    ''');
  }

  Future<void> _upgradeToV2(Database db) async {
    try {
      await db.execute(
        "ALTER TABLE cache ADD COLUMN sync_status TEXT NOT NULL DEFAULT 'synced'",
      );
    } catch (_) {}
    for (final col in [
      "ALTER TABLE pending_ops ADD COLUMN op_type TEXT NOT NULL DEFAULT 'unknown'",
      "ALTER TABLE pending_ops ADD COLUMN sync_status TEXT NOT NULL DEFAULT 'pending'",
      "ALTER TABLE pending_ops ADD COLUMN judge_id INTEGER",
      "ALTER TABLE pending_ops ADD COLUMN user_id INTEGER",
      "ALTER TABLE pending_ops ADD COLUMN exercise_id INTEGER",
      "ALTER TABLE pending_ops ADD COLUMN list_id TEXT",
      "ALTER TABLE pending_ops ADD COLUMN eval_item_id INTEGER",
      "ALTER TABLE pending_ops ADD COLUMN media_local_path TEXT",
    ]) {
      try {
        await db.execute(col);
      } catch (_) {}
    }
    await db.execute('''
      CREATE TABLE IF NOT EXISTS media_files (
        id TEXT PRIMARY KEY,
        local_path TEXT NOT NULL,
        row_index INTEGER NOT NULL,
        media_kind TEXT NOT NULL,
        evaluation_list_item_id INTEGER,
        bundle_action_eval_id INTEGER,
        sync_status TEXT NOT NULL DEFAULT 'pending',
        server_confirmed INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        last_error TEXT,
        sheet_cache_key TEXT
      )
    ''');
  }

  Future<void> _upgradeToV3(Database db) async {
    await db.execute('''
      CREATE TABLE IF NOT EXISTS local_users (
        user_id INTEGER PRIMARY KEY,
        username TEXT NOT NULL,
        military_number TEXT,
        password_hash TEXT NOT NULL,
        session_json TEXT NOT NULL,
        updated_at TEXT NOT NULL
      )
    ''');
    await db.execute('''
      CREATE TABLE IF NOT EXISTS device_meta (
        meta_key TEXT PRIMARY KEY,
        meta_value TEXT NOT NULL
      )
    ''');
  }


  Future<void> _upgradeToV4(Database db) async {
    const cols = <String, String>{
      'client_uuid': 'TEXT',
      'user_id': 'INTEGER',
      'military_number': 'TEXT',
      'exercise_id': 'INTEGER',
      'original_filename': 'TEXT',
      'local_filename': 'TEXT',
      'mime_type': 'TEXT',
      'file_size': 'INTEGER NOT NULL DEFAULT 0',
      'checksum': 'TEXT',
      'updated_at': 'TEXT',
      'uploaded_bytes': 'INTEGER NOT NULL DEFAULT 0',
      'total_bytes': 'INTEGER NOT NULL DEFAULT 0',
      'upload_session_id': 'TEXT',
      'attempt_count': 'INTEGER NOT NULL DEFAULT 0',
      'last_attempt_at': 'TEXT',
      'server_media_id': 'INTEGER',
    };
    for (final e in cols.entries) {
      try {
        await db.execute('ALTER TABLE media_files ADD COLUMN ${e.key} ${e.value}');
      } catch (_) {}
    }
  }

  /// مفتاح كاش معزول بمستخدم — يمنع تسرّب بيانات محكم لآخر.
  static String userKey(int userId, String key) => 'u$userId:$key';

  Future<void> cacheSetForUser(
    int userId,
    String key,
    Map<String, dynamic> data, {
    String syncStatus = SyncStatuses.synced,
  }) {
    return cacheSet(userKey(userId, key), data, syncStatus: syncStatus);
  }

  Future<Map<String, dynamic>?> cacheGetForUser(int userId, String key) {
    return cacheGet(userKey(userId, key));
  }

  Future<void> setDeviceMeta(String key, String value) async {
    if (kIsWeb) {
      final prefs = _prefs ?? await SharedPreferences.getInstance();
      await prefs.setString('device_meta_$key', value);
      return;
    }
    final db = await _database;
    await db.insert(
      'device_meta',
      {'meta_key': key, 'meta_value': value},
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  Future<String?> getDeviceMeta(String key) async {
    if (kIsWeb) {
      final prefs = _prefs ?? await SharedPreferences.getInstance();
      return prefs.getString('device_meta_$key');
    }
    final db = await _database;
    final rows = await db.query(
      'device_meta',
      where: 'meta_key = ?',
      whereArgs: [key],
      limit: 1,
    );
    if (rows.isEmpty) return null;
    return rows.first['meta_value'] as String?;
  }

  Future<void> upsertLocalUser({
    required int userId,
    required String username,
    required String passwordHash,
    required Map<String, dynamic> session,
    String militaryNumber = '',
  }) async {
    final payload = {
      'user_id': userId,
      'username': username.trim().toLowerCase(),
      'military_number': militaryNumber,
      'password_hash': passwordHash,
      'session_json': jsonEncode(session),
      'updated_at': DateTime.now().toIso8601String(),
    };
    if (kIsWeb) {
      final prefs = _prefs ?? await SharedPreferences.getInstance();
      await prefs.setString('local_user_$userId', jsonEncode(payload));
      final idx = prefs.getStringList('local_user_ids') ?? <String>[];
      if (!idx.contains('$userId')) {
        idx.add('$userId');
        await prefs.setStringList('local_user_ids', idx);
      }
      return;
    }
    final db = await _database;
    await db.insert(
      'local_users',
      payload,
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  Future<Map<String, dynamic>?> localUserByUsername(String username) async {
    final u = username.trim().toLowerCase();
    if (kIsWeb) {
      final prefs = _prefs ?? await SharedPreferences.getInstance();
      final ids = prefs.getStringList('local_user_ids') ?? <String>[];
      for (final id in ids) {
        final raw = prefs.getString('local_user_$id');
        if (raw == null) continue;
        try {
          final m = Map<String, dynamic>.from(jsonDecode(raw) as Map);
          if ((m['username'] ?? '').toString() == u) return m;
        } catch (_) {}
      }
      return null;
    }
    final db = await _database;
    final rows = await db.query(
      'local_users',
      where: 'username = ?',
      whereArgs: [u],
      limit: 1,
    );
    return rows.isEmpty ? null : Map<String, dynamic>.from(rows.first);
  }

  Future<List<Map<String, dynamic>>> allLocalUsers() async {
    if (kIsWeb) {
      final prefs = _prefs ?? await SharedPreferences.getInstance();
      final ids = prefs.getStringList('local_user_ids') ?? <String>[];
      final out = <Map<String, dynamic>>[];
      for (final id in ids) {
        final raw = prefs.getString('local_user_$id');
        if (raw == null) continue;
        try {
          out.add(Map<String, dynamic>.from(jsonDecode(raw) as Map));
        } catch (_) {}
      }
      return out;
    }
    final db = await _database;
    final rows = await db.query('local_users', orderBy: 'username ASC');
    return rows.map(Map<String, dynamic>.from).toList();
  }

  Future<void> cacheSet(
    String key,
    Map<String, dynamic> json, {
    String syncStatus = SyncStatuses.synced,
  }) async {
    if (kIsWeb) {
      final prefs = _prefs ?? await SharedPreferences.getInstance();
      await prefs.setString(
        '$_cachePrefix$key',
        jsonEncode({
          'body': json,
          'updated_at': DateTime.now().toIso8601String(),
          'sync_status': syncStatus,
        }),
      );
      return;
    }
    final db = await _database;
    await db.insert(
      'cache',
      {
        'cache_key': key,
        'json_body': jsonEncode(json),
        'updated_at': DateTime.now().toIso8601String(),
        'sync_status': syncStatus,
      },
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  Future<Map<String, dynamic>?> cacheGet(String key) async {
    if (kIsWeb) {
      final prefs = _prefs ?? await SharedPreferences.getInstance();
      final raw = prefs.getString('$_cachePrefix$key');
      if (raw == null) return null;
      try {
        final decoded = jsonDecode(raw);
        if (decoded is Map) {
          final root = Map<String, dynamic>.from(decoded);
          final body = root['body'];
          if (body is Map) return Map<String, dynamic>.from(body);
          return root;
        }
      } catch (_) {}
      return null;
    }
    final db = await _database;
    final rows = await db.query(
      'cache',
      where: 'cache_key = ?',
      whereArgs: [key],
      limit: 1,
    );
    if (rows.isEmpty) return null;
    try {
      final decoded = jsonDecode(rows.first['json_body'] as String);
      if (decoded is Map) return Map<String, dynamic>.from(decoded);
    } catch (_) {}
    return null;
  }

  Future<String?> cacheSyncStatus(String key) async {
    if (kIsWeb) {
      final prefs = _prefs ?? await SharedPreferences.getInstance();
      final raw = prefs.getString('$_cachePrefix$key');
      if (raw == null) return null;
      try {
        final decoded = jsonDecode(raw);
        if (decoded is Map) return (decoded['sync_status'] ?? '').toString();
      } catch (_) {}
      return null;
    }
    final db = await _database;
    final rows = await db.query(
      'cache',
      columns: ['sync_status'],
      where: 'cache_key = ?',
      whereArgs: [key],
      limit: 1,
    );
    if (rows.isEmpty) return null;
    return rows.first['sync_status'] as String?;
  }

  Future<DateTime?> cacheUpdatedAt(String key) async {
    if (kIsWeb) {
      final prefs = _prefs ?? await SharedPreferences.getInstance();
      final raw = prefs.getString('$_cachePrefix$key');
      if (raw == null) return null;
      try {
        final decoded = jsonDecode(raw);
        if (decoded is Map) {
          return DateTime.tryParse('${decoded['updated_at'] ?? ''}');
        }
      } catch (_) {}
      return null;
    }
    final db = await _database;
    final rows = await db.query(
      'cache',
      columns: ['updated_at'],
      where: 'cache_key = ?',
      whereArgs: [key],
      limit: 1,
    );
    if (rows.isEmpty) return null;
    return DateTime.tryParse(rows.first['updated_at'] as String);
  }

  Future<void> enqueueOp(PendingOp op) async {
    if (kIsWeb) {
      final ops = await pendingOps();
      ops.removeWhere((o) => o.id == op.id);
      ops.add(op);
      await _saveOps(ops);
      return;
    }
    final db = await _database;
    await db.insert(
      'pending_ops',
      op.toRow(),
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  Future<List<PendingOp>> pendingOps({int? userId}) async {
    if (kIsWeb) {
      final prefs = _prefs ?? await SharedPreferences.getInstance();
      final raw = prefs.getString(_opsKey);
      if (raw == null || raw.isEmpty) return [];
      try {
        final decoded = jsonDecode(raw);
        if (decoded is! List) return [];
        return decoded
            .whereType<Map>()
            .map((e) => PendingOp.fromJson(Map<String, dynamic>.from(e)))
            .where((o) => o.syncStatus != SyncStatuses.synced)
            .where((o) => userId == null || o.userId == userId)
            .toList()
          ..sort((a, b) => a.createdAt.compareTo(b.createdAt));
      } catch (_) {
        return [];
      }
    }
    final db = await _database;
    if (userId == null) {
      final rows = await db.query(
        'pending_ops',
        where: "sync_status != ?",
        whereArgs: [SyncStatuses.synced],
        orderBy: 'created_at ASC',
      );
      return rows.map(PendingOp.fromRow).toList();
    }
    final rows = await db.query(
      'pending_ops',
      where: "sync_status != ? AND user_id = ?",
      whereArgs: [SyncStatuses.synced, userId],
      orderBy: 'created_at ASC',
    );
    return rows.map(PendingOp.fromRow).toList();
  }

  Future<void> _saveOps(List<PendingOp> ops) async {
    final prefs = _prefs ?? await SharedPreferences.getInstance();
    await prefs.setString(
      _opsKey,
      jsonEncode(ops.map((o) => o.toJson()).toList()),
    );
  }

  Future<int> pendingOpsCount({int? userId}) async {
    return (await pendingOps(userId: userId)).length;
  }

  Future<void> removeOp(String id) async {
    if (kIsWeb) {
      final ops = await pendingOps();
      ops.removeWhere((o) => o.id == id);
      await _saveOps(ops);
      return;
    }
    final db = await _database;
    await db.delete('pending_ops', where: 'id = ?', whereArgs: [id]);
  }

  Future<void> updateOp(PendingOp op) async {
    if (kIsWeb) {
      final ops = await pendingOps();
      final i = ops.indexWhere((o) => o.id == op.id);
      if (i < 0) {
        ops.add(op);
      } else {
        ops[i] = op;
      }
      await _saveOps(ops);
      return;
    }
    final db = await _database;
    await db.insert(
      'pending_ops',
      op.toRow(),
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  Future<void> markOpFailed(String id, String error) async {
    final ops = await pendingOps();
    final i = ops.indexWhere((o) => o.id == id);
    if (i < 0) return;
    final old = ops[i];
    await updateOp(
      old.copyWith(
        attempts: old.attempts + 1,
        lastError: error,
        syncStatus: SyncStatuses.failed,
      ),
    );
  }

  Future<void> markOpSyncing(String id) async {
    final ops = await pendingOps();
    final i = ops.indexWhere((o) => o.id == id);
    if (i < 0) return;
    await updateOp(ops[i].copyWith(syncStatus: SyncStatuses.syncing));
  }

  Future<Directory> mediaRoot() async {
    final root = await getApplicationDocumentsDirectory();
    final dir = Directory(p.join(root.path, 'media'));
    if (!await dir.exists()) {
      await dir.create(recursive: true);
    }
    return dir;
  }

  @Deprecated('Use mediaRoot')
  Future<Directory> mediaDirectory() => mediaRoot();

  Future<Directory> _mediaSubdir(String kind, {required bool pending}) async {
    final root = await mediaRoot();
    final branch = pending ? 'pending' : 'synced';
    final folder = kind == 'video'
        ? 'videos'
        : (kind == 'file' ? 'files' : 'images');
    final dir = Directory(p.join(root.path, branch, folder));
    if (!await dir.exists()) {
      await dir.create(recursive: true);
    }
    return dir;
  }

  /// ينسخ الملف فوراً إلى App Private Storage (ليس content URI).
  Future<String> persistMediaFile(
    String sourcePath,
    String opId, {
    String mediaKind = 'photo',
  }) async {
    if (kIsWeb) return sourcePath;
    final dir = await _mediaSubdir(mediaKind, pending: true);
    final ext = p.extension(sourcePath);
    final safeName = '$opId$ext';
    final dest = p.join(dir.path, safeName);
    await File(sourcePath).copy(dest);
    return dest;
  }

  Future<void> upsertMedia(LocalMediaRecord rec) async {
    if (kIsWeb) {
      final list = await mediaRecords();
      list.removeWhere((m) => m.id == rec.id);
      list.add(rec);
      final prefs = _prefs ?? await SharedPreferences.getInstance();
      await prefs.setString(
        _mediaKey,
        jsonEncode(list.map((m) => m.toRow()).toList()),
      );
      return;
    }
    final db = await _database;
    await db.insert(
      'media_files',
      rec.toRow(),
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  Future<List<LocalMediaRecord>> mediaRecords({bool pendingOnly = false}) async {
    if (kIsWeb) {
      final prefs = _prefs ?? await SharedPreferences.getInstance();
      final raw = prefs.getString(_mediaKey);
      if (raw == null || raw.isEmpty) return [];
      try {
        final decoded = jsonDecode(raw);
        if (decoded is! List) return [];
        var list = decoded
            .whereType<Map>()
            .map((e) => LocalMediaRecord.fromRow(Map<String, dynamic>.from(e)))
            .toList();
        if (pendingOnly) {
          list = list
              .where((m) => !m.serverConfirmed && m.syncStatus != SyncStatuses.synced)
              .toList();
        }
        return list;
      } catch (_) {
        return [];
      }
    }
    final db = await _database;
    final rows = pendingOnly
        ? await db.query(
            'media_files',
            where: 'server_confirmed = 0',
            orderBy: 'created_at ASC',
          )
        : await db.query('media_files', orderBy: 'created_at ASC');
    return rows.map(LocalMediaRecord.fromRow).toList();
  }

  Future<LocalMediaRecord?> mediaById(String id) async {
    final all = await mediaRecords();
    try {
      return all.firstWhere((m) => m.id == id);
    } catch (_) {
      return null;
    }
  }

  Future<void> patchMedia(
    String id, {
    String? syncStatus,
    String? lastError,
    String? checksum,
    String? mimeType,
    int? fileSize,
    int? uploadedBytes,
    int? totalBytes,
    String? uploadSessionId,
    int? attemptCount,
    int? serverMediaId,
  }) async {
    final rec = await mediaById(id);
    if (rec == null) return;
    await upsertMedia(
      rec.copyWith(
        syncStatus: syncStatus,
        lastError: lastError,
        checksum: checksum,
        mimeType: mimeType,
        fileSize: fileSize,
        uploadedBytes: uploadedBytes,
        totalBytes: totalBytes,
        uploadSessionId: uploadSessionId,
        attemptCount: attemptCount,
        serverMediaId: serverMediaId,
        updatedAt: DateTime.now().toIso8601String(),
        lastAttemptAt: DateTime.now().toIso8601String(),
      ),
    );
  }

  /// بعد تأكيد السيرفر: انقل إلى media/synced دون حذف فوري.
  Future<void> markMediaSynced(String id, {int? serverMediaId}) async {
    final rec = await mediaById(id);
    if (rec == null) return;
    var newPath = rec.localPath;
    if (!kIsWeb && rec.localPath.isNotEmpty) {
      try {
        final src = File(rec.localPath);
        if (await src.exists()) {
          final dir = await _mediaSubdir(rec.mediaKind, pending: false);
          final name = p.basename(rec.localPath);
          final destPath = p.join(dir.path, name);
          if (destPath != rec.localPath) {
            await src.copy(destPath);
            try {
              await src.delete();
            } catch (_) {}
            newPath = destPath;
          }
        }
      } catch (_) {}
    }
    await upsertMedia(
      rec.copyWith(
        localPath: newPath,
        syncStatus: SyncStatuses.synced,
        serverConfirmed: true,
        uploadedBytes: rec.totalBytes > 0 ? rec.totalBytes : rec.fileSize,
        serverMediaId: serverMediaId ?? rec.serverMediaId,
        updatedAt: DateTime.now().toIso8601String(),
      ),
    );
  }

  @Deprecated('Use markMediaSynced')
  Future<void> markMediaConfirmed(String id) => markMediaSynced(id);

  Future<Map<String, int>> mediaStorageStats() async {
    final all = await mediaRecords();
    var pendingBytes = 0;
    var syncedBytes = 0;
    var pendingCount = 0;
    var syncedCount = 0;
    var images = 0;
    var videos = 0;
    for (final m in all) {
      final sz = m.fileSize > 0 ? m.fileSize : m.totalBytes;
      if (m.serverConfirmed || m.syncStatus == SyncStatuses.synced) {
        syncedBytes += sz;
        syncedCount++;
      } else if (m.syncStatus != 'cancelled') {
        pendingBytes += sz;
        pendingCount++;
        if (m.mediaKind == 'video') {
          videos++;
        } else {
          images++;
        }
      }
    }
    return {
      'pending_bytes': pendingBytes,
      'synced_bytes': syncedBytes,
      'pending_count': pendingCount,
      'synced_count': syncedCount,
      'pending_images': images,
      'pending_videos': videos,
    };
  }

  Future<int> deleteSyncedMediaFiles() async {
    final all = await mediaRecords();
    var n = 0;
    for (final m in all) {
      if (!(m.serverConfirmed || m.syncStatus == SyncStatuses.synced)) continue;
      if (!kIsWeb && m.localPath.isNotEmpty) {
        try {
          final f = File(m.localPath);
          if (await f.exists()) {
            await f.delete();
            n++;
          }
        } catch (_) {}
      }
      await upsertMedia(
        m.copyWith(localPath: '', updatedAt: DateTime.now().toIso8601String()),
      );
    }
    return n;
  }

  Future<void> clearAll() async {
    if (kIsWeb) {
      final prefs = _prefs ?? await SharedPreferences.getInstance();
      final keys = prefs
          .getKeys()
          .where(
            (k) =>
                k.startsWith(_cachePrefix) ||
                k.startsWith('local_user_') ||
                k.startsWith('device_meta_'),
          )
          .toList();
      for (final k in keys) {
        await prefs.remove(k);
      }
      await prefs.remove(_opsKey);
      await prefs.remove(_mediaKey);
      await prefs.remove('local_user_ids');
      return;
    }
    final db = await _database;
    await db.delete('cache');
    await db.delete('pending_ops');
    await db.delete('media_files');
    try {
      await db.delete('local_users');
      await db.delete('device_meta');
    } catch (_) {}
  }
}
