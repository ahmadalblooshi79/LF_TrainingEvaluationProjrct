// ignore_for_file: avoid_web_libraries_in_flutter, deprecated_member_use

import 'dart:html' as html;
import 'dart:indexed_db' as idb;
import 'dart:typed_data';

const _dbName = 'lf_library_pdfs';
const _storeName = 'pdfs';

Future<idb.Database> _openDb() {
  return html.window.indexedDB!.open(
    _dbName,
    version: 1,
    onUpgradeNeeded: (e) {
      final db = (e.target as idb.OpenDBRequest).result;
      if (!db.objectStoreNames!.contains(_storeName)) {
        db.createObjectStore(_storeName);
      }
    },
  );
}

Future<void> putLibraryPdf(int nodeId, List<int> bytes) async {
  if (nodeId <= 0 || bytes.isEmpty) return;
  final db = await _openDb();
  final tx = db.transaction(_storeName, 'readwrite');
  final store = tx.objectStore(_storeName);
  store.put(html.Blob([Uint8List.fromList(bytes)], 'application/pdf'), nodeId);
  await tx.completed;
}

Future<List<int>?> getLibraryPdf(int nodeId) async {
  if (nodeId <= 0) return null;
  final db = await _openDb();
  final tx = db.transaction(_storeName, 'readonly');
  final result = await tx.objectStore(_storeName).getObject(nodeId);
  await tx.completed;
  if (result == null) return null;
  if (result is Uint8List) return result.isEmpty ? null : result;
  if (result is ByteBuffer) {
    final u = result.asUint8List();
    return u.isEmpty ? null : u;
  }
  if (result is html.Blob) {
    final reader = html.FileReader();
    reader.readAsArrayBuffer(result);
    await reader.onLoad.first;
    final buf = reader.result;
    if (buf is ByteBuffer) {
      final u = buf.asUint8List();
      return u.isEmpty ? null : u;
    }
    if (buf is Uint8List) return buf.isEmpty ? null : buf;
  }
  if (result is List) {
    final u = List<int>.from(result);
    return u.isEmpty ? null : u;
  }
  return null;
}

Future<bool> hasLibraryPdf(int nodeId) async {
  if (nodeId <= 0) return false;
  final db = await _openDb();
  final tx = db.transaction(_storeName, 'readonly');
  final result = await tx.objectStore(_storeName).getObject(nodeId);
  await tx.completed;
  return result != null;
}

Future<void> pruneLibraryPdfsExcept(Set<int> keepIds) async {
  final db = await _openDb();
  final tx = db.transaction(_storeName, 'readwrite');
  final store = tx.objectStore(_storeName);
  final cursor = store.openCursor(autoAdvance: true);
  await for (final c in cursor) {
    final key = c.key;
    final id = key is int ? key : int.tryParse('$key');
    if (id == null || !keepIds.contains(id)) {
      c.delete();
    }
  }
  await tx.completed;
}

Future<void> clearLibraryPdfs() async {
  final db = await _openDb();
  final tx = db.transaction(_storeName, 'readwrite');
  tx.objectStore(_storeName).clear();
  await tx.completed;
}
