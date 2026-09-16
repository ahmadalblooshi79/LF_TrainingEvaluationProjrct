import 'package:flutter_test/flutter_test.dart';
import 'package:lf_training_evaluation/models/eval_sheet.dart';
import 'package:lf_training_evaluation/models/eval_sheet_scoring.dart';

EvalRowInput _score({
  required String acquired,
  String notes = '',
  String maxVal = '5',
}) {
  return EvalRowInput(
    rowKind: 'score',
    element: 'بند',
    maxVal: maxVal,
    acquired: acquired,
    notes: notes,
  );
}

void main() {
  test('NA acquired excludes that row max from the total', () {
    final rows = [
      _score(acquired: '4', maxVal: '5'),
      _score(acquired: 'na', maxVal: '5'),
    ];
    final t = evalSheetTotals(rows: rows, templateMax: (_) => 5);
    expect(t.sumMax, 5);
    expect(t.sumAcq, 4);
    expect(t.anyAcq, isTrue);
  });

  test('fail row without notes blocks approval', () {
    final rows = [
      _score(acquired: '2', maxVal: '10'),
      _score(acquired: '8', maxVal: '10'),
    ];
    final missing = rowsMissingRequiredNotes(
      rows: rows,
      percentOf: (i) => rowPercent(input: rows[i], templateMax: 10),
    );
    expect(missing, [0]);
  });

  test('fail row with its own notes is allowed', () {
    final rows = [
      _score(acquired: '2', maxVal: '10', notes: 'ضعف التنفيذ'),
    ];
    final missing = rowsMissingRequiredNotes(
      rows: rows,
      percentOf: (i) => rowPercent(input: rows[i], templateMax: 10),
    );
    expect(missing, isEmpty);
  });

  test('notes on a good row do not cover a failing row', () {
    final rows = [
      _score(acquired: '2', maxVal: '10'),
      _score(acquired: '10', maxVal: '10', notes: 'ملاحظة عامة'),
    ];
    final missing = rowsMissingRequiredNotes(
      rows: rows,
      percentOf: (i) => rowPercent(input: rows[i], templateMax: 10),
    );
    expect(missing, [0]);
  });
}
