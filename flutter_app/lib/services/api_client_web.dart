import 'dart:async';

import 'package:cookie_jar/cookie_jar.dart';
import 'package:http/http.dart' as http;

Future<CookieJar> createCookieJar() async => CookieJar();

Future<void> saveCookiesFromResponse(
  CookieJar jar,
  Uri uri,
  http.Response resp,
) async {
  // Browser handles Set-Cookie for same-origin PWA.
}

Future<List<Cookie>> loadCookiesForRequest(CookieJar jar, Uri uri) async {
  try {
    return await jar.loadForRequest(uri);
  } catch (_) {
    return const [];
  }
}

bool isNetworkError(Object e) => e is http.ClientException;

Future<http.Response> sendHttp({
  required String method,
  required Uri uri,
  required Map<String, String> headers,
  List<int>? bodyBytes,
  required Duration timeout,
  CookieJar? cookieJar,
}) async {
  final client = http.Client();
  try {
    final req = http.Request(method.toUpperCase(), uri);
    req.headers.addAll(headers);
    if (bodyBytes != null) {
      req.bodyBytes = bodyBytes;
    }
    final streamed = await client.send(req).timeout(timeout);
    return await http.Response.fromStream(streamed).timeout(timeout);
  } finally {
    client.close();
  }
}

Future<({bool ok, String detail})> probeServer(
  String baseUrl, {
  Duration timeout = const Duration(seconds: 10),
}) async {
  final base = baseUrl.trim().replaceAll(RegExp(r'/+$'), '');
  final origin = base.isEmpty ? Uri.base.origin : base;
  try {
    final resp = await http
        .get(
          Uri.parse('$origin/api/tablet/health'),
          headers: const {'Accept': 'application/json'},
        )
        .timeout(timeout);
    if (resp.statusCode >= 200 && resp.statusCode < 300) {
      return (ok: true, detail: 'OK ${resp.statusCode}');
    }
    return (ok: false, detail: 'HTTP ${resp.statusCode}');
  } on TimeoutException {
    return (ok: false, detail: 'انتهت مهلة الاتصال');
  } catch (e) {
    return (ok: false, detail: '$e');
  }
}
