import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// طريقة مزامنة التابلت مع السيرفر على الشبكة المحلية (Wi‑Fi / Ethernet).
enum TabletSyncMode {
  /// رفع + تنزيل تلقائياً عند الاتصال بشبكة محلية والوصول للسيرفر.
  automatic,

  /// المزامنة فقط عند ضغط المحكم (شاشة إدارة المزامنة).
  manual,
}

/// تفضيلات المزامنة — محفوظة على الجهاز.
class SyncPreferences {
  SyncPreferences._internal();
  static final SyncPreferences instance = SyncPreferences._internal();

  static const String kSyncModeKey = 'tablet_sync_mode';

  final ValueNotifier<TabletSyncMode> mode =
      ValueNotifier<TabletSyncMode>(TabletSyncMode.manual);

  bool _ready = false;

  Future<void> init() async {
    if (_ready) return;
    final prefs = await SharedPreferences.getInstance();
    final raw = (prefs.getString(kSyncModeKey) ?? '').trim();
    mode.value = raw == 'automatic'
        ? TabletSyncMode.automatic
        : TabletSyncMode.manual;
    _ready = true;
  }

  Future<void> setMode(TabletSyncMode next) async {
    mode.value = next;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(
      kSyncModeKey,
      next == TabletSyncMode.automatic ? 'automatic' : 'manual',
    );
  }

  bool get isAutomatic => mode.value == TabletSyncMode.automatic;
}
