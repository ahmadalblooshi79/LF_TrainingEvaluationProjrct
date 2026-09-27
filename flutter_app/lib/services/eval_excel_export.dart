import 'dart:convert';
import 'dart:io';

import 'package:archive/archive.dart';
import 'package:crypto/crypto.dart';
import 'package:flutter/foundation.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';

import 'auth_service.dart';
import 'local_recovery_parser.dart';
import 'local_recovery_service.dart';
import 'local_recovery_xlsx.dart';

const String kExcelExportFormatVersion = '1';
const String kSystemMetadataSheet = '_System_Metadata';

class EvalExcelExportResult {
  final bool ok;
  final String fileName;
  final String filePath;
  final int bytes;
  final bool isZip;
  final String? error;
  final List<String> warnings;
  final Uint8List? data;

  const EvalExcelExportResult({
    required this.ok,
    required this.fileName,
    required this.filePath,
    required this.bytes,
    required this.isZip,
    this.error,
    this.warnings = const [],
    this.data,
  });
}

class EvalExcelListDraft {
  final int evalItemId;
  final String listName;
  final String unitId;
  final String unitName;
  final String evaluationType;
  final String stageId;
  final String stageName;
  final String dilemmaName;
  final int? dilemmaId;
  final String clientOpId;
  final String savedAt;
  final String approvedAt;
  final bool approved;
  final String saveStatus;
  final List<RecoveredEvalRow> rows;
  final RecoveredPendingOp? pending;
  final ParsedCacheEvaluation? cache;
  final bool sourceMismatch;
  final List<RecoveredMediaItem> media;

  const EvalExcelListDraft({
    required this.evalItemId,
    required this.listName,
    required this.unitId,
    required this.unitName,
    required this.evaluationType,
    required this.stageId,
    required this.stageName,
    required this.dilemmaName,
    this.dilemmaId,
    required this.clientOpId,
    required this.savedAt,
    required this.approvedAt,
    required this.approved,
    required this.saveStatus,
    required this.rows,
    this.pending,
    this.cache,
    required this.sourceMismatch,
    required this.media,
  });
}

class EvalExcelExportService {
  EvalExcelExportService._();
  static final EvalExcelExportService instance = EvalExcelExportService._();

  Future<List<EvalExcelListDraft>> listSavedEvaluations() async {
    final scan = await LocalRecoveryService.instance.scan();
    return draftsFromScan(scan);
  }

