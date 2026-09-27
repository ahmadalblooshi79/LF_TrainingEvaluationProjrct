import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../theme/device_layout.dart';
import 'auth_service.dart';
import 'device_presence_service.dart';
import 'eval_excel_export.dart';
import 'offline_store.dart';
import 'package_sync_service.dart';
import 'sync_service.dart';

const int kTabletLocalApiPort = 8765;
const String kTabletLocalApiTokenPref = 'lf_local_api_token';

/// واجهة HTTP محلية للشبكة التشغيلية فقط — ليست للإنترنت.
class TabletLocalApi {
  TabletLocalApi._();
  static final TabletLocalApi instance = TabletLocalApi._();

  HttpServer? _server;
  String _token = '';
  bool _starting = false;

  String get token => _token;
  int get port => kTabletLocalApiPort;
  bool get running => _server != null;

  Future<void> initToken() async {
    if (kIsWeb) return;
    final prefs = await SharedPreferences.getInstance();
    var t = (prefs.getString(kTabletLocalApiTokenPref) ?? '').trim();
    if (t.isEmpty) {
      final r = Random.secure();
      t = List.generate(32, (_) => r.nextInt(256).toRadixString(16).padLeft(2, '0'))
          .join();
      await prefs.setString(kTabletLocalApiTokenPref, t);
    }
    _token = t;
  }

  Future<void> start() async {
    if (kIsWeb) return;
    if (_server != null || _starting) return;
    _starting = true;
    await initToken();
    try {
      _server = await HttpServer.bind(InternetAddress.anyIPv4, kTabletLocalApiPort);
      _server!.listen(_handle);
    } catch (e) {
      debugPrint('TabletLocalApi bind failed: $e');
      _server = null;
    } finally {
      _starting = false;
    }
  }

  Future<void> stop() async {
    await _server?.close(force: true);
    _server = null;
  }

  bool _authorized(HttpRequest req) {
    final h = req.headers.value('authorization') ?? '';
    final bearer = h.toLowerCase().startsWith('bearer ')
        ? h.substring(7).trim()
        : '';
    final headerTok = (req.headers.value('x-lf-tablet-token') ?? '').trim();
    final tok = bearer.isNotEmpty ? bearer : headerTok;
    return tok.isNotEmpty && tok == _token;
  }

  Future<void> _handle(HttpRequest req) async {
    try {
      if (!_authorized(req)) {
        await _json(req, {'ok': false, 'error': 'unauthorized'}, status: 401);
        return;
      }
      final path = req.uri.path;
      final method = req.method.toUpperCase();
      if (method == 'GET' && path == '/v1/health') {
        await _json(req, {
          'ok': true,
          'ready': true,
          'device_id': DevicePresenceService.instance.deviceId,
        });
        return;
      }
      if (method == 'GET' && path == '/v1/identity') {
        await _json(req, await _identity());
        return;
      }
      if (method == 'GET' && path == '/v1/summary') {
        await _json(req, await _summary());
        return;
      }
      if (method == 'GET' && path == '/v1/evaluations') {
        await _json(req, await _evaluations());
        return;
      }
      final pkg = RegExp(r'^/v1/evaluations/(\d+)/package$').firstMatch(path);
      if (method == 'GET' && pkg != null) {
        await _sendPackage(req, int.parse(pkg.group(1)!));
        return;
      }
      if (method == 'POST' && path == '/v1/ack') {
        final body = await _readJson(req);
        await _ack(body);
        await _json(req, {'ok': true, 'kept_local': true});
        return;
      }
      if (method == 'POST' && path == '/v1/update') {
        final body = await _readJson(req);
        final result = await _update(body);
        final code = result['code'] == 'LOCAL_WORK_EXISTS' ? 409 : 200;
        await _json(req, result, status: code);
        return;
      }
      await _json(req, {'ok': false, 'error': 'not_found'}, status: 404);
    } catch (e) {
      await _json(req, {'ok': false, 'error': '$e'}, status: 500);
    }
  }

