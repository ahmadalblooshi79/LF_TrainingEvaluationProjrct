import 'dart:convert';

import 'package:archive/archive.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lf_training_evaluation/services/eval_backup_assembler.dart';

Map<String, dynamic> _pending({
  required int id,
  required int exerciseId,
  required int userId,
  String? title,
  required String path,
  String unitKey = 'snipers',
  String unitLabel = 'سرية القناصة',
}) {
  return {
    'id': 'op-$id',
    'method': 'PUT',
    'path': path,
    'body': jsonEncode({
      'client_op_id': 'op-$id',
      'payload': {
        if (title != null) 'title': title,
        'unit_key': unitKey,
        'unit_label': unitLabel,
        'exercise_id': exerciseId,
        'rows': [
          {
            'row_kind': 'criterion',
            'element': 'عنصر',
            'max_val': '10',
            'acquired': '7',
            'notes': 'ملاحظة $id',
          }
        ],
      },
    }),
    'kind': 'save',
    'op_type': 'save_results',
    'created_at': '2026-09-27T12:00:00Z',
    'attempts': 0,
    'last_error': '',
    'sync_status': 'pending',
    'judge_id': userId,
    'user_id': userId,
    'exercise_id': exerciseId,
    'list_id': '$id',
    'eval_item_id': id,
    'media_local_path': '',
  };
}

Map<String, dynamic> _cacheDetail({
  required String key,
  required String title,
  int? exerciseId,
  bool saved = true,
}) {
  return {
    'cache_key': key,
    'json_body': jsonEncode({
      'title': title,
      if (exerciseId != null) 'exercise_id': exerciseId,
      'locally_modified': saved,
      'saved_payload': {
        'rows': [
          {
            'row_kind': 'criterion',
            'element': 'كاش',
            'max_val': '10',
            'acquired': '4',
            'notes': '',
          }
        ],
      },
    }),
    'sync_status': 'pending',
    'updated_at': '2026-09-27T12:00:00Z',
  };
}

EvalBackupScope get _currentB => const EvalBackupScope(
      exerciseId: 2,
      exerciseName: 'جاهزية المهمة 2026',
      userId: 3,
      judgeId: 3,
      judgeName: 'محكم',
      unitKey: 'snipers',
      unitName: 'سرية القناصة',
      deviceId: 'tab-1',
      appVersion: '2.7.31',
      createdAt: '2026-09-27T12:00:00Z',
    );

