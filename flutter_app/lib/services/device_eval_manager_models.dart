import '../models/eval_sheet.dart';
import '../models/list_row.dart';
import 'scoped_backup_inventory.dart';
import 'scoped_backup_paths.dart';

const String kDeviceEvalManagerTitle = 'إدارة قوائم التقييم';
const String kDeviceEvalUserLabel = 'المحكم / المستخدم';
const String kDeviceEvalUserSearchHint = 'البحث عن المستخدم بالاسم';
const String kDeviceEvalProcedureTab = 'قوائم تقييم الإجراءات';
const String kDeviceEvalDilemmaTab = 'قوائم تقييم المعاضل';
const String kDeviceEvalMissingUserData = 'بيانات هذا المستخدم غير متوفرة على الجهاز';
const String kDeviceEvalEmptyLists = 'لا توجد قوائم لهذا المستخدم';
const String kDeviceEvalNeedsServer = 'يتطلب هذا الإجراء الاتصال بالسيرفر';
const String kDeviceEvalReopenNeedsServer =
    'يتطلب إعادة فتح القائمة الاتصال بالسيرفر';
const String kDeviceEvalReopenLocalOk = 'تم إعادة فتح القائمة على الجهاز';
const String kDeviceEvalDownloadFailed = 'تعذر تنزيل الملف';
const String kDeviceEvalDownloadOk = 'تم تنزيل القائمة بنجاح';
const String kDeviceEvalExcelOffline =
    'تنزيل Excel غير متوفر على الجهاز ويتطلب الاتصال بالسيرفر';
const String kDeviceEvalExcelUnsupported =
    'لا يوجد ملف Excel أصلي لهذه القائمة على الجهاز';
const String kDeviceEvalReopenStatus = 'معاد للتقييم';

enum DeviceEvalKind { procedure, dilemma }

class DeviceEvalUser {
  final int userId;
  final String username;
  final String displayName;

  const DeviceEvalUser({
    required this.userId,
    required this.username,
    required this.displayName,
  });

  String get label {
    final name = displayName.trim();
    final user = username.trim();
    return [
      if (name.isNotEmpty) name,
      if (user.isNotEmpty) user,
      'رقم $userId',
    ].join(' — ');
  }

  Map<String, dynamic> toJson() => {
        'user_id': userId,
        'username': username,
        'display_name': displayName,
      };

  factory DeviceEvalUser.fromLocalRow(Map<String, dynamic> row) {
    return DeviceEvalUser(
      userId: rowAsInt(row['user_id']) ?? 0,
      username: '${row['username'] ?? ''}',
      displayName: '${row['display_name'] ?? ''}',
    );
  }
}

class DeviceEvalListSummary {
  final DeviceEvalKind kind;
  final int userId;
  final int exerciseId;
  final int listId;
  final String unitKey;
  final String unitLabel;
  final String phaseKey;
  final String title;
  final String statusLabel;
  final String workflowLabel;
  final String? lastUpdated;
  final int imageCount;
  final int videoCount;

  const DeviceEvalListSummary({
    required this.kind,
    required this.userId,
    required this.exerciseId,
    required this.listId,
    required this.unitKey,
    required this.unitLabel,
    required this.phaseKey,
    required this.title,
    required this.statusLabel,
    this.workflowLabel = '',
    this.lastUpdated,
    this.imageCount = 0,
    this.videoCount = 0,
  });

  bool get isApproved {
    final s = statusLabel.trim();
    if (s.contains('بإنتظار') || s.contains('بانتظار') || s.contains('معاد')) {
      return false;
    }
    return s == 'معتمد' || s == 'منجز' || s == 'ينجز';
  }

  bool get canOfferReopen => isApproved && !workflowLabel.contains('معاد');
}

class DeviceEvalMediaRef {
  final String id;
  final int userId;
  final int exerciseId;
  final int? evaluationListItemId;
  final int? bundleActionEvalId;
  final String mediaKind;
  final String localPath;
  final String originalFilename;
  final String localFilename;
  final int rowIndex;
  final int fileSize;
  final String? sheetCacheKey;

  const DeviceEvalMediaRef({
    required this.id,
    required this.userId,
    required this.exerciseId,
    this.evaluationListItemId,
    this.bundleActionEvalId,
    required this.mediaKind,
    required this.localPath,
    required this.originalFilename,
    required this.localFilename,
    required this.rowIndex,
    this.fileSize = 0,
    this.sheetCacheKey,
  });

  bool get isVideo {
    final k = mediaKind.toLowerCase();
    return k.contains('video') || k.contains('فيديو');
  }

