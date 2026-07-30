import 'dart:io';

import 'package:cookie_jar/cookie_jar.dart';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';

Future<CookieJar> createCookieJar() async {
  try {
    final dir = await getApplicationDocumentsDirectory();
    final cookiePath = '${dir.path}${Platform.pathSeparator}.cookies';
    return PersistCookieJar(
      storage: FileStorage(cookiePath),
      ignoreExpires: false,
    );
  } catch (_) {
    return PersistCookieJar();
  }
}

Future<void> saveCookiesFromResponse(
  CookieJar jar,
  Uri uri,
  http.Response resp,
) async {
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
}

bool isNetworkError(Object e) => e is SocketException || e is HttpException;

List<String> _splitSetCookieHeader(String raw) {
  final re = RegExp(r",(?=\s*[!#$%&'*+\-.0-9A-Z^_`a-z|~]+=)");
  return raw.split(re).map((s) => s.trim()).toList();
}
