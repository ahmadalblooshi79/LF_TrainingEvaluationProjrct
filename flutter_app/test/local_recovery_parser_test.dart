import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:lf_training_evaluation/services/local_recovery_parser.dart';
import 'package:lf_training_evaluation/services/local_recovery_xlsx.dart';

Map<String, dynamic> _pendingRow({
  required String id,
  String opType = 'save_results',
  String body = '',
  String syncStatus = 'pending',
  int attempts = 0,
  String lastError = '',
  int evalItemId = 10,
  int listId = 10,
  int userId = 3,
  int exerciseId = 1,
}) {
  return {
    'id': id,
    'method': 'POST',
    'path': '/api/tablet/evaluation-list/$evalItemId/save-results',
    'body': body,
    'kind': 'حفظ النتائج',
    'op_type': opType,
    'created_at': '2026-09-27T08:00:00.000Z',
    'attempts': attempts,
    'last_error': lastError,
    'sync_status': syncStatus,
    'judge_id': userId,
    'user_id': userId,
    'exercise_id': exerciseId,
    'list_id': '$listId',
    'eval_item_id': evalItemId,
    'media_local_path': '',
  };
}

String _saveBody({
  required String clientOpId,
  required List<Map<String, dynamic>> rows,
}) {
  return jsonEncode({
    'client_op_id': clientOpId,
    'judge_id': 3,
    'payload': {'rows': rows},
  });
}

RecoveryContext get _ctx => const RecoveryContext(
      exportTimestamp: '2026-09-27T08:01:00.000Z',
      appVersion: '2.7.25',
      deviceId: 'tablet-test-1',
      exerciseId: 1,
      judgeId: 3,
      userId: 3,
      judgeName: 'قاضي تجريبي',
      unit: 'وحدة الاختبار',
      databaseVersion: '4',
    );

