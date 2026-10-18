import 'dart:io';

import 'package:archive/archive_io.dart';
import 'package:path/path.dart' as p;

/// Zip [source] into [destZip] using file streams. Does not load whole files.
Future<File> zipExportDirectory({
  required Directory source,
  required File destZip,
}) async {
  if (!source.existsSync()) {
    throw const FileSystemException('source_missing');
  }
  if (p.isWithin(source.path, destZip.path)) {
    throw const FileSystemException('zip_inside_source');
  }
  await destZip.parent.create(recursive: true);
  if (destZip.existsSync()) {
    await destZip.delete();
  }
  final encoder = ZipFileEncoder();
  encoder.zipDirectory(
    source,
    filename: destZip.path,
    level: ZipFileEncoder.STORE,
  );
  if (!destZip.existsSync() || destZip.lengthSync() <= 0) {
    throw const FileSystemException('zip_failed');
  }
  return destZip;
}
