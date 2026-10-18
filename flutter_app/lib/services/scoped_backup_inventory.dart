import 'dart:convert';

import 'eval_cache_merge.dart';
import 'scoped_backup_models.dart';

const List<String> kScopedBackupCacheBarePrefixes = [
  'evaluation_list_detail:',
  'evaluation_lists',
  'action_eval_detail:',
  'action_eval_lists',
  'judge_signature',
  'polarity_notes',
  'incomplete',
  'home',
  'flow:',
  'objectives',
];

const Set<String> kScopedBackupExcludedBareKeys = {
  'session_bundle',
  'local_auth',
  'bootstrap',
};

const Set<String> kScopedBackupSecretFieldNames = {
  'password',
  'password_hash',
  'passwordHash',
  'salt',
  'local_auth_salt_v2',
  'reconnect_ticket',
  'reconnectTicket',
  'cookie',
  'cookies',
  'hmac_secret',
  'hmacSecret',
  'device_admin_password',
  'device_admin_password_hash',
  'judge_cookie',
  'device_cookie',
};

final _userPrefix = RegExp(r'^u(\d+):');

int? cacheKeyUserId(String cacheKey) {
  final m = _userPrefix.firstMatch(cacheKey);
  if (m == null) return null;
  return int.tryParse(m.group(1) ?? '');
}

String cacheKeyBare(String cacheKey) {
  final m = _userPrefix.firstMatch(cacheKey);
  if (m == null) return cacheKey;
  return cacheKey.substring(m.end);
}

bool cacheKeyBelongsToUser(String cacheKey, int userId) {
  return cacheKeyUserId(cacheKey) == userId;
}

bool judgeMayBackupUser({
  required int sessionUserId,
  required int selectedUserId,
  required bool deviceManager,
}) {
  if (deviceManager) return true;
  return sessionUserId > 0 && sessionUserId == selectedUserId;
}

bool cacheKeyIsOperational(String cacheKey) {
  final bare = cacheKeyBare(cacheKey);
  if (kScopedBackupExcludedBareKeys.contains(bare)) return false;
  for (final prefix in kScopedBackupCacheBarePrefixes) {
    if (bare == prefix || bare.startsWith(prefix)) return true;
  }
  return false;
}

bool jsonContainsSecretField(dynamic node) {
  if (node is Map) {
    for (final e in node.entries) {
      final key = '${e.key}';
      if (kScopedBackupSecretFieldNames.contains(key)) return true;
      if (jsonContainsSecretField(e.value)) return true;
    }
    return false;
  }
  if (node is List) {
    for (final e in node) {
      if (jsonContainsSecretField(e)) return true;
    }
  }
  return false;
}

dynamic stripSecretFields(dynamic node) {
  if (node is Map) {
    final out = <String, dynamic>{};
    node.forEach((k, v) {
      if (kScopedBackupSecretFieldNames.contains('$k')) return;
      out['$k'] = stripSecretFields(v);
    });
    return out;
  }
  if (node is List) {
    return node.map(stripSecretFields).toList();
  }
  return node;
}

bool rowIntEquals(dynamic raw, int want) {
  if (raw == null) return false;
  if (raw is int) return raw == want;
  if (raw is num) return raw.toInt() == want;
  return int.tryParse('$raw'.trim()) == want;
}

int? rowAsInt(dynamic raw) {
  if (raw == null) return null;
  if (raw is int) return raw;
  if (raw is num) return raw.toInt();
  return int.tryParse('$raw'.trim());
}

bool pendingBelongsToScope(
  Map<String, dynamic> row, {
  required int userId,
  required int exerciseId,
}) {
  return rowIntEquals(row['user_id'], userId) &&
      rowIntEquals(row['exercise_id'], exerciseId);
}

