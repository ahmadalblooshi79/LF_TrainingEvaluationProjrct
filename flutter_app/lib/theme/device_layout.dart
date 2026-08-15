import 'package:flutter/widgets.dart';

/// إطار التصميم المستهدف لهاتف Samsung S25 Ultra (منطقي):
/// Portrait 480×1040 — Landscape 1040×480 — نسبة ≈ 19.5:9
class DeviceLayout {
  DeviceLayout._();

  static const String product = String.fromEnvironment(
    'LF_PRODUCT',
    defaultValue: 'tablet',
  );

  static const String appVersion = String.fromEnvironment(
    'LF_APP_VERSION',
    defaultValue: '2.7.0',
  );

  static const double phoneDesignWidth = 480;
  static const double phoneDesignHeight = 1040;

  /// Pinch zoom bounds (phone build only).
  static const double phoneMinZoom = 0.75;
  static const double phoneMaxZoom = 2.75;

  /// بناء هاتف صريح عبر `--dart-define=LF_PRODUCT=phone`
  static bool get isPhoneBuild => product == 'phone';

  /// شاشة ضيقة تناسب إطار 480 (أو أقل من حد اللوح).
  static bool isPhoneWidth(BuildContext context) {
    final w = MediaQuery.sizeOf(context).width;
    return isPhoneBuild || w < 600;
  }

  static bool isCompactHeader(BuildContext context) => isPhoneWidth(context);

  /// مقياس نص مضغوط لملء شاشة الهاتف دون تكدّس مفرط.
  static double textScale(BuildContext context) {
    return isPhoneWidth(context) ? 0.90 : 1.0;
  }

  static EdgeInsets pagePadding(BuildContext context) {
    return isPhoneWidth(context)
        ? const EdgeInsets.fromLTRB(8, 6, 8, 6)
        : const EdgeInsets.all(16);
  }

  static double listSpacing(BuildContext context) {
    return isPhoneWidth(context) ? 6 : 10;
  }

  static double cardRadius(BuildContext context) {
    return isPhoneWidth(context) ? 8 : 12;
  }
}
