const int kScopedBackupFormatVersion = 1;
const int kScopedBackupSupportedSchema = 4;
const String kTabletApplicationId = 'ae.lf.training.lf_training_evaluation';
const String kScopedBackupManifestName = 'backup_manifest.json';
const String kScopedBackupCompleteName = 'BACKUP_COMPLETE';
const int kScopedBackupChunkSize = 1024 * 1024;
const int kScopedBackupOverheadBytes = 64 * 1024 * 1024;

const bool kScopedRestoreUsesClearAll = false;
const bool kScopedRestoreReplacesDatabaseFile = false;
const bool kScopedBackupDeletesSourceMedia = false;
const bool kScopedBackupMovesSourceMedia = false;
const bool kScopedBackupClearsPendingOps = false;
const bool kScopedBackupClearsMediaFiles = false;
const bool kScopedBackupClearsLocalUsers = false;
const bool kScopedBackupExportsAuthSecrets = false;

const Set<String> kKnownPendingOpTypes = {
  'save_results',
  'approve',
  'media_upload',
  'polarity_notes_bulk',
  'polarity_note_save',
  'polarity_note_delete',
  'save_signature',
};

enum ScopedBackupStatus {
  idle,
  creating,
  created,
  verifying,
  verified,
  failed,
  cancelled,
  corrupt,
}

enum RestoreConflictClass {
  missingLocally,
  same,
  backupOlder,
  backupNewer,
  localUnsynced,
  conflict,
}

class ScopedBackupProgress {
  final String stage;
  final String currentFile;
  final int bytesProcessed;
  final int totalBytes;
  final int percent;

  const ScopedBackupProgress({
    required this.stage,
    this.currentFile = '',
    this.bytesProcessed = 0,
    this.totalBytes = 0,
    this.percent = 0,
  });
}

class ScopedBackupFileEntry {
  final String relativePath;
  final int size;
  final String sha256;
  final String kind;
  final int? evaluationListId;
  final String? evaluationType;
  final int? exerciseId;
  final int? userId;
  final String? displayName;
  final int? evaluationItemId;
  final String? mediaId;
  final String? mediaType;
  final String? sourceLocalPath;

  const ScopedBackupFileEntry({
    required this.relativePath,
    required this.size,
    required this.sha256,
    required this.kind,
    this.evaluationListId,
    this.evaluationType,
    this.exerciseId,
    this.userId,
    this.displayName,
    this.evaluationItemId,
    this.mediaId,
    this.mediaType,
    this.sourceLocalPath,
  });

  Map<String, dynamic> toJson() => {
        'relative_path': relativePath,
        'size': size,
        'sha256': sha256,
        'kind': kind,
        if (evaluationListId != null) 'evaluation_list_id': evaluationListId,
        if (evaluationType != null && evaluationType!.isNotEmpty)
          'evaluation_type': evaluationType,
        if (exerciseId != null) 'exercise_id': exerciseId,
        if (userId != null) 'user_id': userId,
        if (displayName != null && displayName!.isNotEmpty)
          'display_name': displayName,
        if (evaluationItemId != null) 'evaluation_item_id': evaluationItemId,
        if (mediaId != null && mediaId!.isNotEmpty) 'media_id': mediaId,
        if (mediaType != null && mediaType!.isNotEmpty) 'media_type': mediaType,
        if (sourceLocalPath != null && sourceLocalPath!.isNotEmpty)
          'source_local_path': sourceLocalPath,
      };

  factory ScopedBackupFileEntry.fromJson(Map<String, dynamic> json) {
    return ScopedBackupFileEntry(
      relativePath: '${json['relative_path'] ?? ''}',
      size: _asInt(json['size']),
      sha256: '${json['sha256'] ?? ''}',
      kind: '${json['kind'] ?? ''}',
      evaluationListId: json['evaluation_list_id'] == null
          ? null
          : _asInt(json['evaluation_list_id']),
      evaluationType: json['evaluation_type']?.toString(),
      exerciseId: json['exercise_id'] == null ? null : _asInt(json['exercise_id']),
      userId: json['user_id'] == null ? null : _asInt(json['user_id']),
      displayName: json['display_name']?.toString(),
      evaluationItemId: json['evaluation_item_id'] == null
          ? null
          : _asInt(json['evaluation_item_id']),
      mediaId: json['media_id']?.toString(),
      mediaType: json['media_type']?.toString(),
      sourceLocalPath: json['source_local_path']?.toString(),
    );
  }
}