  String get downloadName {
    final orig = originalFilename.trim();
    if (orig.isNotEmpty) return orig;
    final local = localFilename.trim();
    if (local.isNotEmpty) return local;
    final pathName = localPath.replaceAll('\\', '/').split('/').last;
    if (pathName.isNotEmpty) return pathName;
    return isVideo ? 'video_$id.mp4' : 'image_$id.jpg';
  }

  factory DeviceEvalMediaRef.fromRow(Map<String, dynamic> row) {
    return DeviceEvalMediaRef(
      id: '${row['id'] ?? ''}',
      userId: rowAsInt(row['user_id']) ?? 0,
      exerciseId: rowAsInt(row['exercise_id']) ?? 0,
      evaluationListItemId: rowAsInt(row['evaluation_list_item_id']),
      bundleActionEvalId: rowAsInt(row['bundle_action_eval_id']),
      mediaKind: '${row['media_kind'] ?? 'photo'}',
      localPath: '${row['local_path'] ?? ''}',
      originalFilename: '${row['original_filename'] ?? ''}',
      localFilename: '${row['local_filename'] ?? ''}',
      rowIndex: rowAsInt(row['row_index']) ?? 0,
      fileSize: rowAsInt(row['file_size']) ?? 0,
      sheetCacheKey: row['sheet_cache_key']?.toString(),
    );
  }
}

class DeviceEvalListsLoad {
  final bool dataAvailable;
  final List<DeviceEvalListSummary> lists;

  const DeviceEvalListsLoad({
    required this.dataAvailable,
    required this.lists,
  });

  String get emptyMessage =>
      dataAvailable ? kDeviceEvalEmptyLists : kDeviceEvalMissingUserData;
}

bool deviceManagerUserMatches(Map<String, dynamic> user, String query) {
  final q = normalizeUserSearchQuery(query);
  if (q.isEmpty) return true;
  final needle = q.toLowerCase();
  final name = '${user['display_name'] ?? ''}'.toLowerCase();
  final username = '${user['username'] ?? ''}'.toLowerCase();
  return name.contains(needle) || username.contains(needle);
}

List<Map<String, dynamic>> filterDeviceManagerUsers(
  List<Map<String, dynamic>> users,
  String query,
) {
  final q = normalizeUserSearchQuery(query);
  if (q.isEmpty) return List<Map<String, dynamic>>.from(users);
  return [
    for (final user in users)
      if (deviceManagerUserMatches(user, q)) user,
  ];
}

bool cacheKeyIsProcedureLists(String bare) {
  return bare == 'evaluation_lists::' ||
      bare == 'evaluation_lists' ||
      bare.startsWith('evaluation_lists:');
}

bool cacheKeyIsDilemmaLists(String bare) {
  return bare == 'action_eval_lists:' ||
      bare == 'action_eval_lists' ||
      bare.startsWith('action_eval_lists:');
}

bool cacheKeyIsProcedureDetail(String bare) {
  return bare.startsWith('evaluation_list_detail:');
}

bool cacheKeyIsDilemmaDetail(String bare) {
  return bare.startsWith('action_eval_detail:');
}

bool userHasLocalListCache({
  required Iterable<String> cacheKeys,
  required int userId,
  required DeviceEvalKind kind,
}) {
  for (final key in cacheKeys) {
    if (cacheKeyUserId(key) != userId) continue;
    final bare = cacheKeyBare(key);
    if (kind == DeviceEvalKind.procedure &&
        (cacheKeyIsProcedureLists(bare) || cacheKeyIsProcedureDetail(bare))) {
      return true;
    }
    if (kind == DeviceEvalKind.dilemma &&
        (cacheKeyIsDilemmaLists(bare) || cacheKeyIsDilemmaDetail(bare))) {
      return true;
    }
  }
  return false;
}

int? payloadExerciseId(Map<String, dynamic> payload) {
  return rowAsInt(payload['exercise_id'] ?? payload['exerciseId']);
}

bool payloadMatchesExercise(Map<String, dynamic> payload, int exerciseId) {
  final id = payloadExerciseId(payload);
  if (id == null || id == 0) return true;
  return id == exerciseId;
}

List<ListRow> listRowsFromPayload(Map<String, dynamic> payload) {
  final raw = payload['lists'] ?? payload['rows'];
  if (raw is! List) return const [];
  return [
    for (final item in raw)
      if (item is Map)
        ListRow.fromJson(Map<String, dynamic>.from(item)),
  ];
}

int stableListId(ListRow row, DeviceEvalKind kind) {
  if (kind == DeviceEvalKind.procedure) {
    return row.itemId ?? rowAsInt(row.id) ?? 0;
  }
  return row.slotId ?? row.slotIndex ?? rowAsInt(row.id) ?? 0;
}

