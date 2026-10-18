import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:lf_training_evaluation/services/device_eval_manager_models.dart';
import 'package:lf_training_evaluation/services/eval_cache_merge.dart';
import 'package:lf_training_evaluation/services/eval_status.dart';
import 'package:lf_training_evaluation/services/home_progress.dart';
import 'package:lf_training_evaluation/services/offline_store.dart';
import 'package:lf_training_evaluation/services/scoped_backup_paths.dart';
import 'package:path/path.dart' as p;

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  String readFlutter(String rel) {
    final candidates = [
      File(rel),
      File(p.join('flutter_app', rel)),
      File(p.join('..', rel)),
    ];
    for (final f in candidates) {
      if (f.existsSync()) return f.readAsStringSync();
    }
    fail('missing $rel cwd=${Directory.current.path}');
  }

  test('1-18 save waiting persist approval reopen consistency', () {
    final saved = <String, dynamic>{
      'locally_modified': true,
      'is_approved': false,
      'can_edit': true,
      'saved_payload': {
        'rows': [
          {'acquired': '8', 'notes': 'ملاحظة', 'element': 'بند'},
        ],
      },
      'saved_rows': [
        {'acquired': '8', 'notes': 'ملاحظة'},
      ],
      'local_media': [
        {'local_path': '/tmp/a.jpg', 'row_index': 0},
      ],
    };
    expect(evalStatusFromSheet(saved), kEvalStatusWaiting);
    expect(
      evalStatusIsIncomplete(statusLabel: kEvalStatusWaiting),
      isTrue,
    );

    final merged = mergeServerCacheWithLocal(
      server: {
        'is_approved': false,
        'status_label': 'لم ينجز',
        'eval_rows': <dynamic>[],
      },
      local: saved,
      cacheStatus: SyncStatuses.pending,
    );
    expect(merged['status_label'], kEvalStatusWaiting);
    expect(merged['is_approved'], isFalse);
    expect((merged['saved_payload'] as Map)['rows'].first['notes'], 'ملاحظة');
    expect((merged['local_media'] as List).first['local_path'], '/tmp/a.jpg');

    final approved = applyLocalReopenToDetail({
      ...saved,
      'locally_approved': true,
      'is_approved': true,
      'can_edit': false,
      'locally_modified': false,
      'status_label': kEvalStatusApproved,
      'workflow': {'label': kEvalStatusApproved, 'reopened': false},
    });
    expect(evalStatusFromSheet(approved), kEvalStatusReopened);
    expect(approved['can_edit'], isTrue);
    expect(approved['is_approved'], isFalse);

    final repo = readFlutter('lib/services/tablet_repository.dart');
    expect(repo.contains("newClientOpId('save-el-"), isTrue);
    expect(repo.contains("newClientOpId('save-ae-"), isTrue);
    expect(repo.contains('kEvalStatusWaiting'), isTrue);
    expect(repo.contains("opType: 'save_results'"), isTrue);
    expect(repo.contains("opType: 'approve'"), isTrue);
    expect(repo.contains('chief-reopen'), isFalse);
    final reopenSrc = readFlutter('lib/services/device_eval_manager_service.dart');
    expect(reopenSrc.contains('chief-reopen'), isTrue);
  });

  test('upload alone does not mark approved', () {
    final local = <String, dynamic>{
      'locally_modified': true,
      'locally_approved': false,
      'saved_payload': {
        'rows': [
          {'acquired': '3', 'notes': 'ن'},
        ],
      },
    };
    final merged = mergeServerCacheWithLocal(
      server: {'ok': true, 'is_approved': false},
      local: local,
      cacheStatus: SyncStatuses.synced,
    );
    expect(merged['status_label'], kEvalStatusWaiting);
    expect(merged['locally_approved'], isFalse);
  });

  test('19-28 unique progress current user/exercise', () {
    final procedure = [
      {'item_id': 11, 'title': 'أ', 'status_label': kEvalStatusApproved, 'status_done': true, 'list_type': 'judge_eval'},
      {'item_id': 11, 'title': 'أ مكرر', 'status_label': kEvalStatusApproved, 'status_done': true, 'list_type': 'judge_eval'},
      {'item_id': 12, 'title': 'ب', 'status_label': kEvalStatusWaiting, 'list_type': 'judge_eval'},
    ];
    final dilemma = [
      {'slot_id': 21, 'slot_index': 1, 'title': 'م1', 'status_label': kEvalStatusNotDone, 'list_type': 'planner_flow_action'},
      {'slot_index': 1, 'slot_id': 21, 'title': 'م1 نسخة', 'status_label': kEvalStatusNotDone, 'list_type': 'planner_flow_action'},
      {'slot_id': 22, 'title': 'م2', 'status_label': kEvalStatusApproved, 'status_done': true, 'list_type': 'planner_flow_action'},
    ];
    final snap = snapshotFromRows(procedureRows: procedure, dilemmaRows: dilemma);
    expect(snap.procedureCount, 2);
    expect(snap.dilemmaCount, 2);
    expect(snap.totalCount, 4);
    expect(snap.completedCount, 2);
    expect(snap.incompleteCount, 2);
    expect(snap.stats.totalCount, snap.completedCount + snap.incompleteCount);
    expect(
      snap.incomplete.map((e) => e.identity).toSet(),
      {'p:12', 'd:21'},
    );
  });

  test('same display name different ids counted once each', () {
    final snap = snapshotFromRows(
      procedureRows: [
        {'item_id': 1, 'title': 'قائمة الرماية', 'list_type': 'judge_eval'},
        {'item_id': 2, 'title': 'قائمة الرماية', 'list_type': 'judge_eval'},
      ],
      dilemmaRows: const [],
    );
    expect(snap.procedureCount, 2);
  });

  test('29-43 header home settings layout', () {
    final header = readFlutter('lib/widgets/app_header.dart');
    expect(header.contains('نظام التحكيم الذكي'), isTrue);
    expect(header.contains("join(' – ')"), isTrue);
    expect(header.contains('const SizedBox.shrink()'), isTrue);
    expect(header.contains("push('/library')"), isFalse);

    final home = readFlutter('lib/screens/home_screen.dart');
    expect(home.contains('kHomeFunctionsExact'), isTrue);
    expect(home.contains('home_settings_button'), isTrue);
    expect(home.contains('width: 80'), isTrue);
    expect(home.contains('height: 80'), isTrue);
    expect(home.contains('عرض جميع المهام'), isFalse);

    expect(kHomeFunctionsExact.map((e) => e.title).toList(), [
      'قوائم تقييم الإجراءات',
      'قوائم تقييم المعاضل',
      'مجرى الأحداث والمعاضل',
      'الإيجابيات والسلبيات',
      'المهام غير المكتملة',
      'الأهداف التدريبية',
      'كراسات الواجبات',
      'برنامج التمرين',
      'الخريطة',
      'المكتبة',
    ]);
    expect(kHomeFunctionsExact[7].route, '/exercise-details');
    expect(kHomeFunctionsExact[7].tab, 'program');
    expect(kHomeFunctionsExact[8].tab, 'map');
    expect(kHomeFunctionsExact[9].route, '/library');
    expect(kHomeFunctionsExact[4].route, '/incomplete');

    final settings = readFlutter('lib/screens/settings_screen.dart');
    expect(settings.contains("showLogout: false"), isTrue);
    expect(settings.contains("label: const Text('خروج')"), isFalse);
    expect(settings.contains('إعادة ضبط بيانات الجهاز'), isTrue);
    expect(settings.contains('Manage Local Storage'), isFalse);

    final hub = readFlutter('lib/screens/device_admin_hub_screen.dart');
    expect(hub.contains('Manage Local Storage'), isFalse);
    expect(hub.contains('DeviceResetService'), isTrue);
  });

  test('44-62 device reset local only preserves backups', () {
    final reset = readFlutter('lib/services/device_reset_service.dart');
    expect(reset.contains('beginRestoreHold'), isTrue);
    expect(reset.contains('clearAll()'), isTrue);
    expect(reset.contains('forgetLocalSession'), isTrue);
    expect(reset.contains('mediaRoot()'), isTrue);
    expect(reset.contains('delete(recursive: true)'), isTrue);
    expect(reset.contains("delete('/api/"), isFalse);
    expect(reset.contains('SmartArbitration_Backups'), isFalse);
    expect(reset.contains('getDownloadsDirectory'), isFalse);
    expect(kPublicBackupRootFolder, 'SmartArbitration_Backups');
    expect(OfflineStore.databaseSchemaVersion, 4);

    final settings = readFlutter('lib/screens/settings_screen.dart');
    expect(settings.contains('يوجد على الجهاز أعمال لم تتم مزامنتها مع السيرفر'), isTrue);
    expect(settings.contains('إلغاء'), isTrue);
    expect(settings.contains('إعادة ضبط الجهاز'), isTrue);
  });

  test('schema migration C.2.1 untouched', () {
    expect(OfflineStore.databaseSchemaVersion, 4);
    final reset = readFlutter('lib/services/device_reset_service.dart');
    expect(reset.contains('eval_backup_assembler'), isFalse);
    expect(reset.contains('CREATE TABLE'), isFalse);
  });
}
