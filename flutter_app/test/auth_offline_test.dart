import 'package:flutter_test/flutter_test.dart';
import 'package:lf_training_evaluation/services/auth_service.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
  });

  test('credentialDigest is stable for same inputs and not plain password', () async {
    final a = await credentialDigest('Judge1', 'secret');
    final b = await credentialDigest('Judge1', 'secret');
    final c = await credentialDigest('Judge1', 'other');
    expect(a, b);
    expect(a, isNot(c));
    expect(a.contains('secret'), isFalse);
    expect(a.length, greaterThanOrEqualTo(32));
  });

  test('AuthService starts logged out', () {
    expect(AuthService.instance.isLoggedIn, isFalse);
  });
}
