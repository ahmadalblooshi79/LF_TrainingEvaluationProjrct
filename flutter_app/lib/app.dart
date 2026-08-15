import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import 'screens/action_eval_lists_screen.dart';
import 'screens/device_admin_hub_screen.dart';
import 'screens/device_setup_screen.dart';
import 'screens/eval_sheet_screen.dart';
import 'screens/evaluation_lists_screen.dart';
import 'screens/exercise_details_screen.dart';
import 'screens/flow_screen.dart';
import 'screens/home_screen.dart';
import 'screens/library_screen.dart';
import 'screens/login_screen.dart';
import 'screens/messages_screen.dart';
import 'screens/notifications_screen.dart';
import 'screens/positives_negatives_screen.dart';
import 'screens/objectives_screen.dart';
import 'screens/server_connect_screen.dart';
import 'screens/settings_screen.dart';
import 'screens/sync_status_screen.dart';
import 'services/auth_service.dart';
import 'services/device_admin_service.dart';
import 'theme/app_theme.dart';
import 'theme/device_layout.dart';
import 'widgets/phone_zoom_shell.dart';

class _AuthRefresh extends ChangeNotifier {
  _AuthRefresh() {
    AuthService.instance.addListener(notifyListeners);
    DeviceAdminService.instance.addListener(notifyListeners);
  }

  @override
  void dispose() {
    AuthService.instance.removeListener(notifyListeners);
    DeviceAdminService.instance.removeListener(notifyListeners);
    super.dispose();
  }
}

final _authRefresh = _AuthRefresh();

final GoRouter _router = GoRouter(
  initialLocation: '/login',
  refreshListenable: _authRefresh,
  redirect: (context, state) {
    final admin = DeviceAdminService.instance.isLocalAdminSession;
    final loggedIn = AuthService.instance.isLoggedIn;
    final loc = state.matchedLocation;
    final public = loc == '/login' || loc == '/server-connect';
    final deviceOnly = loc == '/device-admin' || loc == '/device-setup';

    if (admin) {
      if (loc == '/login') return '/device-admin';
      if (deviceOnly || loc == '/server-connect') return null;
      return '/device-admin';
    }
    if (!loggedIn) {
      if (deviceOnly) return '/login';
      return public ? null : '/login';
    }
    if (loc == '/login') return '/home';
    if (deviceOnly) return '/home';
    return null;
  },
  routes: [
    GoRoute(path: '/login', builder: (context, state) => const LoginScreen()),
    GoRoute(
      path: '/server-connect',
      builder: (context, state) => const ServerConnectScreen(),
    ),
    GoRoute(
      path: '/device-admin',
      builder: (context, state) => const DeviceAdminHubScreen(),
    ),
    GoRoute(
      path: '/device-setup',
      builder: (context, state) => const DeviceSetupScreen(),
    ),
    GoRoute(path: '/home', builder: (context, state) => const HomeScreen()),
    GoRoute(
      path: '/exercise-details',
      builder: (context, state) => const ExerciseDetailsScreen(),
    ),
    GoRoute(path: '/library', builder: (context, state) => const LibraryScreen()),
    GoRoute(
      path: '/notifications',
      builder: (context, state) => const NotificationsScreen(),
    ),
    GoRoute(
      path: '/messages',
      builder: (context, state) => const MessagesScreen(),
    ),
    GoRoute(path: '/flow', builder: (context, state) => const FlowScreen()),
    GoRoute(
      path: '/action-eval',
      builder: (context, state) => const ActionEvalListsScreen(),
    ),
    GoRoute(
      path: '/action-eval/:slot',
      builder: (context, state) {
        final slot = int.tryParse(state.pathParameters['slot'] ?? '') ?? 0;
        return EvalSheetScreen.actionEval(
          slot: slot,
          fallbackTitle: state.extra is String ? state.extra as String : null,
        );
      },
    ),
    GoRoute(
      path: '/evaluation-lists',
      builder: (context, state) => const EvaluationListsScreen(),
    ),
    GoRoute(
      path: '/evaluation-lists/:unitKey/:itemId',
      builder: (context, state) {
        final unitKey = state.pathParameters['unitKey'] ?? '';
        final itemId = int.tryParse(state.pathParameters['itemId'] ?? '') ?? 0;
        return EvalSheetScreen.evaluationList(
          unitKey: unitKey,
          itemId: itemId,
          fallbackTitle: state.extra is String ? state.extra as String : null,
        );
      },
    ),
    GoRoute(
      path: '/positives-negatives',
      builder: (context, state) => const PositivesNegativesScreen(),
    ),
    GoRoute(
      path: '/objectives',
      builder: (context, state) => const ObjectivesScreen(),
    ),
    GoRoute(
      path: '/settings',
      builder: (context, state) => const SettingsScreen(),
    ),
    GoRoute(
      path: '/sync-status',
      builder: (context, state) => const SyncStatusScreen(),
    ),
  ],
);

class LfTrainingEvaluationApp extends StatelessWidget {
  const LfTrainingEvaluationApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        ChangeNotifierProvider<AuthService>.value(value: AuthService.instance),
        ChangeNotifierProvider<DeviceAdminService>.value(
          value: DeviceAdminService.instance,
        ),
      ],
      child: MaterialApp.router(
        title: 'التحكيم الذكي',
        debugShowCheckedModeBanner: false,
        theme: AppTheme.light(compact: DeviceLayout.isPhoneBuild),
        locale: const Locale('ar'),
        supportedLocales: const [Locale('ar')],
        localizationsDelegates: const [
          GlobalMaterialLocalizations.delegate,
          GlobalWidgetsLocalizations.delegate,
          GlobalCupertinoLocalizations.delegate,
        ],
        builder: (context, child) {
          final content = child ?? const SizedBox.shrink();
          final mq = MediaQuery.of(context);
          final phoneFactor = DeviceLayout.textScale(context);
          final systemFactor = mq.textScaler.scale(1.0);
          final scaled = MediaQuery(
            data: mq.copyWith(
              textScaler: TextScaler.linear(phoneFactor * systemFactor),
            ),
            child: Directionality(
              textDirection: TextDirection.rtl,
              child: content,
            ),
          );
          return PhoneZoomShell(child: scaled);
        },
        routerConfig: _router,
      ),
    );
  }
}
