import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../models/user.dart';
import 'api_client.dart';
import 'offline_store.dart';

const String _kLastSessionCacheKey = 'session_bundle';
const String _kWasLoggedInPrefKey = 'was_logged_in';

/// Holds the current judge session (or lack thereof) and exposes
/// login/logout against `/api/tablet/auth/*`.
class AuthService extends ChangeNotifier {
  AuthService._internal();
  static final AuthService instance = AuthService._internal();

  SessionBundle? _session;
  bool _loading = false;
  String? _lastError;

  SessionBundle? get session => _session;
  bool get isLoggedIn => _session != null;
  bool get loading => _loading;
  String? get lastError => _lastError;

  Future<void> restoreFromCache() async {
    final cached = await OfflineStore.instance.cacheGet(_kLastSessionCacheKey);
    if (cached != null) {
      try {
        _session = SessionBundle.fromJson(cached);
        notifyListeners();
      } catch (_) {}
    }
  }

  /// Confirms the persisted cookie is still valid with the server. Only
  /// call when online; leaves the cached session untouched on failure so
  /// the UI can keep working offline.
  Future<bool> refreshFromServer() async {
    try {
      final data = await ApiClient.instance.get('/api/tablet/me');
      _session = SessionBundle.fromJson(data);
      await OfflineStore.instance.cacheSet(_kLastSessionCacheKey, data);
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

  Future<bool> login(String username, String password) async {
    _loading = true;
    _lastError = null;
    notifyListeners();
    try {
      final data = await ApiClient.instance.post(
        '/api/tablet/auth/login',
        body: {'username': username, 'password': password},
      );
      _session = SessionBundle.fromJson(data);
      await OfflineStore.instance.cacheSet(_kLastSessionCacheKey, data);
      final prefs = await SharedPreferences.getInstance();
      await prefs.setBool(_kWasLoggedInPrefKey, true);
      return true;
    } on ApiException catch (e) {
      _lastError = e.message;
      return false;
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
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_kWasLoggedInPrefKey, false);
    await ApiClient.instance.clearCookies();
    notifyListeners();
  }
}
