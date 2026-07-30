import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lf_training_evaluation/screens/login_screen.dart';

void main() {
  testWidgets('LoginScreen shows the login button', (WidgetTester tester) async {
    await tester.pumpWidget(
      const MaterialAppSmokeHost(child: LoginScreen()),
    );
    await tester.pump();

    expect(find.text('تسجيل الدخول'), findsOneWidget);
  });
}

/// Minimal RTL Material host so [LoginScreen] can be pumped in isolation
/// without booting the full app (routing/providers are exercised
/// separately via integration testing).
class MaterialAppSmokeHost extends StatelessWidget {
  const MaterialAppSmokeHost({super.key, required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      locale: const Locale('ar'),
      home: Directionality(textDirection: TextDirection.rtl, child: child),
    );
  }
}
