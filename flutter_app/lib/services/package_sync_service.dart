import '../models/list_row.dart';
import 'api_client.dart';
import 'auth_service.dart';
import 'device_admin_service.dart';
import 'library_pdf_cache.dart';
import 'notifications_badge_service.dart';
import 'offline_store.dart';
import 'tablet_repository.dart';

typedef ProvisionProgress = void Function(String message);

/// تنزيل وتخزين حزمة التمرين مع عزل كل محكم في Local DB.
class PackageSyncService {
  PackageSyncService._();
  static final PackageSyncService instance = PackageSyncService._();

  String? lastError;
  int lastJudgeCount = 0;

  Future<bool> setupLogin(String username, String password) async {
    lastError = null;
    try {
      await ApiClient.instance.post(
        '/api/tablet/device/setup-login',
        body: {'username': username, 'password': password},
        timeout: const Duration(seconds: 30),
      );
      return true;
    } on ApiOfflineException catch (e) {
      lastError = e.message;
      return false;
    } on ApiException catch (e) {
      lastError = e.message;
      return false;
    } catch (e) {
      lastError = 'تعذر الاتصال بالسيرفر: $e';
      return false;
    }
  }

  Future<Map<String, dynamic>> _get(
    String path, {
    Map<String, dynamic>? query,
    Duration timeout = const Duration(seconds: 90),
  }) {
    return ApiClient.instance.get(path, query: query, timeout: timeout);
  }

  Future<void> _putJudge(
    int userId,
    String cacheKey,
    Map<String, dynamic> data, {
    bool writeUnscoped = false,
  }) {
    return TabletRepository.instance.provisionPutForUser(
      userId: userId,
      cacheKey: cacheKey,
      data: data,
      writeUnscoped: writeUnscoped,
    );
  }

  Future<bool> _pdfBytesReady(int nodeId) async {
    if (!await LibraryPdfCache.has(nodeId)) return false;
    final b = await LibraryPdfCache.get(nodeId);
    return b != null && b.isNotEmpty;
  }

  Future<bool> _namedPdfReady(String dayId) async {
    if (!await LibraryPdfCache.hasNamed(dayId)) return false;
    final b = await LibraryPdfCache.getNamed(dayId);
    return b != null && b.isNotEmpty;
  }

  Future<void> _provisionActionDetails(
    int userId,
    Map<String, dynamic> listsPayload,
  ) async {
    final lists = ((listsPayload['lists'] as List?) ?? const [])
        .whereType<Map>()
        .map((e) => ListRow.fromJson(e.cast<String, dynamic>()))
        .toList();
    for (final row in lists) {
      final slot = TabletRepository.instance.actionEvalOpenId(row);
      if (slot == null) continue;
      final q = <String, dynamic>{};
      if (row.slotId != null) q['action_eval_id'] = row.slotId;
      try {
        final detail = await _get(
          '/api/tablet/device/judge/$userId/action-eval/$slot',
          query: q.isEmpty ? null : q,
        );
        await _putJudge(userId, 'action_eval_detail:$slot', detail);
      } catch (_) {}
    }
  }

  Future<void> _provisionEvalDetails(
    int userId,
    Map<String, dynamic> payload,
    String unitKey,
  ) async {
    final lists = ((payload['lists'] as List?) ?? const [])
        .whereType<Map>()
        .map((e) => ListRow.fromJson(e.cast<String, dynamic>()))
        .toList();
    for (final row in lists) {
      final id =
          row.itemId ?? (row.id is int ? row.id as int : int.tryParse('${row.id}'));
      if (id == null) continue;
      final uk = row.unitKey.isNotEmpty ? row.unitKey : unitKey;
      if (uk.isEmpty) continue;
      try {
        final detail = await _get(
          '/api/tablet/device/judge/$userId/evaluation-lists/$uk/$id',
        );
        await _putJudge(userId, 'evaluation_list_detail:$uk:$id', detail);
      } catch (_) {}
    }
  }

  Future<bool> _verifyJudgeReady(int userId) async {
    const keys = [
      'home',
      'bootstrap',
      'session_bundle',
      'objectives',
      'evaluation_lists::',
      'action_eval_lists:',
      'flow:',
      'exercise_details',
      'polarity_notes',
      'incomplete',
    ];
    for (final k in keys) {
      final v = await OfflineStore.instance.cacheGetForUser(userId, k);
      if (v == null) return false;
    }
    return true;
  }

