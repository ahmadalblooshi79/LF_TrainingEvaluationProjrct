import 'scoped_backup_paths.dart';

const String kPublicExportRootFolder = 'SmartArbitration';
const String kPublicExportDisplayPrefix = 'Download';
const String kPublicExportAttachmentsFolder = 'المرفقات';

class PublicExportLocation {
  final String exerciseFolder;
  final String judgeFolder;
  final String listFolder;

  const PublicExportLocation({
    required this.exerciseFolder,
    required this.judgeFolder,
    required this.listFolder,
  });

  String get relativeDir =>
      '$kPublicExportRootFolder/$exerciseFolder/$judgeFolder/$listFolder';

  String get attachmentsRelativeDir =>
      '$relativeDir/$kPublicExportAttachmentsFolder';

  String get displayPath => '$kPublicExportDisplayPrefix/$relativeDir';
}

bool isSafePublicExportRelativeDir(String relativeDir) {
  if (relativeDir.isEmpty) return false;
  if (relativeDir.startsWith('/') || relativeDir.startsWith('\\')) {
    return false;
  }
  if (relativeDir.contains('\u0000')) return false;
  if (relativeDir.startsWith('SmartArbitration_Backups')) return false;
  if (!relativeDir.startsWith('$kPublicExportRootFolder/')) return false;
  final parts = relativeDir.split('/');
  if (parts.length < 4) return false;
  for (final part in parts) {
    if (part.isEmpty || part == '.' || part == '..') return false;
    if (part.contains('\\') || _unsafe.hasMatch(part)) return false;
  }
  return true;
}

final RegExp _unsafe = RegExp(r'[\/\\:\*\?"<>\|\x00-\x1F\x7F]');

PublicExportLocation buildPublicExportLocation({
  required String exerciseName,
  required int exerciseId,
  required String judgeName,
  required int userId,
  required String listTitle,
  required int listId,
}) {
  return PublicExportLocation(
    exerciseFolder: sanitizeBackupFolderName(
      exerciseName,
      fallback: 'تمرين $exerciseId',
    ),
    judgeFolder: sanitizeBackupFolderName(
      judgeName,
      fallback: 'محكم $userId',
    ),
    listFolder: sanitizeBackupFolderName(
      listTitle,
      fallback: 'قائمة $listId',
    ),
  );
}