void main() {
  test('A/B parse save_results pending body extracts scores and notes', () {
    final raw = _saveBody(
      clientOpId: 'op-1',
      rows: [
        {
          'row_kind': 'criterion',
          'element': 'Criterion A',
          'max_val': '10',
          'acquired': '7',
          'notes': '',
        },
        {
          'row_kind': 'criterion',
          'element': 'Criterion B',
          'max_val': '10',
          'acquired': '9',
          'notes': 'RECOVERY TEST 001',
        },
      ],
    );
    final parsed = parsePendingBody(raw);
    expect(parsed.parseSuccessful, isTrue);
    expect(parsed.clientOpId, 'op-1');
    expect(parsed.rows.length, 2);
    expect(parsed.rows[0].acquired, '7');
    expect(parsed.rows[0].element, 'Criterion A');
    expect(parsed.rows[0].maxVal, '10');
    expect(parsed.rows[1].acquired, '9');
    expect(parsed.rows[1].notes, 'RECOVERY TEST 001');
    expect(parsed.rowsWithScores, 2);
    expect(parsed.rowsWithNotes, 1);
  });

  test('C malformed body does not crash and marks parse failed', () {
    final parsed = parsePendingBody('{not-json');
    expect(parsed.parseSuccessful, isFalse);
    expect(parsed.rawBody, '{not-json');
    expect(parsed.rows, isEmpty);
    final scan = assembleRecoveryScan(
      context: _ctx,
      pendingRows: [
        _pendingRow(id: 'bad', body: '{not-json', evalItemId: 99),
      ],
      cacheRows: const [],
      mediaRows: const [],
    );
    expect(scan.pendingOps.single.parsed.parseSuccessful, isFalse);
    expect(scan.saveResultsOps, isNotEmpty);
  });

  test('D pending and cache copies are both preserved', () {
    final rows = [
      {
        'row_kind': 'criterion',
        'element': 'A',
        'max_val': '10',
        'acquired': '7',
        'notes': 'RECOVERY TEST 001',
      },
    ];
    final body = _saveBody(clientOpId: 'op-keep', rows: rows);
    final scan = assembleRecoveryScan(
      context: _ctx,
      pendingRows: [
        _pendingRow(id: 'op-keep', body: body, evalItemId: 180),
      ],
      cacheRows: [
        {
          'cache_key': 'u3:evaluation_list_detail:unit:180',
          'json_body': jsonEncode({
            'saved_rows': rows,
            'saved_payload': {'rows': rows},
            'locally_modified': true,
          }),
          'updated_at': '2026-09-27T08:00:00.000Z',
          'sync_status': 'pending',
        },
      ],
      mediaRows: const [],
    );
    expect(scan.saveResultsOps.length, 1);
    expect(scan.cacheEvaluations.length, 1);
    final flat = flattenEvaluationResultRows(scan);
    expect(flat.where((r) => r.recoverySource == 'PENDING_OP'), isNotEmpty);
    expect(flat.where((r) => r.recoverySource == 'CACHE'), isNotEmpty);
    final ident = scan.identities.singleWhere((i) => i.evalItemId == 180);
    expect(ident.pendingCopyExists, isTrue);
    expect(ident.cacheCopyExists, isTrue);
  });

  test('E source mismatch is flagged and not auto-merged', () {
    final pendingRows = [
      {
        'row_kind': 'criterion',
        'element': 'A',
        'max_val': '10',
        'acquired': '7',
        'notes': 'pending notes',
      },
    ];
    final cacheRows = [
      {
        'row_kind': 'criterion',
        'element': 'A',
        'max_val': '10',
        'acquired': '1',
        'notes': 'cache notes',
      },
    ];
    final scan = assembleRecoveryScan(
      context: _ctx,
      pendingRows: [
        _pendingRow(
          id: 'op-mm',
          body: _saveBody(clientOpId: 'op-mm', rows: pendingRows),
          evalItemId: 180,
        ),
      ],
      cacheRows: [
        {
          'cache_key': 'u3:evaluation_list_detail:unit:180',
          'json_body': jsonEncode({
            'saved_rows': cacheRows,
            'saved_payload': {'rows': cacheRows},
            'locally_modified': true,
          }),
          'updated_at': '2026-09-27T08:00:00.000Z',
          'sync_status': 'pending',
        },
      ],
      mediaRows: const [],
    );
    final ident = scan.identities.singleWhere((i) => i.evalItemId == 180);
    expect(ident.sourceMismatch, isTrue);
    expect(ident.recoveryStatus, 'SOURCE MISMATCH');
    expect(scan.counts['source_mismatches'], 1);
    final flat = flattenEvaluationResultRows(scan);
    expect(flat.where((r) => r.row.acquired == '7'), isNotEmpty);
    expect(flat.where((r) => r.row.acquired == '1'), isNotEmpty);
  });

  test('F missing media file is recorded and export assembly continues', () {
    final scan = assembleRecoveryScan(
      context: _ctx,
      pendingRows: [
        _pendingRow(
          id: 'op-media',
          body: _saveBody(
            clientOpId: 'op-media',
            rows: [
              {
                'row_kind': 'criterion',
                'element': 'A',
                'max_val': '10',
                'acquired': '7',
                'notes': '',
              },
            ],
          ),
          evalItemId: 180,
        ),
      ],
      cacheRows: const [],
      mediaRows: [
        {
          'id': 'm-missing',
          'client_uuid': 'cu-1',
          'user_id': 3,
          'exercise_id': 1,
          'evaluation_list_item_id': 180,
          'bundle_action_eval_id': null,
          'row_index': 0,
          'media_kind': 'photo',
          'local_path': '/tmp/does-not-exist.jpg',
          'original_filename': 'shot.jpg',
          'local_filename': 'shot.jpg',
          'file_size': 12,
          'sync_status': 'failed',
          'server_confirmed': 0,
          'attempt_count': 3,
          'last_error': 'upload failed',
          'sheet_cache_key': 'u3:evaluation_list_detail:unit:180',
        },
      ],
      fileStat: (path) => const RecoveryFileStat(exists: false, size: 0),
    );
    expect(scan.media.single.fileExists, isFalse);
    expect(scan.counts['missing_physical_media'], 1);
    expect(scan.pendingOps, isNotEmpty);
  });

  test('G failed pending operation is included', () {
    final scan = assembleRecoveryScan(
      context: _ctx,
      pendingRows: [
        _pendingRow(
          id: 'op-fail',
          body: _saveBody(
            clientOpId: 'op-fail',
            rows: [
              {
                'row_kind': 'criterion',
                'element': 'A',
                'max_val': '10',
                'acquired': '8',
                'notes': 'fail keep',
              },
            ],
          ),
          syncStatus: 'failed',
          attempts: 4,
          lastError: 'timeout',
          evalItemId: 180,
        ),
      ],
      cacheRows: const [],
      mediaRows: const [],
    );
    expect(scan.pendingOps.single.syncStatus, 'failed');
    expect(scan.counts['failed_operations'], 1);
    expect(scan.focusEvalItem(180).lastError, 'timeout');
    expect(scan.focusEvalItem(180).attempts, 4);
  });

  test('H raw pending body is preserved exactly', () {
    const raw =
        '{"client_op_id":"keep-raw","payload":{"rows":[{"row_kind":"criterion","element":"A","max_val":"10","acquired":"7","notes":"RECOVERY TEST 001"}]}}';
    final parsed = parsePendingBody(raw);
    expect(parsed.rawBody, raw);
    expect(identical(parsed.rawBody, raw) || parsed.rawBody == raw, isTrue);
    final op = RecoveredPendingOp.fromRow(_pendingRow(id: 'keep-raw', body: raw));
    expect(op.rawBody, raw);
  });

  test('I recovery scanner SQL is SELECT-only', () {
    expect(kRecoverySelectOnlySql, isNotEmpty);
    for (final sql in kRecoverySelectOnlySql) {
      expect(recoverySqlIsReadOnly(sql), isTrue, reason: sql);
    }
  });

  test('J excel/json assembly works without network', () {
    final body = _saveBody(
      clientOpId: 'offline',
      rows: [
        {
          'row_kind': 'criterion',
          'element': 'Criterion A',
          'max_val': '10',
          'acquired': '7',
          'notes': 'RECOVERY TEST 001',
        },
      ],
    );
    final scan = assembleRecoveryScan(
      context: _ctx,
      pendingRows: [_pendingRow(id: 'offline', body: body, evalItemId: 180)],
      cacheRows: const [],
      mediaRows: const [],
    );
    final xlsx = buildSimpleXlsx({
      '01_Export_Info': [
        ['Field', 'Value'],
        ['Device ID', scan.context.deviceId],
      ],
      '02_Evaluation_Results': [
        ['acquired', 'notes'],
        ['7', 'RECOVERY TEST 001'],
      ],
    });
    expect(xlsx.length, greaterThan(20));
    expect(xlsx[0], 0x50); // P
    expect(xlsx[1], 0x4B); // K
    expect(scan.focusEvalItem(180).pendingSaveFound, isTrue);
    expect(scan.focusEvalItem(180).rowsWithNotes, 1);
    expect(scan.focusEvalItem(180).rowsWithScores, 1);
  });

  test('eval item 180 focus reports pending save independently of UI', () {
    final body = _saveBody(
      clientOpId: 'e180',
      rows: [
        {
          'row_kind': 'criterion',
          'element': 'A',
          'max_val': '10',
          'acquired': '7',
          'notes': '',
        },
        {
          'row_kind': 'criterion',
          'element': 'B',
          'max_val': '10',
          'acquired': '9',
          'notes': 'RECOVERY TEST 001',
        },
      ],
    );
    final scan = assembleRecoveryScan(
      context: _ctx,
      pendingRows: [_pendingRow(id: 'e180', body: body, evalItemId: 180)],
      cacheRows: const [],
      mediaRows: [
        {
          'id': 'img1',
          'media_kind': 'photo',
          'local_path': '/x/a.jpg',
          'evaluation_list_item_id': 180,
          'row_index': 0,
        },
        {
          'id': 'img2',
          'media_kind': 'photo',
          'local_path': '/x/b.jpg',
          'evaluation_list_item_id': 180,
          'row_index': 1,
        },
      ],
      fileStat: (_) => const RecoveryFileStat(exists: true, size: 50),
    );
    final f = scan.focusEvalItem(180);
    expect(f.pendingSaveFound, isTrue);
    expect(f.rowsFound, 2);
    expect(f.rowsWithScores, 2);
    expect(f.rowsWithNotes, 1);
    expect(f.associatedMedia, 2);
  });
}
