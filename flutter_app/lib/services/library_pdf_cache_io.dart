import 'dart:io';

import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';

Future<Directory> _dir() async {
  final root = await getApplicationDocumentsDirectory();
  final d = Directory(p.join(root.path, 'library_pdfs'));
  if (!await d.exists()) {
    await d.create(recursive: true);
  }
  return d;
}

Future<File> _file(int nodeId) async {
  final d = await _dir();
  return File(p.join(d.path, '$nodeId.pdf'));
}

Future<void> putLibraryPdf(int nodeId, List<int> bytes) async {
  if (nodeId <= 0 || bytes.isEmpty) return;
  final f = await _file(nodeId);
  await f.writeAsBytes(bytes, flush: true);
}

Future<List<int>?> getLibraryPdf(int nodeId) async {
  if (nodeId <= 0) return null;
  final f = await _file(nodeId);
  if (!await f.exists()) return null;
  final b = await f.readAsBytes();
  return b.isEmpty ? null : b;
}

Future<bool> hasLibraryPdf(int nodeId) async {
  if (nodeId <= 0) return false;
  return (await _file(nodeId)).exists();
}

Future<void> pruneLibraryPdfsExcept(Set<int> keepIds) async {
  final d = await _dir();
  await for (final ent in d.list()) {
    if (ent is! File) continue;
    final id = int.tryParse(p.basenameWithoutExtension(ent.path));
    if (id == null || !keepIds.contains(id)) {
      try {
        await ent.delete();
      } catch (_) {}
    }
  }
}

Future<void> clearLibraryPdfs() async {
  final d = await _dir();
  if (await d.exists()) {
    try {
      await d.delete(recursive: true);
    } catch (_) {}
  }
  final named = await _namedDir();
  if (await named.exists()) {
    try {
      await named.delete(recursive: true);
    } catch (_) {}
  }
}

String _safeNamedKey(String name) {
  final s = name.trim();
  if (s.isEmpty) return '';
  return s.replaceAll(RegExp(r'[^a-zA-Z0-9_-]'), '_');
}

Future<Directory> _namedDir() async {
  final root = await getApplicationDocumentsDirectory();
  final d = Directory(p.join(root.path, 'flow_day_pdfs'));
  if (!await d.exists()) {
    await d.create(recursive: true);
  }
  return d;
}

Future<File?> _namedFile(String name) async {
  final key = _safeNamedKey(name);
  if (key.isEmpty) return null;
  final d = await _namedDir();
  return File(p.join(d.path, '$key.pdf'));
}

Future<void> putNamedPdf(String name, List<int> bytes) async {
  if (bytes.isEmpty) return;
  final f = await _namedFile(name);
  if (f == null) return;
  await f.writeAsBytes(bytes, flush: true);
}

Future<List<int>?> getNamedPdf(String name) async {
  final f = await _namedFile(name);
  if (f == null || !await f.exists()) return null;
  final b = await f.readAsBytes();
  return b.isEmpty ? null : b;
}

Future<bool> hasNamedPdf(String name) async {
  final f = await _namedFile(name);
  if (f == null) return false;
  return f.exists();
}
