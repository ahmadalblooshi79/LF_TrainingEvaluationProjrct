import 'dart:convert';
import 'dart:io';

import 'package:archive/archive.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lf_training_evaluation/services/eval_backup_assembler.dart';
import 'package:lf_training_evaluation/services/offline_store.dart';
import 'package:lf_training_evaluation/services/scoped_backup_excel.dart';
import 'package:lf_training_evaluation/services/scoped_backup_io.dart';
import 'package:lf_training_evaluation/services/scoped_backup_models.dart';
import 'package:lf_training_evaluation/services/scoped_backup_paths.dart';
import 'package:lf_training_evaluation/services/scoped_backup_service.dart';
import 'package:path/path.dart' as p;

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  const userA = 11;
  const userB = 22;
  const exercise = 100;
  const otherExercise = 200;

  final identityA = ScopedBackupIdentity(
    userId: userA,
    username: 'judge.a',
    displayName: 'أحمد البلوشي',
  );
  final exerciseRow = ScopedBackupExercise(
    exerciseId: exercise,
    name: 'تمرين رياح الصحراء',
  );

  Map<String, dynamic> procedureCache({
    required int userId,
    required int itemId,
    required int exerciseId,
    required String title,
    String acquired = '8',
    String notes = 'ملاحظة محفوظة',
  }) {
    return {
      'cache_key': 'u$userId:evaluation_list_detail:snipers:$itemId',
      'json_body': jsonEncode({
        'id': itemId,
        'item_id': itemId,
        'exercise_id': exerciseId,
        'title': title,
        'unit_key': 'snipers',
        'locally_modified': true,
        'is_approved': false,
        'saved_payload': {
          'rows': [
            {
              'row_kind': 'score',
              'element': 'قيادة وسيطرة',
              'max_val': '10',
              'acquired': acquired,
              'notes': notes,
            }
          ],
        },
      }),
      'updated_at': '2026-10-17T10:00:00Z',
      'sync_status': 'pending',
    };
  }

  Map<String, dynamic> dilemmaCache({
    required int userId,
    required int slotId,
    int? exerciseId,
    required String title,
    String acquired = '6',
    String notes = 'ملاحظة معضلة',
    List<Map<String, dynamic>> localMedia = const [],
  }) {
    return {
      'cache_key': 'u$userId:action_eval_detail:$slotId',
      'json_body': jsonEncode({
        'kind': 'action_eval',
        'id': slotId,
        'slot_id': slotId,
        if (exerciseId != null) 'exercise_id': exerciseId,
        'title': title,
        'eval_dilemma_description': title,
        'locally_modified': true,
        'is_approved': false,
        'eval_rows': [
          {
            'row_kind': 'score',
            'element': 'إجراء المعاضلة',
            'max_val': '10',
            'acquired_initial': '',
          }
        ],
        'saved_payload': {
          'rows': [
            {
              'row_kind': 'score',
              'element': 'إجراء المعاضلة',
              'max_val': '10',
              'acquired': acquired,
              'notes': notes,
            }
          ],
        },
        if (localMedia.isNotEmpty) 'local_media': localMedia,
      }),
      'updated_at': '2026-10-17T10:00:00Z',
      'sync_status': 'pending',
    };
  }

  List<Map<String, dynamic>> unrelatedCache() => [
        {
          'cache_key': 'u$userA:library:information_bank.xlsx',
          'json_body': jsonEncode({
            'exercise_id': exercise,
            'file': 'ibank.xlsx',
            'saved_payload': {
              'rows': [
                {
                  'element': 'بنك المعلومات',
                  'acquired': '1',
                  'notes': 'يجب ألا يُضمّن',
                }
              ],
            },
          }),
          'updated_at': '2026-10-17T10:00:00Z',
          'sync_status': 'synced',
        },
        {
          'cache_key': 'u$userA:unit_designation',
          'json_body': jsonEncode({
            'exercise_id': exercise,
            'title': 'تسكين الوحدات.xlsx',
          }),
          'updated_at': '2026-10-17T10:00:00Z',
          'sync_status': 'synced',
        },
        {
          'cache_key': 'u$userA:planner_config',
          'json_body': jsonEncode({'exercise_id': exercise, 'xlsx': 'setup.xlsx'}),
          'updated_at': '2026-10-17T10:00:00Z',
          'sync_status': 'synced',
        },
        {
          'cache_key': 'u$userA:objectives',
          'json_body': jsonEncode({'exercise_id': exercise}),
          'updated_at': '2026-10-17T10:00:00Z',
          'sync_status': 'synced',
        },
      ];

  Future<ScopedBackupResult> writeBackup({
    required Directory dest,
    required List<Map<String, dynamic>> cache,
    List<Map<String, dynamic>> pending = const [],
    List<Map<String, dynamic>> media = const [],
  }) {
    return ScopedBackupService.instance.writeBackupPackage(
      destinationParent: dest,
      identity: identityA,
      exercise: exerciseRow,
      cacheRows: cache,
      pendingRows: pending,
      mediaRows: media,
      freeBytes: 200 * 1024 * 1024,
      chunkSize: 1024,
    );
  }

  test('1-6 technical backup plus evaluation excel folders and files', () async {
    final dest = await Directory.systemTemp.createTemp('c21-main');
    final cache = [
      procedureCache(
        userId: userA,
        itemId: 1,
        exerciseId: exercise,
        title: 'تقييم القيادة والسيطرة',
      ),
      procedureCache(
        userId: userA,
        itemId: 2,
        exerciseId: exercise,
        title: 'تقييم الانتشار',
      ),
      dilemmaCache(
        userId: userA,
        slotId: 9,
        exerciseId: exercise,
        title: 'تقييم المعاضلة 01',
      ),
      ...unrelatedCache(),
    ];
    final result = await writeBackup(dest: dest, cache: cache);
    expect(result.verified, isTrue);
    final pkg = Directory(result.packagePath!);
    expect(File(p.join(pkg.path, kScopedBackupManifestName)).existsSync(), isTrue);
    expect(File(p.join(pkg.path, kScopedBackupCompleteName)).existsSync(), isTrue);
    expect(Directory(p.join(pkg.path, 'records')).existsSync(), isTrue);
    expect(
      Directory(p.join(pkg.path, kBackupEvalListsRoot, kBackupExcelProcedureFolder))
          .existsSync(),
      isTrue,
    );
    expect(
      Directory(p.join(pkg.path, kBackupEvalListsRoot, kBackupExcelDilemmaFolder))
          .existsSync(),
      isTrue,
    );
    expect(result.procedureExcelCount, 2);
    expect(result.dilemmaExcelCount, 1);
    expect(
      Directory(p.join(
        pkg.path,
        kBackupEvalListsRoot,
        kBackupExcelProcedureFolder,
        'تقييم القيادة والسيطرة',
      )).existsSync(),
      isTrue,
    );
    expect(
      File(p.join(
        pkg.path,
        kBackupEvalListsRoot,
        kBackupExcelProcedureFolder,
        'تقييم القيادة والسيطرة',
        'تقييم القيادة والسيطرة.xlsx',
      )).existsSync(),
      isTrue,
    );
    expect(
      File(p.join(
        pkg.path,
        kBackupEvalListsRoot,
        kBackupExcelDilemmaFolder,
        'تقييم المعاضلة 01',
        'تقييم المعاضلة 01.xlsx',
      )).existsSync(),
      isTrue,
    );
    await dest.delete(recursive: true);
  });

  test('7-11 unrelated, other user, other exercise excel excluded', () async {
    final dest = await Directory.systemTemp.createTemp('c21-iso');
    final cache = [
      procedureCache(
        userId: userA,
        itemId: 1,
        exerciseId: exercise,
        title: 'تقييم القيادة والسيطرة',
      ),
      procedureCache(
        userId: userB,
        itemId: 3,
        exerciseId: exercise,
        title: 'قائمة المحكم الآخر',
      ),
      dilemmaCache(
        userId: userA,
        slotId: 8,
        exerciseId: otherExercise,
        title: 'معضلة تمرين آخر',
      ),
      ...unrelatedCache(),
    ];
    final result = await writeBackup(dest: dest, cache: cache);
    expect(result.verified, isTrue);
    final pkg = Directory(result.packagePath!);
    final excelRoot = Directory(p.join(pkg.path, kBackupEvalListsRoot));
    final names = <String>[];
    await for (final e in excelRoot.list(recursive: true, followLinks: false)) {
      if (e is File) names.add(p.basename(e.path));
    }
    expect(names, contains('تقييم القيادة والسيطرة.xlsx'));
    expect(names, isNot(contains('قائمة المحكم الآخر.xlsx')));
    expect(names, isNot(contains('معضلة تمرين آخر.xlsx')));
    expect(names.any((n) => n.contains('ibank') || n.contains('بنك')), isFalse);
    expect(names.any((n) => n.contains('تسكين')), isFalse);
    expect(names.any((n) => n.contains('setup')), isFalse);
    expect(isUnrelatedExcelSourceKey('u11:library:information_bank.xlsx'), isTrue);
    expect(isUnrelatedExcelSourceKey('u11:unit_designation'), isTrue);
    expect(isUnrelatedExcelSourceKey('u11:evaluation_list_detail:snipers:1'), isFalse);
    expect(result.procedureExcelCount, 1);
    expect(result.dilemmaExcelCount, 0);
    await dest.delete(recursive: true);
  });

  test('12-19 arabic names, duplicates, open, scores, notes, sha, kinds', () async {
    final dest = await Directory.systemTemp.createTemp('c21-content');
    final cache = [
      procedureCache(
        userId: userA,
        itemId: 11,
        exerciseId: exercise,
        title: 'قائمة مشتركة',
        acquired: '9',
        notes: 'ملاحظة الإجراءات',
      ),
      procedureCache(
        userId: userA,
        itemId: 12,
        exerciseId: exercise,
        title: 'قائمة مشتركة',
        acquired: '5',
        notes: 'ملاحظة ثانية',
      ),
      dilemmaCache(
        userId: userA,
        slotId: 21,
        exerciseId: exercise,
        title: 'تقييم المعاضلة 02',
        acquired: '7',
        notes: 'ملاحظة المعاضل',
      ),
    ];
    final before = jsonEncode(cache);
    final result = await writeBackup(dest: dest, cache: cache);
    expect(jsonEncode(cache), before);
    expect(result.verified, isTrue);
    final pkg = Directory(result.packagePath!);
    final procDir = Directory(
      p.join(pkg.path, kBackupEvalListsRoot, kBackupExcelProcedureFolder),
    );
    final folders = procDir
        .listSync()
        .whereType<Directory>()
        .map((e) => p.basename(e.path))
        .toSet();
    expect(folders.length, 2);
    expect(folders.contains('قائمة مشتركة'), isTrue);
    expect(folders.contains('قائمة مشتركة (L12)'), isTrue);
    expect(
      File(p.join(procDir.path, 'قائمة مشتركة', 'قائمة مشتركة.xlsx'))
          .existsSync(),
      isTrue,
    );
    expect(
      File(p.join(procDir.path, 'قائمة مشتركة (L12)', 'قائمة مشتركة (L12).xlsx'))
          .existsSync(),
      isTrue,
    );

    final excelFile = File(
      p.join(
        pkg.path,
        kBackupEvalListsRoot,
        kBackupExcelProcedureFolder,
        'قائمة مشتركة',
        'قائمة مشتركة.xlsx',
      ),
    );
    final bytes = excelFile.readAsBytesSync();
    expect(bytes.length, greaterThan(100));
    expect(bytes[0], 0x50);
    expect(bytes[1], 0x4B);
    final archive = ZipDecoder().decodeBytes(bytes);
    expect(archive.findFile('xl/workbook.xml'), isNotNull);
    expect(archive.findFile('xl/worksheets/sheet1.xml'), isNotNull);
    final sheet = utf8.decode(archive.findFile('xl/worksheets/sheet1.xml')!.content as List<int>);
    expect(sheet.contains('المكتسبة'), isTrue);
    expect(sheet.contains('الملاحظات'), isTrue);
    expect(sheet.contains('عناصر التقييم'), isTrue);
    expect(sheet.contains('9') || sheet.contains('5'), isTrue);
    expect(sheet.contains('ملاحظة'), isTrue);

    final hashed = await streamHashFile(excelFile, chunkSize: 1024);
    final manifest = result.manifest!;
    final excelEntries = manifest.fileInventory
        .where((e) =>
            e.kind == kProcedureExcelKind || e.kind == kDilemmaExcelKind)
        .toList();
    expect(excelEntries.length, 3);
    expect(
      excelEntries.where((e) => e.kind == kProcedureExcelKind).length,
      2,
    );
    expect(
      excelEntries.where((e) => e.kind == kDilemmaExcelKind).length,
      1,
    );
    expect(excelEntries.every((e) => (e.evaluationListId ?? 0) > 0), isTrue);
    expect(
      excelEntries.map((e) => e.evaluationListId).toSet(),
      {11, 12, 21},
    );
    final match = excelEntries.firstWhere(
      (e) => e.relativePath.endsWith('قائمة مشتركة.xlsx'),
    );
    expect(match.sha256, hashed.sha256);
    expect(match.size, hashed.bytes);
    expect(cache.first['json_body'].toString().contains('"is_approved":false'), isTrue);
    await dest.delete(recursive: true);
  });

  test('20-22 excel export does not approve, sync, or mutate source', () async {
    final dest = await Directory.systemTemp.createTemp('c21-safe');
    final cache = [
      procedureCache(
        userId: userA,
        itemId: 1,
        exerciseId: exercise,
        title: 'تقييم الاتصالات',
      ),
    ];
    final fp = fingerprintPayload(cache, ['cache_key', 'json_body', 'sync_status']);
    final result = await writeBackup(dest: dest, cache: cache);
    expect(result.verified, isTrue);
    expect(fingerprintPayload(cache, ['cache_key', 'json_body', 'sync_status']), fp);
    final src = File('lib/services/scoped_backup_excel.dart').readAsStringSync();
    expect(src.contains('SyncService'), isFalse);
    expect(src.contains('is_approved = true'), isFalse);
    expect(src.contains('locally_approved = true'), isFalse);
    expect(src.contains('/api/'), isFalse);
    final restoreSrc = File('lib/services/scoped_backup_service.dart').readAsStringSync();
    final restoreFn = restoreSrc.split('Future<ScopedRestoreResult> restorePackage')[1];
    expect(restoreFn.contains('kBackupExcelRoot'), isFalse);
    expect(restoreFn.contains('procedure_evaluation_excel'), isFalse);
    await dest.delete(recursive: true);
  });

  test('C.2 success message includes real location and excel counts', () {
    final msg = backupSuccessMessage(
      'Download/SmartArbitration_Backups/تمرين/أحمد/Backup_2026-10-17_140530',
      procedureExcelCount: 5,
      dilemmaExcelCount: 3,
    );
    expect(msg, contains(kBackupSuccessHeadline));
    expect(msg, contains('مكان الحفظ:'));
    expect(msg, contains('Download/SmartArbitration_Backups'));
    expect(msg, contains('قوائم تقييم الإجراءات: 5'));
    expect(msg, contains('قوائم تقييم المعاضل: 3'));
    expect(msg, contains('الصور: 0'));
    expect(msg, contains('الفيديوهات: 0'));
  });

  test('C.1/C.2/B surface preserved', () {
    expect(OfflineStore.databaseSchemaVersion, 4);
    expect(kTabletApplicationId, 'ae.lf.training.lf_training_evaluation');
    expect(OfflineStore.backupCacheMetadataColumns.contains('json_body'), isFalse);
    final service = File('lib/services/scoped_backup_service.dart').readAsStringSync();
    expect(service.contains('backupSelectScopedCacheForUser'), isTrue);
    expect(service.contains('copyBackupToPublicDownloads'), isTrue);
    expect(service.contains('writeEvaluationExcelIntoBackup'), isTrue);
    final io = File('lib/services/scoped_backup_io.dart').readAsStringSync();
    expect(io.contains('readAsBytes()'), isFalse);
    expect(io.contains('readAsBytesSync'), isFalse);
    expect(kScopedBackupExportsAuthSecrets, isFalse);
    final screen = File('lib/screens/scoped_backup_screen.dart').readAsStringSync();
    expect(screen.contains('BackupUserSelectPanel'), isTrue);
    expect(screen.contains('kUserNameSearchHint'), isTrue);
  });

  test('existing assembler still produces procedure and dilemma excel offline', () {
    final scope = EvalBackupScope(
      exerciseId: exercise,
      exerciseName: 'تمرين رياح الصحراء',
      userId: userA,
      judgeName: 'أحمد البلوشي',
      unitKey: 'snipers',
      unitName: 'القناصة',
      deviceId: 'dev',
      appVersion: '2.7.37',
      createdAt: '2026-10-17T10:00:00Z',
    );
    final pkg = assembleEvalBackup(
      scope: scope,
      pendingRows: const [],
      cacheRows: [
        procedureCache(
          userId: userA,
          itemId: 1,
          exerciseId: exercise,
          title: 'تقييم القيادة والسيطرة',
        ),
        dilemmaCache(
          userId: userA,
          slotId: 2,
          exerciseId: exercise,
          title: 'تقييم المعاضلة 01',
        ),
      ],
      mediaRows: const [],
    );
    expect(pkg.actionLists.length, 1);
    expect(pkg.dilemmaLists.length, 1);
    expect(pkg.actionLists.single.xlsxBytes.length, greaterThan(100));
    expect(pkg.dilemmaLists.single.xlsxBytes.first, 0x50);
  });

  test('list folders keep excel with associated images/videos only', () async {
    final dest = await Directory.systemTemp.createTemp('c21-media');
    final srcDir = await Directory.systemTemp.createTemp('c21-media-src');
    final imgA1 = File(p.join(srcDir.path, 'a1.jpg'))..writeAsBytesSync([1, 2, 3, 4]);
    final imgA2 = File(p.join(srcDir.path, 'a2.jpg'))..writeAsBytesSync([5, 6, 7, 8]);
    final vidA = File(p.join(srcDir.path, 'a.mp4'))..writeAsBytesSync(List<int>.filled(2048, 9));
    final imgB = File(p.join(srcDir.path, 'b.jpg'))..writeAsBytesSync([9, 9, 9, 9]);
    final imgOtherUser = File(p.join(srcDir.path, 'other.jpg'))..writeAsBytesSync([1, 1]);
    final imgOtherEx = File(p.join(srcDir.path, 'ex.jpg'))..writeAsBytesSync([2, 2]);
    final beforeA = await streamHashFile(vidA, chunkSize: 512);

    final cache = [
      procedureCache(
        userId: userA,
        itemId: 1,
        exerciseId: exercise,
        title: 'تقييم القيادة والسيطرة',
      ),
      procedureCache(
        userId: userA,
        itemId: 2,
        exerciseId: exercise,
        title: 'تقييم الانتشار',
      ),
      dilemmaCache(
        userId: userA,
        slotId: 9,
        exerciseId: exercise,
        title: 'تقييم المعاضلة الأولى',
      ),
      procedureCache(
        userId: userA,
        itemId: 3,
        exerciseId: exercise,
        title: 'تقييم الاتصالات',
      ),
    ];
    final media = [
      {
        'id': 'img-a1',
        'local_path': imgA1.path,
        'user_id': userA,
        'exercise_id': exercise,
        'media_kind': 'photo',
        'original_filename': 'صورة_قيادة.jpg',
        'evaluation_list_item_id': 1,
        'row_index': 2,
      },
      {
        'id': 'img-a2',
        'local_path': imgA2.path,
        'user_id': userA,
        'exercise_id': exercise,
        'media_kind': 'photo',
        'original_filename': 'صورة_قيادة.jpg',
        'evaluation_list_item_id': 1,
        'row_index': 3,
      },
      {
        'id': 'vid-a',
        'local_path': vidA.path,
        'user_id': userA,
        'exercise_id': exercise,
        'media_kind': 'video',
        'original_filename': 'clip.mp4',
        'evaluation_list_item_id': 1,
        'row_index': 4,
      },
      {
        'id': 'img-b',
        'local_path': imgB.path,
        'user_id': userA,
        'exercise_id': exercise,
        'media_kind': 'photo',
        'original_filename': 'انتشار.jpg',
        'evaluation_list_item_id': 2,
      },
      {
        'id': 'img-other-user',
        'local_path': imgOtherUser.path,
        'user_id': userB,
        'exercise_id': exercise,
        'media_kind': 'photo',
        'original_filename': 'other.jpg',
        'evaluation_list_item_id': 1,
      },
      {
        'id': 'img-other-ex',
        'local_path': imgOtherEx.path,
        'user_id': userA,
        'exercise_id': otherExercise,
        'media_kind': 'photo',
        'original_filename': 'wrongex.jpg',
        'evaluation_list_item_id': 1,
      },
    ];
    final result = await writeBackup(dest: dest, cache: cache, media: media);
    expect(result.verified, isTrue);
    expect(result.evaluationImageCount, 3);
    expect(result.evaluationVideoCount, 1);
    final pkg = Directory(result.packagePath!);
    final listA = Directory(p.join(
      pkg.path,
      kBackupEvalListsRoot,
      kBackupExcelProcedureFolder,
      'تقييم القيادة والسيطرة',
    ));
    final listB = Directory(p.join(
      pkg.path,
      kBackupEvalListsRoot,
      kBackupExcelProcedureFolder,
      'تقييم الانتشار',
    ));
    final listNone = Directory(p.join(
      pkg.path,
      kBackupEvalListsRoot,
      kBackupExcelProcedureFolder,
      'تقييم الاتصالات',
    ));
    expect(File(p.join(listA.path, 'تقييم القيادة والسيطرة.xlsx')).existsSync(), isTrue);
    expect(File(p.join(listA.path, 'صورة_قيادة.jpg')).existsSync(), isTrue);
    expect(File(p.join(listA.path, 'صورة_قيادة_2.jpg')).existsSync(), isTrue);
    expect(File(p.join(listA.path, 'clip.mp4')).existsSync(), isTrue);
    expect(File(p.join(listB.path, 'انتشار.jpg')).existsSync(), isTrue);
    expect(File(p.join(listB.path, 'clip.mp4')).existsSync(), isFalse);
    expect(File(p.join(listB.path, 'صورة_قيادة.jpg')).existsSync(), isFalse);
    expect(File(p.join(listNone.path, 'تقييم الاتصالات.xlsx')).existsSync(), isTrue);
    expect(
      listNone.listSync().whereType<File>().map((e) => p.basename(e.path)).toList(),
      ['تقييم الاتصالات.xlsx'],
    );
    expect(File(p.join(listA.path, 'other.jpg')).existsSync(), isFalse);
    expect(File(p.join(listA.path, 'wrongex.jpg')).existsSync(), isFalse);

    final afterA = await streamHashFile(vidA, chunkSize: 512);
    expect(afterA.sha256, beforeA.sha256);

    final vidEntry = result.manifest!.fileInventory.firstWhere(
      (e) => e.kind == kProcedureVideoKind,
    );
    expect(vidEntry.evaluationListId, 1);
    expect(vidEntry.evaluationType, 'procedure');
    expect(vidEntry.userId, userA);
    expect(vidEntry.exerciseId, exercise);
    expect(vidEntry.mediaId, 'vid-a');
    expect(vidEntry.mediaType, 'video');
    expect(vidEntry.evaluationItemId, 4);
    expect(vidEntry.sourceLocalPath, vidA.path);
    final hashedCopy = await streamHashFile(
      File(p.join(pkg.path, vidEntry.relativePath)),
      chunkSize: 512,
    );
    expect(hashedCopy.sha256, vidEntry.sha256);
    expect(Directory(p.join(pkg.path, 'media')).existsSync(), isTrue);
    await dest.delete(recursive: true);
    await srcDir.delete(recursive: true);
  });

  test('associated large video is streamed into the list folder', () async {
    scopedBackupMaxObservedChunk = 0;
    final dest = await Directory.systemTemp.createTemp('c21-large');
    final srcDir = await Directory.systemTemp.createTemp('c21-large-src');
    final src = File(p.join(srcDir.path, 'big.mp4'));
    final sink = src.openWrite();
    sink.add(List<int>.filled(8 * 1024 * 1024, 3));
    await sink.close();
    final before = await streamHashFile(src, chunkSize: 64 * 1024);
    final result = await writeBackup(
      dest: dest,
      cache: [
        procedureCache(
          userId: userA,
          itemId: 1,
          exerciseId: exercise,
          title: 'تقييم القيادة والسيطرة',
        ),
      ],
      media: [
        {
          'id': 'vid-big',
          'local_path': src.path,
          'user_id': userA,
          'exercise_id': exercise,
          'media_kind': 'video',
          'original_filename': 'big.mp4',
          'evaluation_list_item_id': 1,
        },
      ],
    );
    expect(result.verified, isTrue);
    expect(result.evaluationVideoCount, 1);
    final after = await streamHashFile(src, chunkSize: 64 * 1024);
    expect(after.sha256, before.sha256);
    expect(scopedBackupMaxObservedChunk, lessThan(8 * 1024 * 1024));
    final excelSrc = File('lib/services/scoped_backup_excel.dart').readAsStringSync();
    expect(excelSrc.contains('readAsBytes()'), isFalse);
    expect(excelSrc.contains('readAsBytesSync'), isFalse);
    expect(excelSrc.contains('streamCopyFile'), isTrue);
    await dest.delete(recursive: true);
    await srcDir.delete(recursive: true);
  });

  test('dilemma without exercise_id or catalog still writes excel and media', () async {
    final dest = await Directory.systemTemp.createTemp('c21-prod-dilemma');
    final srcDir = await Directory.systemTemp.createTemp('c21-prod-src');
    final imgSheet = File(p.join(srcDir.path, 'sheet.jpg'))
      ..writeAsBytesSync([11, 12, 13]);
    final vid = File(p.join(srcDir.path, 'clip.mp4'))
      ..writeAsBytesSync(List<int>.filled(1024, 4));
    final imgLocal = File(p.join(srcDir.path, 'local.jpg'))
      ..writeAsBytesSync([21, 22, 23]);
    final imgOtherUser = File(p.join(srcDir.path, 'other.jpg'))
      ..writeAsBytesSync([31, 32]);
    final imgOtherEx = File(p.join(srcDir.path, 'ex.jpg'))
      ..writeAsBytesSync([41, 42]);
    final beforeVid = await streamHashFile(vid, chunkSize: 256);

    final result = await writeBackup(
      dest: dest,
      cache: [
        dilemmaCache(
          userId: userA,
          slotId: 41,
          title: 'تقييم المعاضلة الأولى',
          localMedia: [
            {
              'id': 'from-json',
              'local_path': imgLocal.path,
              'media_kind': 'photo',
              'row_index': 0,
            },
          ],
        ),
        dilemmaCache(
          userId: userA,
          slotId: 42,
          title: 'تقييم المعاضلة بلا وسائط',
        ),
        dilemmaCache(
          userId: userB,
          slotId: 41,
          title: 'معضلة محكم آخر',
        ),
        dilemmaCache(
          userId: userA,
          slotId: 99,
          exerciseId: otherExercise,
          title: 'معضلة تمرين آخر',
        ),
      ],
      media: [
        {
          'id': 'sheet-only',
          'local_path': imgSheet.path,
          'user_id': userA,
          'exercise_id': exercise,
          'media_kind': 'photo',
          'original_filename': 'صورة_ورقة.jpg',
          'sheet_cache_key': 'action_eval_detail:41',
        },
        {
          'id': 'vid-bundle',
          'local_path': vid.path,
          'user_id': userA,
          'exercise_id': exercise,
          'media_kind': 'video',
          'original_filename': 'فيديو_01.mp4',
          'bundle_action_eval_id': 41,
        },
        {
          'id': 'other-user',
          'local_path': imgOtherUser.path,
          'user_id': userB,
          'exercise_id': exercise,
          'media_kind': 'photo',
          'sheet_cache_key': 'u$userB:action_eval_detail:41',
          'bundle_action_eval_id': 41,
        },
        {
          'id': 'other-ex',
          'local_path': imgOtherEx.path,
          'user_id': userA,
          'exercise_id': otherExercise,
          'media_kind': 'photo',
          'bundle_action_eval_id': 41,
        },
      ],
    );
    expect(result.verified, isTrue);
    expect(result.dilemmaExcelCount, 2);
    expect(result.evaluationImageCount, 2);
    expect(result.evaluationVideoCount, 1);
    final pkg = Directory(result.packagePath!);
    final withMedia = Directory(p.join(
      pkg.path,
      kBackupEvalListsRoot,
      kBackupExcelDilemmaFolder,
      'تقييم المعاضلة الأولى',
    ));
    final noMedia = Directory(p.join(
      pkg.path,
      kBackupEvalListsRoot,
      kBackupExcelDilemmaFolder,
      'تقييم المعاضلة بلا وسائط',
    ));
    final withMediaNames = withMedia
        .listSync()
        .whereType<File>()
        .map((e) => p.basename(e.path))
        .toSet();
    expect(withMediaNames, contains('تقييم المعاضلة الأولى.xlsx'));
    expect(withMediaNames, contains('صورة_ورقة.jpg'));
    expect(withMediaNames, contains('فيديو_01.mp4'));
    expect(withMediaNames.length, 4);
    expect(File(p.join(noMedia.path, 'تقييم المعاضلة بلا وسائط.xlsx')).existsSync(), isTrue);
    expect(
      noMedia.listSync().whereType<File>().map((e) => p.basename(e.path)).toList(),
      ['تقييم المعاضلة بلا وسائط.xlsx'],
    );
    expect(File(p.join(withMedia.path, 'other.jpg')).existsSync(), isFalse);
    expect(File(p.join(withMedia.path, 'ex.jpg')).existsSync(), isFalse);
    expect(
      Directory(p.join(
        pkg.path,
        kBackupEvalListsRoot,
        kBackupExcelDilemmaFolder,
        'معضلة محكم آخر',
      )).existsSync(),
      isFalse,
    );
    expect(
      Directory(p.join(
        pkg.path,
        kBackupEvalListsRoot,
        kBackupExcelDilemmaFolder,
        'معضلة تمرين آخر',
      )).existsSync(),
      isFalse,
    );
    final afterVid = await streamHashFile(vid, chunkSize: 256);
    expect(afterVid.sha256, beforeVid.sha256);
    final sheetEntry = result.manifest!.fileInventory.firstWhere(
      (e) => e.kind == kDilemmaImageKind && e.mediaId == 'sheet-only',
    );
    expect(sheetEntry.evaluationListId, 41);
    expect(sheetEntry.evaluationType, 'dilemma');
    expect(sheetEntry.userId, userA);
    expect(sheetEntry.exerciseId, exercise);
    await dest.delete(recursive: true);
    await srcDir.delete(recursive: true);
  });
}