void main() {
  test('cross-exercise backup contains only current exercise B', () {
    final pkg = assembleEvalBackup(
      scope: _currentB,
      pendingRows: [
        _pending(
          id: 100,
          exerciseId: 1,
          userId: 3,
          title: 'قائمة التمرين القديم',
          path: '/api/tablet/evaluation-lists/x/100/results',
        ),
        _pending(
          id: 200,
          exerciseId: 2,
          userId: 3,
          title: 'إجراءات حالية 1',
          path: '/api/tablet/evaluation-lists/x/200/results',
        ),
        _pending(
          id: 201,
          exerciseId: 2,
          userId: 3,
          title: 'معضلة حالية 1',
          path: '/api/tablet/action-eval/201/results',
        ),
      ],
      cacheRows: [
        _cacheDetail(
          key: 'u3:evaluation_list_detail:snipers:100',
          title: 'كاش قديم',
          exerciseId: 1,
        ),
        _cacheDetail(
          key: 'u3:evaluation_list_detail:snipers:999',
          title: 'كاش بلا تمرين',
        ),
      ],
      mediaRows: [
        {
          'id': 'img-old',
          'local_path': '/tmp/old.jpg',
          'media_kind': 'image',
          'evaluation_list_item_id': 100,
          'bundle_action_eval_id': null,
          'exercise_id': 1,
        },
        {
          'id': 'img-new',
          'local_path': '/tmp/new.jpg',
          'media_kind': 'image',
          'evaluation_list_item_id': 200,
          'bundle_action_eval_id': null,
          'exercise_id': 2,
        },
        {
          'id': 'vid-new',
          'local_path': '/tmp/new.mp4',
          'media_kind': 'video',
          'evaluation_list_item_id': null,
          'bundle_action_eval_id': 201,
          'exercise_id': 2,
        },
      ],
      existingFilePaths: {'/tmp/old.jpg', '/tmp/new.jpg', '/tmp/new.mp4'},
    );

    expect(pkg.lists.map((e) => e.evalItemId), unorderedEquals([200, 201]));
    expect(pkg.lists.every((e) => e.exerciseId == 2), isTrue);
    expect(pkg.media.map((m) => m.id), unorderedEquals(['img-new', 'vid-new']));
    expect(pkg.media.any((m) => m.id == 'img-old'), isFalse);
    final manifest = pkg.toManifest();
    expect(manifest['exercise_id'], 2);
    final allIds = <int>[
      ...((manifest['action_evaluation_lists'] as List).map((e) => e['eval_item_id'] as int)),
      ...((manifest['dilemma_evaluation_lists'] as List).map((e) => e['eval_item_id'] as int)),
    ];
    expect(allIds, unorderedEquals([200, 201]));
    expect(allIds.contains(100), isFalse);
    expect(allIds.contains(999), isFalse);
  });

  test('one button mixed lists writes one xlsx per list in classified folders', () {
    final pkg = assembleEvalBackup(
      scope: _currentB,
      pendingRows: [
        _pending(
          id: 11,
          exerciseId: 2,
          userId: 3,
          title: 'إجراءات 1',
          path: '/api/tablet/evaluation-lists/x/11/results',
        ),
        _pending(
          id: 12,
          exerciseId: 2,
          userId: 3,
          title: 'إجراءات 2',
          path: '/api/tablet/evaluation-lists/x/12/results',
        ),
        _pending(
          id: 13,
          exerciseId: 2,
          userId: 3,
          title: 'إجراءات 3',
          path: '/api/tablet/evaluation-lists/x/13/results',
        ),
        _pending(
          id: 21,
          exerciseId: 2,
          userId: 3,
          title: 'معضلة 1',
          path: '/api/tablet/action-eval/21/results',
        ),
        _pending(
          id: 22,
          exerciseId: 2,
          userId: 3,
          title: 'معضلة 2',
          path: '/api/tablet/action-eval/22/results',
        ),
      ],
      cacheRows: const [],
      mediaRows: [
        {
          'id': 'img-11',
          'local_path': '/tmp/a.jpg',
          'media_kind': 'image',
          'evaluation_list_item_id': 11,
          'exercise_id': 2,
        },
        {
          'id': 'vid-21',
          'local_path': '/tmp/b.mp4',
          'media_kind': 'video',
          'bundle_action_eval_id': 21,
          'exercise_id': 2,
        },
      ],
      existingFilePaths: {'/tmp/a.jpg', '/tmp/b.mp4'},
    );

    expect(pkg.actionLists, hasLength(3));
    expect(pkg.dilemmaLists, hasLength(2));
    expect(pkg.lists, hasLength(5));
    expect(
      pkg.actionLists.every(
        (e) => e.excelRelPath.startsWith(
          '$kEvalBackupListsRoot/$kEvalBackupActionFolder/',
        ),
      ),
      isTrue,
    );
    expect(
      pkg.dilemmaLists.every(
        (e) => e.excelRelPath.startsWith(
          '$kEvalBackupListsRoot/$kEvalBackupDilemmaFolder/',
        ),
      ),
      isTrue,
    );
    expect(pkg.actionLists.every((e) => e.xlsxBytes.length > 100), isTrue);
    expect(pkg.dilemmaLists.every((e) => e.xlsxBytes.length > 100), isTrue);
    expect(pkg.imageCount, 1);
    expect(pkg.videoCount, 1);
    expect(
      pkg.media.firstWhere((m) => m.isImage).zipPath,
      startsWith('$kEvalBackupImagesRoot/$kEvalBackupActionFolder/'),
    );
    expect(
      pkg.media.firstWhere((m) => m.isVideo).zipPath,
      startsWith('$kEvalBackupVideosRoot/$kEvalBackupDilemmaFolder/'),
    );

    final xlsx = pkg.actionLists.first.xlsxBytes;
    final archive = ZipDecoder().decodeBytes(xlsx);
    expect(archive.findFile('xl/workbook.xml'), isNotNull);
    expect(
      pkg.actionLists.map((e) => e.excelRelPath).toList(),
      containsAll([
        '$kEvalBackupListsRoot/$kEvalBackupActionFolder/إجراءات 1.xlsx',
        '$kEvalBackupListsRoot/$kEvalBackupActionFolder/إجراءات 2.xlsx',
        '$kEvalBackupListsRoot/$kEvalBackupActionFolder/إجراءات 3.xlsx',
      ]),
    );
    expect(
      pkg.dilemmaLists.map((e) => e.excelRelPath).toList(),
      containsAll([
        '$kEvalBackupListsRoot/$kEvalBackupDilemmaFolder/معضلة 1.xlsx',
        '$kEvalBackupListsRoot/$kEvalBackupDilemmaFolder/معضلة 2.xlsx',
      ]),
    );
  });

  test('backup uses catalog system names when pending payload has no title', () {
    final pkg = assembleEvalBackup(
      scope: _currentB,
      pendingRows: [
        _pending(
          id: 557,
          exerciseId: 2,
          userId: 3,
          path: '/api/tablet/evaluation-lists/x/557/results',
        ),
        _pending(
          id: 561,
          exerciseId: 2,
          userId: 3,
          path: '/api/tablet/action-eval/561/results',
        ),
      ],
      cacheRows: [
        {
          'cache_key': 'u3:evaluation_lists:snipers:prep',
          'json_body': jsonEncode({
            'unit_key': 'snipers',
            'exercise_id': 2,
            'lists': [
              {'item_id': 557, 'title': 'تقييم القيادة والسيطرة'},
            ],
          }),
        },
        {
          'cache_key': 'u3:action_eval_lists:day1',
          'json_body': jsonEncode({
            'unit_key': 'snipers',
            'exercise_id': 2,
            'lists': [
              {'slot_id': 561, 'item_title': 'معضلة الإخلاء الطبي'},
            ],
          }),
        },
      ],
      mediaRows: const [],
    );

    expect(pkg.actionLists, hasLength(1));
    expect(pkg.dilemmaLists, hasLength(1));
    expect(pkg.actionLists.single.listName, 'تقييم القيادة والسيطرة');
    expect(pkg.dilemmaLists.single.listName, 'معضلة الإخلاء الطبي');
    expect(
      pkg.actionLists.single.excelRelPath,
      '$kEvalBackupListsRoot/$kEvalBackupActionFolder/تقييم القيادة والسيطرة.xlsx',
    );
    expect(
      pkg.dilemmaLists.single.excelRelPath,
      '$kEvalBackupListsRoot/$kEvalBackupDilemmaFolder/معضلة الإخلاء الطبي.xlsx',
    );
    expect(pkg.actionLists.single.excelRelPath.contains('557'), isFalse);
    expect(pkg.dilemmaLists.single.excelRelPath.contains('561'), isFalse);
  });

  test('backup prefers cache detail title over numeric Evaluation_id fallback', () {
    final pkg = assembleEvalBackup(
      scope: _currentB,
      pendingRows: [
        _pending(
          id: 200,
          exerciseId: 2,
          userId: 3,
          path: '/api/tablet/evaluation-lists/x/200/results',
        ),
      ],
      cacheRows: [
        _cacheDetail(
          key: 'u3:evaluation_list_detail:snipers:200',
          title: 'إجراءات حالية 1',
          exerciseId: 2,
        ),
      ],
      mediaRows: const [],
    );
    expect(pkg.actionLists.single.listName, 'إجراءات حالية 1');
    expect(
      pkg.actionLists.single.excelRelPath,
      endsWith('/إجراءات حالية 1.xlsx'),
    );
  });

  test('duplicate list names keep unique excel files', () {
    final pkg = assembleEvalBackup(
      scope: _currentB,
      pendingRows: [
        _pending(
          id: 11,
          exerciseId: 2,
          userId: 3,
          title: 'قائمة مشتركة',
          path: '/api/tablet/evaluation-lists/x/11/results',
        ),
        _pending(
          id: 12,
          exerciseId: 2,
          userId: 3,
          title: 'قائمة مشتركة',
          path: '/api/tablet/evaluation-lists/x/12/results',
        ),
      ],
      cacheRows: const [],
      mediaRows: const [],
    );
    final paths = pkg.actionLists.map((e) => e.excelRelPath).toSet();
    expect(paths, hasLength(2));
    expect(paths.any((p) => p.endsWith('/قائمة مشتركة.xlsx')), isTrue);
    expect(paths.any((p) => p.contains('_11.xlsx') || p.contains('_12.xlsx')), isTrue);
  });
}
