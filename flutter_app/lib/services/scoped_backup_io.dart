import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:path/path.dart' as p;

import 'scoped_backup_inventory.dart';
import 'scoped_backup_models.dart';

typedef BackupCancelCheck = bool Function();
typedef BackupByteProgress = void Function(int delta);

/// Test/debug: largest buffer observed by streaming hash/copy in this isolate.
int scopedBackupMaxObservedChunk = 0;

void _noteChunk(int n) {
  if (n > scopedBackupMaxObservedChunk) scopedBackupMaxObservedChunk = n;
}

class ScopedBackupIoException implements Exception {
  final String message;
  const ScopedBackupIoException(this.message);
  @override
  String toString() => message;
}

class StreamHashResult {
  final int bytes;
  final String sha256;
  const StreamHashResult({required this.bytes, required this.sha256});
}

class _DigestSink implements Sink<Digest> {
  Digest? value;
  @override
  void add(Digest data) => value = data;
  @override
  void close() {}
}

ByteConversionSink startSha256Sink(_DigestSink out) {
  return sha256.startChunkedConversion(out);
}

/// Stream-hash a file. Memory is bounded by [chunkSize], not file size.
Future<StreamHashResult> streamHashFile(
  File file, {
  int chunkSize = kScopedBackupChunkSize,
  BackupCancelCheck? isCancelled,
  BackupByteProgress? onBytes,
}) async {
  if (!file.existsSync()) {
    throw const ScopedBackupIoException('source_missing');
  }
  final out = _DigestSink();
  final sink = startSha256Sink(out);
  var total = 0;
  final raf = await file.open();
  try {
    while (true) {
      if (isCancelled?.call() == true) {
        throw const ScopedBackupIoException('cancelled');
      }
      final chunk = await raf.read(chunkSize);
      if (chunk.isEmpty) break;
      sink.add(chunk);
      total += chunk.length;
      _noteChunk(chunk.length);
      onBytes?.call(chunk.length);
    }
  } finally {
    await raf.close();
  }
  sink.close();
  return StreamHashResult(bytes: total, sha256: '${out.value}');
}

/// Stream-copy [source] to [dest]. Never loads the whole file.
/// Re-hashes destination bytes while writing. Fails if size/hash diverge.
Future<StreamHashResult> streamCopyFile({
  required File source,
  required File dest,
  required int expectedSize,
  String? expectedSha256,
  int chunkSize = kScopedBackupChunkSize,
  BackupCancelCheck? isCancelled,
  BackupByteProgress? onBytes,
}) async {
  if (!source.existsSync()) {
    throw const ScopedBackupIoException('source_missing');
  }
  final liveSize = await source.length();
  if (liveSize != expectedSize) {
    throw const ScopedBackupIoException('source_changed_size');
  }
  await dest.parent.create(recursive: true);
  if (dest.existsSync()) {
    await dest.delete();
  }
  final digestOut = _DigestSink();
  final hasher = startSha256Sink(digestOut);
  var total = 0;
  final reader = source.openRead();
  final writer = dest.openWrite();
  try {
    await for (final chunk in reader) {
      if (isCancelled?.call() == true) {
        throw const ScopedBackupIoException('cancelled');
      }
      if (chunk.length > chunkSize * 4) {
        var offset = 0;
        while (offset < chunk.length) {
          final end = (offset + chunkSize < chunk.length)
              ? offset + chunkSize
              : chunk.length;
          final part = chunk.sublist(offset, end);
          hasher.add(part);
          writer.add(part);
          total += part.length;
          _noteChunk(part.length);
          onBytes?.call(part.length);
          offset = end;
        }
      } else {
        hasher.add(chunk);
        writer.add(chunk);
        total += chunk.length;
        _noteChunk(chunk.length);
        onBytes?.call(chunk.length);
      }
    }
    await writer.flush();
  } catch (e) {
    await writer.close();
    if (dest.existsSync()) {
      try {
        await dest.delete();
      } catch (_) {}
    }
    rethrow;
  }
  await writer.close();
  hasher.close();
  final hash = '${digestOut.value}';
  if (total != expectedSize ||
      (expectedSha256 != null &&
          expectedSha256.isNotEmpty &&
          hash != expectedSha256)) {
    if (dest.existsSync()) {
      try {
        await dest.delete();
      } catch (_) {}
    }
    if (total != expectedSize) {
      throw const ScopedBackupIoException('copy_size_mismatch');
    }
    throw const ScopedBackupIoException('copy_hash_mismatch');
  }
  return StreamHashResult(bytes: total, sha256: hash);
}

