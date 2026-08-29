import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:cookie_jar/cookie_jar.dart';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';

Future<CookieJar> createCookieJar() async {
  try {
    final dir = await getApplicationDocumentsDirectory();
    final cookiePath = '${dir.path}${Platform.pathSeparator}.cookies';
    await Directory(cookiePath).create(recursive: true);
    return PersistCookieJar(
      storage: FileStorage(cookiePath),
      ignoreExpires: false,
    );
  } catch (_) {
    return CookieJar();
  }
}

Future<void> saveCookiesFromResponse(
  CookieJar jar,
  Uri uri,
  http.Response resp,
) async {
  try {
    final raw = resp.headers['set-cookie'];
    if (raw == null || raw.isEmpty) return;
    final parts = _splitSetCookieHeader(raw);
    final cookies = <Cookie>[];
    for (final part in parts) {
      try {
        cookies.add(Cookie.fromSetCookieValue(part));
      } catch (_) {}
    }
    if (cookies.isNotEmpty) {
      await jar.saveFromResponse(uri, cookies);
    }
  } catch (_) {}
}

Future<List<Cookie>> loadCookiesForRequest(CookieJar jar, Uri uri) async {
  try {
    return await jar.loadForRequest(uri);
  } catch (_) {
    return const [];
  }
}

bool isNetworkError(Object e) =>
    e is SocketException ||
    e is HttpException ||
    e is HandshakeException ||
    e is TlsException ||
    (e is http.ClientException);

/// طلب HTTP عبر HttpClient جديد كل مرة + حفظ كوكيز الجلسة.
Future<http.Response> sendHttp({
  required String method,
  required Uri uri,
  required Map<String, String> headers,
  List<int>? bodyBytes,
  required Duration timeout,
  CookieJar? cookieJar,
}) async {
  final client = HttpClient()
    ..connectionTimeout = timeout
    ..idleTimeout = const Duration(seconds: 20)
    ..autoUncompress = true
    ..maxConnectionsPerHost = 4;
  try {
    final HttpClientRequest req;
    switch (method.toUpperCase()) {
      case 'GET':
        req = await client.getUrl(uri).timeout(timeout);
        break;
      case 'POST':
        req = await client.postUrl(uri).timeout(timeout);
        break;
      case 'PUT':
        req = await client.putUrl(uri).timeout(timeout);
        break;
      case 'DELETE':
        req = await client.deleteUrl(uri).timeout(timeout);
        break;
      default:
        throw HttpException('Unsupported method $method');
    }
    headers.forEach((k, v) {
      if (k.toLowerCase() == 'content-length') return;
      req.headers.set(k, v);
    });
    req.headers.set(HttpHeaders.connectionHeader, 'close');
    if (bodyBytes != null && bodyBytes.isNotEmpty) {
      req.contentLength = bodyBytes.length;
      req.add(bodyBytes);
    }
    final resp = await req.close().timeout(timeout);
    final builder = BytesBuilder(copy: false);
    await for (final chunk in resp.timeout(timeout)) {
      builder.add(chunk);
    }
    final bytes = builder.takeBytes();

    if (cookieJar != null && resp.cookies.isNotEmpty) {
      try {
        await cookieJar.saveFromResponse(uri, resp.cookies);
      } catch (_) {}
    }

    final headerMap = <String, String>{};
    resp.headers.forEach((name, values) {
      headerMap[name] = values.join(', ');
    });
    return http.Response.bytes(
      bytes,
      resp.statusCode,
      headers: headerMap,
      request: http.Request(method.toUpperCase(), uri),
    );
  } finally {
    client.close(force: true);
  }
}

/// فحص وصول مباشر بدون كوكيز.
Future<({bool ok, String detail})> probeServer(
  String baseUrl, {
  Duration timeout = const Duration(seconds: 10),
}) async {
  final base = baseUrl.trim().replaceAll(RegExp(r'/+$'), '');
  if (base.isEmpty) {
    return (ok: false, detail: 'لم يُضبط عنوان السيرفر');
  }
  final uri = Uri.tryParse('$base/api/tablet/health');
  if (uri == null || !uri.hasScheme || uri.host.isEmpty) {
    return (ok: false, detail: 'عنوان غير صالح: $base');
  }

  final port = uri.hasPort
      ? uri.port
      : (uri.scheme == 'https' ? 443 : 80);

  try {
    final socket = await Socket.connect(uri.host, port, timeout: timeout);
    await socket.close();
  } on SocketException catch (e) {
    final msg = (e.message).trim();
    final os = e.osError;
    return (
      ok: false,
      detail:
          'لا وصول لـ ${uri.host}:$port'
          '${msg.isNotEmpty ? ' ($msg)' : ''}'
          '${os != null ? ' [${os.message}]' : ''}',
    );
  } on TimeoutException {
    return (ok: false, detail: 'انتهت مهلة TCP إلى ${uri.host}:$port');
  } catch (e) {
    return (ok: false, detail: 'فشل TCP: $e');
  }

  final client = HttpClient()
    ..connectionTimeout = timeout
    ..idleTimeout = const Duration(seconds: 5)
    ..autoUncompress = true;
  try {
    final req = await client.getUrl(uri).timeout(timeout);
    req.headers.set(HttpHeaders.acceptHeader, 'application/json');
    req.headers.set(HttpHeaders.connectionHeader, 'close');
    req.followRedirects = true;
    final resp = await req.close().timeout(timeout);
    final body = await resp.transform(utf8.decoder).join();
    if (resp.statusCode >= 200 && resp.statusCode < 300) {
      return (ok: true, detail: 'OK ${resp.statusCode}');
    }
    return (
      ok: false,
      detail: 'HTTP ${resp.statusCode}${body.isNotEmpty ? ': $body' : ''}',
    );
  } on TimeoutException {
    return (
      ok: false,
      detail: 'انتهت مهلة HTTP — السيرفر وصل TCP لكن /api/tablet/health لم يرد',
    );
  } on SocketException catch (e) {
    return (ok: false, detail: 'Socket أثناء HTTP: ${e.message}');
  } on HttpException catch (e) {
    return (ok: false, detail: 'HTTP: ${e.message}');
  } catch (e) {
    return (ok: false, detail: 'خطأ: $e');
  } finally {
    client.close(force: true);
  }
}

List<String> _splitSetCookieHeader(String raw) {
  final re = RegExp(r",(?=\s*[!#$%&'*+\-.0-9A-Z^_`a-z|~]+=)");
  return raw.split(re).map((s) => s.trim()).toList();
}
