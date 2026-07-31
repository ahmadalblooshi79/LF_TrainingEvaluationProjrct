import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:lf_training_evaluation/models/eval_sheet.dart';

void main() {
  test('EvalSheetDetail.fromJson seeds rows from eval_rows', () {
    final json = jsonDecode(r'''
{
  "ok": true,
  "kind": "evaluation_list",
  "item_id": 1,
  "title": "test.xlsx",
  "unit_key": "ul_brigade_grp_cmd",
  "unit_label": "قيادة مجموعة اللواء",
  "phase_key": "opening",
  "eval_structured": true,
  "eval_rows": [
    {
      "row_kind": "score",
      "element": "بند تجريبي",
      "element_prefix_kind": "plain",
      "element_prefix": "",
      "element_rest": "بند تجريبي",
      "element_indent": 0,
      "max_val": "5",
      "max_num": 5,
      "acquired_raw": "",
      "acquired_initial": "4",
      "notes_initial": ""
    }
  ],
  "acquired_options": [["", "—"], ["4", "4"]],
  "saved_payload": {"rows": []},
  "can_edit": true,
  "can_approve": false,
  "is_approved": false,
  "workflow": {"label": "", "reopened": false}
}
''') as Map<String, dynamic>;
    final d = EvalSheetDetail.fromJson(json);
    expect(d.evalRows.length, 1);
    expect(d.savedRows.length, 1);
    expect(d.savedRows.first.element, 'بند تجريبي');
    expect(d.savedRows.first.acquired, '4');
  });

  test('fromJson with Map from dynamic list like JS', () {
    final raw = <dynamic>[
      <dynamic, dynamic>{
        'row_kind': 'score',
        'element': 'X',
        'max_val': '5',
        'max_num': 5,
        'acquired_initial': '',
        'notes_initial': '',
        'element_prefix_kind': 'plain',
        'element_prefix': '',
        'element_rest': 'X',
        'element_indent': 0,
        'acquired_raw': '',
      }
    ];
    final json = <String, dynamic>{
      'eval_rows': raw,
      'eval_structured': true,
      'title': 't',
      'saved_payload': <String, dynamic>{},
    };
    final d = EvalSheetDetail.fromJson(json);
    expect(d.evalRows.length, 1, reason: 'whereType Map must accept Map<dynamic,dynamic>');
    expect(d.savedRows.length, 1);
  });
}