Future<void> writeUtf8File(File dest, String text) async {
  await dest.parent.create(recursive: true);
  await dest.writeAsString(text, encoding: utf8, flush: true);
}

Future<void> writeBytesChunked(
  File dest,
  List<int> bytes, {
  int chunkSize = kScopedBackupChunkSize,
}) async {
  await dest.parent.create(recursive: true);
  final raf = await dest.open(mode: FileMode.write);
  try {
    var offset = 0;
    while (offset < bytes.length) {
      final end = offset + chunkSize < bytes.length
          ? offset + chunkSize
          : bytes.length;
      await raf.writeFrom(bytes.sublist(offset, end));
      offset = end;
    }
    await raf.flush();
  } finally {
    await raf.close();
  }
}

Future<void> deleteDirIfExists(Directory dir) async {
  if (await dir.exists()) {
    await dir.delete(recursive: true);
  }
}

Future<void> renameDirCommitted(Directory from, Directory to) async {
  await deleteDirIfExists(to);
  await from.rename(to.path);
}

String fingerprintPayload(List<Map<String, dynamic>> rows, List<String> keys) {
  final parts = <String>[];
  for (final row in rows) {
    final slice = <String, dynamic>{};
    for (final k in keys) {
      slice[k] = row[k];
    }
    parts.add(jsonEncode(slice));
  }
  parts.sort();
  return sha256.convert(utf8.encode(parts.join('\n'))).toString();
}

Future<Map<String, String>> hashExistingMediaFiles(
  List<Map<String, dynamic>> mediaRows, {
  int chunkSize = kScopedBackupChunkSize,
}) async {
  final out = <String, String>{};
  for (final row in mediaRows) {
    final path = '${row['local_path'] ?? ''}';
    if (path.isEmpty) continue;
    final f = File(path);
    if (!f.existsSync()) {
      out[path] = 'MISSING';
      continue;
    }
    final r = await streamHashFile(f, chunkSize: chunkSize);
    out[path] = '${r.bytes}:${r.sha256}';
  }
  return out;
}

class BackupValidationIssue {
  final String code;
  final String detail;
  const BackupValidationIssue(this.code, [this.detail = '']);
}

