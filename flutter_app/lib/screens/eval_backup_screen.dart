import 'package:flutter/material.dart';

import '../services/eval_backup_assembler.dart';
import '../services/eval_backup_service.dart';
import '../theme/app_theme.dart';
import '../widgets/app_header.dart';

class EvalBackupScreen extends StatefulWidget {
  const EvalBackupScreen({super.key});

  @override
  State<EvalBackupScreen> createState() => _EvalBackupScreenState();
}

class _EvalBackupScreenState extends State<EvalBackupScreen> {
  bool _loading = true;
  bool _busy = false;
  String? _error;
  EvalBackupPackage? _preview;
  EvalBackupResult? _result;
  String? _savedName;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
      _result = null;
      _savedName = null;
    });
    try {
      final preview = await EvalBackupService.instance.preview();
      if (!mounted) return;
      setState(() {
        _preview = preview;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = '$e';
      });
    }
  }

  Future<void> _create() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final result = await EvalBackupService.instance.createBackup(
        preview: _preview,
      );
      if (!mounted) return;
      setState(() {
        _busy = false;
        _result = result;
        _preview = result.package ?? _preview;
        if (!result.ok) _error = result.error ?? 'فشل إنشاء النسخة الاحتياطية';
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = '$e';
      });
    }
  }

  Future<void> _save() async {
    final result = _result;
    if (result == null || !result.ok) return;
    setState(() => _busy = true);
    try {
      final dest = await EvalBackupService.instance.copyExportToUserLocation(result);
      if (!mounted) return;
      setState(() {
        _busy = false;
        _savedName = dest?['name'];
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
    final result = _result;
    if (result == null || !result.ok) return;
    try {
      await EvalBackupService.instance.shareExport(result);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('تعذّرت المشاركة: $e')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final preview = _preview;
    final result = _result;
    final pkg = result?.package ?? preview;
    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppHeader(
        pageTitle: 'نسخة احتياطية للتمرين الحالي',
        onBack: () => Navigator.of(context).maybePop(),
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator(color: AppColors.gold))
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                if (_error != null)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: Text(_error!, style: AppTextStyles.body.copyWith(color: AppColors.notDoneRed)),
                  ),
                if (pkg != null) ...[
                  Text(
                    result != null && result.ok
                        ? 'تم إنشاء النسخة الاحتياطية للتمرين الحالي بنجاح'
                        : 'نسخة احتياطية للتمرين الحالي',
                    style: AppTextStyles.subtitle,
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 12),
                  _card([
                    Text('التمرين: ${pkg.scope.exerciseName.isEmpty ? pkg.scope.exerciseId : pkg.scope.exerciseName}'),
                    const SizedBox(height: 8),
                    Text('قوائم تقييم الإجراءات: ${pkg.actionLists.length}'),
                    Text('قوائم تقييم المعاضل: ${pkg.dilemmaLists.length}'),
                    Text('إجمالي القوائم: ${pkg.lists.length}'),
                    Text('الصور: ${pkg.imageCount}'),
                    Text('الفيديوهات: ${pkg.videoCount}'),
                    if (pkg.actionLists.isNotEmpty) ...[
                      const SizedBox(height: 12),
                      Text('أسماء قوائم تقييم الإجراءات:', style: AppTextStyles.subtitle),
                      const SizedBox(height: 4),
                      for (final list in pkg.actionLists)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 4),
                          child: Text('• ${list.listName}'),
                        ),
                    ],
                    if (pkg.dilemmaLists.isNotEmpty) ...[
                      const SizedBox(height: 8),
                      Text('أسماء قوائم تقييم المعاضل:', style: AppTextStyles.subtitle),
                      const SizedBox(height: 4),
                      for (final list in pkg.dilemmaLists)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 4),
                          child: Text('• ${list.listName}'),
                        ),
                    ],
                  ]),
                  const SizedBox(height: 16),
                  if (result == null || !result.ok)
                    ElevatedButton(
                      onPressed: _busy ? null : _create,
                      style: ElevatedButton.styleFrom(
                        backgroundColor: AppColors.buttonBrown,
                        foregroundColor: AppColors.white,
                        padding: const EdgeInsets.symmetric(vertical: 14),
                      ),
                      child: Text(_busy ? 'جاري الإنشاء…' : 'إنشاء نسخة احتياطية للتمرين الحالي'),
                    )
                  else ...[
                    if (_savedName != null)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 12),
                        child: Text('تم الحفظ: $_savedName', textAlign: TextAlign.center),
                      ),
                    OutlinedButton(
                      onPressed: _busy ? null : _save,
                      child: const Text('حفظ في الجهاز'),
                    ),
                    const SizedBox(height: 8),
                    ElevatedButton(
                      onPressed: _busy ? null : _share,
                      style: ElevatedButton.styleFrom(
                        backgroundColor: AppColors.buttonBrown,
                        foregroundColor: AppColors.white,
                      ),
                      child: const Text('مشاركة'),
                    ),
                  ],
                ],
              ],
            ),
    );
  }

  Widget _card(List<Widget> children) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.cardWhite,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.goldBorder),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: children,
      ),
    );
  }
}
