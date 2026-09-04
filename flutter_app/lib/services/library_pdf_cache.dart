import 'library_pdf_cache_stub.dart'
    if (dart.library.html) 'library_pdf_cache_web.dart'
    if (dart.library.io) 'library_pdf_cache_io.dart' as backend;

/// تخزين بايتات PDF المكتبة / أوراق التمرين على الجهاز للعرض دون شبكة.
class LibraryPdfCache {
  static Future<void> put(int nodeId, List<int> bytes) =>
      backend.putLibraryPdf(nodeId, bytes);

  static Future<List<int>?> get(int nodeId) => backend.getLibraryPdf(nodeId);

  static Future<bool> has(int nodeId) => backend.hasLibraryPdf(nodeId);

  static Future<void> pruneExcept(Set<int> keepIds) =>
      backend.pruneLibraryPdfsExcept(keepIds);

  static Future<void> clearAll() => backend.clearLibraryPdfs();

  static Future<void> putNamed(String name, List<int> bytes) =>
      backend.putNamedPdf(name, bytes);

  static Future<List<int>?> getNamed(String name) => backend.getNamedPdf(name);

  static Future<bool> hasNamed(String name) => backend.hasNamedPdf(name);
}
