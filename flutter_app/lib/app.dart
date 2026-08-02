import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import 'screens/action_eval_lists_screen.dart';
import 'screens/eval_sheet_screen.dart';
import 'screens/evaluation_lists_screen.dart';
import 'screens/exercise_details_screen.dart';
import 'screens/flow_screen.dart';
import 'screens/home_screen.dart';
import 'screens/library_screen.dart';
import 'screens/login_screen.dart';
import 'screens/messages_screen.dart';
import 'screens/notifications_screen.dart';
import 'screens/objectives_screen.dart';
import 'screens/server_connect_screen.dart';
import 'screens/settings_screen.dart';
import 'screens/sync_status_screen.dart';
import 'services/auth_service.dart';
import 'theme/app_theme.dart';

final GoRouter _router = GoRouter(
  initialLocation: '/login',
  refreshListenable: AuthService.instance,
  redirect: (context, state) {
    final loggedIn = AuthService.instance.isLoggedIn;
    final loc = state.matchedLocation;
    final public = loc == '/login' || loc == '/server-connect';
    if (!loggedIn) return public ? null : '/login';
    if (loc == '/login') return '/home';
    return null;
  },
  routes: [
    GoRoute(path: '/login', builder: (context, state) => const LoginScreen()),
    GoRoute(path: '/server-connect', builder: (context, state) => const ServerConnectScreen()),
    GoRoute(path: '/home', builder: (context, state) => const HomeScreen()),
    GoRoute(path: '/exercise-details', builder: (context, state) => const ExerciseDetailsScreen()),
    GoRoute(path: '/library', builder: (context, state) => const LibraryScreen()),
    GoRoute(path: '/notifications', builder: (context, state) => const NotificationsScreen()),
    GoRoute(path: '/messages', builder: (context, state) => const MessagesScreen()),
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
    GoRoute(path: '/objectives', builder: (context, state) => const ObjectivesScreen()),
    GoRoute(path: '/settings', builder: (context, state) => const SettingsScreen()),
    GoRoute(path: '/sync-status', builder: (context, state) => const SyncStatusScreen()),
  ],
);

class LfTrainingEvaluationApp extends StatelessWidget {
  const LfTrainingEvaluationApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        ChangeNotifierProvider<AuthService>.value(value: AuthService.instance),
      ],
      child: MaterialApp.router(
        title: 'التحكيم الذكي',
        debugShowCheckedModeBanner: false,
        theme: AppTheme.light(),
        locale: const Locale('ar'),
        supportedLocales: const [Locale('ar')],
        localizationsDelegates: const [
          GlobalMaterialLocalizations.delegate,
          GlobalWidgetsLocalizations.delegate,
          GlobalCupertinoLocalizations.delegate,
        ],
        builder: (context, child) => Directionality(
          textDirection: TextDirection.rtl,
          child: child ?? const SizedBox.shrink(),
        ),
        routerConfig: _router,
      ),
    );
  }
}
