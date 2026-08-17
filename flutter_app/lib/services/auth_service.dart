import 'dart:convert';
import 'dart:math';

import 'package:crypto/crypto.dart';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../models/user.dart';
import 'api_client.dart';
import 'connectivity_service.dart';
import 'offline_store.dart';

const String kLastSessionCacheKey = 'session_bundle';
const String kLocalAuthCacheKey = 'local_auth';
const String kWasLoggedInPrefKey = 'was_logged_in';
const String kLastSyncAtPrefKey = 'last_sync_at';
const String kCredentialSaltPrefKey = 'local_auth_salt_v2';

/// بصمة محلية لكلمة المرور (SHA-256 + ملح الجهاز) — بدون حفظ النص الصريح.
Future<String> credentialDigest(String username, String password) async {
  final prefs = await SharedPreferences.getInstance();
  var salt = prefs.getString(kCredentialSaltPrefKey) ?? '';
  if (salt.isEmpty) {
    final rnd = Random.secure();
    final bytes = List<int>.generate(24, (_) => rnd.nextInt(256));
    salt = base64UrlEncode(bytes);
    await prefs.setString(kCredentialSaltPrefKey, salt);
  }
  final material =
      'lf.v2|$salt|${username.trim().toLowerCase()}|$password';
  return sha256.convert(utf8.encode(material)).toString();
}

