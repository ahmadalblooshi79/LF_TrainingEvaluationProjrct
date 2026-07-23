import 'package:flutter_test/flutter_test.dart';
import 'package:lf_training_evaluation/main.dart';

void main() {
  testWidgets('MainPage shows evaluation lists button', (WidgetTester tester) async {
    await tester.pumpWidget(const LfTrainingEvaluationApp());
    await tester.pumpAndSettle();

    expect(find.text('قوائم التقييم'), findsOneWidget);
  });
}
