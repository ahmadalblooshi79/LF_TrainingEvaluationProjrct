import 'dart:io';

import 'package:path/path.dart' as p;

import 'scoped_backup_io.dart';
import 'scoped_backup_models.dart';

const String kPublicBackupRootFolder = 'SmartArbitration_Backups';
const String kPublicBackupDisplayPrefix = 'Download';
const String kNoMatchingUserMessage = 'لا يوجد مستخدم مطابق';
const String kBackupSuccessHeadline = 'تم إنشاء النسخة الاحتياطية بنجاح';
const String kBackupLocationLabel = 'مكان الحفظ:';
const String kUserNameSearchHint = 'البحث عن المستخدم بالاسم';

final RegExp _unsafeFolderChars = RegExp(r'[\/\\:\*\?"<>\|\x00-\x1F\x7F]');

class PublicBackupLocation {
  final String exerciseFolder;
  final String judgeFolder;
  final String instanceFolder;

  const PublicBackupLocation({
    required this.exerciseFolder,
    required this.judgeFolder,
    required this.instanceFolder,
  });

  String get relativeDir =>
      '$kPublicBackupRootFolder/$exerciseFolder/$judgeFolder/$instanceFolder';

  String get displayPath => '$kPublicBackupDisplayPrefix/$relativeDir';

  PublicBackupLocation copyWith({String? instanceFolder}) {
    return PublicBackupLocation(
      exerciseFolder: exerciseFolder,
      judgeFolder: judgeFolder,
      instanceFolder: instanceFolder ?? this.instanceFolder,
    );
  }
}

String sanitizeBackupFolderName(
  String raw, {
  String fallback = 'غير_مسمى',
}) {
  var s = raw.trim().replaceAll(_unsafeFolderChars, '_');
  s = s.replaceAll(RegExp(r'\s+'), ' ').trim();
  s = s.replaceAll(RegExp(r'^[\. ]+|[\. ]+$'), '');
  if (s == '.' || s == '..' || s.isEmpty) return fallback;
  if (s.contains('..')) {
    s = s.replaceAll('..', '_');
  }
  if (s.isEmpty || s == '.' || s == '..') return fallback;
  if (s.length > 80) {
    s = s.substring(0, 80).trim();
  }
  if (s.isEmpty) return fallback;
  return s;
}

bool isSafePublicRelativeDir(String relativeDir) {
  if (relativeDir.isEmpty) return false;
  if (relativeDir.startsWith('/') || relativeDir.startsWith('\\')) {
    return false;
  }
  if (relativeDir.contains('\u0000')) return false;
  if (!relativeDir.startsWith('$kPublicBackupRootFolder/')) return false;
  final parts = relativeDir.split('/');
  if (parts.length < 4) return false;
  for (final part in parts) {
    if (part.isEmpty || part == '.' || part == '..') return false;
    if (part.contains('\\') || _unsafeFolderChars.hasMatch(part)) return false;
  }
  return true;
}

String exerciseFolderName(ScopedBackupExercise exercise) {
  final display = exercise.name.trim();
  if (display.isNotEmpty) {
    return sanitizeBackupFolderName(display, fallback: 'تمرين ${exercise.exerciseId}');
  }
  return sanitizeBackupFolderName(
    'تمرين ${exercise.exerciseId}',
    fallback: 'exercise_${exercise.exerciseId}',
  );
}

String judgeFolderName({
  required String displayName,
  required int userId,
  required Iterable<String> siblingDisplayNames,
}) {
  final trimmed = displayName.trim();
  if (trimmed.isEmpty) {
    return sanitizeBackupFolderName(
      'مستخدم $userId',
      fallback: 'user_$userId',
    );
  }
  final sanitized = sanitizeBackupFolderName(
    trimmed,
    fallback: 'مستخدم $userId',
  );
  final duplicate = siblingDisplayNames.where((n) => n.trim() == trimmed).length > 1;
  if (duplicate) {
    return sanitizeBackupFolderName(
      '$sanitized (U$userId)',
      fallback: 'user_$userId',
    );
  }
  return sanitized;
}

