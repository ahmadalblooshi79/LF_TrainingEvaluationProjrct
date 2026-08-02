import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../models/user.dart';
import 'api_client.dart';
import 'offline_store.dart';

const String kLastSessionCacheKey = 'session_bundle';
const String kLocalAuthCacheKey = 'local_auth';
const String kWasLoggedInPrefKey = 'was_logged_in';
const String kLastSyncAtPrefKey = 'last_sync_at';

/// بصمة محلية بسيطة لبيانات الدخول (بدون الاعتماد على السيرفر).
String credentialDigest(String username, String password) {
  final raw = utf8.encode('lf.v1|${username.trim().toLowerCase()}|$password');
  var h1 = 2166136261;
  var h2 = 0x811c9dc5;
  for (final b in raw) {
    h1 = ((h1 ^ b) * 16777619) & 0xFFFFFFFF;
    h2 = ((h2 << 5) + h2 + b) & 0xFFFFFFFF;
  }
  return '${h1.toRadixString(16).padLeft(8, '0')}${h2.toRadixString(16).padLeft(8, '0')}';
}

/// Holds the current judge session (or lack thereof) and exposes
/// login/logout against `/api/tablet/auth/*` مع دعم Offline.
class AuthService extends ChangeNotifier {
  AuthService._internal();
  static final AuthService instance = AuthService._internal();

  SessionBundle? _session;
  bool _loading = false;
  String? _lastError;
  bool _lastLoginWasOffline = false;

  SessionBundle? get session => _session;
  bool get isLoggedIn => _session != null;
  bool get loading => _loading;
  String? get lastError => _lastError;
  bool get lastLoginWasOffline => _lastLoginWasOffline;

  Future<void> restoreFromCache() async {
    final cached = await OfflineStore.instance.cacheGet(kLastSessionCacheKey);
    if (cached != null) {
      try {
        _session = SessionBundle.fromJson(cached);
        notifyListeners();
      } catch (_) {}
    }
  }

  /// هل توجد بيانات دخول محلية صالحة للعمل Offline؟
  Future<bool> hasOfflineCredentials() async {
    final auth = await OfflineStore.instance.cacheGet(kLocalAuthCacheKey);
    final session = await OfflineStore.instance.cacheGet(kLastSessionCacheKey);
    if (auth == null || session == null) return false;
    final hash = (auth['password_hash'] ?? '').toString();
    final user = (auth['username'] ?? '').toString();
    return hash.isNotEmpty && user.isNotEmpty;
  }

  Future<bool> canOfflineLoginAs(String username) async {
    final auth = await OfflineStore.instance.cacheGet(kLocalAuthCacheKey);
    if (auth == null) return false;
    final stored = (auth['username'] ?? '').toString().trim().toLowerCase();
    return stored == username.trim().toLowerCase() &&
        (auth['password_hash'] ?? '').toString().isNotEmpty &&
        await OfflineStore.instance.cacheGet(kLastSessionCacheKey) != null;
  }

  /// Confirms the persisted cookie is still valid with the server. Only
  /// call when online; leaves the cached session untouched on failure so
  /// the UI can keep working offline.
  Future<bool> refreshFromServer() async {
    try {
      final reachable = await ApiClient.instance.ping(
        timeout: const Duration(seconds: 3),
      );
      if (!reachable) return false;
      final data = await ApiClient.instance.get(
        '/api/tablet/me',
        timeout: const Duration(seconds: 8),
      );
      _session = SessionBundle.fromJson(data);
      await OfflineStore.instance.cacheSet(kLastSessionCacheKey, data);
      notifyListeners();
      return true;
    } on ApiOfflineException {
      return false;
    } catch (e) {
      if (e is ApiException && e.status == 401) {
        _session = null;
        notifyListeners();
      }
      return false;
    }
  }

  Future<void> _persistLocalAuth(String username, String password) async {
    await OfflineStore.instance.cacheSet(kLocalAuthCacheKey, {
      'username': username.trim().toLowerCase(),
      'password_hash': credentialDigest(username, password),
      'saved_at': DateTime.now().toIso8601String(),
    });
  }