class ScopedBackupIdentity {
  final int userId;
  final String username;
  final String militaryNumber;
  final String displayName;

  const ScopedBackupIdentity({
    required this.userId,
    required this.username,
    this.militaryNumber = '',
    this.displayName = '',
  });

  Map<String, dynamic> toJson() => {
        'user_id': userId,
        'username': username,
        'military_number': militaryNumber,
        'display_name': displayName,
      };

  factory ScopedBackupIdentity.fromJson(Map<String, dynamic> json) {
    return ScopedBackupIdentity(
      userId: _asInt(json['user_id']),
      username: '${json['username'] ?? ''}',
      militaryNumber: '${json['military_number'] ?? ''}',
      displayName: '${json['display_name'] ?? ''}',
    );
  }
}

class ScopedBackupExercise {
  final int exerciseId;
  final String name;
  final String code;

  const ScopedBackupExercise({
    required this.exerciseId,
    this.name = '',
    this.code = '',
  });

  Map<String, dynamic> toJson() => {
        'exercise_id': exerciseId,
        'exercise_name': name,
        'exercise_code': code,
      };

  factory ScopedBackupExercise.fromJson(Map<String, dynamic> json) {
    return ScopedBackupExercise(
      exerciseId: _asInt(json['exercise_id'] ?? json['id']),
      name: '${json['exercise_name'] ?? json['name'] ?? ''}',
      code: '${json['exercise_code'] ?? json['code'] ?? ''}',
    );
  }
}

class ScopedBackupManifest {
  final int backupFormatVersion;
  final String applicationId;
  final String applicationVersion;
  final int applicationVersionCode;
  final int schemaVersion;
  final String createdAt;
  final ScopedBackupExercise exercise;
  final ScopedBackupIdentity user;
  final String deviceId;
  final Map<String, int> recordCounts;
  final Map<String, int> pendingCountsByStatus;
  final int mediaCount;
  final int totalMediaBytes;
  final List<ScopedBackupFileEntry> fileInventory;
  final String completionStatus;
  final String? verifiedAt;
  final List<String> warnings;

  const ScopedBackupManifest({
    required this.backupFormatVersion,
    required this.applicationId,
    required this.applicationVersion,
    required this.applicationVersionCode,
    required this.schemaVersion,
    required this.createdAt,
    required this.exercise,
    required this.user,
    this.deviceId = '',
    this.recordCounts = const {},
    this.pendingCountsByStatus = const {},
    this.mediaCount = 0,
    this.totalMediaBytes = 0,
    this.fileInventory = const [],
    this.completionStatus = 'writing',
    this.verifiedAt,
    this.warnings = const [],
  });

  Map<String, dynamic> toJson() => {
        'backup_format_version': backupFormatVersion,
        'application_id': applicationId,
        'application_version': applicationVersion,
        'application_version_code': applicationVersionCode,
        'schema_version': schemaVersion,
        'created_at': createdAt,
        'exercise_id': exercise.exerciseId,
        'exercise_name': exercise.name,
        'exercise_code': exercise.code,
        'user_id': user.userId,
        'username': user.username,
        'military_number': user.militaryNumber,
        'display_name': user.displayName,
        'device_id': deviceId,
        'record_counts': recordCounts,
        'pending_operation_counts_by_status': pendingCountsByStatus,
        'media_counts': mediaCount,
        'total_media_bytes': totalMediaBytes,
        'file_inventory': fileInventory.map((e) => e.toJson()).toList(),
        'completion_status': completionStatus,
        if (verifiedAt != null) 'verified_at': verifiedAt,
        if (warnings.isNotEmpty) 'warnings': warnings,
      };

