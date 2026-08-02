import 'dart:async';

import 'package:flutter/material.dart';

import 'app.dart';
import 'services/api_client.dart';
import 'services/auth_service.dart';
import 'services/connectivity_service.dart';
import 'services/health_service.dart';
import 'services/offline_store.dart';
import 'services/sync_service.dart';
import 'services/tablet_repository.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  await ApiClient.instance.init();
  await OfflineStore.instance.init();
  await ConnectivityService.instance.init();
  await AuthService.instance.restoreFromCache();

  // Health check قصير يحدد وضع Offline دون تعليق الواجهة.
  unawaited(HealthService.instance.start());
  unawaited(SyncService.instance.start());
  if (AuthService.instance.isLoggedIn) {
    unawaited(AuthService.instance.refreshFromServer());
    unawaited(TabletRepository.instance.prefetchForOffline());
  }

  runApp(const LfTrainingEvaluationApp());
}