  List<EvalExcelListDraft> draftsFromScan(LocalRecoveryScan scan) {
    final byId = <int, EvalExcelListDraft>{};
    for (final op in scan.saveResultsOps) {
      final id = op.evalItemId ?? 0;
      if (id <= 0) continue;
      final cache = scan.cacheEvaluations.where((c) => c.evalItemId == id).toList();
      final parsedCache = cache.isNotEmpty ? cache.first : null;
      final ident = scan.identities.where((i) => i.evalItemId == id).toList();
      final mismatch = ident.any((i) => i.sourceMismatch);
      final rows = op.parsed.rows;
      Map<String, dynamic> decoded = {};
      if (op.parsed.decoded is Map) {
        decoded = Map<String, dynamic>.from(op.parsed.decoded as Map);
      }
      final payload = decoded['payload'] is Map
          ? Map<String, dynamic>.from(decoded['payload'] as Map)
          : decoded;
      byId[id] = EvalExcelListDraft(
        evalItemId: id,
        listName: _titleFrom(payload, parsedCache, id),
        unitId: recoveryAsString(payload['unit_key'] ?? payload['unit_id']),
        unitName: recoveryAsString(
          payload['unit_label'] ?? payload['unit_name'] ?? scan.context.unit,
        ),
        evaluationType: op.path.contains('action-eval') || op.path.contains('action_eval')
            ? 'action_eval'
            : 'evaluation_list',
        stageId: recoveryAsString(payload['exercise_phase'] ?? payload['phase_key']),
        stageName: recoveryAsString(payload['phase_label'] ?? payload['exercise_phase']),
        dilemmaName: recoveryAsString(
          payload['dilemma_description'] ?? payload['eval_dilemma_description'],
        ),
        dilemmaId: recoveryAsInt(payload['dilemma_id']),
        clientOpId: op.parsed.clientOpId.isNotEmpty ? op.parsed.clientOpId : op.id,
        savedAt: op.createdAt,
        approvedAt: recoveryAsString(payload['approved_at']),
        approved: payload['is_approved'] == true ||
            recoveryAsString(payload['is_approved']).toLowerCase() == 'true',
        saveStatus: op.syncStatus,
        rows: rows,
        pending: op,
        cache: parsedCache,
        sourceMismatch: mismatch,
        media: scan.media
            .where(
              (m) =>
                  m.evaluationListItemId == id || m.bundleActionEvalId == id,
            )
            .toList(),
      );
    }
    for (final cache in scan.cacheEvaluations) {
      final id = cache.evalItemId ?? 0;
      if (id <= 0 || byId.containsKey(id)) continue;
      if (!cache.savedPayloadExists && cache.savedRows.isEmpty) continue;
      Map<String, dynamic> decoded = {};
      try {
        final raw = jsonDecode(cache.jsonBodyRaw);
        if (raw is Map) decoded = Map<String, dynamic>.from(raw);
      } catch (_) {}
      byId[id] = EvalExcelListDraft(
        evalItemId: id,
        listName: _titleFrom(decoded, cache, id),
        unitId: recoveryAsString(decoded['unit_key'] ?? decoded['unit_id']),
        unitName: recoveryAsString(
          decoded['unit_label'] ?? decoded['unit_name'] ?? scan.context.unit,
        ),
        evaluationType: cache.cacheKey.contains('action_eval')
            ? 'action_eval'
            : 'evaluation_list',
        stageId: recoveryAsString(decoded['phase_key'] ?? decoded['exercise_phase']),
        stageName: recoveryAsString(decoded['phase_label'] ?? decoded['exercise_phase']),
        dilemmaName: recoveryAsString(
          decoded['eval_dilemma_description'] ?? decoded['dilemma_description'],
        ),
        dilemmaId: recoveryAsInt(decoded['dilemma_id']),
        clientOpId: '',
        savedAt: cache.updatedAt,
        approvedAt: recoveryAsString(decoded['approval_signature_at']),
        approved: decoded['is_approved'] == true || decoded['locally_approved'] == true,
        saveStatus: cache.syncStatus,
        rows: cache.savedRows,
        cache: cache,
        sourceMismatch: false,
        media: scan.media
            .where(
              (m) =>
                  m.evaluationListItemId == id || m.bundleActionEvalId == id,
            )
            .toList(),
      );
    }
    final out = byId.values.toList()
      ..sort((a, b) => a.evalItemId.compareTo(b.evalItemId));
    return out;
  }

  String _titleFrom(Map<String, dynamic> payload, ParsedCacheEvaluation? cache, int id) {
    for (final k in ['title', 'eval_doc_title', 'list_name', 'evaluation_list_name']) {
      final v = recoveryAsString(payload[k]);
      if (v.isNotEmpty) return v;
    }
    if (cache != null) {
      try {
        final raw = jsonDecode(cache.jsonBodyRaw);
        if (raw is Map) {
          for (final k in ['title', 'eval_doc_title']) {
            final v = recoveryAsString(raw[k]);
            if (v.isNotEmpty) return v;
          }
        }
      } catch (_) {}
    }
    return 'Evaluation_$id';
  }

  Future<EvalExcelExportResult> exportLists(
    List<EvalExcelListDraft> lists, {
    LocalRecoveryScan? scan,
  }) async {
    scan ??= await LocalRecoveryService.instance.scan();
    if (lists.isEmpty) {
      return const EvalExcelExportResult(
        ok: false,
        fileName: '',
        filePath: '',
        bytes: 0,
        isZip: false,
        error: 'لا توجد قوائم محفوظة للتصدير',
      );
    }
    if (lists.length == 1) {
      return _exportOne(lists.first, scan);
    }
    return _exportMany(lists, scan);
  }

  Future<EvalExcelExportResult> exportEvalItem(int evalItemId) async {
    final scan = await LocalRecoveryService.instance.scan();
    final drafts = draftsFromScan(scan).where((d) => d.evalItemId == evalItemId).toList();
    if (drafts.isEmpty) {
      return EvalExcelExportResult(
        ok: false,
        fileName: '',
        filePath: '',
        bytes: 0,
        isZip: false,
        error: 'لا يوجد حفظ محلي للقائمة #$evalItemId',
      );
    }
    return _exportOne(drafts.first, scan);
  }

