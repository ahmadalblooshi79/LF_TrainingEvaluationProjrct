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

  CookieJar? _cookieJar;
  String _baseUrl = '';
  bool _ready = false;

  final ValueNotifier<bool> online = ValueNotifier<bool>(true);

  /// آخر تفاصيل فحص الاتصال (للواجهة).
  String lastPingDetail = '';

  String get baseUrl => _baseUrl;

  /// On web, empty baseUrl means same origin (served from Flask `/tablet/`).
  bool get isConfigured => kIsWeb || _baseUrl.trim().isNotEmpty;

  Future<void> init() async {
    if (_ready) return;
    final prefs = await SharedPreferences.getInstance();
    final raw = (prefs.getString(kServerBaseUrlPrefKey) ?? '').trim();
    _baseUrl = raw.isEmpty ? '' : _normalizeBaseUrl(raw);
    // أعد حفظ العنوان المطبَّع (منفذ 8005 / أرقام لاتينية) إن تغيّر
    if (_baseUrl.isNotEmpty && _baseUrl != raw) {
      await prefs.setString(kServerBaseUrlPrefKey, _baseUrl);
    }
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
    await init();
    final next = _normalizeBaseUrl(url);
    // لا تمسح عنوان السيرفر المحفوظ عند تحديث التطبيق أو تمرير قيمة فارغة
    if (next.isEmpty && _baseUrl.isNotEmpty) return;
    _baseUrl = next;
    if (_baseUrl.isEmpty) return;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(kServerBaseUrlPrefKey, _baseUrl);
  }

  /// يطبيّع العنوان: أرقام عربية → لاتينية، http افتراضي، منفذ 8005 إن غاب.
  static String _normalizeBaseUrl(String url) {
    var u = _toWesternDigits(url.trim())
        .replaceAll('\u200e', '')
        .replaceAll('\u200f', '')
        .replaceAll('\u202a', '')
        .replaceAll('\u202b', '')
        .replaceAll('\u202c', '')
        .replaceAll(' ', '');
    if (u.endsWith('/')) u = u.substring(0, u.length - 1);
    if (u.isEmpty) return u;
    if (!u.startsWith('http://') && !u.startsWith('https://')) {
      u = 'http://$u';
    }
    final parsed = Uri.tryParse(u);
    if (parsed == null || !parsed.hasAuthority) return u;
    // إن لم يُحدد المنفذ لـ http → المنفذ الافتراضي للتطبيق 8005
    if (!parsed.hasPort &&
        (parsed.scheme == 'http' || parsed.scheme.isEmpty)) {
      return parsed.replace(scheme: 'http', port: 8005).toString().replaceAll(RegExp(r'/$'), '');
    }
    return parsed.toString().replaceAll(RegExp(r'/$'), '');
  }

  static String _toWesternDigits(String input) {
    const eastern = '٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹';
    const western = '01234567890123456789';
    final buf = StringBuffer();
    for (final rune in input.runes) {
      final ch = String.fromCharCode(rune);
      final i = eastern.indexOf(ch);
      buf.write(i >= 0 ? western[i] : ch);
    }
    return buf.toString();
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

  Future<Map<String, String>> _headersFor(
    Uri uri, {
    bool jsonBody = false,
  }) async {
    final headers = <String, String>{'Accept': 'application/json'};
    if (jsonBody) headers['Content-Type'] = 'application/json';
    if (!kIsWeb) {
      final cookies =
          await io_env.loadCookiesForRequest(_cookieJar ?? CookieJar(), uri);
      if (cookies.isNotEmpty) {
        headers['Cookie'] =
            cookies.map((c) => '${c.name}=${c.value}').join('; ');
      }
    }
    try {
      final prefs = await SharedPreferences.getInstance();
      final did = (prefs.getString('lf_device_id') ?? '').trim();
      if (did.isNotEmpty) {
        // معرّف الجهاز ASCII فقط
        headers['X-LF-Device-Id'] = did.replaceAll(RegExp(r'[^\x20-\x7E]'), '');
      }
      final dname = (prefs.getString('lf_device_name') ?? '').trim();
      if (dname.isNotEmpty) {
        // ترويسات HTTP لا تقبل العربية — نرسلها مرمّزة ثم يفكّها السيرفر
        headers['X-LF-Device-Name'] = Uri.encodeComponent(dname);
      }
    } catch (_) {}
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
    final headers = await _headersFor(uri, jsonBody: body != null);
    if (idempotencyKey != null && idempotencyKey.isNotEmpty) {
      headers['Idempotency-Key'] = idempotencyKey;
      headers['X-Client-Op-Id'] = idempotencyKey;
    }
    final effectiveTimeout = timeout ??
        (method == 'GET'
            ? const Duration(seconds: 45)
            : const Duration(seconds: 20));
    try {
      final encodedBody =
          body == null ? null : utf8.encode(jsonEncode(body));
      final resp = await io_env.sendHttp(
        method: method,
        uri: uri,
        headers: headers,
        bodyBytes: encodedBody,
        timeout: effectiveTimeout,
        cookieJar: kIsWeb ? null : _cookieJar,
      );
      // احتياطي إن لم تُحفظ كوكيز dart:io
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
      online.value = false;
      final msg = e.toString();
      throw ApiOfflineException(
        msg.isNotEmpty && msg != 'Instance of \'ApiOfflineException\''
            ? 'تعذّر الاتصال بالخادم ($msg)'
            : 'تعذّر الاتصال بالخادم',
      );
    }
  }

  Future<Map<String, dynamic>> get(
    String path, {
    Map<String, dynamic>? query,
    Duration? timeout,
  }) {
    return _send('GET', path, query: query, timeout: timeout);
  }

  /// جلب بايتات ملف ثنائي (مثل PDF المكتبة) مع جلسة المصادقة.
  Future<List<int>> getBytes(
    String path, {
    Map<String, dynamic>? query,
    Duration? timeout,
  }) async {
    await init();
    final uri = _uri(path, query);
    final headers = await _headersFor(uri, jsonBody: false);
    headers['Accept'] = '*/*';
    final effectiveTimeout = timeout ?? const Duration(seconds: 90);
    try {
      final resp = await io_env.sendHttp(
        method: 'GET',
        uri: uri,
        headers: headers,
        timeout: effectiveTimeout,
        cookieJar: kIsWeb ? null : _cookieJar,
      );
      await _saveCookies(uri, resp);
      online.value = true;
      if (resp.statusCode >= 200 && resp.statusCode < 300) {
        return resp.bodyBytes;
      }
      if (resp.statusCode == 401) {
        throw ApiException('غير مسجّل الدخول', status: 401);
      }
      var msg = 'تعذّر فتح الملف (${resp.statusCode})';
      try {
        final decoded = jsonDecode(utf8.decode(resp.bodyBytes));
        if (decoded is Map && decoded['error'] != null) {
          final err = decoded['error'].toString().trim();
          if (err.isNotEmpty) msg = err;
        }
      } catch (_) {}
      throw ApiException(msg, status: resp.statusCode);
    } on TimeoutException {
      online.value = false;
      throw ApiOfflineException('انتهت مهلة تحميل الملف');
    } on ApiException {
      rethrow;
    } catch (e) {
      online.value = false;
      throw ApiOfflineException('تعذّر الاتصال بالخادم ($e)');
    }
  }

  /// مسار مطلق لملف على السيرفر (للعرض عبر iframe في الويب).
  String absoluteUrl(String path) {
    final base = _baseUrl.isEmpty ? Uri.base.origin : _baseUrl;
    if (path.startsWith('http://') || path.startsWith('https://')) return path;
    final p = path.startsWith('/') ? path : '/$path';
    return '$base$p';
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

  Future<Map<String, dynamic>> delete(
    String path, {
    String? idempotencyKey,
    Duration? timeout,
  }) {
    return _send(
      'DELETE',
      path,
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
    final headers = await _headersFor(uri, jsonBody: false);
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

  /// رفع جزء واحد من ملف وسائط (streaming من البايتات المحسوبة مسبقاً للجزء).
  Future<Map<String, dynamic>> uploadMediaChunk({
    required String uploadSessionId,
    required String clientUuid,
    required int chunkNumber,
    required int totalChunks,
    required String chunkChecksum,
    required List<int> chunkBytes,
  }) async {
    await init();
    final uri = _uri('/api/tablet/media/upload/chunk');
    final headers = await _headersFor(uri, jsonBody: false);
    final req = http.MultipartRequest('POST', uri);
    req.headers.addAll(headers);
    req.fields['upload_session_id'] = uploadSessionId;
    req.fields['client_uuid'] = clientUuid;
    req.fields['chunk_number'] = '$chunkNumber';
    req.fields['total_chunks'] = '$totalChunks';
    req.fields['chunk_checksum'] = chunkChecksum;
    req.files.add(
      http.MultipartFile.fromBytes(
        'chunk',
        chunkBytes,
        filename: 'chunk_$chunkNumber.bin',
      ),
    );
    try {
      final streamed =
          await req.send().timeout(const Duration(minutes: 10));
      final resp = await http.Response.fromStream(streamed);
      await _saveCookies(uri, resp);
      online.value = true;
      final data = await _decode(resp);
      if (resp.statusCode >= 200 && resp.statusCode < 300) return data;
      throw ApiException(
        (data['error'] ?? 'فشل رفع الجزء').toString(),
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

  Future<bool> ping({Duration timeout = const Duration(seconds: 10)}) async {
    try {
      await init();
      if (!isConfigured) {
        online.value = false;
        lastPingDetail = 'لم يُضبط عنوان السيرفر';
        return false;
      }
      final base = _baseUrl.isEmpty ? Uri.base.origin : _baseUrl;
      final result = await io_env.probeServer(base, timeout: timeout);
      lastPingDetail = result.detail;
      online.value = result.ok;
      return result.ok;
    } catch (e) {
      online.value = false;
      lastPingDetail = '$e';
      return false;
    }
  }
}