  Future<Map<String, dynamic>> _identity() async {
    final session = AuthService.instance.session;
    return {
      'ok': true,
      'device_id': DevicePresenceService.instance.deviceId,
      'device_name': DevicePresenceService.instance.deviceName,
      'judge_id': session?.user.id,
      'judge_name': session?.user.judgeDisplayName ?? '',
      'user_id': session?.user.id,
      'unit_id': session?.unitKey ?? '',
      'unit_name': session?.unitLabel ?? '',
      'exercise_id': session?.exercise?.id,
      'exercise_name': session?.exercise?.name ?? session?.exercise?.code ?? '',
      'app_version': DeviceLayout.appVersion,
      'package_version': DeviceLayout.appVersion,
      'local_api_port': kTabletLocalApiPort,
    };
  }

  Future<Map<String, dynamic>> _summary() async {
    final drafts = await EvalExcelExportService.instance.listSavedEvaluations();
    final pending = SyncService.instance.pendingCount.value;
    return {
      'ok': true,
      'pending_saves': pending,
      'local_pending_saves': pending,
      'saved_count': drafts.length,
      'local_saved_count': drafts.length,
      'lists': [
        for (final d in drafts)
          {
            'eval_item_id': d.evalItemId,
            'title': d.listName,
            'unit_id': d.unitId,
            'unit_name': d.unitName,
            'has_local_result': true,
            'local_result': true,
            'source_mismatch': d.sourceMismatch,
            'approved': d.approved,
            'media_count': d.media.length,
          }
      ],
    };
  }

  Future<Map<String, dynamic>> _evaluations() async {
    final s = await _summary();
    return {
      'ok': true,
      'evaluations': s['lists'],
    };
  }

  Future<void> _sendPackage(HttpRequest req, int evalItemId) async {
    final result = await EvalExcelExportService.instance.exportEvalItem(evalItemId);
    if (!result.ok || result.data == null) {
      await _json(req, {'ok': false, 'error': result.error ?? 'export_failed'}, status: 404);
      return;
    }
    req.response.statusCode = 200;
    req.response.headers.contentType = ContentType('application', result.isZip ? 'zip' : 'vnd.openxmlformats-officedocument.spreadsheetml.sheet');
    req.response.headers.set('Content-Disposition', 'attachment; filename="${result.fileName}"');
    req.response.add(result.data!);
    await req.response.close();
  }

  Future<void> _ack(Map<String, dynamic> body) async {
    final ids = <int>[];
    final raw = body['eval_item_ids'];
    if (raw is List) {
      for (final x in raw) {
        final n = int.tryParse('$x');
        if (n != null && n > 0) ids.add(n);
      }
    }
    final now = DateTime.now().toIso8601String();
    for (final id in ids) {
      await OfflineStore.instance.setDeviceMeta('server_received:$id', now);
    }
  }

  Future<Map<String, dynamic>> _update(Map<String, dynamic> body) async {
    final ids = <int>[];
    final raw = body['eval_item_ids'];
    if (raw is List) {
      for (final x in raw) {
        final n = int.tryParse('$x');
        if (n != null && n > 0) ids.add(n);
      }
    }
    final drafts = await EvalExcelExportService.instance.listSavedEvaluations();
    final localIds = drafts.map((d) => d.evalItemId).toSet();
    final affected = ids.isEmpty
        ? localIds.toList()
        : ids.where(localIds.contains).toList();
    if (affected.isNotEmpty) {
      return {
        'ok': false,
        'code': 'LOCAL_WORK_EXISTS',
        'status': 'LOCAL_WORK_EXISTS',
        'message': 'يوجد عمل محلي على الجهاز لم يتم استلامه.',
        'eval_item_ids': affected,
      };
    }
    final ok = await PackageSyncService.instance.updateMyData();
    if (!ok) {
      return {
        'ok': false,
        'error': PackageSyncService.instance.lastError ?? 'update_failed',
      };
    }
    return {'ok': true, 'updated': true};
  }

  Future<Map<String, dynamic>> _readJson(HttpRequest req) async {
    final raw = await utf8.decoder.bind(req).join();
    if (raw.trim().isEmpty) return {};
    final decoded = jsonDecode(raw);
    if (decoded is Map<String, dynamic>) return decoded;
    if (decoded is Map) return Map<String, dynamic>.from(decoded);
    return {};
  }

  Future<void> _json(HttpRequest req, Map<String, dynamic> body, {int status = 200}) async {
    req.response.statusCode = status;
    req.response.headers.contentType = ContentType.json;
    req.response.write(jsonEncode(body));
    await req.response.close();
  }
}