  Future<EvalExcelExportResult> _exportOne(
    EvalExcelListDraft draft,
    LocalRecoveryScan scan,
  ) async {
    final safe = _safeName(draft.listName.isEmpty ? 'Evaluation_${draft.evalItemId}' : draft.listName);
    final xlsx = _buildXlsx(draft, scan);
    final hasMedia = draft.media.any((m) => m.fileExists);
    if (!hasMedia) {
      return _persist('$safe.xlsx', xlsx, isZip: false);
    }
    final zip = _buildZip(draft, scan, xlsx, '$safe.xlsx');
    return _persist('Evaluation_$safe.zip', zip, isZip: true);
  }

  Future<EvalExcelExportResult> _exportMany(
    List<EvalExcelListDraft> lists,
    LocalRecoveryScan scan,
  ) async {
    final files = <String, List<int>>{};
    for (final draft in lists) {
      final safe = _safeName(
        draft.listName.isEmpty ? 'Evaluation_${draft.evalItemId}' : draft.listName,
      );
      final xlsx = _buildXlsx(draft, scan);
      if (draft.media.any((m) => m.fileExists)) {
        files['Evaluation_$safe.zip'] = _buildZip(draft, scan, xlsx, '$safe.xlsx');
      } else {
        files['$safe.xlsx'] = xlsx;
      }
    }
    final archive = Archive();
    files.forEach((name, bytes) {
      archive.addFile(ArchiveFile(name, bytes.length, bytes));
    });
    final encoded = ZipEncoder().encode(archive);
    if (encoded == null || encoded.isEmpty) {
      return const EvalExcelExportResult(
        ok: false,
        fileName: '',
        filePath: '',
        bytes: 0,
        isZip: true,
        error: 'تعذّر إنشاء الحزمة',
      );
    }
    return _persist(
      'Evaluations_export.zip',
      Uint8List.fromList(encoded),
      isZip: true,
    );
  }

  Uint8List _buildXlsx(EvalExcelListDraft draft, LocalRecoveryScan scan) {
    final ctx = scan.context;
    final session = AuthService.instance.session;
    final judgeName = ctx.judgeName.isNotEmpty
        ? ctx.judgeName
        : (session?.user.judgeDisplayName ?? '');
    final metaRows = <List<String>>[
      ['key', 'value'],
      ['export_format_version', kExcelExportFormatVersion],
      ['device_id', ctx.deviceId],
      ['exercise_id', '${ctx.exerciseId ?? ''}'],
      ['exercise_name', ''],
      ['judge_id', '${draft.pending?.judgeId ?? ctx.judgeId ?? ''}'],
      ['judge_name', judgeName],
      ['user_id', '${draft.pending?.userId ?? ctx.userId ?? ''}'],
      ['unit_id', draft.unitId],
      ['unit_name', draft.unitName],
      ['evaluation_list_id', draft.pending?.listId ?? ''],
      ['evaluation_list_name', draft.listName],
      ['eval_item_id', '${draft.evalItemId}'],
      ['evaluation_type', draft.evaluationType],
      ['stage_id', draft.stageId],
      ['stage_name', draft.stageName],
      ['dilemma_id', '${draft.dilemmaId ?? ''}'],
      ['dilemma_name', draft.dilemmaName],
      ['client_op_id', draft.clientOpId],
      ['saved_at', draft.savedAt],
      ['approved_at', draft.approvedAt],
      ['app_version', ctx.appVersion],
      ['package_version', ctx.appVersion],
      ['save_status', draft.saveStatus],
      ['approval_status', draft.approved ? 'approved' : 'not_approved'],
      ['source_mismatch', draft.sourceMismatch ? 'YES' : 'NO'],
    ];
    final listRows = <List<String>>[
      ['قائمة التقييم', draft.listName],
      ['الوحدة', draft.unitName],
      ['المحكم', judgeName],
      ['حالة الحفظ', draft.saveStatus],
      ['حالة الاعتماد', draft.approved ? 'معتمدة' : 'غير معتمدة'],
      ['تاريخ الاعتماد', draft.approvedAt],
      if (draft.sourceMismatch)
        ['تنبيه', 'SOURCE MISMATCH — نُسختا pending و cache محفوظتان'],
      [],
      ['م', 'نوع الصف', 'عناصر التقييم', 'القصوى', 'المكتسبة', 'الملاحظات'],
    ];
    var i = 1;
    for (final row in draft.rows) {
      listRows.add([
        '$i',
        row.rowKind,
        row.element,
        row.maxVal,
        row.acquired,
        row.notes,
      ]);
      i++;
    }
    final sheetName = _sheetName(draft.listName);
    return buildSimpleXlsx(
      {
        sheetName: listRows,
        kSystemMetadataSheet: metaRows,
      },
      hiddenSheetNames: {kSystemMetadataSheet},
    );
  }