  Future<bool> downloadAndStorePackage({ProvisionProgress? onProgress}) async {
    lastError = null;
    lastJudgeCount = 0;
    final failures = <String>[];
    try {
      onProgress?.call('الاتصال بالسيرفر');
      onProgress?.call('تنزيل معلومات التمرين');
      final manifest = await _get('/api/tablet/device/manifest');
      final judges = (manifest['judges'] as List?) ?? const [];
      if (judges.isEmpty) {
        lastError =
            'الحزمة وصلت لكن بدون محكمين — تأكد من وجود حسابات محكمين في التمرين';
        await DeviceAdminService.instance.clearDeviceReady();
        return false;
      }

      onProgress?.call('تنزيل حسابات المحكمين');
      final judgeIds = <int>[];
      for (final raw in judges) {
        if (raw is! Map) continue;
        final j = Map<String, dynamic>.from(raw);
        final userId = (j['user_id'] as num?)?.toInt() ?? 0;
        final username = (j['username'] ?? '').toString().trim();
        if (userId <= 0 || username.isEmpty) continue;
        final seed = (j['local_password_seed'] ?? username).toString();
        final sessionMap = j['session'] is Map
            ? Map<String, dynamic>.from(j['session'] as Map)
            : <String, dynamic>{};
        final sessionPayload = {'ok': true, ...sessionMap};
        final hash = await credentialDigest(username, seed);
        await OfflineStore.instance.upsertLocalUser(
          userId: userId,
          username: username,
          passwordHash: hash,
          session: sessionPayload,
          militaryNumber: (j['military_number'] ?? '').toString(),
        );
        await _putJudge(userId, 'session_bundle', sessionPayload);
        judgeIds.add(userId);
      }
      lastJudgeCount = judgeIds.length;
      if (judgeIds.isEmpty) {
        lastError =
            'الحزمة وصلت لكن بدون محكمين — تأكد من وجود حسابات محكمين في التمرين';
        await DeviceAdminService.instance.clearDeviceReady();
        return false;
      }

      if (manifest['exercise'] is Map) {
        await OfflineStore.instance.cacheSet(
          'device_exercise',
          Map<String, dynamic>.from(manifest['exercise'] as Map),
        );
      }

      Map<String, dynamic>? sharedExerciseDetails;
      try {
        sharedExerciseDetails = await _get('/api/tablet/device/exercise-details');
        await OfflineStore.instance.cacheSet(
          'exercise_details',
          sharedExerciseDetails,
        );
      } catch (e) {
        failures.add('تفاصيل التمرين: $e');
      }

      final flowDayIds = <String>{};
      final n = judgeIds.length;
      for (var i = 0; i < n; i++) {
        final userId = judgeIds[i];
        onProgress?.call('تهيئة المحكم ${i + 1} من $n');
        try {
          final bootstrap = await _get(
            '/api/tablet/device/judge/$userId/bootstrap',
          );
          await _putJudge(userId, 'bootstrap', bootstrap);
          if (bootstrap['home'] is Map) {
            await _putJudge(
              userId,
              'home',
              Map<String, dynamic>.from(bootstrap['home'] as Map),
            );
          } else {
            final home = await _get('/api/tablet/device/judge/$userId/home');
            await _putJudge(userId, 'home', home);
          }

          onProgress?.call('تنزيل قوائم التقييم');
          try {
            final ev = await _get(
              '/api/tablet/device/judge/$userId/evaluation-lists',
            );
            await _putJudge(userId, 'evaluation_lists::', ev);
            final uk = (ev['unit_key'] ?? '').toString();
            final defaultPhase = (ev['phase_key'] ?? '').toString();
            await TabletRepository.instance.provisionMirrorEvalListsForUser(
              userId,
              ev,
              unitKey: uk,
              phase: defaultPhase,
            );
            await _provisionEvalDetails(userId, ev, uk);
            final phaseTabs = ((ev['phase_tabs'] as List?) ?? const [])
                .whereType<Map>()
                .map((e) => (e['key'] ?? '').toString())
                .where((id) => id.isNotEmpty);
            for (final pk in phaseTabs) {
              if (pk == defaultPhase) continue;
              try {
                final q = <String, dynamic>{'phase': pk};
                if (uk.isNotEmpty) q['unit_key'] = uk;
                final phaseEv = await _get(
                  '/api/tablet/device/judge/$userId/evaluation-lists',
                  query: q,
                );
                await TabletRepository.instance.provisionMirrorEvalListsForUser(
                  userId,
                  phaseEv,
                  unitKey: uk,
                  phase: pk,
                );
                await _provisionEvalDetails(userId, phaseEv, uk);
              } catch (_) {}
            }
          } catch (e) {
            failures.add('قوائم التقييم للمحكم $userId: $e');
          }

          onProgress?.call('تنزيل قوائم تقييم المعاضل');
          try {
            final lists = await _get(
              '/api/tablet/device/judge/$userId/action-eval',
            );
            await _putJudge(userId, 'action_eval_lists:', lists);
            await _provisionActionDetails(userId, lists);
            final dayTabs = ((lists['day_tabs'] as List?) ?? const [])
                .whereType<Map>()
                .map((e) => (e['id'] ?? '').toString())
                .where((id) => id.isNotEmpty);
            for (final d in dayTabs) {
              try {
                final dayLists = await _get(
                  '/api/tablet/device/judge/$userId/action-eval',
                  query: {'day': d},
                );
                await _putJudge(userId, 'action_eval_lists:$d', dayLists);
                await _provisionActionDetails(userId, dayLists);
              } catch (_) {}
            }
          } catch (e) {
            failures.add('قوائم تقييم المعاضل للمحكم $userId: $e');
          }

          onProgress?.call('تنزيل مجرى الأحداث والمعاضل');
          try {
            final flow = await _get('/api/tablet/device/judge/$userId/flow');
            await _putJudge(userId, 'flow:', flow);
            final days = ((flow['days'] as List?) ?? const [])
                .whereType<Map>()
                .map((e) => (e['id'] ?? '').toString())
                .where((id) => id.isNotEmpty);
            for (final d in days) {
              flowDayIds.add(d);
              try {
                final dayFlow = await _get(
                  '/api/tablet/device/judge/$userId/flow',
                  query: {'day': d},
                );
                await _putJudge(userId, 'flow:$d', dayFlow);
              } catch (_) {}
            }
          } catch (e) {
            failures.add('المجرى للمحكم $userId: $e');
          }

          if (sharedExerciseDetails != null) {
            await _putJudge(
              userId,
              'exercise_details',
              sharedExerciseDetails,
              writeUnscoped: false,
            );
          } else {
            try {
              final ed = await _get(
                '/api/tablet/device/judge/$userId/exercise-details',
              );
              await _putJudge(userId, 'exercise_details', ed);
            } catch (e) {
              failures.add('تفاصيل التمرين للمحكم $userId: $e');
            }
          }

          try {
            final obj = await _get(
              '/api/tablet/device/judge/$userId/objectives',
            );
            await _putJudge(userId, 'objectives', obj);
          } catch (_) {
            await _putJudge(userId, 'objectives', {
              'ok': true,
              'objectives': manifest['objectives'] ?? [],
            });
          }

          try {
            final notes = await _get(
              '/api/tablet/device/judge/$userId/polarity-notes',
            );
            await _putJudge(userId, 'polarity_notes', notes);
          } catch (_) {
            await _putJudge(userId, 'polarity_notes', {
              'ok': true,
              'notes': <dynamic>[],
            });
          }

          try {
            final inc = await _get(
              '/api/tablet/device/judge/$userId/incomplete',
            );
            await _putJudge(userId, 'incomplete', inc);
          } catch (_) {
            await _putJudge(userId, 'incomplete', {
              'ok': true,
              'count': 0,
              'tasks': <dynamic>[],
            });
          }
        } catch (e) {
          failures.add('تهيئة المحكم $userId: $e');
        }
      }

      onProgress?.call('تنزيل المكتبة وأوراق التمرين');
      final pdfIds = <int>{};
      Map<String, dynamic>? libraryPayload;
      Map<String, dynamic>? papersPayload;
      try {
        libraryPayload = await _get('/api/tablet/device/library');
        await OfflineStore.instance.cacheSet('library', libraryPayload);
        pdfIds.addAll(
          TabletRepository.instance.collectPdfNodeIds(libraryPayload['trees']),
        );
        for (final uid in judgeIds) {
          await _putJudge(
            uid,
            'library',
            libraryPayload,
            writeUnscoped: false,
          );
        }
      } catch (e) {
        failures.add('المكتبة: $e');
      }
      try {
        papersPayload = await _get('/api/tablet/device/exercise-papers');
        await OfflineStore.instance.cacheSet('exercise_papers', papersPayload);
        pdfIds.addAll(
          TabletRepository.instance.collectPdfNodeIds(papersPayload['tree']),
        );
        for (final uid in judgeIds) {
          await _putJudge(
            uid,
            'exercise_papers',
            papersPayload,
            writeUnscoped: false,
          );
        }
      } catch (e) {
        failures.add('أوراق التمرين: $e');
      }

      onProgress?.call('تنزيل ملفات PDF');
      final missingPdfs = <String>[];
      for (final id in pdfIds) {
        try {
          if (await _pdfBytesReady(id)) continue;
          final bytes = await ApiClient.instance.getBytes(
            '/api/tablet/device/files/library/$id',
            timeout: const Duration(seconds: 120),
          );
          if (bytes.isNotEmpty) {
            await LibraryPdfCache.put(id, bytes);
          } else {
            missingPdfs.add('مكتبة $id');
          }
        } catch (e) {
          missingPdfs.add('مكتبة $id ($e)');
        }
      }
      var flowJudgeHint = judgeIds.isEmpty ? 0 : judgeIds.first;
      for (final dayId in flowDayIds) {
        try {
          if (await _namedPdfReady(dayId)) continue;
          final bytes = await ApiClient.instance.getBytes(
            '/api/tablet/device/files/flow-days/$dayId',
            query: flowJudgeHint > 0 ? {'judge_id': flowJudgeHint} : null,
            timeout: const Duration(seconds: 120),
          );
          if (bytes.isNotEmpty) {
            await LibraryPdfCache.putNamed(dayId, bytes);
          }
        } on ApiException catch (e) {
          if (e.status == 404) continue;
          missingPdfs.add('مجرى $dayId');
        } catch (e) {
          missingPdfs.add('مجرى $dayId ($e)');
        }
      }
      if (missingPdfs.isNotEmpty) {
        failures.add('ملفات PDF ناقصة: ${missingPdfs.length}');
      }

      onProgress?.call('التحقق من البيانات');
      var allJudgesOk = true;
      for (final uid in judgeIds) {
        if (!await _verifyJudgeReady(uid)) {
          allJudgesOk = false;
          failures.add('التحقق: بيانات ناقصة للمحكم $uid');
        }
      }
      final libOk = await OfflineStore.instance.cacheGet('library') != null;
      final papersOk =
          await OfflineStore.instance.cacheGet('exercise_papers') != null;
      if (!libOk) failures.add('التحقق: المكتبة غير مخزّنة');
      if (!papersOk) failures.add('التحقق: أوراق التمرين غير مخزّنة');
      for (final id in pdfIds) {
        if (!await _pdfBytesReady(id)) {
          allJudgesOk = false;
          failures.add('التحقق: PDF مكتبة $id');
        }
      }

      final ready = allJudgesOk &&
          libOk &&
          papersOk &&
          missingPdfs.isEmpty &&
          failures.isEmpty;
      if (!ready) {
        lastError = failures.isEmpty
            ? 'التهيئة غير مكتملة'
            : failures.take(4).join('\n');
        await DeviceAdminService.instance.clearDeviceReady();
        return false;
      }

      await DeviceAdminService.instance.markDeviceReady();
      onProgress?.call('تمت تهيئة الجهاز بنجاح');
      return true;
    } on ApiOfflineException catch (e) {
      lastError = e.message;
      await DeviceAdminService.instance.clearDeviceReady();
      return false;
    } on ApiException catch (e) {
      lastError = e.message;
      await DeviceAdminService.instance.clearDeviceReady();
      return false;
    } catch (e) {
      final msg = '$e';
      if (msg.contains('QuotaExceeded')) {
        lastError =
            'امتلأ التخزين المحلي للمتصفح. امسح بيانات الموقع ثم أعد تهيئة الجهاز.';
      } else {
        lastError = 'فشل تنزيل الحزمة: $e';
      }
      await DeviceAdminService.instance.clearDeviceReady();
      return false;
    }
  }

