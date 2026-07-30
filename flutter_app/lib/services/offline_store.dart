import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:sqflite/sqflite.dart';
import 'package:path/path.dart' as p;

/// A queued write operation (save results / approve) performed while the
/// tablet had no connection to the server, replayed later by [SyncService].
class PendingOp {
  final String id;
  final String method; // PUT | POST
  final String path;
  final Map<String, dynamic> body;
  final String kind; // human label, e.g. "حفظ نتائج"
  final String createdAt;
  final int attempts;
  final String? lastError;

  const PendingOp({
    required this.id,
    required this.method,
    required this.path,
    required this.body,
    required this.kind,
    required this.createdAt,
    this.attempts = 0,
    this.lastError,
  });

  Map<String, dynamic> toRow() => {
        'id': id,
        'method': method,
        'path': path,
        'body': jsonEncode(body),
        'kind': kind,
        'created_at': createdAt,
        'attempts': attempts,
        'last_error': lastError,
      };

  factory PendingOp.fromRow(Map<String, dynamic> row) {
    Map<String, dynamic> body = {};
    try {
      final decoded = jsonDecode((row['body'] as String?) ?? '{}');
      if (decoded is Map<String, dynamic>) body = decoded;
    } catch (_) {}
    return PendingOp(
      id: row['id'] as String,
      method: row['method'] as String,
      path: row['path'] as String,
      body: body,
      kind: (row['kind'] as String?) ?? '',
      createdAt: (row['created_at'] as String?) ?? '',
      attempts: (row['attempts'] as int?) ?? 0,
      lastError: row['last_error'] as String?,
    );
  }

  Map<String, dynamic> toJson() => toRow();

  factory PendingOp.fromJson(Map<String, dynamic> json) =>
      PendingOp.fromRow(json);
}

/// Local cache + pending queue. Uses sqflite on mobile/desktop and
/// SharedPreferences on web (PWA).
class OfflineStore {
  OfflineStore._internal();
  static final OfflineStore instance = OfflineStore._internal();

  Database? _db;
  SharedPreferences? _prefs;
  static const _cachePrefix = 'pwa_cache_';
  static const _opsKey = 'pwa_pending_ops';

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
      version: 1,
      onCreate: (db, version) async {
        await db.execute('''
          CREATE TABLE cache (
            cache_key TEXT PRIMARY KEY,
            json_body TEXT NOT NULL,
            updated_at TEXT NOT NULL
          )
        ''');
        await db.execute('''
          CREATE TABLE pending_ops (
            id TEXT PRIMARY KEY,
            method TEXT NOT NULL,
            path TEXT NOT NULL,
            body TEXT NOT NULL,
            kind TEXT NOT NULL,
            created_at TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT
          )
        ''');
      },
    );
    return _db!;
  }

  Future<void> cacheSet(String key, Map<String, dynamic> json) async {
    if (kIsWeb) {
      final prefs = _prefs ?? await SharedPreferences.getInstance();
      await prefs.setString(
        '$_cachePrefix$key',
        jsonEncode({
          'body': json,
          'updated_at': DateTime.now().toIso8601String(),
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

  Future<List<PendingOp>> pendingOps() async {
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
            .toList()
          ..sort((a, b) => a.createdAt.compareTo(b.createdAt));
      } catch (_) {
        return [];
      }
    }
    final db = await _database;
    final rows = await db.query('pending_ops', orderBy: 'created_at ASC');
    return rows.map(PendingOp.fromRow).toList();
  }

  Future<void> _saveOps(List<PendingOp> ops) async {
    final prefs = _prefs ?? await SharedPreferences.getInstance();
    await prefs.setString(
      _opsKey,
      jsonEncode(ops.map((o) => o.toJson()).toList()),
    );
  }

  Future<int> pendingOpsCount() async {
    if (kIsWeb) return (await pendingOps()).length;
    final db = await _database;
    final result = Sqflite.firstIntValue(
      await db.rawQuery('SELECT COUNT(*) FROM pending_ops'),
    );
    return result ?? 0;
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

  Future<void> markOpFailed(String id, String error) async {
    if (kIsWeb) {
      final ops = await pendingOps();
      final i = ops.indexWhere((o) => o.id == id);
      if (i < 0) return;
      final old = ops[i];
      ops[i] = PendingOp(
        id: old.id,
        method: old.method,
        path: old.path,
        body: old.body,
        kind: old.kind,
        createdAt: old.createdAt,
        attempts: old.attempts + 1,
        lastError: error,
      );
      await _saveOps(ops);
      return;
    }
    final db = await _database;
    await db.rawUpdate(
      'UPDATE pending_ops SET attempts = attempts + 1, last_error = ? WHERE id = ?',
      [error, id],
    );
  }

  Future<void> clearAll() async {
    if (kIsWeb) {
      final prefs = _prefs ?? await SharedPreferences.getInstance();
      final keys = prefs.getKeys().where((k) => k.startsWith(_cachePrefix)).toList();
      for (final k in keys) {
        await prefs.remove(k);
      }
      await prefs.remove(_opsKey);
      return;
    }
    final db = await _database;
    await db.delete('cache');
    await db.delete('pending_ops');
  }
}
