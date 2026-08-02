import 'dart:async';
import 'dart:convert';

import 'package:cookie_jar/cookie_jar.dart';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

// dart:io is unavailable on web — load IO helpers only on native.
import 'api_client_io.dart' if (dart.library.html) 'api_client_web.dart' as io_env;

class ApiException implements Exception {
  final String message;
  final int status;
  ApiException(this.message, {this.status = 0});

  @override
  String toString() => message;
}

/// Thrown when the request could not reach the server at all.
class ApiOfflineException extends ApiException {
  ApiOfflineException([super.message = 'تعذّر الاتصال بالخادم']) : super(status: 0);
}

const String kServerBaseUrlPrefKey = 'server_base_url';

/// JSON HTTP client for `{serverBase}/api/tablet/*`.
///
/// On native: persists Flask session cookies via [PersistCookieJar].
/// On web (PWA): uses same-origin browser cookies when [baseUrl] is empty.
class ApiClient {
  ApiClient._internal();
  static final ApiClient instance = ApiClient._internal();

  final http.Client _http = http.Client();
  CookieJar? _cookieJar;
  String _baseUrl = '';
  bool _ready = false;

  final ValueNotifier<bool> online = ValueNotifier<bool>(true);

  String get baseUrl => _baseUrl;

  /// On web, empty baseUrl means same origin (served from Flask `/tablet/`).
  bool get isConfigured => kIsWeb || _baseUrl.trim().isNotEmpty;

  Future<void> init() async {
    if (_ready) return;
    final prefs = await SharedPreferences.getInstance();
    _baseUrl = (prefs.getString(kServerBaseUrlPrefKey) ?? '').trim();
    if (kIsWeb) {
      // Browser manages cookies for same-origin PWA; keep an in-memory jar
      // only as a no-op helper for header parsing paths.
      _cookieJar = CookieJar();
      if (_baseUrl.isEmpty) {
        _baseUrl = Uri.base.origin;
      }
    } else {
      _cookieJar = await io_env.createCookieJar();
    }
    _ready = true;
  }

  Future<void> setBaseUrl(String url) async {
    _baseUrl = _normalizeBaseUrl(url);
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(kServerBaseUrlPrefKey, _baseUrl);
  }

  static String _normalizeBaseUrl(String url) {
    var u = url.trim();
    if (u.endsWith('/')) u = u.substring(0, u.length - 1);
    if (u.isNotEmpty && !u.startsWith('http://') && !u.startsWith('https://')) {
      u = 'http://$u';
    }
    return u;
  }

  Future<void> clearCookies() async {
    await _cookieJar?.deleteAll();
  }

  Uri _uri(String path, [Map<String, dynamic>? query]) {
    if (!isConfigured) {
      throw ApiException('لم يتم ضبط عنوان الخادم بعد — افتح الإعدادات');
    }
    final base = _baseUrl.isEmpty ? Uri.base.origin : _baseUrl;
    final full = Uri.parse('$base$path');
    if (query == null || query.isEmpty) return full;
    return full.replace(
      queryParameters: {
        ...full.queryParameters,
        ...query.map((k, v) => MapEntry(k, v?.toString() ?? '')),
      },
    );
  }

  Future<Map<String, String>> _headersFor(Uri uri, {bool json = true}) async {
    final headers = <String, String>{'Accept': 'application/json'};
    if (json) headers['Content-Type'] = 'application/json';
    if (!kIsWeb) {
      final cookies = await _cookieJar?.loadForRequest(uri) ?? const [];
      if (cookies.isNotEmpty) {
        headers['Cookie'] =
            cookies.map((c) => '${c.name}=${c.value}').join('; ');
      }
    }
    return headers;
  }

  Future<void> _saveCookies(Uri uri, http.Response resp) async {
    if (kIsWeb || _cookieJar == null) return;
    await io_env.saveCookiesFromResponse(_cookieJar!, uri, resp);
  }

  Future<Map<String, dynamic>> _decode(http.Response resp) async {
    if (resp.body.isEmpty) return <String, dynamic>{};
    try {
      final decoded = jsonDecode(utf8.decode(resp.bodyBytes));
      if (decoded is Map) return Map<String, dynamic>.from(decoded);
      return <String, dynamic>{'data': decoded};
    } catch (_) {
      return <String, dynamic>{};
    }
  }