  /// تحديث بيانات المحكم الحالي فقط من السيرفر.
  Future<bool> updateMyData() async {
    lastError = null;
    final session = AuthService.instance.session;
    final uid = session?.user.id ?? 0;
    if (uid <= 0) {
      lastError = 'لا توجد جلسة محكم';
      return false;
    }
    try {
      final data = await ApiClient.instance.get(
        '/api/tablet/me/updates',
        timeout: const Duration(seconds: 60),
      );
      await OfflineStore.instance.cacheSetForUser(uid, 'bootstrap', data);
      await OfflineStore.instance.cacheSetForUser(uid, 'session_bundle', data);
      if (data['home'] is Map) {
        await OfflineStore.instance.cacheSetForUser(
          uid,
          'home',
          Map<String, dynamic>.from(data['home'] as Map),
        );
      }
      final objectives = {
        'ok': true,
        'user': data['user'],
        'exercise': data['exercise'],
        'objectives': data['objectives'] ?? [],
      };
      await OfflineStore.instance.cacheSetForUser(uid, 'objectives', objectives);
      if (data['polarity_notes'] is Map) {
        await OfflineStore.instance.cacheSetForUser(
          uid,
          'polarity_notes',
          Map<String, dynamic>.from(data['polarity_notes'] as Map),
        );
      }
      AuthService.instance.applySessionJson(data);
      try {
        await TabletRepository.instance.prefetchForOffline();
      } catch (_) {}
      try {
        await TabletRepository.instance.fetchExerciseDetails();
      } catch (_) {}
      await AuthService.saveLastSyncAt(DateTime.now());
      await NotificationsBadgeService.instance.reportSyncEvent(
        kind: 'update',
        detail: 'تم تحديث بياناتي من النظام.',
      );
      return true;
    } on ApiException catch (e) {
      lastError = e.message;
      return false;
    } catch (e) {
      lastError = '$e';
      return false;
    }
  }
}