String formatBackupTimestamp(DateTime localTime) {
  String two(int n) => n.toString().padLeft(2, '0');
  return '${localTime.year.toString().padLeft(4, '0')}-'
      '${two(localTime.month)}-'
      '${two(localTime.day)}_'
      '${two(localTime.hour)}'
      '${two(localTime.minute)}'
      '${two(localTime.second)}';
}

String backupInstanceFolderName(
  DateTime localTime, {
  Iterable<String> existingNames = const [],
}) {
  final base = 'Backup_${formatBackupTimestamp(localTime)}';
  final taken = existingNames.toSet();
  if (!taken.contains(base)) return base;
  var i = 2;
  while (taken.contains('${base}_$i')) {
    i++;
  }
  return '${base}_$i';
}

PublicBackupLocation buildPublicBackupLocation({
  required ScopedBackupExercise exercise,
  required ScopedBackupIdentity identity,
  required Iterable<String> siblingDisplayNames,
  DateTime? now,
  Iterable<String> existingInstanceNames = const [],
}) {
  return PublicBackupLocation(
    exerciseFolder: exerciseFolderName(exercise),
    judgeFolder: judgeFolderName(
      displayName: identity.displayName,
      userId: identity.userId,
      siblingDisplayNames: siblingDisplayNames,
    ),
    instanceFolder: backupInstanceFolderName(
      now ?? DateTime.now(),
      existingNames: existingInstanceNames,
    ),
  );
}

String backupSuccessMessage(
  String displayPath, {
  int procedureExcelCount = 0,
  int dilemmaExcelCount = 0,
  int evaluationImageCount = 0,
  int evaluationVideoCount = 0,
}) {
  return '$kBackupSuccessHeadline\n\n'
      '$kBackupLocationLabel\n$displayPath\n\n'
      'قوائم تقييم الإجراءات: $procedureExcelCount\n'
      'قوائم تقييم المعاضل: $dilemmaExcelCount\n'
      'الصور: $evaluationImageCount\n'
      'الفيديوهات: $evaluationVideoCount';
}

String normalizeUserSearchQuery(String query) => query.trim();

bool userDisplayNameMatches(Map<String, dynamic> user, String query) {
  final q = normalizeUserSearchQuery(query);
  if (q.isEmpty) return true;
  final name = '${user['display_name'] ?? ''}'.toLowerCase();
  return name.contains(q.toLowerCase());
}

List<Map<String, dynamic>> filterUsersByDisplayName(
  List<Map<String, dynamic>> users,
  String query,
) {
  final q = normalizeUserSearchQuery(query);
  if (q.isEmpty) return List<Map<String, dynamic>>.from(users);
  return [
    for (final user in users)
      if (userDisplayNameMatches(user, q)) user,
  ];
}

/// Copies a verified private package into a fake or real Downloads root
/// using the production streaming copy path. Never loads whole files.
Future<PublicBackupLocation> copyVerifiedBackupToPublicLayout({
  required Directory verifiedPackage,
  required Directory downloadsRoot,
  required PublicBackupLocation location,
  int chunkSize = kScopedBackupChunkSize,
  BackupCancelCheck? isCancelled,
}) async {
  if (!isSafePublicRelativeDir(location.relativeDir)) {
    throw const ScopedBackupIoException('unsafe_public_path');
  }
  final destParent = Directory(
    p.join(
      downloadsRoot.path,
      kPublicBackupRootFolder,
      location.exerciseFolder,
      location.judgeFolder,
    ),
  );
  await destParent.create(recursive: true);
  var instance = location.instanceFolder;
  var dest = Directory(p.join(destParent.path, instance));
  var n = 2;
  while (dest.existsSync()) {
    instance = '${location.instanceFolder}_$n';
    dest = Directory(p.join(destParent.path, instance));
    n++;
  }
  await copyDirectoryStreaming(
    source: verifiedPackage,
    dest: dest,
    chunkSize: chunkSize,
    isCancelled: isCancelled,
  );
  return location.copyWith(instanceFolder: instance);
}