List<DeviceEvalListSummary> summariesFromListPayload({
  required Map<String, dynamic> payload,
  required DeviceEvalKind kind,
  required int userId,
  required int exerciseId,
  String? cacheUpdatedAt,
}) {
  if (!payloadMatchesExercise(payload, exerciseId)) return const [];
  final out = <DeviceEvalListSummary>[];
  final seen = <int>{};
  for (final row in listRowsFromPayload(payload)) {
    final id = stableListId(row, kind);
    if (id <= 0 || !seen.add(id)) continue;
    out.add(
      DeviceEvalListSummary(
        kind: kind,
        userId: userId,
        exerciseId: exerciseId,
        listId: id,
        unitKey: row.unitKey,
        unitLabel: row.unitLabel,
        phaseKey: row.phaseKey,
        title: row.title.trim().isEmpty ? 'قائمة $id' : row.title,
        statusLabel: row.statusLabel,
        workflowLabel: row.displayDispatch,
        lastUpdated: _reliableTimestamp(row.date, cacheUpdatedAt),
      ),
    );
  }
  return out;
}

String? _reliableTimestamp(String date, String? updatedAt) {
  final d = date.trim();
  if (d.isNotEmpty) return d;
  final u = (updatedAt ?? '').trim();
  if (u.isNotEmpty) return u;
  return null;
}

bool mediaBelongsToList({
  required DeviceEvalMediaRef media,
  required DeviceEvalKind kind,
  required int userId,
  required int exerciseId,
  required int listId,
}) {
  if (media.userId != userId) return false;
  if (media.exerciseId != 0 && media.exerciseId != exerciseId) return false;
  if (kind == DeviceEvalKind.procedure) {
    return media.evaluationListItemId != null &&
        media.evaluationListItemId == listId;
  }
  return media.bundleActionEvalId != null && media.bundleActionEvalId == listId;
}

List<DeviceEvalMediaRef> mediaForManagedList({
  required Iterable<DeviceEvalMediaRef> all,
  required DeviceEvalKind kind,
  required int userId,
  required int exerciseId,
  required int listId,
}) {
  return [
    for (final m in all)
      if (mediaBelongsToList(
        media: m,
        kind: kind,
        userId: userId,
        exerciseId: exerciseId,
        listId: listId,
      ))
        m,
  ];
}

({int images, int videos}) mediaCounts(Iterable<DeviceEvalMediaRef> media) {
  var images = 0;
  var videos = 0;
  for (final m in media) {
    if (m.isVideo) {
      videos += 1;
    } else {
      images += 1;
    }
  }
  return (images: images, videos: videos);
}

EvalSheetDetail inspectOnlyDetail(EvalSheetDetail detail) {
  return detail.copyWith(canEdit: false, canApprove: false);
}

Map<String, dynamic> applyLocalReopenToDetail(Map<String, dynamic> cached) {
  final next = Map<String, dynamic>.from(cached);
  next['can_edit'] = true;
  next['can_approve'] = true;
  next['is_approved'] = false;
  next['locally_approved'] = false;
  next['status_label'] = kDeviceEvalReopenStatus;
  next['device_manager_reopened'] = true;
  next['workflow'] = {
    'label': kDeviceEvalReopenStatus,
    'reopened': true,
  };
  return next;
}

bool inspectOpenMutatesDetail(EvalSheetDetail before, EvalSheetDetail after) {
  return before.canEdit != after.canEdit ||
      before.canApprove != after.canApprove ||
      before.isApproved != after.isApproved ||
      before.savedRows.length != after.savedRows.length;
}

String uniqueDownloadFileName(String name, Set<String> existing) {
  var safe = name.trim();
  if (safe.isEmpty) safe = 'file';
  safe = safe.replaceAll(RegExp(r'[\/\\:\*\?"<>\|\x00-\x1F\x7F]'), '_');
  if (!existing.contains(safe.toLowerCase())) {
    existing.add(safe.toLowerCase());
    return safe;
  }
  final dot = safe.lastIndexOf('.');
  final stem = dot > 0 ? safe.substring(0, dot) : safe;
  final ext = dot > 0 ? safe.substring(dot) : '';
  var i = 2;
  while (existing.contains('${stem}_$i$ext'.toLowerCase())) {
    i++;
  }
  final out = '${stem}_$i$ext';
  existing.add(out.toLowerCase());
  return out;
}

String reopenOfflineMessage({required bool online}) {
  // إعادة الفتح محلية على الجهاز ولا تتطلب السيرفر.
  return '';
}

bool reopenButtonVisible({
  required bool approved,
  required bool inspectOnly,
}) {
  return inspectOnly && approved;
}
