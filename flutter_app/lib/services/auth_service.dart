import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:crypto/crypto.dart';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../models/user.dart';
import 'api_client.dart';
import 'connectivity_service.dart';
import 'device_presence_service.dart';
import 'identity_log.dart';
import 'offline_store.dart';

const String kLastSessionCacheKey = 'session_bundle';
const String kLocalAuthCacheKey = 'local_auth';
const String kWasLoggedInPrefKey = 'was_logged_in';
const String kLastSyncAtPrefKey = 'last_sync_at';
const String kCredentialSaltPrefKey = 'local_auth_salt_v2';

String reconnectTicketPrefKey(int userId) => 'reconnect_ticket_u$userId';

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

/// Reconstruct Device-Sync seed in memory only when it matches the stored hash.
/// Never persists the returned secret.
Future<String?> matchingProvisionPassword({
  required String storedHash,
  required String username,
  required String militaryNumber,
}) async {
  if (storedHash.isEmpty) return null;
  final candidates = <String>[];
  final mil = militaryNumber.trim();
  if (mil.isNotEmpty) candidates.add(mil);
  final u = username.trim();
  if (u.isNotEmpty && !candidates.contains(u)) candidates.add(u);
  for (final c in candidates) {
    if (storedHash == await credentialDigest(username, c)) return c;
    if (storedHash == _legacyCredentialDigest(username, c)) return c;
  }
  return null;
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
  final ValueNotifier<bool> serverSessionUsable = ValueNotifier<bool>(false);
  final ValueNotifier<bool> recoveringServerSession = ValueNotifier<bool>(false);
  Completer<bool>? _recoverInFlight;
  int _recoverFailCount = 0;
  DateTime? _recoverBackoffUntil;

  SessionBundle? get session => _session;
  bool get isLoggedIn => _session != null;
  bool get loading => _loading;
  String? get lastError => _lastError;
  bool get lastLoginWasOffline => _lastLoginWasOffline;
  String? get savedUsernameHint => _savedUsernameHint;
  bool get offlineCredsAvailable => _offlineCredsAvailable;
  bool get isRecoveringServerSession => recoveringServerSession.value;

  void markServerSessionUnusable() {
    if (serverSessionUsable.value) {
      serverSessionUsable.value = false;
      notifyListeners();
    }
  }

  Future<void> persistReconnectTicket(int userId, String? ticket) async {
    if (userId <= 0) return;
    final t = (ticket ?? '').trim();
    if (t.isEmpty) return;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(reconnectTicketPrefKey(userId), t);
    try {
      final row = await OfflineStore.instance.localUserByUsername(
        _session?.user.username ?? '',
      );
      Map<String, dynamic> sessionMap = {};
      if (row != null) {
        final raw = row['session_json'];
        if (raw is String && raw.isNotEmpty) {
          try {
            sessionMap = Map<String, dynamic>.from(jsonDecode(raw) as Map);
          } catch (_) {}
        }
      }
      sessionMap['reconnect_ticket'] = t;
      final hash = (row?['password_hash'] ?? '').toString();
      if (_session != null && hash.isNotEmpty) {
        await OfflineStore.instance.upsertLocalUser(
          userId: userId,
          username: _session!.user.username,
          passwordHash: hash,
          session: sessionMap.isEmpty
              ? {..._session!.toJson(), 'reconnect_ticket': t}
              : sessionMap,
          militaryNumber: (row?['military_number'] ?? '').toString(),
        );
      }
    } catch (_) {}
  }

  Future<String?> loadReconnectTicket(int userId) async {
    if (userId <= 0) return null;
    final prefs = await SharedPreferences.getInstance();
    final fromPrefs = (prefs.getString(reconnectTicketPrefKey(userId)) ?? '').trim();
    if (fromPrefs.isNotEmpty) return fromPrefs;
    try {
      final username = _session?.user.username ?? '';
      if (username.isEmpty) return null;
      final row = await OfflineStore.instance.localUserByUsername(username);
      if (row == null) return null;
      final raw = row['session_json'];
      Map<String, dynamic>? sessionMap;
      if (raw is String && raw.isNotEmpty) {
        sessionMap = Map<String, dynamic>.from(jsonDecode(raw) as Map);
      } else if (raw is Map) {
        sessionMap = Map<String, dynamic>.from(raw);
      }
      final t = (sessionMap?['reconnect_ticket'] ?? '').toString().trim();
      return t.isEmpty ? null : t;
    } catch (_) {
      return null;
    }
  }

  /// Restore a legitimate Flask session for the currently logged-in local judge.
  /// Never logs out locally. Never deletes pending/media/users.
  Future<bool> recoverServerSession({bool force = false}) async {
    if (_session == null) return false;
    if (_recoverInFlight != null) return _recoverInFlight!.future;
    if (!force &&
        _recoverBackoffUntil != null &&
        DateTime.now().isBefore(_recoverBackoffUntil!)) {
      return serverSessionUsable.value;
    }
    final pending = Completer<bool>();
    _recoverInFlight = pending;
    recoveringServerSession.value = true;
    notifyListeners();
    try {
      final uid = _session!.user.id;
      final username = _session!.user.username;

      try {
        final me = await ApiClient.instance.get(
          '/api/tablet/me',
          timeout: const Duration(seconds: 8),
        );
        if (serverPayloadMatchesSession(me) && applySessionJson(me, source: 'recover.me')) {
          await persistReconnectTicket(uid, me['reconnect_ticket']?.toString());
          serverSessionUsable.value = true;
          _recoverFailCount = 0;
          pending.complete(true);
          return true;
        }
      } on ApiException catch (e) {
        if (e.status != 401 && e.status != 403) {
          serverSessionUsable.value = false;
          pending.complete(false);
          return false;
        }
      } on ApiOfflineException {
        serverSessionUsable.value = false;
        pending.complete(false);
        return false;
      }

      final ticket = await loadReconnectTicket(uid);
      if (ticket != null && ticket.isNotEmpty) {
        try {
          final data = await ApiClient.instance.post(
            '/api/tablet/auth/reconnect',
            body: {
              'user_id': uid,
              'username': username,
              'reconnect_ticket': ticket,
            },
            timeout: const Duration(seconds: 12),
          );
          if (serverPayloadMatchesSession(data) &&
              applySessionJson(data, source: 'recover.ticket')) {
            await persistReconnectTicket(
              uid,
              data['reconnect_ticket']?.toString() ?? ticket,
            );
            serverSessionUsable.value = true;
            _recoverFailCount = 0;
            pending.complete(true);
            return true;
          }
        } on ApiException catch (e) {
          if (e.status != 401 && e.status != 403) {
            serverSessionUsable.value = false;
            pending.complete(false);
            return false;
          }
        } on ApiOfflineException {
          serverSessionUsable.value = false;
          pending.complete(false);
          return false;
        }
      }

      final row = await OfflineStore.instance.localUserByUsername(username);
      final storedHash = (row?['password_hash'] ?? '').toString();
      final mil = (row?['military_number'] ?? '').toString();
      final seed = await matchingProvisionPassword(
        storedHash: storedHash,
        username: username,
        militaryNumber: mil,
      );
      if (seed != null) {
        try {
          final data = await ApiClient.instance.post(
            '/api/tablet/auth/login',
            body: {'username': username, 'password': seed},
            timeout: const Duration(seconds: 12),
          );
          if (serverPayloadMatchesSession(data) &&
              applySessionJson(data, source: 'recover.seed')) {
            await persistReconnectTicket(uid, data['reconnect_ticket']?.toString());
            serverSessionUsable.value = true;
            _recoverFailCount = 0;
            pending.complete(true);
            return true;
          }
        } on ApiException catch (_) {
          // fall through to fail closed
        } on ApiOfflineException {
          serverSessionUsable.value = false;
          pending.complete(false);
          return false;
        }
      }

      serverSessionUsable.value = false;
      _recoverFailCount += 1;
      final waitSec = _recoverFailCount >= 3 ? 30 : (_recoverFailCount == 2 ? 8 : 2);
      _recoverBackoffUntil = DateTime.now().add(Duration(seconds: waitSec));
      pending.complete(false);
      return false;
    } finally {
      recoveringServerSession.value = false;
      _recoverInFlight = null;
      notifyListeners();
    }
  }

  /// عند الإقلاع: نقرأ بيانات الدخول المحلية دون فتح جلسة تلقائياً.
  Future<void> prepareLocalAuth() async {
    _session = null;
    serverSessionUsable.value = false;
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

  int? get currentUserId => _session?.user.id;

  static int? userIdFromPayload(Map<String, dynamic> data) {
    final u = data['user'];
    if (u is Map) return (u['id'] as num?)?.toInt();
    return (data['user_id'] as num?)?.toInt();
  }

  bool serverPayloadMatchesSession(Map<String, dynamic> data) {
    final expected = currentUserId;
    final got = userIdFromPayload(data);
    if (expected == null || expected <= 0) return true;
    if (got == null || got <= 0) return true;
    if (got != expected) {
      identityLog(
        'IDENTITY MISMATCH expected=$expected received=$got endpoint=payload',
      );
      return false;
    }
    return true;
  }

  bool applySessionJson(Map<String, dynamic> data, {String source = 'unknown'}) {
    try {
      final next = SessionBundle.fromJson(data);
      final oldId = _session?.user.id;
      identityLog(
        'CURRENT USER WRITE ATTEMPT old_user_id=$oldId new_user_id=${next.user.id} source=$source',
      );
      if (oldId != null &&
          oldId > 0 &&
          next.user.id > 0 &&
          next.user.id != oldId) {
        identityLog(
          'IDENTITY MISMATCH expected=$oldId received=${next.user.id} source=$source',
        );
        return false;
      }
      _session = next;
      notifyListeners();
      return true;
    } catch (_) {
      return false;
    }
  }

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
      identityLog(
        'SERVER SESSION CHECK server_user_id=${userIdFromPayload(data)}',
      );
      if (!applySessionJson(data, source: 'refreshFromServer')) {
        return false;
      }
      await OfflineStore.instance.cacheSet(kLastSessionCacheKey, data);
      notifyListeners();
      return true;
    } on ApiOfflineException {
      return false;
    } catch (e) {
      // 401: جلسة السيرفر غير صالحة — لا تُسقط الجلسة المحلية ولا تُحذف البيانات.
      if (e is ApiException && e.status == 401) {
        serverSessionUsable.value = false;
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
        identityLog(
          'LOGIN SUCCESS user_id=${_session?.user.id} source=offline_local_user',
        );
        _lastLoginWasOffline = true;
        serverSessionUsable.value = false;
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
      identityLog(
        'LOGIN SUCCESS user_id=${_session?.user.id} source=offline_legacy',
      );
      _lastLoginWasOffline = true;
      serverSessionUsable.value = false;
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
      final configured = ApiClient.instance.isConfigured;

      if (!configured) {
        if (offlineReady) {
          return await _loginOffline(username, password);
        }
        _lastError =
            'اضبط عنوان السيرفر ثم سجّل الدخول مرة واحدة عبر الشبكة.\n'
            'بعدها يمكنك الدخول offline بدون سيرفر.';
        return false;
      }

      // جرّب السيرفر دائماً عند وجود عنوان — مؤشر الشبكة قد يكون خاطئاً
      final reachable = await ApiClient.instance.ping(
        timeout: const Duration(seconds: 8),
      );

      if (!reachable) {
        if (offlineReady) {
          return await _loginOffline(username, password);
        }
        final base = ApiClient.instance.baseUrl;
        _lastError =
            'تعذّر الاتصال بالخادم ($base).\n'
            'تأكد أن السيرفر يعمل على نفس الشبكة وأن المنفذ صحيح (افتراضي 8005).';
        return false;
      }

      try {
        final data = await ApiClient.instance.post(
          '/api/tablet/auth/login',
          body: {'username': username, 'password': password},
          timeout: const Duration(seconds: 10),
        );
        _session = SessionBundle.fromJson(data);
        identityLog('LOGIN SUCCESS user_id=${_session?.user.id} source=online');
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
          await persistReconnectTicket(uid, data['reconnect_ticket']?.toString());
        }
        serverSessionUsable.value = true;
        final prefs = await SharedPreferences.getInstance();
        await prefs.setBool(kWasLoggedInPrefKey, true);
        _lastLoginWasOffline = false;
        unawaited(DevicePresenceService.instance.register(isLogin: true));
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
    identityLog('LOGOUT user_id=${_session?.user.id} source=explicit');
    _session = null;
    serverSessionUsable.value = false;
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
