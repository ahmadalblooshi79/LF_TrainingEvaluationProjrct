import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lf_training_evaluation/screens/scoped_backup_screen.dart';
import 'package:lf_training_evaluation/services/offline_store.dart';
import 'package:lf_training_evaluation/services/scoped_backup_io.dart';
import 'package:lf_training_evaluation/services/scoped_backup_models.dart';
import 'package:lf_training_evaluation/services/scoped_backup_paths.dart';
import 'package:lf_training_evaluation/services/scoped_backup_service.dart';
import 'package:path/path.dart' as p;

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  const exerciseId = 100;
  const userA = 27;
  const userB = 28;

  final exercise = ScopedBackupExercise(
    exerciseId: exerciseId,
    name: 'تمرين رياح الصحراء',
  );
  final identityA = ScopedBackupIdentity(
    userId: userA,
    username: 'judge.a',
    displayName: 'أحمد البلوشي',
  );
  final identityDup = ScopedBackupIdentity(
    userId: userB,
    username: 'judge.b',
    displayName: 'أحمد البلوشي',
  );

  List<Map<String, dynamic>> sampleUsers() => [
        {
          'user_id': userA,
          'username': 'judge.a',
          'display_name': 'أحمد البلوشي',
        },
        {
          'user_id': 9,
          'username': 'judge.m',
          'display_name': 'محمد أحمد',
        },
        {
          'user_id': 5,
          'username': 'judge.k',
          'display_name': 'خالد عبدالله',
        },
        {
          'user_id': userB,
          'username': 'judge.b',
          'display_name': 'أحمد البلوشي',
        },
        {
          'user_id': 40,
          'username': 'Ahmed.latin',
          'display_name': 'Ahmed Ali',
        },
      ];

  String labelOf(Map<String, dynamic> u) {
    final name = '${u['display_name'] ?? ''}'.trim();
    final username = '${u['username'] ?? ''}'.trim();
    final id = u['user_id'];
    return [
      if (name.isNotEmpty) name,
      if (username.isNotEmpty) username,
      'رقم $id',
    ].join(' — ');
  }

  Future<ScopedBackupResult> writeTinyBackup(Directory dest) {
    return ScopedBackupService.instance.writeBackupPackage(
      destinationParent: dest,
      identity: identityA,
      exercise: exercise,
      cacheRows: [
        {
          'cache_key': 'u$userA:home',
          'json_body': jsonEncode({'exercise_id': exerciseId}),
          'updated_at': '2026-01-01T00:00:00Z',
          'sync_status': 'synced',
        },
      ],
      pendingRows: const [],
      mediaRows: const [],
      freeBytes: 200 * 1024 * 1024,
      chunkSize: 1024,
    );
  }

  test('1-5 public Downloads hierarchy uses display names and timestamp', () async {
    final srcDest = await Directory.systemTemp.createTemp('c2-src');
    final downloads = await Directory.systemTemp.createTemp('c2-dl');
    final written = await writeTinyBackup(srcDest);
    expect(written.verified, isTrue);
    final when = DateTime(2026, 10, 17, 14, 5, 30);
    final location = buildPublicBackupLocation(
      exercise: exercise,
      identity: identityA,
      siblingDisplayNames: const ['أحمد البلوشي', 'محمد أحمد', 'خالد عبدالله'],
      now: when,
    );
    expect(location.exerciseFolder, 'تمرين رياح الصحراء');
    expect(location.judgeFolder, 'أحمد البلوشي');
    expect(location.instanceFolder, 'Backup_2026-10-17_140530');
    expect(
      location.displayPath,
      'Download/SmartArbitration_Backups/تمرين رياح الصحراء/أحمد البلوشي/Backup_2026-10-17_140530',
    );
    expect(location.displayPath.startsWith('Download/SmartArbitration_Backups/'), isTrue);

    final published = await copyVerifiedBackupToPublicLayout(
      verifiedPackage: Directory(written.packagePath!),
      downloadsRoot: downloads,
      location: location,
      chunkSize: 1024,
    );
    final saved = Directory(p.join(
      downloads.path,
      kPublicBackupRootFolder,
      published.exerciseFolder,
      published.judgeFolder,
      published.instanceFolder,
    ));
    expect(saved.existsSync(), isTrue);
    expect(File(p.join(saved.path, kScopedBackupManifestName)).existsSync(), isTrue);
    expect(published.displayPath, location.displayPath);
    await srcDest.delete(recursive: true);
    await downloads.delete(recursive: true);
  });

  test('6 multiple backups do not overwrite each other', () async {
    final srcDest = await Directory.systemTemp.createTemp('c2-multi-src');
    final downloads = await Directory.systemTemp.createTemp('c2-multi-dl');
    final written = await writeTinyBackup(srcDest);
    final when = DateTime(2026, 10, 17, 14, 5, 30);
    final location = buildPublicBackupLocation(
      exercise: exercise,
      identity: identityA,
      siblingDisplayNames: const ['أحمد البلوشي'],
      now: when,
    );
    final first = await copyVerifiedBackupToPublicLayout(
      verifiedPackage: Directory(written.packagePath!),
      downloadsRoot: downloads,
      location: location,
    );
    final second = await copyVerifiedBackupToPublicLayout(
      verifiedPackage: Directory(written.packagePath!),
      downloadsRoot: downloads,
      location: location,
    );
    expect(first.instanceFolder, 'Backup_2026-10-17_140530');
    expect(second.instanceFolder, 'Backup_2026-10-17_140530_2');
    expect(
      Directory(p.join(
        downloads.path,
        kPublicBackupRootFolder,
        first.exerciseFolder,
        first.judgeFolder,
        first.instanceFolder,
      )).existsSync(),
      isTrue,
    );
    expect(
      Directory(p.join(
        downloads.path,
        kPublicBackupRootFolder,
        second.exerciseFolder,
        second.judgeFolder,
        second.instanceFolder,
      )).existsSync(),
      isTrue,
    );
    await srcDest.delete(recursive: true);
    await downloads.delete(recursive: true);
  });

  test('7-9 Arabic preserved, unsafe chars sanitized, duplicate names uniqued', () {
    expect(
      sanitizeBackupFolderName('تمرين رياح الصحراء'),
      'تمرين رياح الصحراء',
    );
    expect(sanitizeBackupFolderName('../evil/name'), isNot(contains('..')));
    expect(sanitizeBackupFolderName('../evil/name'), isNot(contains('/')));
    expect(sanitizeBackupFolderName('a:b*c?d'), isNot(contains(':')));
    expect(sanitizeBackupFolderName('a:b*c?d'), isNot(contains('*')));
    final unique = judgeFolderName(
      displayName: 'أحمد البلوشي',
      userId: userA,
      siblingDisplayNames: const ['أحمد البلوشي'],
    );
    expect(unique, 'أحمد البلوشي');
    final collided = judgeFolderName(
      displayName: 'أحمد البلوشي',
      userId: userA,
      siblingDisplayNames: sampleUsers().map((u) => '${u['display_name']}'),
    );
    expect(collided, 'أحمد البلوشي (U27)');
    final other = judgeFolderName(
      displayName: identityDup.displayName,
      userId: identityDup.userId,
      siblingDisplayNames: sampleUsers().map((u) => '${u['display_name']}'),
    );
    expect(other, 'أحمد البلوشي (U28)');
    expect(collided, isNot(other));
    expect(isSafePublicRelativeDir('../SmartArbitration_Backups/a/b/c'), isFalse);
    expect(isSafePublicRelativeDir('/data/data/x'), isFalse);
  });

  test('10-12 manifest keeps real ids, success path matches disk, source unchanged', () async {
    final srcDest = await Directory.systemTemp.createTemp('c2-id-src');
    final downloads = await Directory.systemTemp.createTemp('c2-id-dl');
    final written = await writeTinyBackup(srcDest);
    final cacheBefore = File(p.join(written.packagePath!, 'records', 'cache.json'))
        .readAsStringSync();
    final location = buildPublicBackupLocation(
      exercise: exercise,
      identity: identityA,
      siblingDisplayNames: const ['أحمد البلوشي'],
      now: DateTime(2026, 10, 18, 9, 12, 45),
    );
    final published = await copyVerifiedBackupToPublicLayout(
      verifiedPackage: Directory(written.packagePath!),
      downloadsRoot: downloads,
      location: location,
    );
    final publicDir = Directory(p.join(
      downloads.path,
      kPublicBackupRootFolder,
      published.exerciseFolder,
      published.judgeFolder,
      published.instanceFolder,
    ));
    final issues = await validateBackupPackage(publicDir, chunkSize: 1024);
    expect(issues, isEmpty);
    final manifest = ScopedBackupManifest.fromJson(
      jsonDecode(
        File(p.join(publicDir.path, kScopedBackupManifestName)).readAsStringSync(),
      ) as Map<String, dynamic>,
    );
    expect(manifest.exercise.exerciseId, exerciseId);
    expect(manifest.user.userId, userA);
    expect(manifest.exercise.name, 'تمرين رياح الصحراء');
    expect(published.displayPath.endsWith(published.instanceFolder), isTrue);
    expect(
      backupSuccessMessage(published.displayPath),
      contains(kBackupSuccessHeadline),
    );
    expect(backupSuccessMessage(published.displayPath), contains(kBackupLocationLabel));
    expect(backupSuccessMessage(published.displayPath), contains(published.displayPath));
    expect(
      File(p.join(written.packagePath!, 'records', 'cache.json')).readAsStringSync(),
      cacheBefore,
    );
    await srcDest.delete(recursive: true);
    await downloads.delete(recursive: true);
  });

  testWidgets('13-14 search field is above preserved dropdown', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: BackupUserSelectPanel(
            users: sampleUsers(),
            selectedUserId: userA,
            searchQuery: '',
            enabled: true,
            userLabel: labelOf,
            onSearchChanged: (_) {},
            onSelected: (_) {},
          ),
        ),
      ),
    );
    final search = tester.getRect(find.byKey(const Key('backup_user_search')));
    final dropdown = tester.getRect(find.byKey(const Key('backup_user_dropdown')));
    expect(search.bottom <= dropdown.top, isTrue);
    expect(find.byType(DropdownButtonFormField<int>), findsOneWidget);
    expect(find.text(kUserNameSearchHint), findsWidgets);
  });

  test('15-21 search filtering, trim, latin case, no-match, restore full list', () {
    final users = sampleUsers();
    final empty = filterUsersByDisplayName(users, '');
    expect(empty.length, users.length);
    expect(empty.map((u) => u['user_id']), users.map((u) => u['user_id']));

    final exact = filterUsersByDisplayName(users, 'خالد عبدالله');
    expect(exact.map((u) => u['user_id']), [5]);

    final partial = filterUsersByDisplayName(users, 'أحمد');
    expect(partial.map((u) => u['user_id']), containsAll([userA, 9, userB]));
    expect(partial.map((u) => u['user_id']), isNot(contains(5)));

    final trimmed = filterUsersByDisplayName(users, '  أحمد  ');
    expect(trimmed.map((u) => u['user_id']), partial.map((u) => u['user_id']));

    final latin = filterUsersByDisplayName(users, 'ahmed');
    expect(latin.map((u) => u['user_id']), [40]);

    final none = filterUsersByDisplayName(users, 'اسم غير موجود');
    expect(none, isEmpty);
    expect(kNoMatchingUserMessage, 'لا يوجد مستخدم مطابق');

    final restored = filterUsersByDisplayName(users, '');
    expect(restored.length, users.length);
  });

  testWidgets('20 no-match message is shown without an invalid selection', (tester) async {
    int? selected = userA;
    await tester.pumpWidget(
      MaterialApp(
        home: StatefulBuilder(
          builder: (context, setState) {
            return Scaffold(
              body: BackupUserSelectPanel(
                users: sampleUsers(),
                selectedUserId: selected,
                searchQuery: 'اسم غير موجود',
                enabled: true,
                userLabel: labelOf,
                onSearchChanged: (_) {},
                onSelected: (v) => setState(() => selected = v),
              ),
            );
          },
        ),
      ),
    );
    expect(find.text(kNoMatchingUserMessage), findsOneWidget);
    expect(selected, userA);
  });

  test('22-24 duplicate names keep separate user_id; offline filter only', () {
    final users = sampleUsers();
    final hits = filterUsersByDisplayName(users, 'أحمد البلوشي');
    expect(hits.length, 2);
    expect(hits.map((u) => u['user_id']).toSet(), {userA, userB});
    expect(hits[0]['user_id'], isNot(hits[1]['user_id']));
    final src = File('lib/screens/scoped_backup_screen.dart').readAsStringSync();
    expect(src.contains('filterUsersByDisplayName'), isTrue);
    expect(src.contains('ApiClient'), isFalse);
    expect(src.contains('/api/'), isFalse);
    final paths = File('lib/services/scoped_backup_paths.dart').readAsStringSync();
    expect(paths.contains('http'), isFalse);
  });

  testWidgets('23 selecting a filtered duplicate keeps the correct user_id', (tester) async {
    int? selected = userA;
    await tester.pumpWidget(
      MaterialApp(
        home: StatefulBuilder(
          builder: (context, setState) {
            return Scaffold(
              body: BackupUserSelectPanel(
                users: sampleUsers(),
                selectedUserId: selected,
                searchQuery: 'أحمد البلوشي',
                enabled: true,
                userLabel: labelOf,
                onSearchChanged: (_) {},
                onSelected: (v) => setState(() => selected = v),
              ),
            );
          },
        ),
      ),
    );
    await tester.tap(find.byKey(const Key('backup_user_dropdown')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('أحمد البلوشي — judge.b — رقم 28').last);
    await tester.pumpAndSettle();
    expect(selected, userB);
  });

  test('25-35 C.1 OOM fix, streaming, isolation, secrets, restore, Phase B surface', () {
    expect(OfflineStore.databaseSchemaVersion, 4);
    expect(kTabletApplicationId, 'ae.lf.training.lf_training_evaluation');
    expect(OfflineStore.backupCacheMetadataColumns.contains('json_body'), isFalse);
    final service = File('lib/services/scoped_backup_service.dart').readAsStringSync();
    final createFn = service.split('createBackupForUser')[1].split('File? signature')[0];
    expect(createFn.contains('recoverySelectCache()'), isFalse);
    expect(createFn.contains('SELECT * FROM cache'), isFalse);
    expect(createFn.contains('backupSelectScopedCacheForUser'), isTrue);
    expect(service.contains('copyBackupToPublicDownloads'), isTrue);
    expect(service.contains("'exportBackupFolder'"), isTrue);
    final io = File('lib/services/scoped_backup_io.dart').readAsStringSync();
    expect(io.contains('readAsBytes()'), isFalse);
    expect(io.contains('readAsBytesSync'), isFalse);
    expect(io.contains('streamHashFile'), isTrue);
    expect(io.contains('streamCopyFile'), isTrue);
    expect(kScopedBackupExportsAuthSecrets, isFalse);
    expect(kScopedBackupClearsPendingOps, isFalse);
    expect(kScopedRestoreUsesClearAll, isFalse);
    final native = File(
      'android/app/src/main/kotlin/ae/lf/training/lf_training_evaluation/MainActivity.kt',
    ).readAsStringSync();
    expect(native.contains('copyBackupToPublicDownloads'), isTrue);
    expect(native.contains('MediaStore.Files.getContentUri'), isTrue);
    expect(native.contains('insert(MediaStore.Downloads'), isFalse);
    expect(native.contains('IS_PENDING, 1'), isTrue);
    expect(native.contains('IS_PENDING, 0'), isTrue);
    expect(native.contains('MediaScannerConnection.scanFile'), isTrue);
    expect(native.contains('openOutputStream(uri, "w")?.use'), isTrue);
    expect(native.contains('output.flush()'), isTrue);
    expect(native.contains('fileCount'), isTrue);
    expect(native.contains('DATE_MODIFIED'), isTrue);
    expect(native.contains('RELATIVE_PATH'), isTrue);
    expect(native.contains('copyStream'), isTrue);
    expect(native.contains('readBytes()'), isFalse);
    expect(native.contains('MANAGE_EXTERNAL_STORAGE'), isFalse);
    final manifest = File('android/app/src/main/AndroidManifest.xml').readAsStringSync();
    expect(manifest.contains('MANAGE_EXTERNAL_STORAGE'), isFalse);
    expect(manifest.contains('WRITE_EXTERNAL_STORAGE'), isTrue);
    expect(manifest.contains('maxSdkVersion="28"'), isTrue);
    final screen = File('lib/screens/scoped_backup_screen.dart').readAsStringSync();
    expect(screen.contains('حفظ النسخة الاحتياطية في الجهاز'), isFalse);
    expect(screen.contains('exportPackageToUserLocation'), isFalse);
    expect(screen.contains('BackupUserSelectPanel'), isTrue);
    expect(screen.contains('kUserNameSearchHint'), isTrue);
  });

  test('restore validates manifest identity, not folder names', () async {
    final srcDest = await Directory.systemTemp.createTemp('c2-rst-src');
    final downloads = await Directory.systemTemp.createTemp('c2-rst-dl');
    final written = await writeTinyBackup(srcDest);
    final published = await copyVerifiedBackupToPublicLayout(
      verifiedPackage: Directory(written.packagePath!),
      downloadsRoot: downloads,
      location: buildPublicBackupLocation(
        exercise: exercise,
        identity: identityA,
        siblingDisplayNames: const ['أحمد البلوشي'],
        now: DateTime(2026, 10, 19, 15, 30, 10),
      ),
    );
    final publicDir = Directory(p.join(
      downloads.path,
      kPublicBackupRootFolder,
      'wrong-exercise-folder',
      'wrong-user-folder',
      published.instanceFolder,
    ));
    await publicDir.parent.create(recursive: true);
    await copyDirectoryStreaming(
      source: Directory(p.join(
        downloads.path,
        kPublicBackupRootFolder,
        published.exerciseFolder,
        published.judgeFolder,
        published.instanceFolder,
      )),
      dest: publicDir,
      chunkSize: 1024,
    );
    final issues = await validateBackupPackage(publicDir, chunkSize: 1024);
    expect(issues, isEmpty);
    final manifest = await ScopedBackupService.instance.readManifest(publicDir);
    expect(manifest!.exercise.exerciseId, exerciseId);
    expect(manifest.user.userId, userA);
    expect(published.exerciseFolder, isNot('100'));
    final preview = ScopedBackupService.instance.buildRestorePreview(
      manifest: manifest,
      validationIssues: issues,
      currentExerciseId: exerciseId,
      selectedUserId: userA,
      userProvisioned: true,
      localCacheByKey: const {},
      localCacheStatus: const {},
      localCacheUpdated: const {},
      existingPendingIds: const {},
      livePendingIds: const {},
      backupCache: const [],
      backupPending: const [],
      backupMedia: const [],
    );
    expect(preview.canRestore, isTrue);
    final wrongUser = ScopedBackupService.instance.buildRestorePreview(
      manifest: manifest,
      validationIssues: issues,
      currentExerciseId: exerciseId,
      selectedUserId: userB,
      userProvisioned: true,
      localCacheByKey: const {},
      localCacheStatus: const {},
      localCacheUpdated: const {},
      existingPendingIds: const {},
      livePendingIds: const {},
      backupCache: const [],
      backupPending: const [],
      backupMedia: const [],
    );
    expect(wrongUser.canRestore, isFalse);
    await srcDest.delete(recursive: true);
    await downloads.delete(recursive: true);
  });

  test('fallback exercise folder uses id only when display name is empty', () {
    final loc = buildPublicBackupLocation(
      exercise: const ScopedBackupExercise(exerciseId: 77, name: ''),
      identity: const ScopedBackupIdentity(userId: 3, username: 'x'),
      siblingDisplayNames: const [''],
      now: DateTime(2026, 1, 2, 3, 4, 5),
    );
    expect(loc.exerciseFolder, 'تمرين 77');
    expect(loc.judgeFolder, 'مستخدم 3');
    expect(loc.instanceFolder, 'Backup_2026-01-02_030405');
  });

  test('nested test.xlsx and test.jpg remain readable after public layout copy', () async {
    final src = await Directory.systemTemp.createTemp('c2-mtp-src');
    final downloads = await Directory.systemTemp.createTemp('c2-mtp-dl');
    final nested = Directory(p.join(src.path, 'مجلد_فرعي'))..createSync();
    File(p.join(src.path, 'test.xlsx')).writeAsBytesSync([0x50, 0x4B, 0x03, 0x04]);
    File(p.join(nested.path, 'test.jpg')).writeAsBytesSync([0xFF, 0xD8, 0xFF, 0xD9]);
    File(p.join(src.path, kScopedBackupCompleteName)).writeAsStringSync('complete\n');
    final published = await copyVerifiedBackupToPublicLayout(
      verifiedPackage: src,
      downloadsRoot: downloads,
      location: buildPublicBackupLocation(
        exercise: exercise,
        identity: identityA,
        siblingDisplayNames: const ['أحمد البلوشي'],
        now: DateTime(2026, 10, 17, 16, 30, 0),
      ),
    );
    final saved = Directory(p.join(
      downloads.path,
      kPublicBackupRootFolder,
      published.exerciseFolder,
      published.judgeFolder,
      published.instanceFolder,
    ));
    final xlsx = File(p.join(saved.path, 'test.xlsx'));
    final jpg = File(p.join(saved.path, 'مجلد_فرعي', 'test.jpg'));
    expect(xlsx.existsSync(), isTrue);
    expect(jpg.existsSync(), isTrue);
    expect(xlsx.readAsBytesSync(), [0x50, 0x4B, 0x03, 0x04]);
    expect(jpg.readAsBytesSync(), [0xFF, 0xD8, 0xFF, 0xD9]);
    final native = File(
      'android/app/src/main/kotlin/ae/lf/training/lf_training_evaluation/MainActivity.kt',
    ).readAsStringSync();
    expect(native.contains('posixRelative'), isTrue);
    expect(native.contains('parentRel'), isTrue);
    await src.delete(recursive: true);
    await downloads.delete(recursive: true);
  });
}