List<BackupValidationIssue> validateBackupPackageSync(Directory packageDir) {
  final issues = <BackupValidationIssue>[];
  final manifestFile = File(p.join(packageDir.path, kScopedBackupManifestName));
  final completeFile = File(p.join(packageDir.path, kScopedBackupCompleteName));
  if (!manifestFile.existsSync()) {
    issues.add(const BackupValidationIssue('manifest_missing'));
    return issues;
  }
  if (!completeFile.existsSync()) {
    issues.add(const BackupValidationIssue('completion_marker_missing'));
  }
  Map<String, dynamic> json;
  try {
    json = jsonDecode(manifestFile.readAsStringSync()) as Map<String, dynamic>;
  } catch (_) {
    issues.add(const BackupValidationIssue('manifest_corrupt'));
    return issues;
  }
  ScopedBackupManifest manifest;
  try {
    manifest = ScopedBackupManifest.fromJson(json);
  } catch (_) {
    issues.add(const BackupValidationIssue('manifest_corrupt'));
    return issues;
  }
  if (manifest.backupFormatVersion != kScopedBackupFormatVersion) {
    issues.add(BackupValidationIssue(
      'unsupported_format',
      '${manifest.backupFormatVersion}',
    ));
  }
  if (manifest.schemaVersion != kScopedBackupSupportedSchema) {
    issues.add(BackupValidationIssue(
      'unsupported_schema',
      '${manifest.schemaVersion}',
    ));
  }
  if (manifest.exercise.exerciseId <= 0 || manifest.user.userId <= 0) {
    issues.add(const BackupValidationIssue('required_metadata_missing'));
  }
  if (manifest.completionStatus != 'complete' &&
      manifest.completionStatus != 'verified') {
    issues.add(BackupValidationIssue(
      'completion_status_invalid',
      manifest.completionStatus,
    ));
  }
  final seen = <String>{};
  for (final entry in manifest.fileInventory) {
    if (!isSafeRelativeBackupPath(entry.relativePath)) {
      issues.add(BackupValidationIssue('unsafe_path', entry.relativePath));
      continue;
    }
    if (!seen.add(entry.relativePath)) {
      issues.add(BackupValidationIssue('duplicate_entry', entry.relativePath));
    }
    if (p.isAbsolute(entry.relativePath)) {
      issues.add(BackupValidationIssue('absolute_restore_path', entry.relativePath));
    }
    final f = File(p.join(packageDir.path, entry.relativePath));
    if (!f.existsSync()) {
      issues.add(BackupValidationIssue('missing_file', entry.relativePath));
      continue;
    }
    final size = f.lengthSync();
    if (size != entry.size) {
      issues.add(BackupValidationIssue('size_mismatch', entry.relativePath));
    }
  }
  return issues;
}

/// Independent validation that re-reads files and verifies SHA-256.
Future<List<BackupValidationIssue>> validateBackupPackage(
  Directory packageDir, {
  int chunkSize = kScopedBackupChunkSize,
  BackupCancelCheck? isCancelled,
  BackupByteProgress? onBytes,
}) async {
  final issues = validateBackupPackageSync(packageDir);
  if (issues.any((e) =>
      e.code == 'manifest_missing' || e.code == 'manifest_corrupt')) {
    return issues;
  }
  final manifestFile = File(p.join(packageDir.path, kScopedBackupManifestName));
  final json =
      jsonDecode(await manifestFile.readAsString()) as Map<String, dynamic>;
  final manifest = ScopedBackupManifest.fromJson(json);
  for (final entry in manifest.fileInventory) {
    if (!isSafeRelativeBackupPath(entry.relativePath)) continue;
    final f = File(p.join(packageDir.path, entry.relativePath));
    if (!f.existsSync()) continue;
    try {
      final hashed = await streamHashFile(
        f,
        chunkSize: chunkSize,
        isCancelled: isCancelled,
        onBytes: onBytes,
      );
      if (hashed.bytes != entry.size) {
        issues.add(BackupValidationIssue('size_mismatch', entry.relativePath));
      }
      if (hashed.sha256 != entry.sha256) {
        issues.add(BackupValidationIssue('hash_mismatch', entry.relativePath));
      }
    } on ScopedBackupIoException catch (e) {
      issues.add(BackupValidationIssue('hash_failed', e.message));
    }
  }
  return issues;
}

Future<void> copyDirectoryStreaming({
  required Directory source,
  required Directory dest,
  int chunkSize = kScopedBackupChunkSize,
  BackupCancelCheck? isCancelled,
  BackupByteProgress? onBytes,
}) async {
  await dest.create(recursive: true);
  await for (final entity in source.list(recursive: true, followLinks: false)) {
    if (entity is! File) continue;
    final rel = p.relative(entity.path, from: source.path).replaceAll('\\', '/');
    if (!isSafeRelativeBackupPath(rel)) {
      throw ScopedBackupIoException('unsafe_path:$rel');
    }
    final target = File(p.join(dest.path, rel));
    await streamCopyFile(
      source: entity,
      dest: target,
      expectedSize: await entity.length(),
      chunkSize: chunkSize,
      isCancelled: isCancelled,
      onBytes: onBytes,
    );
  }
}
