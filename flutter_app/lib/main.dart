import 'dart:async';

import 'package:flutter/material.dart';

import 'app.dart';
import 'services/api_client.dart';
import 'services/auth_service.dart';
import 'services/connectivity_service.dart';
import 'services/device_admin_service.dart';
import 'services/health_service.dart';
import 'services/notifications_badge_service.dart';
import 'services/offline_store.dart';
import 'services/sync_service.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // Offline-First: التخزين المحلي أولاً — لا ننتظر السيرفر لفتح التطبيق.
  await OfflineStore.instance.init();
  await ApiClient.instance.init();
  await ConnectivityService.instance.init();
  await DeviceAdminService.instance.init();
  await AuthService.instance.prepareLocalAuth();

  // فحص الصحة والمزامنة في الخلفية فقط (لا يمنع الواجهة ولا يسجّل دخولاً تلقائياً).
  unawaited(HealthService.instance.start());
  unawaited(SyncService.instance.start());
  unawaited(NotificationsBadgeService.instance.start());

  runApp(const LfTrainingEvaluationApp());
}