  List<int> _buildZip(
    EvalExcelListDraft draft,
    LocalRecoveryScan scan,
    Uint8List xlsx,
    String xlsxName,
  ) {
    final files = <String, List<int>>{xlsxName: xlsx};
    final mediaManifest = <Map<String, dynamic>>[];
    for (final m in draft.media) {
      if (!m.fileExists || m.localPath.isEmpty || kIsWeb) continue;
      try {
        final f = File(m.localPath);
        if (!f.existsSync()) continue;
        final bytes = f.readAsBytesSync();
        final folder = m.isVideo
            ? 'media/videos'
            : (m.isImage ? 'media/images' : 'media/files');
        final name = p.basename(m.localPath);
        final rel = '$folder/$name';
        files[rel] = bytes;
        mediaManifest.add({
          ...m.toJson(),
          'exported_path': rel,
          'eval_item_id': draft.evalItemId,
          'sha256': sha256.convert(bytes).toString(),
        });
      } catch (_) {}
    }
    final manifest = {
      'export_format_version': kExcelExportFormatVersion,
      'eval_item_id': draft.evalItemId,
      'evaluation_list_name': draft.listName,
      'device_id': scan.context.deviceId,
      'client_op_id': draft.clientOpId,
      'source_mismatch': draft.sourceMismatch,
      'pending_preserved': draft.pending != null,
      'cache_preserved': draft.cache != null,
      'media': mediaManifest,
    };
    files['manifest.json'] =
        utf8.encode(const JsonEncoder.withIndent('  ').convert(manifest));
    final archive = Archive();
    files.forEach((name, bytes) {
      archive.addFile(ArchiveFile(name, bytes.length, bytes));
    });
    return ZipEncoder().encode(archive) ?? <int>[];
  }

  Future<EvalExcelExportResult> _persist(
    String name,
    List<int> bytes, {
    required bool isZip,
  }) async {
    if (bytes.isEmpty) {
      return EvalExcelExportResult(
        ok: false,
        fileName: name,
        filePath: '',
        bytes: 0,
        isZip: isZip,
        error: 'الملف فارغ',
      );
    }
    final data = bytes is Uint8List ? bytes : Uint8List.fromList(bytes);
    var savedPath = '';
    if (!kIsWeb) {
      try {
        final docs = await getApplicationDocumentsDirectory();
        final dir = Directory(p.join(docs.path, 'excel_exports'));
        if (!await dir.exists()) {
          await dir.create(recursive: true);
        }
        final out = File(p.join(dir.path, name));
        await out.writeAsBytes(data, flush: true);
        savedPath = out.path;
      } catch (e) {
        return EvalExcelExportResult(
          ok: false,
          fileName: name,
          filePath: '',
          bytes: data.length,
          isZip: isZip,
          error: '$e',
          data: data,
        );
      }
    }
    return EvalExcelExportResult(
      ok: true,
      fileName: name,
      filePath: savedPath,
      bytes: data.length,
      isZip: isZip,
      data: data,
    );
  }

  Future<Map<String, String>?> saveToUserLocation(EvalExcelExportResult result) {
    return LocalRecoveryService.instance.copyExportToUserLocation(
      RecoveryExportResult(
        ok: result.ok,
        zipName: result.fileName,
        zipPath: result.filePath,
        zipBytes: result.bytes,
        zipBytesData: result.data,
      ),
    );
  }

  String _safeName(String s) {
    final t = s.replaceAll(RegExp(r'[\\/:*?"<>|]'), '_').trim();
    if (t.isEmpty) return 'evaluation';
    return t.length > 40 ? t.substring(0, 40) : t;
  }

  String _sheetName(String s) {
    var t = _safeName(s).replaceAll("'", '');
    if (t.length > 31) t = t.substring(0, 31);
    if (t == kSystemMetadataSheet) t = 'Evaluation';
    return t.isEmpty ? 'Evaluation' : t;
  }
}