  Future<bool> _loginOffline(String username, String password) async {
    final auth = await OfflineStore.instance.cacheGet(kLocalAuthCacheKey);
    final session = await OfflineStore.instance.cacheGet(kLastSessionCacheKey);
    if (auth == null || session == null) {
      _lastError =
          'تعذر الاتصال بالخادم.\nلا توجد بيانات محلية صالحة لتسجيل الدخول.';
      return false;
    }
    final storedUser = (auth['username'] ?? '').toString().trim().toLowerCase();
    final storedHash = (auth['password_hash'] ?? '').toString();
    if (storedUser != username.trim().toLowerCase() ||
        storedHash != credentialDigest(username, password)) {
      _lastError = 'بيانات الدخول غير صحيحة أو غير متاحة محلياً.';
      return false;
    }
    try {
      _session = SessionBundle.fromJson(session);
      _lastLoginWasOffline = true;
      final prefs = await SharedPreferences.getInstance();
      await prefs.setBool(kWasLoggedInPrefKey, true);
      return true;
    } catch (_) {
      _lastError = 'تعذر قراءة الجلسة المحلية.';
      return false;
    }
  }

  String _friendlyNetworkError({required bool offlineAvailable}) {
    if (offlineAvailable) {
      return 'تعذر الاتصال بالخادم.\nسيتم العمل باستخدام البيانات المحلية.';
    }
    return 'تعذر الاتصال بالخادم.';
  }

  Future<bool> login(String username, String password) async {
    _loading = true;
    _lastError = null;
    _lastLoginWasOffline = false;
    notifyListeners();
    try {
      final offlineReady = await canOfflineLoginAs(username);

      // فحص سريع: إن تعذّر الوصول ندخل Offline فوراً إن أمكن
      final reachable = await ApiClient.instance.ping(
        timeout: const Duration(seconds: 3),
      );
      if (!reachable) {
        if (offlineReady) {
          return await _loginOffline(username, password);
        }
        _lastError = _friendlyNetworkError(offlineAvailable: false);
        return false;
      }

      try {
        final data = await ApiClient.instance.post(
          '/api/tablet/auth/login',
          body: {'username': username, 'password': password},
          timeout: const Duration(seconds: 10),
        );
        _session = SessionBundle.fromJson(data);
        await OfflineStore.instance.cacheSet(kLastSessionCacheKey, data);
        await _persistLocalAuth(username, password);
        final prefs = await SharedPreferences.getInstance();
        await prefs.setBool(kWasLoggedInPrefKey, true);
        _lastLoginWasOffline = false;
        return true;
      } on ApiOfflineException {
        if (offlineReady) {
          return await _loginOffline(username, password);
        }
        _lastError = _friendlyNetworkError(offlineAvailable: false);
        return false;
      } on ApiException catch (e) {
        // مهلات الشبكة أحياناً تُغلَّف كرسالة عربية قديمة
        final msg = e.message;
        final isTimeout = e is ApiOfflineException ||
            msg.contains('مهلة') ||
            msg.contains('تعذّر الاتصال') ||
            msg.contains('تعذر الاتصال');
        if (isTimeout || e.status == 0) {
          if (offlineReady) {
            return await _loginOffline(username, password);
          }
          _lastError = _friendlyNetworkError(offlineAvailable: false);
          return false;
        }
        _lastError = msg;
        return false;
      }
    } finally {
      _loading = false;
      notifyListeners();
    }
  }

  Future<void> logout() async {
    try {
      await ApiClient.instance.post('/api/tablet/auth/logout');
    } catch (_) {
      // best effort — clear local state regardless of network outcome
    }
    _session = null;
    _lastLoginWasOffline = false;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(kWasLoggedInPrefKey, false);
    await ApiClient.instance.clearCookies();
    // الإبقاء على local_auth + session_bundle للعمل Offline لاحقاً
    notifyListeners();
  }

  static Future<DateTime?> loadLastSyncAt() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(kLastSyncAtPrefKey);
    if (raw == null || raw.isEmpty) return null;
    return DateTime.tryParse(raw);
  }

  static Future<void> saveLastSyncAt(DateTime at) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(kLastSyncAtPrefKey, at.toIso8601String());
  }
}
