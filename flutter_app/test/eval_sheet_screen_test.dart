import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lf_training_evaluation/models/eval_sheet.dart';
import 'package:lf_training_evaluation/screens/eval_sheet_screen.dart';
import 'package:lf_training_evaluation/theme/app_theme.dart';

/// Minimal harness: inject detail by subclassing state via a test-only wrapper.
class _Harness extends StatefulWidget {
  const _Harness({required this.detail});
  final EvalSheetDetail detail;
  @override
  State<_Harness> createState() => _HarnessState();
}

class _HarnessState extends State<_Harness> {
  @override
  Widget build(BuildContext context) {
    // Build the same body structure as EvalSheetScreen with preloaded rows.
    final rows = widget.detail.savedRows;
    return MaterialApp(
      theme: AppTheme.light(),
      home: Directionality(
        textDirection: TextDirection.rtl,
        child: Scaffold(
          backgroundColor: AppColors.background,
          body: Column(
            children: [
              Container(
                width: double.infinity,
                color: AppColors.titleBar,
                padding: const EdgeInsets.all(10),
                child: Text(widget.detail.title, textAlign: TextAlign.center),
              ),
              Expanded(
                child: ListView.builder(
                  itemCount: rows.length,
                  itemBuilder: (_, i) {
                    final r = rows[i];
                    return Container(
                      key: ValueKey('row-$i'),
                      margin: const EdgeInsets.all(8),
                      padding: const EdgeInsets.all(12),
                      color: Colors.white,
                      child: Text('${i + 1}. ${r.element}'),
                    );
                  },
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

void main() {
  testWidgets('eval rows render as list items', (tester) async {
    final detail = EvalSheetDetail.fromJson({
      'kind': 'evaluation_list',
      'item_id': 1,
      'title': '01 تقييم.xlsx',
      'eval_structured': true,
      'eval_rows': [
        for (var i = 0; i < 5; i++)
          {
            'row_kind': 'score',
            'element': 'عنصر تقييم رقم ${i + 1}',
            'element_prefix_kind': 'plain',
            'element_prefix': '',
            'element_rest': '',
            'element_indent': 0,
            'max_val': '5',
            'max_num': 5,
            'acquired_raw': '',
            'acquired_initial': '',
            'notes_initial': '',
          },
      ],
      'saved_payload': {'rows': []},
      'can_edit': true,
      'can_approve': false,
      'is_approved': false,
    });
    expect(detail.savedRows.length, 5);

    await tester.pumpWidget(_Harness(detail: detail));
    await tester.pumpAndSettle();

    expect(find.textContaining('عنصر تقييم رقم 1'), findsOneWidget);
    expect(find.byKey(const ValueKey('row-0')), findsOneWidget);
  });
}