bool mediaBelongsToScope(
  Map<String, dynamic> row, {
  required int userId,
  required int exerciseId,
  required Set<int> selectedEvalIds,
}) {
  final owner = rowAsInt(row['user_id']);
  if (owner != null && owner > 0 && owner != userId) return false;
  final ex = rowAsInt(row['exercise_id']);
  if (ex != null && ex > 0 && ex != exerciseId) return false;
  if (owner == userId) {
    if (ex == null || ex == 0 || ex == exerciseId) return true;
  }
  final evalId = rowAsInt(row['evaluation_list_item_id']);
  final slotId = rowAsInt(row['bundle_action_eval_id']);
  final linked = (evalId != null && selectedEvalIds.contains(evalId)) ||
      (slotId != null && selectedEvalIds.contains(slotId));
  if (owner == null || owner == 0) {
    if (ex == exerciseId) return true;
    if ((ex == null || ex == 0) && linked) return true;
  }
  return false;
}

Set<int> evalIdsFromCacheAndPending({
  required List<Map<String, dynamic>> cacheRows,
  required List<Map<String, dynamic>> pendingRows,
}) {
  final ids = <int>{};
  for (final row in pendingRows) {
    final id = rowAsInt(row['eval_item_id']);
    if (id != null && id > 0) ids.add(id);
  }
  for (final row in cacheRows) {
    final key = '${row['cache_key'] ?? ''}';
    final bare = cacheKeyBare(key);
    final detail = RegExp(r'(?:evaluation_list_detail:[^:]+:|action_eval_detail:)(\d+)$')
        .firstMatch(bare);
    if (detail != null) {
      final n = int.tryParse(detail.group(1) ?? '');
      if (n != null && n > 0) ids.add(n);
    }
    final body = _decodeBody(row['json_body']);
    if (body is Map) {
      for (final field in ['id', 'eval_item_id', 'evaluation_list_item_id']) {
        final n = rowAsInt(body[field]);
        if (n != null && n > 0) ids.add(n);
      }
    }
  }
  return ids;
}

bool cacheRowExerciseCompatible(
  Map<String, dynamic> row, {
  required int exerciseId,
}) {
  final body = _decodeBody(row['json_body']);
  if (body is! Map) return true;
  final ex = rowAsInt(body['exercise_id']);
  if (ex != null && ex > 0 && ex != exerciseId) return false;
  return true;
}

List<Map<String, dynamic>> selectUserExerciseCache({
  required List<Map<String, dynamic>> allCache,
  required int userId,
  required int exerciseId,
}) {
  final out = <Map<String, dynamic>>[];
  for (final row in allCache) {
    final key = '${row['cache_key'] ?? ''}';
    if (!cacheKeyBelongsToUser(key, userId)) continue;
    if (!cacheKeyIsOperational(key)) continue;
    if (!cacheRowExerciseCompatible(row, exerciseId: exerciseId)) continue;
    final copy = Map<String, dynamic>.from(row);
    final body = _decodeBody(copy['json_body']);
    copy['json_body'] = jsonEncode(stripSecretFields(body));
    out.add(copy);
  }
  return out;
}

List<Map<String, dynamic>> selectUserExercisePending({
  required List<Map<String, dynamic>> allPending,
  required int userId,
  required int exerciseId,
}) {
  return [
    for (final row in allPending)
      if (pendingBelongsToScope(row, userId: userId, exerciseId: exerciseId))
        Map<String, dynamic>.from(row),
  ];
}

List<Map<String, dynamic>> selectUserExerciseMedia({
  required List<Map<String, dynamic>> allMedia,
  required int userId,
  required int exerciseId,
  required Set<int> selectedEvalIds,
}) {
  return [
    for (final row in allMedia)
      if (mediaBelongsToScope(
        row,
        userId: userId,
        exerciseId: exerciseId,
        selectedEvalIds: selectedEvalIds,
      ))
        Map<String, dynamic>.from(row),
  ];
}

ScopedBackupIdentity identityFromLocalUser(Map<String, dynamic> row) {
  var display = '';
  try {
    final session = jsonDecode('${row['session_json'] ?? '{}'}');
    if (session is Map) {
      final user = session['user'];
      if (user is Map) {
        display = '${user['judge_display_name'] ?? user['full_name'] ?? ''}';
      }
    }
  } catch (_) {}
  return ScopedBackupIdentity(
    userId: rowAsInt(row['user_id']) ?? 0,
    username: '${row['username'] ?? ''}',
    militaryNumber: '${row['military_number'] ?? ''}',
    displayName: display,
  );
}