  factory ScopedBackupManifest.fromJson(Map<String, dynamic> json) {
    final inventoryRaw = json['file_inventory'];
    final inventory = <ScopedBackupFileEntry>[];
    if (inventoryRaw is List) {
      for (final e in inventoryRaw) {
        if (e is Map) {
          inventory.add(
            ScopedBackupFileEntry.fromJson(Map<String, dynamic>.from(e)),
          );
        }
      }
    }
    Map<String, int> asIntMap(dynamic raw) {
      if (raw is! Map) return {};
      return raw.map((k, v) => MapEntry('$k', _asInt(v)));
    }

    return ScopedBackupManifest(
      backupFormatVersion: _asInt(json['backup_format_version']),
      applicationId: '${json['application_id'] ?? ''}',
      applicationVersion: '${json['application_version'] ?? ''}',
      applicationVersionCode: _asInt(json['application_version_code']),
      schemaVersion: _asInt(json['schema_version']),
      createdAt: '${json['created_at'] ?? ''}',
      exercise: ScopedBackupExercise(
        exerciseId: _asInt(json['exercise_id']),
        name: '${json['exercise_name'] ?? ''}',
        code: '${json['exercise_code'] ?? ''}',
      ),
      user: ScopedBackupIdentity(
        userId: _asInt(json['user_id']),
        username: '${json['username'] ?? ''}',
        militaryNumber: '${json['military_number'] ?? ''}',
        displayName: '${json['display_name'] ?? ''}',
      ),
      deviceId: '${json['device_id'] ?? ''}',
      recordCounts: asIntMap(json['record_counts']),
      pendingCountsByStatus: asIntMap(json['pending_operation_counts_by_status']),
      mediaCount: _asInt(json['media_counts'] ?? json['media_count']),
      totalMediaBytes: _asInt(json['total_media_bytes']),
      fileInventory: inventory,
      completionStatus: '${json['completion_status'] ?? ''}',
      verifiedAt: json['verified_at']?.toString(),
      warnings: json['warnings'] is List
          ? (json['warnings'] as List).map((e) => '$e').toList()
          : const [],
    );
  }

  ScopedBackupManifest copyWith({
    String? completionStatus,
    String? verifiedAt,
    List<ScopedBackupFileEntry>? fileInventory,
    List<String>? warnings,
  }) {
    return ScopedBackupManifest(
      backupFormatVersion: backupFormatVersion,
      applicationId: applicationId,
      applicationVersion: applicationVersion,
      applicationVersionCode: applicationVersionCode,
      schemaVersion: schemaVersion,
      createdAt: createdAt,
      exercise: exercise,
      user: user,
      deviceId: deviceId,
      recordCounts: recordCounts,
      pendingCountsByStatus: pendingCountsByStatus,
      mediaCount: mediaCount,
      totalMediaBytes: totalMediaBytes,
      fileInventory: fileInventory ?? this.fileInventory,
      completionStatus: completionStatus ?? this.completionStatus,
      verifiedAt: verifiedAt ?? this.verifiedAt,
      warnings: warnings ?? this.warnings,
    );
  }
}

class RestorePreviewItem {
  final String kind;
  final String id;
  final RestoreConflictClass classification;
  final String detail;

  const RestorePreviewItem({
    required this.kind,
    required this.id,
    required this.classification,
    this.detail = '',
  });
}

class RestorePreview {
  final ScopedBackupManifest manifest;
  final List<RestorePreviewItem> items;
  final List<String> blockers;
  final List<String> warnings;
  final bool canRestore;

  const RestorePreview({
    required this.manifest,
    this.items = const [],
    this.blockers = const [],
    this.warnings = const [],
    required this.canRestore,
  });
}

int _asInt(dynamic raw) {
  if (raw is int) return raw;
  if (raw is num) return raw.toInt();
  return int.tryParse('$raw'.trim()) ?? 0;
}
