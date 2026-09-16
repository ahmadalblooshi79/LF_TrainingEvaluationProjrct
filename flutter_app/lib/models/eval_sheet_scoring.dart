import 'eval_sheet.dart';

const kNonApprovableGrades = {'راسب', 'مقبول', 'متوسط'};

bool acquiredIsNa(String acquired) {
  final s = acquired.trim().toLowerCase();
  return s == 'na' || s == 'n/a' || s == 'لا ينطبق';
}

double? parseEvalNum(String s) {
  final t = s.trim().replaceAll(',', '.');
  if (t.isEmpty) return null;
  return double.tryParse(t);
}

String gradeFromPct(double? p) {
  if (p == null) return 'غير محسوب';
  if (p < 60) return 'راسب';
  if (p < 70) return 'مقبول';
  if (p < 80) return 'جيد';
  if (p < 90) return 'جيد جداً';
  return 'ممتاز';
}

double? rowPercent({
  required EvalRowInput input,
  required double? templateMax,
}) {
  if (input.rowKind == 'section') return null;
  if (input.acquired.isEmpty || acquiredIsNa(input.acquired)) return null;
  final n = parseEvalNum(input.acquired);
  if (n == null) return null;
  final mx = templateMax;
  if (mx != null && n > mx + 1e-6) return null;
  return (n / (mx ?? 5)) * 100;
}

({double sumMax, double sumAcq, bool anyAcq}) evalSheetTotals({
  required List<EvalRowInput> rows,
  required double? Function(int index) templateMax,
}) {
  double sumMax = 0, sumAcq = 0;
  var anyAcq = false;
  for (var i = 0; i < rows.length; i++) {
    if (rows[i].rowKind == 'section') continue;
    if (acquiredIsNa(rows[i].acquired)) continue;
    final mx = templateMax(i);
    if (mx != null) sumMax += mx;
    final acq = rows[i].acquired;
    if (acq.isEmpty) continue;
    final n = parseEvalNum(acq);
    if (n == null) continue;
    if (mx != null && n > mx + 1e-6) continue;
    sumAcq += n;
    anyAcq = true;
  }
  return (sumMax: sumMax, sumAcq: sumAcq, anyAcq: anyAcq);
}

List<int> rowsMissingRequiredNotes({
  required List<EvalRowInput> rows,
  required double? Function(int index) percentOf,
}) {
  final out = <int>[];
  for (var i = 0; i < rows.length; i++) {
    if (rows[i].rowKind == 'section') continue;
    final grade = gradeFromPct(percentOf(i));
    if (!kNonApprovableGrades.contains(grade)) continue;
    if (rows[i].notes.trim().isEmpty) out.add(i);
  }
  return out;
}
