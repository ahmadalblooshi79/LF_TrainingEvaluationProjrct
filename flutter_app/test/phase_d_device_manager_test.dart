import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lf_training_evaluation/models/eval_sheet.dart';
import 'package:lf_training_evaluation/screens/device_admin_hub_screen.dart';
import 'package:lf_training_evaluation/services/device_eval_manager_excel.dart';
import 'package:lf_training_evaluation/services/device_eval_manager_models.dart';
import 'package:lf_training_evaluation/services/device_eval_manager_paths.dart';
import 'package:lf_training_evaluation/services/device_eval_manager_zip.dart';
import 'package:lf_training_evaluation/services/offline_store.dart';
import 'package:lf_training_evaluation/services/scoped_backup_io.dart';
import 'package:lf_training_evaluation/services/scoped_backup_paths.dart';
import 'package:path/path.dart' as p;

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  const userA = 27;
  const userB = 28;
  const exerciseA = 100;
  const exerciseB = 200;

  List<Map<String, dynamic>> sampleUsers() => [
        {
          'user_id': userA,
          'username': 'judge.a',
          'display_name': 'أحمد البلوشي',
        },
        {
          'user_id': userB,
          'username': 'judge.b',
          'display_name': 'أحمد البلوشي',
        },
        {
          'user_id': 9,
          'username': 'judge.m',
          'display_name': 'محمد أحمد',
        },
        {
          'user_id': 40,
          'username': 'Ahmed.latin',
          'display_name': 'Ahmed Ali',
        },
      ];

  Map<String, dynamic> procedurePayload({
    required int itemId,
    required int exerciseId,
    required String title,
    String status = 'غير مكتملة',
    String notes = 'ملاحظة أ',
    String acquired = '8',
  }) {
    return {
      'exercise_id': exerciseId,
      'lists': [
        {
          'item_id': itemId,
          'title': title,
          'unit_key': 'snipers',
          'unit_label': 'القناصة',
          'phase_key': 'opening',
          'status_label': status,
          'workflow_label': status,
        },
      ],
    };
  }

  Map<String, dynamic> dilemmaPayload({
    required int slotId,
    required int exerciseId,
    required String title,
  }) {
    return {
      'exercise_id': exerciseId,
      'lists': [
        {
          'slot_id': slotId,
          'title': title,
          'unit_key': 'snipers',
          'unit_label': 'القناصة',
          'phase_key': 'execution',
          'status_label': 'بإنتظار الاعتماد',
        },
      ],
    };
  }

  Map<String, dynamic> sheetJson({
    required int itemId,
    required String acquired,
    required String notes,
    bool canEdit = true,
    bool approved = false,
    String status = 'غير مكتملة',
  }) {
    return {
      'kind': 'evaluation_list',
      'item_id': itemId,
      'title': 'قائمة $itemId',
      'unit_key': 'snipers',
      'unit_label': 'القناصة',
      'phase_key': 'opening',
      'eval_structured': true,
      'eval_rows': [
        {
          'row_kind': 'score',
          'element': 'بند تجريبي',
          'element_prefix_kind': 'plain',
          'element_prefix': '',
          'element_rest': 'بند تجريبي',
          'element_indent': 0,
          'max_val': '10',
          'max_num': 10,
          'acquired_raw': acquired,
          'acquired_initial': acquired,
          'notes_initial': notes,
        },
      ],
      'saved_payload': {
        'rows': [
          {'acquired': acquired, 'notes': notes, 'element': 'بند تجريبي'},
        ],
      },
      'can_edit': canEdit,
      'can_approve': false,
      'is_approved': approved,
      'status_label': status,
      'workflow': {'label': status, 'reopened': false},
    };
  }

  DeviceEvalMediaRef media({
    required String id,
    required int userId,
    required int exerciseId,
    int? itemId,
    int? slotId,
    required String kind,
    required String path,
    String name = '',
  }) {
    return DeviceEvalMediaRef(
      id: id,
      userId: userId,
      exerciseId: exerciseId,
      evaluationListItemId: itemId,
      bundleActionEvalId: slotId,
      mediaKind: kind,
      localPath: path,
      originalFilename: name,
      localFilename: name,
      rowIndex: 0,
    );
  }

  String readFlutter(String rel) {
    final candidates = [
      File(rel),
      File(p.join('flutter_app', rel)),
      File(p.join('..', rel)),
    ];
    for (final f in candidates) {
      if (f.existsSync()) return f.readAsStringSync();
    }
    fail('missing $rel cwd=${Directory.current.path}');
  }

  test('1 Device Manager evaluation management entry exists', () {
    const hub = DeviceAdminHubScreen();
    expect(hub, isA<Widget>());
    final src = readFlutter('lib/screens/device_admin_hub_screen.dart');
    expect(src.contains('device_eval_manager_entry'), isTrue);
    expect(src.contains('kDeviceEvalManagerTitle'), isTrue);
    final app = readFlutter('lib/app.dart');
    expect(app.contains('/device-eval-manager'), isTrue);
    expect(app.contains('/device-eval-inspect'), isTrue);
  });

  test('2-5 user search, dropdown identity, partial, duplicate names', () {
    final users = sampleUsers();
    final partial = filterDeviceManagerUsers(users, ' أحمد ');
    expect(partial.map((u) => u['user_id']), containsAll([userA, userB, 9]));
    final latin = filterDeviceManagerUsers(users, 'ahmed');
    expect(latin.single['user_id'], 40);
    final dups = filterDeviceManagerUsers(users, 'أحمد البلوشي');
    expect(dups.map((u) => u['user_id']).toSet(), {userA, userB});
    expect(DeviceEvalUser.fromLocalRow(dups.first).userId, isNot(DeviceEvalUser.fromLocalRow(dups.last).userId));
  });

  test('6-11 user/exercise/procedure/dilemma isolation', () {
    final aProc = summariesFromListPayload(
      payload: procedurePayload(itemId: 11, exerciseId: exerciseA, title: 'إجراءات أ'),
      kind: DeviceEvalKind.procedure,
      userId: userA,
      exerciseId: exerciseA,
    );
    final bProc = summariesFromListPayload(
      payload: procedurePayload(itemId: 12, exerciseId: exerciseA, title: 'إجراءات ب'),
      kind: DeviceEvalKind.procedure,
      userId: userB,
      exerciseId: exerciseA,
    );
    final aDil = summariesFromListPayload(
      payload: dilemmaPayload(slotId: 21, exerciseId: exerciseA, title: 'معضلة أ'),
      kind: DeviceEvalKind.dilemma,
      userId: userA,
      exerciseId: exerciseA,
    );
    final otherEx = summariesFromListPayload(
      payload: procedurePayload(itemId: 11, exerciseId: exerciseB, title: 'تمرين آخر'),
      kind: DeviceEvalKind.procedure,
      userId: userA,
      exerciseId: exerciseA,
    );
    expect(aProc.single.userId, userA);
    expect(bProc.single.userId, userB);
    expect(aProc.single.kind, DeviceEvalKind.procedure);
    expect(aDil.single.kind, DeviceEvalKind.dilemma);
    expect(aProc.single.listId, isNot(aDil.single.listId));
    expect(otherEx, isEmpty);
  });

  test('12 missing local-user data message', () {
    expect(
      userHasLocalListCache(
        cacheKeys: ['u$userB:evaluation_lists::'],
        userId: userA,
        kind: DeviceEvalKind.procedure,
      ),
      isFalse,
    );
    expect(
      const DeviceEvalListsLoad(dataAvailable: false, lists: []).emptyMessage,
      kDeviceEvalMissingUserData,
    );
  });

  test('13 empty list state', () {
    expect(
      const DeviceEvalListsLoad(dataAvailable: true, lists: []).emptyMessage,
      kDeviceEvalEmptyLists,
    );
  });

  test('14-22 open inspect does not mutate, attribution and fields', () {
    final json = sheetJson(
      itemId: 11,
      acquired: '8',
      notes: 'ملاحظة المحكم أ',
      canEdit: true,
      status: 'غير مكتملة',
    );
    final original = jsonDecode(jsonEncode(json)) as Map<String, dynamic>;
    final detail = EvalSheetDetail.fromJson(json);
    final inspect = inspectOnlyDetail(detail);
    expect(inspect.canEdit, isFalse);
    expect(inspect.canApprove, isFalse);
    expect(detail.canEdit, isTrue);
    expect(inspect.savedRows.single.acquired, '8');
    expect(inspect.savedRows.single.notes, 'ملاحظة المحكم أ');
    expect(inspect.unitLabel, 'القناصة');
    expect(inspect.phaseKey, 'opening');
    expect(jsonEncode(json), jsonEncode(original));
    final approved = EvalSheetDetail.fromJson(
      sheetJson(
        itemId: 11,
        acquired: '9',
        notes: 'م',
        canEdit: false,
        approved: true,
        status: 'معتمد',
      ),
    );
    expect(approved.isApproved, isTrue);
    expect(inspectOnlyDetail(approved).isApproved, isTrue);
    expect(reopenButtonVisible(approved: true, inspectOnly: true), isTrue);
    expect(reopenButtonVisible(approved: true, inspectOnly: false), isFalse);
  });

  test('23-27 media association and isolation', () {
    final all = [
      media(id: 'ia', userId: userA, exerciseId: exerciseA, itemId: 11, kind: 'photo', path: '/a1.jpg', name: 'a.jpg'),
      media(id: 'va', userId: userA, exerciseId: exerciseA, itemId: 11, kind: 'video', path: '/a1.mp4', name: 'a.mp4'),
      media(id: 'ib', userId: userA, exerciseId: exerciseA, itemId: 12, kind: 'photo', path: '/b.jpg', name: 'b.jpg'),
      media(id: 'ub', userId: userB, exerciseId: exerciseA, itemId: 11, kind: 'photo', path: '/c.jpg', name: 'c.jpg'),
      media(id: 'ex', userId: userA, exerciseId: exerciseB, itemId: 11, kind: 'photo', path: '/d.jpg', name: 'd.jpg'),
    ];
    final listA = mediaForManagedList(
      all: all,
      kind: DeviceEvalKind.procedure,
      userId: userA,
      exerciseId: exerciseA,
      listId: 11,
    );
    expect(listA.map((m) => m.id).toSet(), {'ia', 'va'});
    expect(mediaCounts(listA).images, 1);
    expect(mediaCounts(listA).videos, 1);
  });

  test('28-32 media download unique names streaming cancel public path', () async {
    final used = <String>{};
    expect(uniqueDownloadFileName('shot.jpg', used), 'shot.jpg');
    expect(uniqueDownloadFileName('shot.jpg', used), 'shot_2.jpg');
    final loc = buildPublicExportLocation(
      exerciseName: 'تمرين رياح الصحراء',
      exerciseId: exerciseA,
      judgeName: 'أحمد البلوشي',
      userId: userA,
      listTitle: 'قائمة الرماية',
      listId: 11,
    );
    expect(loc.displayPath, contains('Download/SmartArbitration/'));
    expect(loc.displayPath, contains('تمرين رياح الصحراء'));
    expect(loc.displayPath, contains('أحمد البلوشي'));
    expect(isSafePublicExportRelativeDir(loc.relativeDir), isTrue);
    expect(isSafePublicExportRelativeDir('SmartArbitration_Backups/a/b/c'), isFalse);
    expect(isSafePublicRelativeDir(loc.relativeDir), isFalse);

    final dir = await Directory.systemTemp.createTemp('phase_d_media');
    final src = File(p.join(dir.path, 'video.bin'));
    final dest = File(p.join(dir.path, 'copy.bin'));
    final raf = await src.open(mode: FileMode.write);
    await raf.writeFrom(List<int>.filled(256 * 1024, 7));
    await raf.close();
    scopedBackupMaxObservedChunk = 0;
    await streamCopyFile(
      source: src,
      dest: dest,
      expectedSize: await src.length(),
      chunkSize: 64 * 1024,
    );
    expect(await dest.length(), await src.length());
    expect(scopedBackupMaxObservedChunk, lessThanOrEqualTo(64 * 1024 * 4));
    expect(src.readAsBytesSync(), dest.readAsBytesSync());

    final dest2 = File(p.join(dir.path, 'copy2.bin'));
    var ticks = 0;
    try {
      await streamCopyFile(
        source: src,
        dest: dest2,
        expectedSize: await src.length(),
        chunkSize: 32 * 1024,
        isCancelled: () {
          ticks += 1;
          return ticks > 1;
        },
      );
      fail('expected cancel');
    } on ScopedBackupIoException {
      expect(dest2.existsSync(), isFalse);
      expect(src.existsSync(), isTrue);
    }
  });

  test('33-40 excel architecture reuse and list download path', () {
    final service = readFlutter('lib/services/device_eval_manager_service.dart');
    expect(service.contains('/export.xlsx'), isTrue);
    expect(service.contains('downloadToFile'), isTrue);
    expect(service.contains('buildLocalEvalListXlsx'), isTrue);
    expect(service.contains('_publishZippedStaging'), isTrue);
    expect(service.contains('buildEvaluationListXlsx'), isFalse);
    expect(service.contains('SmartArbitration_Backups'), isFalse);
    expect(service.contains('copyExportToPublicDownloads'), isTrue);
    final excel = readFlutter('lib/services/device_eval_manager_excel.dart');
    expect(excel.contains('buildSimpleXlsx'), isTrue);
    final native = readFlutter(
      'android/app/src/main/kotlin/ae/lf/training/lf_training_evaluation/MainActivity.kt',
    );
    expect(native.contains('copyExportToPublicDownloads'), isTrue);
    expect(native.contains('isSafePublicExportRelativeDir'), isTrue);
    final loc = buildPublicExportLocation(
      exerciseName: 'Ex',
      exerciseId: 1,
      judgeName: 'J',
      userId: 1,
      listTitle: 'L',
      listId: 1,
    );
    expect(loc.relativeDir.startsWith('SmartArbitration/'), isTrue);
    expect(loc.attachmentsRelativeDir.endsWith('/المرفقات'), isTrue);
  });

  test('41-51 reopen is local-first and optional on server', () {
    expect(reopenOfflineMessage(online: false), isEmpty);
    expect(reopenOfflineMessage(online: true), isEmpty);
    final reopened = applyLocalReopenToDetail(
      sheetJson(
        itemId: 11,
        acquired: '9',
        notes: 'م',
        canEdit: false,
        approved: true,
        status: 'معتمد',
      ),
    );
    expect(reopened['can_edit'], isTrue);
    expect(reopened['can_approve'], isTrue);
    expect(reopened['is_approved'], isFalse);
    expect(reopened['locally_approved'], isFalse);
    expect(reopened['device_manager_reopened'], isTrue);
    expect(EvalSheetDetail.fromJson(reopened).canEdit, isTrue);
    expect(EvalSheetDetail.fromJson(reopened).isApproved, isFalse);
    final service = readFlutter('lib/services/device_eval_manager_service.dart');
    expect(service.contains('_applyLocalReopenToCaches'), isTrue);
    expect(service.contains('/api/tablet/device/eval/chief-reopen'), isTrue);
    expect(service.contains('withDeviceAuth'), isTrue);
    final api = File(p.join('..', 'app', 'tablet_api.py')).existsSync()
        ? File(p.join('..', 'app', 'tablet_api.py')).readAsStringSync()
        : File('app/tablet_api.py').readAsStringSync();
    expect(api.contains('can_chief_reopen_evaluation_for_judge'), isTrue);
    expect(api.contains('apply_chief_reopen'), isTrue);
    expect(api.contains('device/eval/chief-reopen'), isTrue);
    final inspect = readFlutter('lib/screens/device_eval_inspect_screen.dart');
    expect(inspect.contains('هل تريد إعادة فتح هذه القائمة؟'), isTrue);
    expect(inspect.contains('معاينة للقراءة فقط'), isTrue);
  });

  test('excel and attachments download as zip', () async {
    final summary = DeviceEvalListSummary(
      kind: DeviceEvalKind.procedure,
      userId: userA,
      exerciseId: exerciseA,
      listId: 11,
      unitKey: 'snipers',
      unitLabel: 'القناصة',
      phaseKey: 'opening',
      title: 'قائمة الرماية',
      statusLabel: 'معتمد',
    );
    final bytes = buildLocalEvalListXlsx(
      summary: summary,
      user: DeviceEvalUser.fromLocalRow({
        'user_id': userA,
        'username': 'judge.a',
        'display_name': 'أحمد البلوشي',
      }),
      exerciseName: 'تمرين رياح الصحراء',
      rows: [
        EvalRowInput.fromEvalRow(
          EvalRow.fromJson({
            'row_kind': 'score',
            'element': 'بند تجريبي',
            'max_val': '10',
            'acquired_raw': '8',
            'acquired_initial': '8',
            'notes_initial': 'ملاحظة',
          }),
        ),
      ],
    );
    expect(bytes.length, greaterThan(100));
    expect(bytes[0], 0x50);
    expect(bytes[1], 0x4b);

    final dir = await Directory.systemTemp.createTemp('phase_d_zip');
    final xlsx = File(p.join(dir.path, 'list.xlsx'));
    await xlsx.writeAsBytes(bytes, flush: true);
    final photo = File(p.join(dir.path, 'shot.jpg'));
    await photo.writeAsBytes(List<int>.filled(64, 9), flush: true);
    final zip = File(p.join(dir.parent.path, 'list_export.zip'));
    await zipExportDirectory(source: dir, destZip: zip);
    expect(zip.existsSync(), isTrue);
    expect(zip.lengthSync(), greaterThan(0));
    expect(zip.readAsBytesSync().sublist(0, 2), [0x50, 0x4b]);
  });

  test('settings screen no longer offers local recovery', () {
    final src = readFlutter('lib/screens/settings_screen.dart');
    expect(src.contains('استعادة البيانات المحلية'), isFalse);
    expect(src.contains("push('/recovery')"), isFalse);
  });

  test('52-63 regression: judge home, schema, backup, C.2.1 not in Phase D', () {
    expect(OfflineStore.databaseSchemaVersion, 4);
    final home = readFlutter('lib/screens/home_screen.dart');
    expect(home.contains(kDeviceEvalManagerTitle), isFalse);
    expect(home.contains('/device-eval-manager'), isFalse);
    expect(kPublicBackupRootFolder, 'SmartArbitration_Backups');
    final dFiles = [
      readFlutter('lib/services/device_eval_manager_service.dart'),
      readFlutter('lib/services/device_eval_manager_paths.dart'),
      readFlutter('lib/screens/device_eval_manager_screen.dart'),
    ].join('\n');
    expect(dFiles.contains('readAsBytes'), isFalse);
    expect(dFiles.contains('readAsBytesSync'), isFalse);
    expect(dFiles.contains('largeHeap'), isFalse);
    expect(dFiles.contains('clearAll'), isFalse);
    expect(dFiles.contains('backup_manifest.json'), isFalse);
    expect(dFiles.contains('scoped_backup_excel'), isFalse);
  });

  testWidgets('user search widget keeps user_id in dropdown', (tester) async {
    final users = sampleUsers();
    var query = '';
    int? selected = userA;
    await tester.pumpWidget(
      MaterialApp(
        home: StatefulBuilder(
          builder: (context, setState) {
            final filtered = filterDeviceManagerUsers(users, query);
            return Scaffold(
              body: Column(
                children: [
                  TextField(
                    key: const Key('device_eval_user_search'),
                    onChanged: (v) => setState(() => query = v),
                  ),
                  DropdownButton<int>(
                    key: const Key('device_eval_user_dropdown'),
                    value: filtered.any((u) => u['user_id'] == selected)
                        ? selected
                        : null,
                    items: [
                      for (final u in filtered)
                        DropdownMenuItem(
                          value: u['user_id'] as int,
                          child: Text(DeviceEvalUser.fromLocalRow(u).label),
                        ),
                    ],
                    onChanged: (v) => setState(() => selected = v),
                  ),
                ],
              ),
            );
          },
        ),
      ),
    );
    await tester.enterText(
      find.byKey(const Key('device_eval_user_search')),
      'أحمد البلوشي',
    );
    await tester.pump();
    await tester.tap(find.byKey(const Key('device_eval_user_dropdown')));
    await tester.pumpAndSettle();
    expect(find.textContaining('رقم $userA').evaluate().length, greaterThan(0));
    expect(find.textContaining('رقم $userB').evaluate().length, greaterThan(0));
  });
}
