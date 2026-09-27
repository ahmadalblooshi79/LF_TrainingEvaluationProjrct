import 'dart:convert';

import 'package:archive/archive.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lf_training_evaluation/services/eval_excel_export.dart';
import 'package:lf_training_evaluation/services/local_recovery_parser.dart';
import 'package:lf_training_evaluation/services/local_recovery_xlsx.dart';

void main() {
  test('excel metadata sheet is hidden and keyed', () {
    final xlsx = buildSimpleXlsx(
      {
        'تقييم القيادة': [
          ['عناصر التقييم', 'القصوى', 'المكتسبة', 'الملاحظات'],
          ['قيادة', '10', '7', 'جيد'],
        ],
        kSystemMetadataSheet: [
          ['key', 'value'],
          ['export_format_version', kExcelExportFormatVersion],
          ['eval_item_id', '180'],
          ['unit_name', 'سرية القناصة'],
          ['evaluation_list_name', 'تقييم القيادة والسيطرة'],
        ],
      },
      hiddenSheetNames: {kSystemMetadataSheet},
    );
    expect(xlsx.length, greaterThan(100));
    final archive = ZipDecoder().decodeBytes(xlsx);
    final workbook = archive.findFile('xl/workbook.xml');
    expect(workbook, isNotNull);
    final xml = utf8.decode(workbook!.content as List<int>);
    expect(xml.contains(kSystemMetadataSheet), isTrue);
    expect(xml.contains('state="hidden"'), isTrue);
    final metaSheet = archive.findFile('xl/worksheets/sheet2.xml');
    expect(metaSheet, isNotNull);
    final metaXml = utf8.decode(metaSheet!.content as List<int>);
    expect(metaXml.contains('export_format_version'), isTrue);
  });

  test('drafts prefer pending over cache without dropping either', () {
    final pendingBody = jsonEncode({
      'client_op_id': 'op-180',
      'payload': {
        'rows': [
          {
            'row_kind': 'criterion',
            'element': 'A',
            'max_val': '10',
            'acquired': '7',
            'notes': 'pending',
          }
        ],
        'title': 'تقييم القيادة والسيطرة',
        'unit_label': 'سرية القناصة',
      },
    });
    final cacheBody = jsonEncode({
      'title': 'تقييم القيادة والسيطرة',
      'locally_modified': true,
      'saved_payload': {
        'rows': [
          {
            'row_kind': 'criterion',
            'element': 'A',
            'max_val': '10',
            'acquired': '1',
            'notes': 'cache',
          }
        ],
      },
    });
    final scan = assembleRecoveryScan(
      context: const RecoveryContext(
        exportTimestamp: '2026-09-27T00:00:00Z',
        appVersion: '2.7.27',
        deviceId: 'tab-1',
        judgeName: 'محكم',
        unit: 'سرية القناصة',
        databaseVersion: '4',
        exerciseId: 1,
        judgeId: 3,
        userId: 3,
      ),
      pendingRows: [
        {
          'id': 'op-180',
          'method': 'PUT',
          'path': '/api/tablet/evaluation-lists/x/180/results',
          'body': pendingBody,
          'kind': 'save',
          'op_type': 'save_results',
          'created_at': '2026-09-27T00:00:00Z',
          'attempts': 0,
          'last_error': '',
          'sync_status': 'pending',
          'judge_id': 3,
          'user_id': 3,
          'exercise_id': 1,
          'list_id': 'x',
          'eval_item_id': 180,
          'media_local_path': '',
        }
      ],
      cacheRows: [
        {
          'cache_key': 'u3:evaluation_list_detail:snipers:180',
          'json_body': cacheBody,
          'sync_status': 'pending',
          'updated_at': '2026-09-27T00:00:00Z',
        }
      ],
      mediaRows: const [],
    );
    final drafts = EvalExcelExportService.instance.draftsFromScan(scan);
    expect(drafts, hasLength(1));
    expect(drafts.first.evalItemId, 180);
    expect(drafts.first.rows.first.notes, 'pending');
    expect(drafts.first.pending, isNotNull);
    expect(drafts.first.cache, isNotNull);
    expect(drafts.first.sourceMismatch, isTrue);
  });
}
