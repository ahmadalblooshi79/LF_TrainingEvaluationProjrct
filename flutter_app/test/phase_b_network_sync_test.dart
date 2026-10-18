import 'package:flutter_test/flutter_test.dart';
import 'package:lf_training_evaluation/services/auth_service.dart';
import 'package:lf_training_evaluation/services/eval_cache_merge.dart';
import 'package:lf_training_evaluation/services/offline_store.dart';
import 'package:lf_training_evaluation/services/package_sync_service.dart';
import 'package:lf_training_evaluation/services/sync_service.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() async {
    SharedPreferences.setMockInitialValues({
      kCredentialSaltPrefKey: 'unit-test-salt',
    });
  });

  test('SQLite schema remains 4', () {
    expect(OfflineStore.databaseSchemaVersion, 4);
  });

  test('Device Sync concurrency is bounded', () {
    expect(kDeviceSyncConcurrency, 4);
    expect(kDeviceSyncConcurrency, lessThanOrEqualTo(8));
  });

  test('health without auth is not connected', () {
    expect(
      resolveSyncUiState(
        syncing: false,
        healthReachable: true,
        authenticated: false,
        connecting: false,
        pending: 0,
        hasLastError: false,
        hasLastSuccess: false,
      ),
      SyncUiState.offline,
    );
  });

  test('ethernet/health connecting is connecting not connected', () {
    expect(
      resolveSyncUiState(
        syncing: false,
        healthReachable: true,
        authenticated: false,
        connecting: true,
        pending: 0,
        hasLastError: false,
        hasLastSuccess: false,
      ),
      SyncUiState.connecting,
    );
  });

  test('connected requires health AND authenticated session', () {
    expect(
      resolveSyncUiState(
        syncing: false,
        healthReachable: true,
        authenticated: true,
        connecting: false,
        pending: 0,
        hasLastError: false,
        hasLastSuccess: false,
      ),
      SyncUiState.online,
    );
    expect(
      resolveSyncUiState(
        syncing: false,
        healthReachable: false,
        authenticated: true,
        connecting: false,
        pending: 0,
        hasLastError: false,
        hasLastSuccess: false,
      ),
      SyncUiState.offline,
    );
  });

  test('connectivity event is not server-connected', () {
    expect(
      resolveSyncUiState(
        syncing: false,
        healthReachable: false,
        authenticated: false,
        connecting: false,
        pending: 0,
        hasLastError: false,
        hasLastSuccess: false,
      ),
      isNot(SyncUiState.online),
    );
  });

  test('PendingOp from 2.7.32 row remains parseable including unknown opType', () {
    final op = PendingOp.fromRow({
      'id': 'op-old-1',
      'method': 'PUT',
      'path': '/api/tablet/evaluation-lists/u/1/results',
      'body': '{"client_op_id":"op-old-1"}',
      'kind': 'eval',
      'op_type': 'save_results',
      'created_at': '2026-01-01T00:00:00.000',
      'attempts': 0,
      'sync_status': 'pending',
      'user_id': 12,
      'exercise_id': 3,
      'list_id': '1',
      'eval_item_id': 1,
    });
    expect(op.id, 'op-old-1');
    expect(op.opType, 'save_results');
    expect(op.path, contains('/api/tablet/'));
    expect(op.userId, 12);

    final unknown = PendingOp.fromRow({
      'id': 'op-x',
      'method': 'POST',
      'path': '/api/tablet/legacy',
      'body': '{}',
      'kind': '',
      'created_at': '2026-01-01T00:00:00.000',
    });
    expect(unknown.opType, 'unknown');
    expect(unknown.id, 'op-x');
  });

  test('old media_files row is readable without new required fields', () {
    final rec = LocalMediaRecord.fromRow({
      'id': 'media-old',
      'local_path': '/data/user/0/ae.lf.training.lf_training_evaluation/app_flutter/media/pending/videos/media-old.mp4',
      'row_index': 2,
      'media_kind': 'video',
      'sync_status': 'pending',
      'server_confirmed': 0,
      'created_at': '2026-01-01T00:00:00.000',
      'upload_session_id': 'sess-1',
      'uploaded_bytes': 10485760,
      'file_size': 40000000,
    });
    expect(rec.id, 'media-old');
    expect(rec.localPath, contains('media/pending/videos'));
    expect(rec.uploadSessionId, 'sess-1');
    expect(rec.fileSize, 40000000);
  });

  test('mergeServerCacheWithLocal keeps locally_modified work', () {
    final merged = mergeServerCacheWithLocal(
      server: {
        'saved_payload': {'server': true},
        'workflow': {'reopened': false},
      },
      local: {
        'locally_modified': true,
        'saved_payload': {'score': 7, 'note': 'محلي'},
        'saved_rows': [
          {'acquired': '7'},
        ],
      },
      cacheStatus: SyncStatuses.pending,
    );
    expect(merged['locally_modified'], isTrue);
    expect(merged['saved_payload']['score'], 7);
    expect(merged['saved_payload']['note'], 'محلي');
  });

  test('matchingProvisionPassword returns seed only when hash matches', () async {
    final hash = await credentialDigest('j100', 'j100');
    final match = await matchingProvisionPassword(
      storedHash: hash,
      username: 'j100',
      militaryNumber: 'j100',
    );
    expect(match, 'j100');
    final no = await matchingProvisionPassword(
      storedHash: 'not-a-real-hash',
      username: 'j100',
      militaryNumber: 'j100',
    );
    expect(no, isNull);
  });

  test('reconnect ticket pref key is user scoped', () {
    expect(reconnectTicketPrefKey(12), 'reconnect_ticket_u12');
  });

  test('startup prepareLocalAuth does not enable server session', () {
    expect(AuthService.instance.isLoggedIn, isFalse);
    expect(AuthService.instance.serverSessionUsable.value, isFalse);
  });
}
