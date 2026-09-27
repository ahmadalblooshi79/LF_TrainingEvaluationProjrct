import 'package:flutter/material.dart';

import '../services/local_recovery_parser.dart';
import '../services/local_recovery_service.dart';
import '../theme/app_theme.dart';
import '../widgets/app_header.dart';

/// Read-only local recovery. Does not sync, upload, or mutate tablet_offline.db.
class LocalRecoveryScreen extends StatefulWidget {
  const LocalRecoveryScreen({super.key});

  @override
  State<LocalRecoveryScreen> createState() => _LocalRecoveryScreenState();
}

class _LocalRecoveryScreenState extends State<LocalRecoveryScreen> {
  bool _busy = false;
  String? _error;
  LocalRecoveryScan? _scan;
  RecoveryExportResult? _export;
  String? _savedDestination;
  String? _savedName;
  final _evalFilter = TextEditingController();

  @override
  void dispose() {
    _evalFilter.dispose();
    super.dispose();
  }

  Future<void> _runScan() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final scan = await LocalRecoveryService.instance.scan();
      if (!mounted) return;
      setState(() {
        _scan = scan;
        _export = null;
        _savedDestination = null;
        _savedName = null;
        _busy = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = '$e';
      });
    }
  }

  Future<void> _exportPackage() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      var scan = _scan;
      scan ??= await LocalRecoveryService.instance.scan();
      final result = await LocalRecoveryService.instance.exportScan(scan);
      if (!mounted) return;
      setState(() {
        _scan = scan;
        _export = result;
        _savedDestination = null;
        _savedName = null;
        _busy = false;
        if (!result.ok) _error = 'فشل إنشاء الحزمة';
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = '$e';
      });
    }
  }

  Future<void> _share() async {
    final exp = _export;
    if (exp == null || !exp.ok) return;
    try {
      await LocalRecoveryService.instance.shareExport(exp);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('تعذّرت المشاركة: $e')),
      );
    }
  }

  Future<void> _saveToDevice() async {
    final exp = _export;
    if (exp == null || !exp.ok) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final dest = await LocalRecoveryService.instance.copyExportToUserLocation(exp);
      if (!mounted) return;
      setState(() {
        _busy = false;
        if (dest != null) {
          _savedName = dest['name'];
          _savedDestination = dest['uri'];
        }
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = '$e';
      });
    }
  }

  void _showDetails() {
    final scan = _scan;
    if (scan == null) return;
    final filter = int.tryParse(_evalFilter.text.trim());
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (ctx) {
        return Directionality(
          textDirection: TextDirection.rtl,
          child: SafeArea(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: SizedBox(
                height: MediaQuery.of(ctx).size.height * 0.75,
                child: ListView(
                  children: [
                    Text('تفاصيل الفحص', style: AppTextStyles.subtitle),
                    const SizedBox(height: 12),
                    if (filter != null) _evalFocusCard(scan.focusEvalItem(filter)),
                    Text('مطابقة المصادر', style: AppTextStyles.subtitle),
                    const SizedBox(height: 8),
                    for (final id in scan.identities)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 8),
                        child: Text(
                          '${id.identity}\n'
                          'Pending copy exists: ${id.pendingCopyExists ? 'YES' : 'NO'}\n'
                          'Cache copy exists: ${id.cacheCopyExists ? 'YES' : 'NO'}\n'
                          'Recovery Status: ${id.recoveryStatus}',
                          style: AppTextStyles.small,
                        ),
                      ),
                    const SizedBox(height: 8),
                    Text(
                      'عمليات معلقة: ${scan.pendingOps.length}',
                      style: AppTextStyles.small,
                    ),
                    for (final o in scan.pendingOps.take(40))
                      Padding(
                        padding: const EdgeInsets.only(top: 6),
                        child: Text(
                          '${o.opType}  ${o.id}\n'
                          'eval_item_id=${o.evalItemId ?? '—'}  '
                          'status=${o.syncStatus}  attempts=${o.attempts}',
                          style: AppTextStyles.small,
                        ),
                      ),
                  ],
                ),
              ),
            ),
          ),
        );
      },
    );
  }

  Widget _evalFocusCard(EvalItemFocus f) {
    return _card(
      children: [
        Text(
          'Evaluation Item: #${f.evalItemId}',
          style: AppTextStyles.subtitle,
        ),
        Text('Pending Save Found: ${f.pendingSaveFound ? 'YES' : 'NO'}'),
        Text('Rows Found: ${f.rowsFound}'),
        Text('Rows With Scores: ${f.rowsWithScores}'),
        Text('Rows With Notes: ${f.rowsWithNotes}'),
        Text('Associated Media: ${f.associatedMedia}'),
        Text('Sync Status: ${f.syncStatus.isEmpty ? '—' : f.syncStatus}'),
        Text('Attempts: ${f.attempts}'),
        Text('Last Error: ${f.lastError.isEmpty ? '—' : f.lastError}'),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final scan = _scan;
    final ctx = scan?.context;
    final c = scan?.counts ?? const <String, int>{};
    final filterId = int.tryParse(_evalFilter.text.trim());

    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppHeader(
        pageTitle: 'استعادة البيانات المحلية',
        showSettings: false,
        showLogout: false,
        showUtilityActions: false,
        onBack: () => Navigator.of(context).maybePop(),
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(
            'فحص وقراءة فقط. لا مزامنة ولا تعديل للبيانات المحلية.',
            style: AppTextStyles.cairo(fontSize: 12, color: AppColors.muted),
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: 12),
          _card(
            children: [
              Text('اسم المحكم: ${ctx?.judgeName.isNotEmpty == true ? ctx!.judgeName : '—'}'),
              Text('الوحدة: ${ctx?.unit.isNotEmpty == true ? ctx!.unit : '—'}'),
              Text('رقم المستخدم / Judge ID: ${ctx?.judgeId ?? ctx?.userId ?? '—'}'),
              Text('رقم التمرين: ${ctx?.exerciseId ?? '—'}'),
              Text('Device ID: ${ctx?.deviceId.isNotEmpty == true ? ctx!.deviceId : '—'}'),
            ],
          ),
          const SizedBox(height: 12),
          if (scan != null)
            _card(
              children: [
                Text('البيانات المحلية', style: AppTextStyles.subtitle),
                const SizedBox(height: 8),
                Text('قوائم تحتوي نتائج محفوظة: ${c['lists_with_saved_results'] ?? 0}'),
                Text('عمليات معلقة: ${c['pending_operations'] ?? 0}'),
                Text('عمليات حفظ نتائج: ${c['save_results_operations'] ?? 0}'),
                Text('صور محلية: ${c['images_local'] ?? 0}'),
                Text('فيديوهات محلية: ${c['videos_local'] ?? 0}'),
                Text('عمليات فاشلة: ${c['failed_operations'] ?? 0}'),
                Text('اختلاف مصادر: ${c['source_mismatches'] ?? 0}'),
              ],
            ),
          const SizedBox(height: 12),
          TextField(
            controller: _evalFilter,
            keyboardType: TextInputType.number,
            decoration: const InputDecoration(
              labelText: 'تصفية رقم عنصر التقييم (مثال: 180)',
            ),
            onChanged: (_) => setState(() {}),
          ),
          if (scan != null && filterId != null) ...[
            const SizedBox(height: 12),
            _evalFocusCard(scan.focusEvalItem(filterId)),
          ],
          const SizedBox(height: 16),
          ElevatedButton.icon(
            onPressed: _busy ? null : _runScan,
            icon: const Icon(Icons.search),
            label: const Text('فحص البيانات المحلية'),
            style: ElevatedButton.styleFrom(
              backgroundColor: AppColors.buttonBrown,
              foregroundColor: AppColors.white,
            ),
          ),
          const SizedBox(height: 8),
          ElevatedButton.icon(
            onPressed: _busy ? null : _exportPackage,
            icon: const Icon(Icons.archive_outlined),
            label: const Text('تصدير حزمة الاستعادة'),
          ),
          if (scan != null) ...[
            const SizedBox(height: 8),
            OutlinedButton.icon(
              onPressed: _busy ? null : _showDetails,
              icon: const Icon(Icons.list_alt),
              label: const Text('عرض تفاصيل الفحص'),
            ),
          ],
          if (_busy) ...[
            const SizedBox(height: 16),
            const Center(child: CircularProgressIndicator()),
          ],
          if (_error != null) ...[
            const SizedBox(height: 12),
            Text(
              _error!,
              style: AppTextStyles.cairo(
                color: AppColors.notDoneRed,
                fontWeight: FontWeight.w600,
              ),
              textAlign: TextAlign.center,
            ),
          ],
          if (_export != null && _export!.ok) ...[
            const SizedBox(height: 16),
            _card(
              children: [
                Text(
                  'تم إنشاء حزمة الاستعادة بنجاح',
                  style: AppTextStyles.cairo(
                    fontWeight: FontWeight.w700,
                    color: AppColors.doneGreen,
                  ),
                ),
                const SizedBox(height: 8),
                Text('File: ${_export!.zipName}'),
                Text(
                  'Size: ${_formatSize(_export!.zipBytes)}',
                ),
                if (_export!.excelError != null)
                  Text(
                    'تعذّر Excel؛ تم حفظ JSON الخام.',
                    style: AppTextStyles.cairo(color: AppColors.notDoneRed),
                  ),
              ],
            ),
            const SizedBox(height: 8),
            ElevatedButton.icon(
              onPressed: _busy ? null : _saveToDevice,
              icon: const Icon(Icons.save_alt),
              label: const Text('حفظ الحزمة في الجهاز'),
              style: ElevatedButton.styleFrom(
                backgroundColor: AppColors.buttonBrown,
                foregroundColor: AppColors.white,
              ),
            ),
            const SizedBox(height: 8),
            OutlinedButton.icon(
              onPressed: _busy ? null : _share,
              icon: const Icon(Icons.share),
              label: const Text('مشاركة الحزمة'),
            ),
            if (_savedName != null) ...[
              const SizedBox(height: 16),
              _card(
                children: [
                  Text(
                    'تم حفظ حزمة الاستعادة بنجاح',
                    style: AppTextStyles.cairo(
                      fontWeight: FontWeight.w700,
                      color: AppColors.doneGreen,
                    ),
                  ),
                  const SizedBox(height: 8),
                  Text('File: $_savedName'),
                  if ((_savedDestination ?? '').isNotEmpty)
                    Text(_savedDestination!),
                ],
              ),
            ],
          ],
          const SizedBox(height: 24),
        ],
      ),
    );
  }

  Widget _card({required List<Widget> children}) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.cardWhite,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.divider),
      ),
      child: DefaultTextStyle(
        style: AppTextStyles.body,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: children,
        ),
      ),
    );
  }

  String _formatSize(int b) {
    if (b < 1024) return '$b B';
    if (b < 1024 * 1024) return '${(b / 1024).toStringAsFixed(1)} KB';
    return '${(b / (1024 * 1024)).toStringAsFixed(1)} MB';
  }
}
