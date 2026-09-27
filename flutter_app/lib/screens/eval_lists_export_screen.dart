import 'package:flutter/material.dart';

import '../services/eval_excel_export.dart';
import '../theme/app_theme.dart';
import '../widgets/app_header.dart';

class EvalListsExportScreen extends StatefulWidget {
  const EvalListsExportScreen({super.key});

  @override
  State<EvalListsExportScreen> createState() => _EvalListsExportScreenState();
}

class _EvalListsExportScreenState extends State<EvalListsExportScreen> {
  bool _loading = true;
  String? _error;
  List<EvalExcelListDraft> _lists = [];
  final Set<int> _selected = {};
  bool _exporting = false;
  String? _hint;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final lists = await EvalExcelExportService.instance.listSavedEvaluations();
      if (!mounted) return;
      setState(() {
        _lists = lists;
        _selected
          ..clear()
          ..addAll(lists.map((e) => e.evalItemId));
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _export(List<EvalExcelListDraft> chosen) async {
    if (chosen.isEmpty) return;
    setState(() {
      _exporting = true;
      _hint = null;
    });
    try {
      final result = await EvalExcelExportService.instance.exportLists(chosen);
      if (!result.ok) {
        if (!mounted) return;
        setState(() => _hint = result.error ?? 'تعذّر التصدير');
        return;
      }
      await EvalExcelExportService.instance.saveToUserLocation(result);
      if (!mounted) return;
      setState(() => _hint = 'تم التصدير: ${result.fileName}');
    } catch (e) {
      if (!mounted) return;
      setState(() => _hint = '$e');
    } finally {
      if (mounted) setState(() => _exporting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppHeader(
        pageTitle: 'تصدير القوائم',
        onBack: () => Navigator.of(context).maybePop(),
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator(color: AppColors.gold))
          : _error != null
              ? Center(child: Text(_error!, style: AppTextStyles.body))
              : Column(
                  children: [
                    Padding(
                      padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
                      child: Text(
                        'التصدير من الحفظ المحلي فقط — دون شبكة.',
                        style: AppTextStyles.small,
                        textAlign: TextAlign.center,
                      ),
                    ),
                    if (_hint != null)
                      Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 16),
                        child: Text(_hint!, style: AppTextStyles.body, textAlign: TextAlign.center),
                      ),
                    Expanded(
                      child: _lists.isEmpty
                          ? Center(child: Text('لا توجد قوائم محفوظة محلياً', style: AppTextStyles.body))
                          : ListView.builder(
                              itemCount: _lists.length,
                              itemBuilder: (context, i) {
                                final row = _lists[i];
                                final on = _selected.contains(row.evalItemId);
                                return CheckboxListTile(
                                  value: on,
                                  onChanged: (v) {
                                    setState(() {
                                      if (v == true) {
                                        _selected.add(row.evalItemId);
                                      } else {
                                        _selected.remove(row.evalItemId);
                                      }
                                    });
                                  },
                                  title: Text(
                                    '#${row.evalItemId} — ${row.listName}',
                                    style: AppTextStyles.body,
                                  ),
                                  subtitle: Text(
                                    '${row.unitName.isEmpty ? row.unitId : row.unitName}'
                                    '${row.sourceMismatch ? ' · تعارض مصدر' : ''}',
                                    style: AppTextStyles.small,
                                  ),
                                );
                              },
                            ),
                    ),
                    Padding(
                      padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          OutlinedButton(
                            onPressed: _exporting
                                ? null
                                : () => _export(
                                      _lists
                                          .where((e) => _selected.contains(e.evalItemId))
                                          .toList(),
                                    ),
                            child: const Text('تصدير المحددة'),
                          ),
                          const SizedBox(height: 8),
                          ElevatedButton(
                            onPressed: _exporting ? null : () => _export(_lists),
                            style: ElevatedButton.styleFrom(
                              backgroundColor: AppColors.buttonBrown,
                              foregroundColor: AppColors.white,
                            ),
                            child: Text(_exporting ? 'جاري التصدير…' : 'تصدير الكل'),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
    );
  }
}
