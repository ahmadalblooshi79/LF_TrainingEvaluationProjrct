import 'api_client.dart';
import 'auth_service.dart';
import 'device_admin_service.dart';
import 'notifications_badge_service.dart';
import 'offline_store.dart';
import 'tablet_repository.dart';

/// تنزيل وتخزين حزمة التمرين مع عزل كل محكم في Local DB.
class PackageSyncService {
  PackageSyncService._();
  static final PackageSyncService instance = PackageSyncService._();

  String? lastError;
  int lastJudgeCount = 0;

  Future<bool> setupLogin(String username, String password) async {
    lastError = null;
    try {
      await ApiClient.instance.post(
        '/api/tablet/device/setup-login',
        body: {'username': username, 'password': password},
        timeout: const Duration(seconds: 12),
      );
      return true;
    } on ApiException catch (e) {
      lastError = e.message;
      return false;
    } catch (e) {
      lastError = 'تعذر الاتصال بالسيرفر: $e';
      return false;
    }
  }

  Future<bool> downloadAndStorePackage() async {
    lastError = null;
    lastJudgeCount = 0;
    try {
      final data = await ApiClient.instance.get(
        '/api/tablet/device/package',
        timeout: const Duration(seconds: 120),
      );
      final judges = (data['judges'] as List?) ?? const [];
      for (final raw in judges) {
        if (raw is! Map) continue;
        final j = Map<String, dynamic>.from(raw);
        final userId = (j['user_id'] as num?)?.toInt() ?? 0;
        final username = (j['username'] ?? '').toString().trim();
        if (userId <= 0 || username.isEmpty) continue;
        final seed = (j['local_password_seed'] ?? username).toString();
        final sessionMap = j['session'] is Map
            ? Map<String, dynamic>.from(j['session'] as Map)
            : <String, dynamic>{};
        final sessionPayload = {
          'ok': true,
          ...sessionMap,
        };
        final hash = await credentialDigest(username, seed);
        await OfflineStore.instance.upsertLocalUser(
          userId: userId,
          username: username,
          passwordHash: hash,
          session: sessionPayload,
          militaryNumber: (j['military_number'] ?? '').toString(),
        );
        if (j['home'] is Map) {
          await OfflineStore.instance.cacheSetForUser(
            userId,
            'home',
            Map<String, dynamic>.from(j['home'] as Map),
          );
        }
        if (j['evaluation_lists'] is Map) {
          await OfflineStore.instance.cacheSetForUser(
            userId,
            'evaluation_lists::',
            Map<String, dynamic>.from(j['evaluation_lists'] as Map),
          );
        }
        final objectives = {
          'ok': true,
          ...sessionMap,
          'objectives': j['objectives'] ?? data['objectives'] ?? [],
        };
        await OfflineStore.instance.cacheSetForUser(
          userId,
          'objectives',
          objectives,
        );
        if (j['polarity_notes'] is Map) {
          await OfflineStore.instance.cacheSetForUser(
            userId,
            'polarity_notes',
            Map<String, dynamic>.from(j['polarity_notes'] as Map),
          );
        }
        await OfflineStore.instance.cacheSetForUser(
          userId,
          'session_bundle',
          sessionPayload,
        );
        await OfflineStore.instance.cacheSetForUser(userId, 'bootstrap', {
          'ok': true,
          ...sessionMap,
          'home': j['home'],
          'objectives': j['objectives'] ?? data['objectives'],
          'incomplete_tasks': j['incomplete_tasks'] ?? [],
          'polarity_notes': j['polarity_notes'],
        });
        lastJudgeCount++;
      }
      if (data['exercise'] is Map) {
        await OfflineStore.instance.cacheSet(
          'device_exercise',
          Map<String, dynamic>.from(data['exercise'] as Map),
        );
      }
      await DeviceAdminService.instance.markDeviceReady();
      return lastJudgeCount > 0;
    } on ApiException catch (e) {
      lastError = e.message;
      return false;
    } catch (e) {
      lastError = 'فشل تنزيل الحزمة: $e';
      return false;
    }
  }

  /// تحديث بيانات المحكم الحالي فقط من السيرفر.
  Future<bool> updateMyData() async {
    lastError = null;
    final session = AuthService.instance.session;
    final uid = session?.user.id ?? 0;
    if (uid <= 0) {
      lastError = 'لا توجد جلسة محكم';
      return false;
    }
    try {
      final data = await ApiClient.instance.get(
        '/api/tablet/me/updates',
        timeout: const Duration(seconds: 60),
      );
      await OfflineStore.instance.cacheSetForUser(uid, 'bootstrap', data);
      await OfflineStore.instance.cacheSetForUser(uid, 'session_bundle', data);
      if (data['home'] is Map) {
        await OfflineStore.instance.cacheSetForUser(
          uid,
          'home',
          Map<String, dynamic>.from(data['home'] as Map),
        );
      }
      final objectives = {
        'ok': true,
        'user': data['user'],
        'exercise': data['exercise'],
        'objectives': data['objectives'] ?? [],
      };
      await OfflineStore.instance.cacheSetForUser(uid, 'objectives', objectives);
      if (data['polarity_notes'] is Map) {
        await OfflineStore.instance.cacheSetForUser(
          uid,
          'polarity_notes',
          Map<String, dynamic>.from(data['polarity_notes'] as Map),
        );
      }
      AuthService.instance.applySessionJson(data);
      try {
        await TabletRepository.instance.prefetchForOffline();
      } catch (_) {}
      await AuthService.saveLastSyncAt(DateTime.now());
      await NotificationsBadgeService.instance.reportSyncEvent(
        kind: 'update',
        detail: 'تم تحديث بياناتي من النظام.',
      );
      return true;
    } on ApiException catch (e) {
      lastError = e.message;
      return false;
    } catch (e) {
      lastError = '$e';
      return false;
    }
  }
}
