import 'offline_store.dart';

bool cacheHasLocalJudgeWork(Map<String, dynamic>? local, String? cacheStatus) {
  if (local == null) return false;
  if (cacheStatus == SyncStatuses.pending ||
      cacheStatus == SyncStatuses.failed ||
      cacheStatus == SyncStatuses.syncing) {
    return true;
  }
  if (local['locally_modified'] == true || local['locally_approved'] == true) {
    return true;
  }
  return false;
}

/// دمج مرجع السيرفر مع عمل المحكم المحلي غير المتزامن.
/// النسخة المحلية تفوز للنتائج/الملاحظات/الوسائط.
Map<String, dynamic> mergeServerCacheWithLocal({
  required Map<String, dynamic> server,
  required Map<String, dynamic> local,
  required String? cacheStatus,
}) {
  final merged = Map<String, dynamic>.from(server);
  final hasWork = cacheHasLocalJudgeWork(local, cacheStatus);

  if (local['local_media'] is List && (local['local_media'] as List).isNotEmpty) {
    merged['local_media'] = local['local_media'];
  }

  if (!hasWork) return merged;

  final serverWf = server['workflow'];
  final serverReopened = serverWf is Map && serverWf['reopened'] == true;
  if (serverReopened) {
    merged['locally_approved'] = false;
    merged['locally_modified'] = local['locally_modified'] == true;
    if (local['locally_modified'] == true) {
      _copySavedWork(local, merged);
    }
  } else {
    merged['locally_modified'] = local['locally_modified'] == true;
    merged['locally_approved'] = local['locally_approved'] == true;
    _copySavedWork(local, merged);
  }
  return merged;
}

String mergeResultSyncStatus({
  required Map<String, dynamic> local,
  required Map<String, dynamic> server,
  required String? cacheStatus,
}) {
  final hasWork = cacheHasLocalJudgeWork(local, cacheStatus);
  if (!hasWork) return SyncStatuses.synced;
  final serverWf = server['workflow'];
  final serverReopened = serverWf is Map && serverWf['reopened'] == true;
  if (serverReopened && local['locally_modified'] != true) {
    return SyncStatuses.synced;
  }
  return SyncStatuses.pending;
}

void _copySavedWork(Map<String, dynamic> local, Map<String, dynamic> merged) {
  if (local['saved_payload'] is Map) {
    merged['saved_payload'] = local['saved_payload'];
  }
  if (local['saved_rows'] != null) {
    merged['saved_rows'] = local['saved_rows'];
  }
  if (local['approval_signature'] is Map) {
    merged['approval_signature'] = local['approval_signature'];
  }
}
