// ignore_for_file: avoid_web_libraries_in_flutter, deprecated_member_use

import 'dart:html' as html;
import 'dart:indexed_db' as idb;

const _dbName = 'lf_tablet_kv';
const _storeName = 'kv';

idb.Database? _db;
Future<idb.Database>? _opening;

Future<void> pwaKvInit() async {
  await _open();
}

Future<idb.Database> _open() {
  if (_db != null) return Future.value(_db);
  return _opening ??= html.window.indexedDB!
      .open(
        _dbName,
        version: 1,
        onUpgradeNeeded: (e) {
          final db = (e.target as idb.OpenDBRequest).result;
          if (!db.objectStoreNames!.contains(_storeName)) {
            db.createObjectStore(_storeName);
          }
        },
      )
      .then((db) {
        _db = db;
        return db;
      });
}

Future<void> pwaKvPut(String key, String value) async {
  final db = await _open();
  final tx = db.transaction(_storeName, 'readwrite');
  tx.objectStore(_storeName).put(value, key);
  await tx.completed;
}

Future<String?> pwaKvGet(String key) async {
  final db = await _open();
  final tx = db.transaction(_storeName, 'readonly');
  final result = await tx.objectStore(_storeName).getObject(key);
  await tx.completed;
  if (result == null) return null;
  return result.toString();
}

Future<void> pwaKvRemove(String key) async {
  final db = await _open();
  final tx = db.transaction(_storeName, 'readwrite');
  tx.objectStore(_storeName).delete(key);
  await tx.completed;
}

Future<List<String>> pwaKvKeys({String prefix = ''}) async {
  final db = await _open();
  final tx = db.transaction(_storeName, 'readonly');
  final store = tx.objectStore(_storeName);
  final out = <String>[];
  final cursor = store.openCursor(autoAdvance: true);
  await for (final c in cursor) {
    final k = '${c.key}';
    if (prefix.isEmpty || k.startsWith(prefix)) out.add(k);
  }
  await tx.completed;
  return out;
}

Future<void> pwaKvClear() async {
  final db = await _open();
  final tx = db.transaction(_storeName, 'readwrite');
  tx.objectStore(_storeName).clear();
  await tx.completed;
}
