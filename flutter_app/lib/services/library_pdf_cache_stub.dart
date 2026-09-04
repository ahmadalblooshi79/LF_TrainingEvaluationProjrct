Future<void> putLibraryPdf(int nodeId, List<int> bytes) async {}

Future<List<int>?> getLibraryPdf(int nodeId) async => null;

Future<bool> hasLibraryPdf(int nodeId) async => false;

Future<void> pruneLibraryPdfsExcept(Set<int> keepIds) async {}

Future<void> clearLibraryPdfs() async {}

Future<void> putNamedPdf(String name, List<int> bytes) async {}

Future<List<int>?> getNamedPdf(String name) async => null;

Future<bool> hasNamedPdf(String name) async => false;