/// توافق مع البصمة القديمة (v1) المخزّنة قبل التحديث.
String _legacyCredentialDigest(String username, String password) {
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
/// login/logout against `/api/tablet/auth/*` مع دعم Offline-First.
class AuthService extends ChangeNotifier {
  AuthService._internal();
  static final AuthService instance = AuthService._internal();

  SessionBundle? _session;
  bool _loading = false;
  String? _lastError;
  bool _lastLoginWasOffline = false;
  String? _savedUsernameHint;
  bool _offlineCredsAvailable = false;

  SessionBundle? get session => _session;
  bool get isLoggedIn => _session != null;
  bool get loading => _loading;
  String? get lastError => _lastError;
  bool get lastLoginWasOffline => _lastLoginWasOffline;
  String? get savedUsernameHint => _savedUsernameHint;
  bool get offlineCredsAvailable => _offlineCredsAvailable;

  /// عند الإقلاع: نقرأ بيانات الدخول المحلية دون فتح جلسة تلقائياً.
  Future<void> prepareLocalAuth() async {
    _session = null;
    _lastLoginWasOffline = false;
    final users = await OfflineStore.instance.allLocalUsers();
    _offlineCredsAvailable = users.isNotEmpty;
    if (users.isNotEmpty) {
      _savedUsernameHint = (users.first['username'] ?? '').toString();
    } else {
      final auth = await OfflineStore.instance.cacheGet(kLocalAuthCacheKey);
      final session = await OfflineStore.instance.cacheGet(kLastSessionCacheKey);
      _offlineCredsAvailable = auth != null &&
          session != null &&
          (auth['password_hash'] ?? '').toString().isNotEmpty;
      _savedUsernameHint = _offlineCredsAvailable
          ? (auth!['username'] ?? '').toString()
          : null;
    }
    notifyListeners();
  }

  void applySessionJson(Map<String, dynamic> data) {
    try {
      _session = SessionBundle.fromJson(data);
      notifyListeners();
    } catch (_) {}
  }

  int? get currentUserId => _session?.user.id;

  @Deprecated('Use prepareLocalAuth')
  Future<void> restoreFromCache() => prepareLocalAuth();

  Future<bool> hasOfflineCredentials() async {
    final users = await OfflineStore.instance.allLocalUsers();
    if (users.isNotEmpty) return true;
    final auth = await OfflineStore.instance.cacheGet(kLocalAuthCacheKey);
    final session = await OfflineStore.instance.cacheGet(kLastSessionCacheKey);
    return auth != null &&
        session != null &&
        (auth['password_hash'] ?? '').toString().isNotEmpty;
  }

  Future<bool> canOfflineLoginAs(String username) async {
    final row = await OfflineStore.instance.localUserByUsername(username);
    if (row != null) return true;
    final auth = await OfflineStore.instance.cacheGet(kLocalAuthCacheKey);
    if (auth == null) return false;
    final stored = (auth['username'] ?? '').toString().trim().toLowerCase();
    return stored == username.trim().toLowerCase() &&
        (auth['password_hash'] ?? '').toString().isNotEmpty &&
        await OfflineStore.instance.cacheGet(kLastSessionCacheKey) != null;
  }

  /// تحديث اختياري من السيرفر أثناء جلسة نشطة — لا يُسقط الجلسة المحلية عند الفشل.
  Future<bool> refreshFromServer() async {
    if (_session == null) return false;
    try {
      if (!ApiClient.instance.isConfigured) return false;
      if (!ConnectivityService.instance.hasNetwork.value) return false;
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
      // 401 من كوكي منتهٍ: نُبقي الجلسة المحلية للعمل Offline.
      if (e is ApiException && e.status == 401) {
        try {
          await ApiClient.instance.clearCookies();
        } catch (_) {}
      }
      return false;
    }
  }

  Future<void> _persistLocalAuth(String username, String password) async {
    final hash = await credentialDigest(username, password);
    await OfflineStore.instance.cacheSet(kLocalAuthCacheKey, {
      'username': username.trim().toLowerCase(),
      'password_hash': hash,
      'hash_version': 2,
      'saved_at': DateTime.now().toIso8601String(),
    });
    _offlineCredsAvailable = true;
    _savedUsernameHint = username.trim().toLowerCase();
  }

  Future<bool> _passwordMatches(Map<String, dynamic> auth, String username, String password) async {
    final storedHash = (auth['password_hash'] ?? '').toString();
    if (storedHash.isEmpty) return false;
    final v2 = await credentialDigest(username, password);
    if (storedHash == v2) return true;
    // ترقية من بصمة v1 إن وُجدت
    if (storedHash == _legacyCredentialDigest(username, password)) {
      await _persistLocalAuth(username, password);
      return true;
    }
    return false;
  }

  Future<bool> _loginOffline(String username, String password) async {
    // 1) مستخدمون من حزمة الجهاز (معزولون)
    final row = await OfflineStore.instance.localUserByUsername(username);
    if (row != null) {
      final storedHash = (row['password_hash'] ?? '').toString();
      final hash = await credentialDigest(username, password);
      final legacy = _legacyCredentialDigest(username, password);
      if (storedHash != hash && storedHash != legacy) {
        _lastError = 'بيانات الدخول غير صحيحة أو غير متاحة محلياً.';
        return false;
      }
      try {
        final sessionRaw = row['session_json'];
        Map<String, dynamic> sessionMap;
        if (sessionRaw is String) {
          sessionMap = Map<String, dynamic>.from(jsonDecode(sessionRaw) as Map);
        } else if (sessionRaw is Map) {
          sessionMap = Map<String, dynamic>.from(sessionRaw);
        } else {
          throw StateError('bad session');
        }
        final uid = (row['user_id'] as num?)?.toInt() ?? 0;
        final scoped = await OfflineStore.instance.cacheGetForUser(
          uid,
          'session_bundle',
        );
        _session = SessionBundle.fromJson(scoped ?? sessionMap);
        _lastLoginWasOffline = true;
        final prefs = await SharedPreferences.getInstance();
        await prefs.setBool(kWasLoggedInPrefKey, true);
        return true;
      } catch (_) {
        _lastError = 'تعذر قراءة الجلسة المحلية.';
        return false;
      }
    }

    // 2) توافق مع local_auth القديم (محكم واحد)
    final auth = await OfflineStore.instance.cacheGet(kLocalAuthCacheKey);
    final session = await OfflineStore.instance.cacheGet(kLastSessionCacheKey);
    if (auth == null || session == null) {
      _lastError =
          'لا توجد بيانات محلية لتسجيل الدخول.\nيلزم تهيئة الجهاز أو اتصال بالسيرفر لأول مرة.';
      return false;
    }
    final storedUser = (auth['username'] ?? '').toString().trim().toLowerCase();
    if (storedUser != username.trim().toLowerCase()) {
      _lastError = 'بيانات الدخول غير صحيحة أو غير متاحة محلياً.';
      return false;
    }
    if (!await _passwordMatches(auth, username, password)) {
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

  String _firstLoginNeedsServerMessage() {
    return 'يلزم اتصال بالسيرفر لأول تسجيل دخول فقط.\n'
        'بعد نجاح الدخول تُحفظ بياناتك محلياً ويمكنك العمل Offline.';
  }

  Future<bool> login(String username, String password) async {
    _loading = true;
    _lastError = null;
    _lastLoginWasOffline = false;
    notifyListeners();
    try {
      final offlineReady = await canOfflineLoginAs(username);
      final hasNet = ConnectivityService.instance.hasNetwork.value;
      final configured = ApiClient.instance.isConfigured;

      // Offline-First: بدون شبكة أو بدون عنوان سيرفر → دخول محلي فوراً
      if (offlineReady && (!hasNet || !configured)) {
        return await _loginOffline(username, password);
      }

      if (!configured) {
        if (offlineReady) {
          return await _loginOffline(username, password);
        }
        _lastError =
            'اضبط عنوان السيرفر ثم سجّل الدخول مرة واحدة عبر الشبكة.\n'
            'بعدها يمكنك الدخول offline بدون سيرفر.';
        return false;
      }

      // إن وُجدت بيانات محلية ولا شبكة ظاهرة: لا ننتظر مهلة Ping
      if (offlineReady && !hasNet) {
        return await _loginOffline(username, password);
      }

      final reachable = hasNet
          ? await ApiClient.instance.ping(timeout: const Duration(seconds: 2))
          : false;

      if (!reachable) {
        if (offlineReady) {
          return await _loginOffline(username, password);
        }
        _lastError = _firstLoginNeedsServerMessage();
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
        final uid = _session?.user.id ?? 0;
        if (uid > 0) {
          final hash = await credentialDigest(username, password);
          await OfflineStore.instance.upsertLocalUser(
            userId: uid,
            username: username,
            passwordHash: hash,
            session: data,
          );
          await OfflineStore.instance.cacheSetForUser(uid, 'session_bundle', data);
        }
        final prefs = await SharedPreferences.getInstance();
        await prefs.setBool(kWasLoggedInPrefKey, true);
        _lastLoginWasOffline = false;
        return true;
      } on ApiOfflineException {
        if (offlineReady) {
          return await _loginOffline(username, password);
        }
        _lastError = _firstLoginNeedsServerMessage();
        return false;
      } on ApiException catch (e) {
        final msg = e.message;
        final isTimeout = e is ApiOfflineException ||
            msg.contains('مهلة') ||
            msg.contains('تعذّر الاتصال') ||
            msg.contains('تعذر الاتصال');
        if (isTimeout || e.status == 0) {
          if (offlineReady) {
            return await _loginOffline(username, password);
          }
          _lastError = _firstLoginNeedsServerMessage();
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

  /// إنهاء الجلسة الحالية فقط — لا يمسح قاعدة البيانات المحلية ولا بيانات الدخول offline.
  Future<void> logout() async {
    try {
      if (ApiClient.instance.isConfigured &&
          ConnectivityService.instance.hasNetwork.value) {
        await ApiClient.instance.post('/api/tablet/auth/logout');
      }
    } catch (_) {
      // best effort
    }
    _session = null;
    _lastLoginWasOffline = false;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(kWasLoggedInPrefKey, false);
    try {
      await ApiClient.instance.clearCookies();
    } catch (_) {}
    // الإبقاء على local_auth + session_bundle + كل كاش التمرين/القوائم
    _offlineCredsAvailable = await hasOfflineCredentials();
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
