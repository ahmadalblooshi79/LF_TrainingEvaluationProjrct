Future<void> putLibraryPdf(int nodeId, List<int> bytes) async {}

Future<List<int>?> getLibraryPdf(int nodeId) async => null;

Future<bool> hasLibraryPdf(int nodeId) async => false;

Future<void> pruneLibraryPdfsExcept(Set<int> keepIds) async {}

Future<void> clearLibraryPdfs() async {}
