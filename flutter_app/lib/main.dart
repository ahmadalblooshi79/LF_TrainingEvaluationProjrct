import 'dart:async';

import 'package:flutter/material.dart';

import 'app.dart';
import 'services/api_client.dart';
import 'services/auth_service.dart';
import 'services/connectivity_service.dart';
import 'services/offline_store.dart';
import 'services/sync_service.dart';
import 'services/tablet_repository.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  await ApiClient.instance.init();
  await OfflineStore.instance.init();
  await ConnectivityService.instance.init();
  await AuthService.instance.restoreFromCache();

  // Best-effort: confirm the cached session cookie is still valid and start
  // flushing any writes queued while offline. Neither call blocks startup.
  unawaited(AuthService.instance.refreshFromServer());
  unawaited(SyncService.instance.start());
  if (AuthService.instance.isLoggedIn) {
    unawaited(TabletRepository.instance.prefetchForOffline());
  }

  runApp(const LfTrainingEvaluationApp());
}
