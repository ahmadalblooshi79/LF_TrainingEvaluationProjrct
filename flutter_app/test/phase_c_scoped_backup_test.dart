import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:lf_training_evaluation/services/offline_store.dart';
import 'package:lf_training_evaluation/services/scoped_backup_inventory.dart';
import 'package:lf_training_evaluation/services/scoped_backup_io.dart';
import 'package:lf_training_evaluation/services/scoped_backup_models.dart';
import 'package:lf_training_evaluation/services/scoped_backup_service.dart';
import 'package:lf_training_evaluation/services/sync_service.dart';
import 'package:path/path.dart' as p;

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  final userA = 11;
  final userB = 22;
  final exercise = 100;

  List<Map<String, dynamic>> sampleCache() => [
        {
          'cache_key': 'u$userA:evaluation_list_detail:snipers:1',
          'json_body': jsonEncode({
            'id': 1,
            'exercise_id': exercise,
            'locally_modified': true,
            'notes': 'a-notes',
          }),
          'updated_at': '2026-01-01T00:00:00Z',
          'sync_status': SyncStatuses.pending,
        },
        {
          'cache_key': 'u$userA:action_eval_detail:7',
          'json_body': jsonEncode({
            'id': 7,
            'exercise_id': exercise,
            'locally_approved': true,
          }),
          'updated_at': '2026-01-01T00:00:00Z',
          'sync_status': SyncStatuses.synced,
        },
        {
          'cache_key': 'u$userA:session_bundle',
          'json_body': jsonEncode({
            'reconnect_ticket': 'SECRET-TICKET',
            'user': {'id': userA},
          }),
          'updated_at': '2026-01-01T00:00:00Z',
          'sync_status': SyncStatuses.synced,
        },
        {
          'cache_key': 'u$userB:evaluation_list_detail:snipers:1',
          'json_body': jsonEncode({
            'id': 1,
            'exercise_id': exercise,
            'notes': 'b-notes',
          }),
          'updated_at': '2026-01-01T00:00:00Z',
          'sync_status': SyncStatuses.synced,
        },
        {
          'cache_key': 'u$userA:home',
          'json_body': jsonEncode({'exercise_id': exercise}),
          'updated_at': '2026-01-01T00:00:00Z',
          'sync_status': SyncStatuses.synced,
        },
      ];

  List<Map<String, dynamic>> samplePending() => [
        {
          'id': 'op-a-save',
          'method': 'POST',
          'path': '/api/tablet/results',
          'body': jsonEncode({'client_op_id': 'op-a-save'}),
          'kind': 'eval',
          'op_type': 'save_results',
          'created_at': '2026-01-01T00:00:00Z',
          'attempts': 0,
          'sync_status': SyncStatuses.pending,
          'user_id': userA,
          'exercise_id': exercise,
          'eval_item_id': 1,
        },
        {
          'id': 'op-a-approve',
          'method': 'POST',
          'path': '/api/tablet/approve',
          'body': jsonEncode({'client_op_id': 'op-a-approve'}),
          'kind': 'eval',
          'op_type': 'approve',
          'created_at': '2026-01-01T00:00:00Z',
          'attempts': 0,
          'sync_status': SyncStatuses.pending,
          'user_id': userA,
          'exercise_id': exercise,
          'eval_item_id': 1,
        },
        {
          'id': 'op-b-save',
          'method': 'POST',
          'path': '/api/tablet/results',
          'body': jsonEncode({'client_op_id': 'op-b-save'}),
          'kind': 'eval',
          'op_type': 'save_results',
          'created_at': '2026-01-01T00:00:00Z',
          'attempts': 0,
          'sync_status': SyncStatuses.pending,
          'user_id': userB,
          'exercise_id': exercise,
          'eval_item_id': 1,
        },
        {
          'id': 'op-unknown',
          'method': 'POST',
          'path': '/api/tablet/future',
          'body': jsonEncode({'client_op_id': 'op-unknown'}),
          'kind': 'eval',
          'op_type': 'future_op',
          'created_at': '2026-01-01T00:00:00Z',
          'attempts': 0,
          'sync_status': SyncStatuses.pending,
          'user_id': userA,
          'exercise_id': exercise,
        },
      ];

  List<Map<String, dynamic>> sampleMedia(String pathA, String pathB) => [
        {
          'id': 'media-a',
          'local_path': pathA,
          'user_id': userA,
          'exercise_id': exercise,
          'media_kind': 'video',
          'original_filename': 'clip-a.mp4',
          'sync_status': SyncStatuses.pending,
          'evaluation_list_item_id': 1,
        },
        {
          'id': 'media-b',
          'local_path': pathB,
          'user_id': userB,
          'exercise_id': exercise,
          'media_kind': 'video',
          'original_filename': 'clip-b.mp4',
          'sync_status': SyncStatuses.pending,
          'evaluation_list_item_id': 1,
        },
      ];

  test('1-5 per-user current-exercise isolation', () {
    final cache = selectUserExerciseCache(
      allCache: sampleCache(),
      userId: userA,
      exerciseId: exercise,
    );
    final keys = cache.map((e) => '${e['cache_key']}').toList();
    expect(keys, contains('u11:evaluation_list_detail:snipers:1'));
    expect(keys, contains('u11:action_eval_detail:7'));
    expect(keys, isNot(contains('u22:evaluation_list_detail:snipers:1')));
    expect(keys, isNot(contains('u11:session_bundle')));

    final pending = selectUserExercisePending(
      allPending: samplePending(),
      userId: userA,
      exerciseId: exercise,
    );
    final pids = pending.map((e) => '${e['id']}').toSet();
    expect(pids, containsAll(['op-a-save', 'op-a-approve', 'op-unknown']));
    expect(pids, isNot(contains('op-b-save')));

    final media = selectUserExerciseMedia(
      allMedia: sampleMedia('/a.mp4', '/b.mp4'),
      userId: userA,
      exerciseId: exercise,
      selectedEvalIds: {1, 7},
    );
    expect(media.map((e) => '${e['id']}'), ['media-a']);
  });

  test('2 Device Manager may select one provisioned user; judge cannot', () {
    expect(
      judgeMayBackupUser(
        sessionUserId: userA,
        selectedUserId: userB,
        deviceManager: true,
      ),
      isTrue,
    );
    expect(
      judgeMayBackupUser(
        sessionUserId: userA,
        selectedUserId: userB,
        deviceManager: false,
      ),
      isFalse,
    );
    expect(
      judgeMayBackupUser(
        sessionUserId: userA,
        selectedUserId: userA,
        deviceManager: false,
      ),
      isTrue,
    );
  });

  test('6 authentication secrets excluded', () {
    final cache = selectUserExerciseCache(
      allCache: sampleCache(),
      userId: userA,
      exerciseId: exercise,
    );
    final blob = jsonEncode(cache);
    expect(blob.contains('SECRET-TICKET'), isFalse);
    expect(blob.contains('reconnect_ticket'), isFalse);
    expect(blob.contains('password_hash'), isFalse);
    expect(kScopedBackupExportsAuthSecrets, isFalse);
    expect(
      jsonContainsSecretField({
        'password_hash': 'x',
        'reconnect_ticket': 'y',
        'local_auth_salt_v2': 'z',
      }),
      isTrue,
    );
    expect(
      stripSecretFields({
        'user_id': 1,
        'password_hash': 'no',
        'reconnect_ticket': 'no',
        'username': 'judge',
      }),
      {'user_id': 1, 'username': 'judge'},
    );
  });

  test('identity display never includes hashes', () {
    final id = identityFromLocalUser({
      'user_id': userA,
      'username': 'judge.a',
      'military_number': '123',
      'password_hash': 'HASH',
      'session_json': jsonEncode({
        'user': {'full_name': 'قاضي أ', 'judge_display_name': 'قاضي أ'},
        'reconnect_ticket': 'TICKET',
      }),
    });
    final json = jsonEncode(id.toJson());
    expect(json.contains('HASH'), isFalse);
    expect(json.contains('TICKET'), isFalse);
    expect(id.username, 'judge.a');
    expect(id.displayName, 'قاضي أ');
  });

  test('7-12 backup does not mutate source maps or original media', () async {
    final dir = await Directory.systemTemp.createTemp('phasec-src');
    final src = File(p.join(dir.path, 'orig.bin'));
    await src.writeAsBytes(List<int>.filled(2048, 7));
    final beforeHash = await streamHashFile(src, chunkSize: 512);
    final cache = sampleCache();
    final pending = samplePending();
    final media = sampleMedia(src.path, p.join(dir.path, 'other.bin'));
    await File(media[1]['local_path'] as String).writeAsBytes([1, 2, 3]);
    final cacheFp = fingerprintPayload(cache, ['cache_key', 'json_body', 'sync_status']);
    final pendingFp = fingerprintPayload(pending, ['id', 'op_type', 'sync_status']);
    final mediaFp = fingerprintPayload(media, ['id', 'local_path', 'sync_status']);
    final dest = await Directory.systemTemp.createTemp('phasec-dst');
    final result = await ScopedBackupService.instance.writeBackupPackage(
      destinationParent: dest,
      identity: ScopedBackupIdentity(userId: userA, username: 'a'),
      exercise: ScopedBackupExercise(exerciseId: exercise, name: 'ex'),
      cacheRows: selectUserExerciseCache(
        allCache: cache,
        userId: userA,
        exerciseId: exercise,
      ),
      pendingRows: selectUserExercisePending(
        allPending: pending,
        userId: userA,
        exerciseId: exercise,
      ),
      mediaRows: selectUserExerciseMedia(
        allMedia: media,
        userId: userA,
        exerciseId: exercise,
        selectedEvalIds: {1},
      ),
      freeBytes: 200 * 1024 * 1024,
      chunkSize: 1024,
    );
    expect(result.verified, isTrue);
    expect(fingerprintPayload(cache, ['cache_key', 'json_body', 'sync_status']), cacheFp);
    expect(fingerprintPayload(pending, ['id', 'op_type', 'sync_status']), pendingFp);
    expect(fingerprintPayload(media, ['id', 'local_path', 'sync_status']), mediaFp);
    final afterHash = await streamHashFile(src, chunkSize: 512);
    expect(afterHash.sha256, beforeHash.sha256);
    expect(kScopedBackupDeletesSourceMedia, isFalse);
    expect(kScopedBackupMovesSourceMedia, isFalse);
    expect(kScopedBackupClearsPendingOps, isFalse);
    expect(kScopedBackupClearsMediaFiles, isFalse);
    expect(kScopedBackupClearsLocalUsers, isFalse);
    await dir.delete(recursive: true);
    await dest.delete(recursive: true);
  });

  test('13-14 large file processed with bounded chunks, no full-file read API', () async {
    final dir = await Directory.systemTemp.createTemp('phasec-large');
    final small = File(p.join(dir.path, 'small.bin'));
    final medium = File(p.join(dir.path, 'medium.bin'));
    final large = File(p.join(dir.path, 'large.bin'));
    await small.writeAsBytes([1, 2, 3, 4]);
    await medium.writeAsBytes(List<int>.filled(64 * 1024, 9));
    final sink = large.openWrite();
    final block = Uint8List(64 * 1024);
    for (var i = 0; i < 128; i++) {
      sink.add(block);
    }
    await sink.close();
    const chunk = 64 * 1024;
    final hashed = await streamHashFile(large, chunkSize: chunk);
    expect(hashed.bytes, 8 * 1024 * 1024);
    final dest = File(p.join(dir.path, 'copy.bin'));
    final copied = await streamCopyFile(
      source: large,
      dest: dest,
      expectedSize: hashed.bytes,
      expectedSha256: hashed.sha256,
      chunkSize: chunk,
    );
    expect(copied.sha256, hashed.sha256);
    expect(copied.bytes, hashed.bytes);
    final source = File('lib/services/scoped_backup_io.dart').readAsStringSync();
    expect(source.contains('readAsBytesSync'), isFalse);
    expect(source.contains('ZipEncoder().encode'), isFalse);
    await dir.delete(recursive: true);
  });

  test('15 backup cancellation leaves source unchanged and removes temp output', () async {
    final dir = await Directory.systemTemp.createTemp('phasec-cancel');
    final src = File(p.join(dir.path, 'v.bin'));
    await src.writeAsBytes(List<int>.filled(32 * 1024, 5));
    final dest = await Directory.systemTemp.createTemp('phasec-cancel-out');
    var calls = 0;
    final result = await ScopedBackupService.instance.writeBackupPackage(
      destinationParent: dest,
      identity: ScopedBackupIdentity(userId: userA, username: 'a'),
      exercise: ScopedBackupExercise(exerciseId: exercise),
      cacheRows: const [],
      pendingRows: const [],
      mediaRows: [
        {
          'id': 'media-a',
          'local_path': src.path,
          'user_id': userA,
          'exercise_id': exercise,
          'media_kind': 'video',
          'original_filename': 'v.mp4',
        },
      ],
      freeBytes: 200 * 1024 * 1024,
      chunkSize: 1024,
      isCancelled: () {
        calls++;
        return calls > 2;
      },
    );
    expect(result.status, ScopedBackupStatus.cancelled);
    expect(src.existsSync(), isTrue);
    expect(dir.listSync().whereType<Directory>(), isEmpty);
    final leftover = dest
        .listSync()
        .whereType<Directory>()
        .where((d) => d.path.contains('.inprogress'));
    expect(leftover, isEmpty);
    await dir.delete(recursive: true);
    await dest.delete(recursive: true);
  });

  test('16-17 completed backup reopens verified; failed is not verified', () async {
    final dir = await Directory.systemTemp.createTemp('phasec-ok');
    final src = File(p.join(dir.path, 'p.bin'));
    await src.writeAsBytes([9, 8, 7, 6]);
    final dest = await Directory.systemTemp.createTemp('phasec-ok-out');
    final ok = await ScopedBackupService.instance.writeBackupPackage(
      destinationParent: dest,
      identity: ScopedBackupIdentity(userId: userA, username: 'a'),
      exercise: ScopedBackupExercise(exerciseId: exercise, name: 'ex'),
      cacheRows: selectUserExerciseCache(
        allCache: sampleCache(),
        userId: userA,
        exerciseId: exercise,
      ),
      pendingRows: selectUserExercisePending(
        allPending: samplePending(),
        userId: userA,
        exerciseId: exercise,
      ),
      mediaRows: [
        {
          'id': 'media-a',
          'local_path': src.path,
          'user_id': userA,
          'exercise_id': exercise,
          'media_kind': 'photo',
          'original_filename': 'p.jpg',
        },
      ],
      freeBytes: 200 * 1024 * 1024,
    );
    expect(ok.status, ScopedBackupStatus.verified);
    expect(ok.verified, isTrue);
    final pkg = Directory(ok.packagePath!);
    final issues = await validateBackupPackage(pkg, chunkSize: 1024);
    expect(issues, isEmpty);
    expect(ok.manifest!.completionStatus, 'verified');

    final missing = await ScopedBackupService.instance.writeBackupPackage(
      destinationParent: dest,
      identity: ScopedBackupIdentity(userId: userA, username: 'a'),
      exercise: ScopedBackupExercise(exerciseId: exercise),
      cacheRows: const [],
      pendingRows: const [],
      mediaRows: [
        {
          'id': 'gone',
          'local_path': p.join(dir.path, 'nope.mp4'),
          'user_id': userA,
          'exercise_id': exercise,
          'media_kind': 'video',
          'original_filename': 'nope.mp4',
        },
      ],
      freeBytes: 200 * 1024 * 1024,
    );
    expect(missing.verified, isFalse);
    expect(missing.status, isNot(ScopedBackupStatus.verified));
    await dir.delete(recursive: true);
    await dest.delete(recursive: true);
  });

  test('18 missing media detected', () async {
    final dest = await Directory.systemTemp.createTemp('phasec-miss');
    final result = await ScopedBackupService.instance.writeBackupPackage(
      destinationParent: dest,
      identity: ScopedBackupIdentity(userId: userA, username: 'a'),
      exercise: ScopedBackupExercise(exerciseId: exercise),
      cacheRows: const [],
      pendingRows: const [],
      mediaRows: [
        {
          'id': 'missing',
          'local_path': '/definitely/not/here.mp4',
          'user_id': userA,
          'exercise_id': exercise,
          'media_kind': 'video',
          'original_filename': 'x.mp4',
        },
      ],
      freeBytes: 200 * 1024 * 1024,
    );
    expect(result.status, ScopedBackupStatus.failed);
    expect(result.error, contains('مفقود'));
    await dest.delete(recursive: true);
  });

  test('19 modified media / hash mismatch detected', () async {
    final dir = await Directory.systemTemp.createTemp('phasec-hash');
    final src = File(p.join(dir.path, 'v.bin'));
    await src.writeAsBytes([1, 2, 3, 4, 5, 6, 7, 8]);
    final hashed = await streamHashFile(src, chunkSize: 4);
    await src.writeAsBytes([9, 9, 9, 9, 9, 9, 9, 9]);
    await expectLater(
      streamCopyFile(
        source: src,
        dest: File(p.join(dir.path, 'out.bin')),
        expectedSize: hashed.bytes,
        expectedSha256: hashed.sha256,
        chunkSize: 4,
      ),
      throwsA(isA<ScopedBackupIoException>()),
    );
    expect(src.readAsBytesSync(), [9, 9, 9, 9, 9, 9, 9, 9]);
    await dir.delete(recursive: true);
  });

  test('20-23 corrupt manifest, unsupported format, traversal, absolute path', () async {
    final dir = await Directory.systemTemp.createTemp('phasec-val');
    File(p.join(dir.path, kScopedBackupManifestName)).writeAsStringSync('{not json');
    File(p.join(dir.path, kScopedBackupCompleteName)).writeAsStringSync('x');
    var issues = validateBackupPackageSync(dir);
    expect(issues.any((e) => e.code == 'manifest_corrupt'), isTrue);

    File(p.join(dir.path, kScopedBackupManifestName)).writeAsStringSync(jsonEncode({
      'backup_format_version': 99,
      'schema_version': 4,
      'exercise_id': 1,
      'user_id': 1,
      'completion_status': 'verified',
      'file_inventory': [
        {'relative_path': '../evil', 'size': 1, 'sha256': 'x', 'kind': 'media'},
        {'relative_path': '/data/evil', 'size': 1, 'sha256': 'x', 'kind': 'media'},
      ],
    }));
    issues = validateBackupPackageSync(dir);
    expect(issues.any((e) => e.code == 'unsupported_format'), isTrue);
    expect(issues.any((e) => e.code == 'unsafe_path'), isTrue);
    expect(isSafeRelativeBackupPath('../evil'), isFalse);
    expect(isSafeRelativeBackupPath('/data/data/x'), isFalse);
    expect(isSafeRelativeBackupPath('C:\\Windows\\x'), isFalse);
    expect(isSafeRelativeBackupPath('media/ok.mp4'), isTrue);
    await dir.delete(recursive: true);
  });

  test('24-29 restore preview policy', () {
    final manifest = ScopedBackupManifest(
      backupFormatVersion: 1,
      applicationId: kTabletApplicationId,
      applicationVersion: '2.7.34',
      applicationVersionCode: 48,
      schemaVersion: 4,
      createdAt: 't',
      exercise: ScopedBackupExercise(exerciseId: exercise),
      user: ScopedBackupIdentity(userId: userA, username: 'a'),
      completionStatus: 'verified',
    );
    final backupCache = selectUserExerciseCache(
      allCache: sampleCache(),
      userId: userA,
      exerciseId: exercise,
    );
    final backupPending = selectUserExercisePending(
      allPending: samplePending(),
      userId: userA,
      exerciseId: exercise,
    );

    final wrongEx = ScopedBackupService.instance.buildRestorePreview(
      manifest: manifest,
      validationIssues: const [],
      currentExerciseId: 999,
      selectedUserId: userA,
      userProvisioned: true,
      localCacheByKey: const {},
      localCacheStatus: const {},
      localCacheUpdated: const {},
      existingPendingIds: const {},
      livePendingIds: const {},
      backupCache: backupCache,
      backupPending: backupPending,
      backupMedia: const [],
    );
    expect(wrongEx.canRestore, isFalse);
    expect(wrongEx.blockers.join(), contains('التمرين'));

    final wrongUser = ScopedBackupService.instance.buildRestorePreview(
      manifest: manifest,
      validationIssues: const [],
      currentExerciseId: exercise,
      selectedUserId: userB,
      userProvisioned: true,
      localCacheByKey: const {},
      localCacheStatus: const {},
      localCacheUpdated: const {},
      existingPendingIds: const {},
      livePendingIds: const {},
      backupCache: backupCache,
      backupPending: backupPending,
      backupMedia: const [],
    );
    expect(wrongUser.canRestore, isFalse);
    expect(wrongUser.blockers.join(), contains('المستخدم'));

    final unprovisioned = ScopedBackupService.instance.buildRestorePreview(
      manifest: manifest,
      validationIssues: const [],
      currentExerciseId: exercise,
      selectedUserId: userA,
      userProvisioned: false,
      localCacheByKey: const {},
      localCacheStatus: const {},
      localCacheUpdated: const {},
      existingPendingIds: const {},
      livePendingIds: const {},
      backupCache: const [],
      backupPending: const [],
      backupMedia: const [],
    );
    expect(unprovisioned.canRestore, isFalse);
    expect(unprovisioned.blockers.join(), contains('غير مُهيأ'));

    final unsynced = classifyRestoreCache(
      localBody: {'locally_modified': true, 'notes': 'new'},
      localStatus: SyncStatuses.pending,
      localUpdatedAt: DateTime.parse('2026-02-01T00:00:00Z'),
      backupBody: {'notes': 'old'},
      backupStatus: SyncStatuses.synced,
      backupUpdatedAt: DateTime.parse('2026-01-01T00:00:00Z'),
    );
    expect(unsynced, RestoreConflictClass.localUnsynced);

    final approved = classifyRestoreCache(
      localBody: {'locally_approved': true, 'v': 1},
      localStatus: SyncStatuses.synced,
      localUpdatedAt: DateTime.parse('2026-02-01T00:00:00Z'),
      backupBody: {'v': 0},
      backupStatus: SyncStatuses.synced,
      backupUpdatedAt: DateTime.parse('2026-01-01T00:00:00Z'),
    );
    expect(approved, RestoreConflictClass.localUnsynced);

    final dupPending = ScopedBackupService.instance.buildRestorePreview(
      manifest: manifest,
      validationIssues: const [],
      currentExerciseId: exercise,
      selectedUserId: userA,
      userProvisioned: true,
      localCacheByKey: const {},
      localCacheStatus: const {},
      localCacheUpdated: const {},
      existingPendingIds: {'op-a-save'},
      livePendingIds: const {},
      backupCache: const [],
      backupPending: backupPending,
      backupMedia: const [],
    );
    expect(
      dupPending.items.where((e) => e.id == 'op-a-save').first.detail,
      'exists',
    );
    expect(
      dupPending.warnings.any((w) => w.startsWith('unknown_op_type:future_op')),
      isTrue,
    );
    expect(dupPending.items.any((e) => e.id == 'op-unknown'), isTrue);
  });

  test('30-32 media copy verifies hash; failed copy rolls back dest only', () async {
    final dir = await Directory.systemTemp.createTemp('phasec-media');
    final src = File(p.join(dir.path, 'ok.bin'));
    await src.writeAsBytes([10, 11, 12, 13]);
    final hashed = await streamHashFile(src, chunkSize: 2);
    final dest = File(p.join(dir.path, 'dest.bin'));
    await streamCopyFile(
      source: src,
      dest: dest,
      expectedSize: hashed.bytes,
      expectedSha256: hashed.sha256,
      chunkSize: 2,
    );
    expect(await streamHashFile(dest, chunkSize: 2), predicate<StreamHashResult>(
      (r) => r.sha256 == hashed.sha256,
    ));
    final badDest = File(p.join(dir.path, 'bad.bin'));
    await expectLater(
      streamCopyFile(
        source: src,
        dest: badDest,
        expectedSize: hashed.bytes,
        expectedSha256: 'deadbeef',
        chunkSize: 2,
      ),
      throwsA(isA<ScopedBackupIoException>()),
    );
    expect(src.existsSync(), isTrue);
    expect(badDest.existsSync(), isFalse);
    await dir.delete(recursive: true);
  });

  test('33-37 restore safety flags and locally_* semantics', () {
    expect(kScopedRestoreUsesClearAll, isFalse);
    expect(kScopedRestoreReplacesDatabaseFile, isFalse);
    expect(OfflineStore.databaseSchemaVersion, 4);
    final keepModified = classifyRestoreCache(
      localBody: {'locally_modified': true, 'score': 1},
      localStatus: SyncStatuses.failed,
      localUpdatedAt: DateTime.parse('2026-03-01T00:00:00Z'),
      backupBody: {'locally_modified': false, 'score': 9},
      backupStatus: SyncStatuses.synced,
      backupUpdatedAt: DateTime.parse('2026-04-01T00:00:00Z'),
    );
    expect(keepModified, RestoreConflictClass.localUnsynced);
    final keepApproved = classifyRestoreCache(
      localBody: {'locally_approved': true},
      localStatus: SyncStatuses.syncing,
      localUpdatedAt: DateTime.parse('2026-03-01T00:00:00Z'),
      backupBody: {'locally_approved': false},
      backupStatus: SyncStatuses.synced,
      backupUpdatedAt: DateTime.parse('2026-04-01T00:00:00Z'),
    );
    expect(keepApproved, RestoreConflictClass.localUnsynced);
  });

  test('38-39 Phase B reconnect hold during restore', () {
    addTearDown(() {
      while (SyncService.instance.isRestoreHeld) {
        SyncService.instance.endRestoreHold();
      }
    });
    expect(SyncService.instance.isRestoreHeld, isFalse);
    SyncService.instance.beginRestoreHold();
    expect(SyncService.instance.isRestoreHeld, isTrue);
    SyncService.instance.beginRestoreHold();
    expect(SyncService.instance.isRestoreHeld, isTrue);
    SyncService.instance.endRestoreHold();
    expect(SyncService.instance.isRestoreHeld, isTrue);
    SyncService.instance.endRestoreHold();
    expect(SyncService.instance.isRestoreHeld, isFalse);
  });

  test('40-42 schema, applicationId, older builds remain readable', () {
    expect(OfflineStore.databaseSchemaVersion, 4);
    expect(kTabletApplicationId, 'ae.lf.training.lf_training_evaluation');
    expect(kScopedBackupFormatVersion, 1);
    expect(kScopedBackupSupportedSchema, 4);
    final m = ScopedBackupManifest.fromJson({
      'backup_format_version': 1,
      'application_version': '2.7.31',
      'application_version_code': 45,
      'schema_version': 4,
      'exercise_id': 3,
      'user_id': 8,
      'completion_status': 'verified',
      'file_inventory': [],
    });
    expect(m.schemaVersion, 4);
    expect(m.backupFormatVersion, 1);
  });

  test('insufficient space blocks before copy', () async {
    final dest = await Directory.systemTemp.createTemp('phasec-space');
    final dir = await Directory.systemTemp.createTemp('phasec-space-src');
    final src = File(p.join(dir.path, 'v.bin'));
    await src.writeAsBytes(List<int>.filled(4096, 1));
    final result = await ScopedBackupService.instance.writeBackupPackage(
      destinationParent: dest,
      identity: ScopedBackupIdentity(userId: userA, username: 'a'),
      exercise: ScopedBackupExercise(exerciseId: exercise),
      cacheRows: const [],
      pendingRows: const [],
      mediaRows: [
        {
          'id': 'media-a',
          'local_path': src.path,
          'user_id': userA,
          'exercise_id': exercise,
          'media_kind': 'video',
          'original_filename': 'v.mp4',
        },
      ],
      freeBytes: 1024,
    );
    expect(result.status, ScopedBackupStatus.failed);
    expect(result.error, contains('مساحة'));
    expect(dest.listSync(), isEmpty);
    await dest.delete(recursive: true);
    await dir.delete(recursive: true);
  });

  test('C.1 bulk cache query does not select json_body', () {
    expect(OfflineStore.backupCacheMetadataColumns.contains('json_body'), isFalse);
    expect(OfflineStore.backupPendingIdColumns.contains('body'), isFalse);
    expect(OfflineStore.backupMediaMetadataColumns.contains('json_body'), isFalse);
    final src = File('lib/services/scoped_backup_service.dart').readAsStringSync();
    final createFn = src.split('createBackupForUser')[1].split('File? signature')[0];
    expect(createFn.contains('recoverySelectCache()'), isFalse);
    expect(createFn.contains('recoverySelectPendingOps()'), isFalse);
    expect(createFn.contains('recoverySelectMedia()'), isFalse);
    expect(createFn.contains('backupSelectScopedCacheForUser'), isTrue);
    expect(createFn.contains('backupSelectPendingForUserExercise'), isTrue);
    expect(createFn.contains('backupSelectMediaMetadataForUserExercise'), isTrue);
  });

  Future<void> _backupStreamingSize(int bytes, String name) async {
    scopedBackupMaxObservedChunk = 0;
    final dir = await Directory.systemTemp.createTemp('phasec1-$name');
    final src = File(p.join(dir.path, '$name.bin'));
    final sink = src.openWrite();
    const blockSize = 64 * 1024;
    final block = Uint8List(blockSize);
    for (var i = 0; i < block.length; i++) {
      block[i] = (i + bytes) & 0xFF;
    }
    var left = bytes;
    while (left > 0) {
      final n = left < blockSize ? left : blockSize;
      sink.add(n == blockSize ? block : block.sublist(0, n));
      left -= n;
    }
    await sink.close();
    final before = await streamHashFile(src, chunkSize: blockSize);
    expect(before.bytes, bytes);
    final dest = await Directory.systemTemp.createTemp('phasec1-$name-out');
    const chunk = 256 * 1024;
    scopedBackupMaxObservedChunk = 0;
    final result = await ScopedBackupService.instance.writeBackupPackage(
      destinationParent: dest,
      identity: ScopedBackupIdentity(userId: userA, username: 'a'),
      exercise: ScopedBackupExercise(exerciseId: exercise, name: 'ex'),
      cacheRows: const [],
      pendingRows: const [],
      mediaRows: [
        {
          'id': 'media-$name',
          'local_path': src.path,
          'user_id': userA,
          'exercise_id': exercise,
          'media_kind': 'video',
          'original_filename': '$name.mp4',
        },
      ],
      freeBytes: bytes + 200 * 1024 * 1024,
      chunkSize: chunk,
    );
    expect(result.verified, isTrue, reason: name);
    expect(result.status, ScopedBackupStatus.verified);
    final after = await streamHashFile(src, chunkSize: blockSize);
    expect(after.sha256, before.sha256);
    expect(after.bytes, bytes);
    expect(scopedBackupMaxObservedChunk, lessThanOrEqualTo(chunk * 4));
    expect(scopedBackupMaxObservedChunk, greaterThan(0));
    expect(scopedBackupMaxObservedChunk, lessThan(bytes));
    await dir.delete(recursive: true);
    await dest.delete(recursive: true);
  }

  test('C.1 A 8 MB media streaming backup', () async {
    await _backupStreamingSize(8 * 1024 * 1024, '8mb');
  });

  test('C.1 B 64 MB media streaming backup', () async {
    await _backupStreamingSize(64 * 1024 * 1024, '64mb');
  }, timeout: const Timeout(Duration(minutes: 2)));

  test('C.1 C 256 MB media streaming backup', () async {
    await _backupStreamingSize(256 * 1024 * 1024, '256mb');
  }, timeout: const Timeout(Duration(minutes: 4)));
}