Map<String, dynamic> safeLocalUserDisplay(Map<String, dynamic> row) {
  final id = identityFromLocalUser(row);
  return id.toJson();
}

bool localWorkIsProtected({
  required Map<String, dynamic>? cacheBody,
  String? cacheStatus,
  bool hasLivePending = false,
}) {
  if (hasLivePending) return true;
  return cacheHasLocalJudgeWork(cacheBody, cacheStatus);
}

RestoreConflictClass classifyRestoreCache({
  required Map<String, dynamic>? localBody,
  required String? localStatus,
  required DateTime? localUpdatedAt,
  required Map<String, dynamic>? backupBody,
  required String? backupStatus,
  required DateTime? backupUpdatedAt,
  bool hasLivePending = false,
}) {
  if (localWorkIsProtected(
    cacheBody: localBody,
    cacheStatus: localStatus,
    hasLivePending: hasLivePending,
  )) {
    if (localBody == null) {
      return RestoreConflictClass.missingLocally;
    }
    if (_canonicalJson(localBody) == _canonicalJson(backupBody)) {
      return RestoreConflictClass.same;
    }
    return RestoreConflictClass.localUnsynced;
  }
  if (localBody == null) return RestoreConflictClass.missingLocally;
  if (_canonicalJson(localBody) == _canonicalJson(backupBody)) {
    return RestoreConflictClass.same;
  }
  final lu = localUpdatedAt;
  final bu = backupUpdatedAt;
  if (lu != null && bu != null) {
    if (bu.isAfter(lu)) return RestoreConflictClass.backupNewer;
    if (bu.isBefore(lu)) return RestoreConflictClass.backupOlder;
  }
  return RestoreConflictClass.conflict;
}

bool isSafeRelativeBackupPath(String relativePath) {
  final raw = relativePath.trim().replaceAll('\\', '/');
  if (raw.isEmpty) return false;
  if (raw.startsWith('/')) return false;
  if (RegExp(r'^[a-zA-Z]:').hasMatch(raw)) return false;
  if (raw.contains('\u0000')) return false;
  final parts = raw.split('/');
  if (parts.any((p) => p == '..' || p == '.' || p.isEmpty)) return false;
  return true;
}

String mediaBackupRelPath(Map<String, dynamic> row) {
  final id = '${row['id'] ?? ''}'.trim();
  final original = '${row['original_filename'] ?? row['local_filename'] ?? ''}';
  var ext = '';
  final dot = original.lastIndexOf('.');
  if (dot >= 0) {
    ext = original.substring(dot).toLowerCase();
    if (!RegExp(r'^\.[a-z0-9]{1,8}$').hasMatch(ext)) ext = '';
  }
  if (ext.isEmpty) {
    final kind = '${row['media_kind'] ?? ''}';
    if (kind == 'video') ext = '.mp4';
    else if (kind == 'photo' || kind == 'image') ext = '.jpg';
  }
  final safeId = id.replaceAll(RegExp(r'[^a-zA-Z0-9._-]'), '_');
  return 'media/$safeId$ext';
}

Map<String, dynamic> portableMediaRow(Map<String, dynamic> row, String relPath) {
  final out = Map<String, dynamic>.from(row);
  out['backup_rel_path'] = relPath;
  out['source_local_path'] = '${row['local_path'] ?? ''}';
  out.remove('local_path');
  out.remove('password_hash');
  return out;
}

dynamic _decodeBody(dynamic raw) {
  if (raw is Map) return Map<String, dynamic>.from(raw);
  if (raw is List) return raw;
  final s = '$raw';
  if (s.isEmpty) return {};
  try {
    return jsonDecode(s);
  } catch (_) {
    return s;
  }
}

String _canonicalJson(dynamic node) {
  return jsonEncode(stripSecretFields(node));
}
