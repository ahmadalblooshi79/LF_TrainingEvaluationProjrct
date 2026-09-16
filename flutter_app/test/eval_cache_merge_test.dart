import 'package:flutter_test/flutter_test.dart';
import 'package:lf_training_evaluation/services/eval_cache_merge.dart';
import 'package:lf_training_evaluation/services/offline_store.dart';

void main() {
  test('unsynced local scores survive empty server download', () {
    final local = <String, dynamic>{
      'locally_modified': true,
      'saved_rows': [
        {'row_kind': 'score', 'acquired': '4', 'notes': 'ملاحظة أ'},
      ],
      'saved_payload': {
        'rows': [
          {'row_kind': 'score', 'acquired': '4', 'notes': 'ملاحظة أ'},
        ],
      },
      'local_media': [
        {'local_path': '/tmp/a.jpg', 'row_index': 0},
      ],
    };
    final server = <String, dynamic>{
      'eval_rows': [
        {'row_kind': 'score', 'acquired_initial': '', 'notes_initial': ''},
      ],
      'saved_rows': <dynamic>[],
      'title': 'قائمة من السيرفر',
    };

    final merged = mergeServerCacheWithLocal(
      server: server,
      local: local,
      cacheStatus: SyncStatuses.pending,
    );

    expect(merged['locally_modified'], isTrue);
    expect(merged['title'], 'قائمة من السيرفر');
    expect((merged['saved_rows'] as List).first['acquired'], '4');
    expect((merged['saved_payload'] as Map)['rows'].first['notes'], 'ملاحظة أ');
    expect((merged['local_media'] as List).first['local_path'], '/tmp/a.jpg');
    expect(
      mergeResultSyncStatus(
        local: local,
        server: server,
        cacheStatus: SyncStatuses.pending,
      ),
      SyncStatuses.pending,
    );
  });

  test('unmodified local cache can take server reference', () {
    final local = <String, dynamic>{'title': 'قديم'};
    final server = <String, dynamic>{'title': 'جديد', 'eval_rows': <dynamic>[]};
    final merged = mergeServerCacheWithLocal(
      server: server,
      local: local,
      cacheStatus: SyncStatuses.synced,
    );
    expect(merged['title'], 'جديد');
  });
}