  Future<Map<String, dynamic>> _send(
    String method,
    String path, {
    Map<String, dynamic>? query,
    Object? body,
    Duration? timeout,
    String? idempotencyKey,
  }) async {
    await init();
    final uri = _uri(path, query);
    final headers = await _headersFor(uri);
    if (idempotencyKey != null && idempotencyKey.isNotEmpty) {
      headers['Idempotency-Key'] = idempotencyKey;
      headers['X-Client-Op-Id'] = idempotencyKey;
    }
    final effectiveTimeout = timeout ??
        (method == 'GET'
            ? const Duration(seconds: 45)
            : const Duration(seconds: 15));
    try {
      http.Response resp;
      final encodedBody = body == null ? null : jsonEncode(body);
      switch (method) {
        case 'GET':
          resp = await _http
              .get(uri, headers: headers)
              .timeout(effectiveTimeout);
          break;
        case 'POST':
          resp = await _http
              .post(uri, headers: headers, body: encodedBody)
              .timeout(effectiveTimeout);
          break;
        case 'PUT':
          resp = await _http
              .put(uri, headers: headers, body: encodedBody)
              .timeout(effectiveTimeout);
          break;
        default:
          throw ApiException('طريقة غير مدعومة: $method');
      }
      await _saveCookies(uri, resp);
      online.value = true;
      final data = await _decode(resp);
      if (resp.statusCode >= 200 && resp.statusCode < 300) {
        return data;
      }
      if (resp.statusCode == 401) {
        throw ApiException(
          (data['error'] ?? 'غير مسجّل الدخول').toString(),
          status: 401,
        );
      }
      throw ApiException(
        (data['error'] ?? 'حدث خطأ (${resp.statusCode})').toString(),
        status: resp.statusCode,
      );
    } on TimeoutException {
      online.value = false;
      throw ApiOfflineException('انتهت مهلة الاتصال بالخادم');
    } on ApiException {
      rethrow;
    } catch (e) {
      if (io_env.isNetworkError(e)) {
        online.value = false;
        throw ApiOfflineException();
      }
      online.value = false;
      throw ApiOfflineException();
    }
  }

  Future<Map<String, dynamic>> get(
    String path, {
    Map<String, dynamic>? query,
    Duration? timeout,
  }) {
    return _send('GET', path, query: query, timeout: timeout);
  }

  Future<Map<String, dynamic>> post(
    String path, {
    Object? body,
    String? idempotencyKey,
    Duration? timeout,
  }) {
    return _send(
      'POST',
      path,
      body: body ?? const {},
      idempotencyKey: idempotencyKey,
      timeout: timeout,
    );
  }

  Future<Map<String, dynamic>> put(
    String path, {
    Object? body,
    String? idempotencyKey,
    Duration? timeout,
  }) {
    return _send(
      'PUT',
      path,
      body: body ?? const {},
      idempotencyKey: idempotencyKey,
      timeout: timeout,
    );
  }

  Future<Map<String, dynamic>> uploadCriterionMedia({
    required String filePath,
    required int rowIndex,
    required String mediaKind,
    int? evaluationListItemId,
    int? bundleActionEvalId,
    String? idempotencyKey,
  }) async {
    await init();
    final uri = _uri('/api/tablet/media/criterion');
    final headers = await _headersFor(uri, json: false);
    if (idempotencyKey != null && idempotencyKey.isNotEmpty) {
      headers['Idempotency-Key'] = idempotencyKey;
      headers['X-Client-Op-Id'] = idempotencyKey;
    }
    final req = http.MultipartRequest('POST', uri);
    req.headers.addAll(headers);
    req.fields['row_index'] = '$rowIndex';
    req.fields['media_kind'] = mediaKind;
    if (idempotencyKey != null) {
      req.fields['client_op_id'] = idempotencyKey;
    }
    if (evaluationListItemId != null) {
      req.fields['evaluation_list_item_id'] = '$evaluationListItemId';
    }
    if (bundleActionEvalId != null) {
      req.fields['bundle_action_eval_id'] = '$bundleActionEvalId';
    }
    req.files.add(await http.MultipartFile.fromPath('file', filePath));
    try {
      final streamed = await req.send().timeout(const Duration(seconds: 60));
      final resp = await http.Response.fromStream(streamed);
      await _saveCookies(uri, resp);
      online.value = true;
      final data = await _decode(resp);
      if (resp.statusCode >= 200 && resp.statusCode < 300) return data;
      throw ApiException(
        (data['error'] ?? 'فشل رفع الملف').toString(),
        status: resp.statusCode,
      );
    } on TimeoutException {
      online.value = false;
      throw ApiOfflineException();
    } catch (e) {
      if (e is ApiException) rethrow;
      online.value = false;
      throw ApiOfflineException();
    }
  }

  Future<bool> ping({Duration timeout = const Duration(seconds: 3)}) async {
    try {
      await get('/api/tablet/health', timeout: timeout);
      return true;
    } catch (_) {
      online.value = false;
      return false;
    }
  }
}
