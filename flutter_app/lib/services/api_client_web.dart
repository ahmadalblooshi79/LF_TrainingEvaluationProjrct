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

bool isNetworkError(Object e) => false;
