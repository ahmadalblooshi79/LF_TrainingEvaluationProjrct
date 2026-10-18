import '../models/eval_sheet.dart';
import 'device_eval_manager_models.dart';
import 'local_recovery_xlsx.dart';

List<int> buildLocalEvalListXlsx({
  required DeviceEvalListSummary summary,
  required DeviceEvalUser user,
  required String exerciseName,
  required List<EvalRowInput> rows,
  EvalSheetDetail? detail,
}) {
  final kindLabel = summary.kind == DeviceEvalKind.procedure
      ? kDeviceEvalProcedureTab
      : kDeviceEvalDilemmaTab;
  var totalMax = 0.0;
  var totalAcquired = 0.0;
  final table = <List<String>>[
    ['قائمة التقييم', summary.title],
    ['النوع', kindLabel],
    ['التمرين', exerciseName],
    ['exercise_id', '${summary.exerciseId}'],
    ['user_id', '${user.userId}'],
    ['evaluation_list_id', '${summary.listId}'],
    ['المحكم', user.displayName.isNotEmpty ? user.displayName : user.label],
    ['الوحدة', summary.unitLabel.isNotEmpty ? summary.unitLabel : summary.unitKey],
    ['المرحلة', summary.phaseKey],
    ['الحالة', summary.statusLabel],
    if ((detail?.dilemmaDescription ?? '').trim().isNotEmpty)
      ['وصف المعضلة', detail?.dilemmaDescription ?? ''],
    if ((detail?.dilemmaRequirements ?? '').trim().isNotEmpty)
      ['متطلبات المعضلة', detail?.dilemmaRequirements ?? ''],
    const [],
    const ['م', 'نوع الصف', 'عناصر التقييم', 'القصوى', 'المكتسبة', 'الملاحظات'],
  ];
  var i = 1;
  for (final row in rows) {
    table.add([
      '$i',
      row.rowKind,
      row.element,
      row.maxVal,
      row.acquired,
      row.notes,
    ]);
    totalMax += _asNum(row.maxVal);
    totalAcquired += _asNum(row.acquired);
    i++;
  }
  final pct =
      totalMax <= 0 ? '' : ((totalAcquired / totalMax) * 100).toStringAsFixed(1);
  table.add(const []);
  table.add([
    'المجموع',
    '',
    '',
    _fmt(totalMax),
    _fmt(totalAcquired),
    '',
  ]);
  table.add(['النسبة %', '', '', '', pct, '']);
  var sheet = summary.title.trim();
  if (sheet.isEmpty) sheet = 'Evaluation';
  if (sheet.length > 31) sheet = sheet.substring(0, 31);
  return buildSimpleXlsx({sheet: table});
}

double _asNum(String raw) {
  final n = double.tryParse(raw.trim().replaceAll(',', '.'));
  return n != null && n.isFinite ? n : 0;
}

String _fmt(double n) => n == n.roundToDouble() ? '${n.round()}' : n.toStringAsFixed(1);
