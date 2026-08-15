import 'dart:async';

import 'package:flutter/foundation.dart';

import 'api_client.dart';
import 'auth_service.dart';
import 'health_service.dart';

/// عدّاد الإشعارات غير المقروءة لشارة أيقونة الجرس.
class NotificationsBadgeService {
  NotificationsBadgeService._();
  static final NotificationsBadgeService instance = NotificationsBadgeService._();

  final ValueNotifier<int> unreadCount = ValueNotifier<int>(0);
  Timer? _timer;
  bool _started = false;

  Future<void> start() async {
    if (_started) return;
    _started = true;
    AuthService.instance.addListener(_onAuth);
    HealthService.instance.serverReachable.addListener(_onHealth);
    await refresh();
    _timer = Timer.periodic(const Duration(seconds: 45), (_) {
      unawaited(refresh());
    });
  }

  void dispose() {
    _timer?.cancel();
    AuthService.instance.removeListener(_onAuth);
    HealthService.instance.serverReachable.removeListener(_onHealth);
  }

  void _onAuth() {
    if (!AuthService.instance.isLoggedIn) {
      unreadCount.value = 0;
      return;
    }
    unawaited(refresh());
  }

  void _onHealth() {
    if (HealthService.instance.serverReachable.value) {
      unawaited(refresh());
    }
  }

  void setUnread(int n) {
    unreadCount.value = n < 0 ? 0 : n;
  }

  Future<void> refresh() async {
    if (!AuthService.instance.isLoggedIn) {
      unreadCount.value = 0;
      return;
    }
    try {
      final data = await ApiClient.instance.get(
        '/api/tablet/notifications',
        timeout: const Duration(seconds: 20),
      );
      final n = (data['unread_count'] as num?)?.toInt();
      if (n != null) {
        unreadCount.value = n;
        return;
      }
      final list = (data['notifications'] as List?) ?? const [];
      unreadCount.value = list
          .whereType<Map>()
          .where((m) => m['is_read'] != true)
          .length;
    } catch (_) {
      // أبقِ القيمة السابقة عند فشل الشبكة
    }
  }

  /// يسجّل تنبيهاً في سجل الإشعارات بعد مزامنة/تحديث ناجح ثم يحدّث الشارة.
  Future<void> reportSyncEvent({
    required String kind,
    String? detail,
  }) async {
    if (!AuthService.instance.isLoggedIn) return;
    try {
      final data = await ApiClient.instance.post(
        '/api/tablet/notifications/sync-event',
        body: {
          'kind': kind,
          if (detail != null && detail.trim().isNotEmpty) 'detail': detail.trim(),
        },
        timeout: const Duration(seconds: 20),
      );
      final n = (data['unread_count'] as num?)?.toInt();
      if (n != null) {
        unreadCount.value = n;
      } else {
        await refresh();
      }
    } catch (_) {
      await refresh();
    }
  }
}
