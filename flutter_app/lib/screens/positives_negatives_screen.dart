import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../models/polarity_note.dart';
import '../services/api_client.dart';
import '../services/auth_service.dart';
import '../services/tablet_repository.dart';
import '../theme/app_theme.dart';
import '../theme/device_layout.dart';
import '../widgets/app_header.dart';
import '../widgets/async_state_views.dart';

/// صفحة المحكم: إيجابيات/سلبيات — مطابقة لصفحة النظام (قائمة مشتركة للوحدة).
class PositivesNegativesScreen extends StatefulWidget {
  const PositivesNegativesScreen({super.key});

  @override
  State<PositivesNegativesScreen> createState() =>
      _PositivesNegativesScreenState();
}

class _PositivesNegativesScreenState extends State<PositivesNegativesScreen> {
  List<PolarityNote> _notes = [];
  final List<TextEditingController> _controllers = [];
  bool _loading = true;
  bool _saving = false;
  bool _fromCache = false;
  String? _error;
  String? _okMsg;
  String _filter = 'positive';
  String _unitKey = '';
  String _unitLabel = '';
  int _posCount = 0;
  int _negCount = 0;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    for (final c in _controllers) {
      c.dispose();
    }
    super.dispose();
  }

  void _disposeControllers() {
    for (final c in _controllers) {
      c.dispose();
    }
    _controllers.clear();
  }

  void _rebuildControllers(List<String> bodies) {
    _disposeControllers();
    final rows = bodies.isEmpty ? <String>[''] : bodies;
    for (final b in rows) {
      _controllers.add(TextEditingController(text: b));
    }
  }

  List<PolarityNote> _notesFor(String polarity) {
    return _notes
        .where((n) => n.polarity == polarity && n.sourceKind == 'general')
        .toList();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
      _okMsg = null;
    });
    try {
      final r = await TabletRepository.instance.fetchPolarityBundle();
      if (!mounted) return;
      final session = AuthService.instance.session;
      setState(() {
        _notes = r.data.notes;
        _fromCache = r.fromCache;
        _unitKey = r.data.unitKey.isNotEmpty
            ? r.data.unitKey
            : (session?.unitKey ?? '');
        _unitLabel = r.data.unitLabel.isNotEmpty
            ? r.data.unitLabel
            : (session?.unitLabel ?? _unitKey);
        _posCount = r.data.posCount;
        _negCount = r.data.negCount;
        _rebuildControllers(
          _notesFor(_filter).map((n) => n.body).toList(),
        );
        _loading = false;
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.message;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = '$e';
        _loading = false;
      });
    }
  }

  void _switchFilter(String next) {
    if (next == _filter) return;
    setState(() {
      _filter = next;
      _okMsg = null;
      _rebuildControllers(
        _notesFor(next).map((n) => n.body).toList(),
      );
    });
  }

  void _addRow() {
    setState(() {
      _controllers.add(TextEditingController());
    });
  }

  void _removeRow(int index) {
    if (_controllers.length <= 1) {
      _controllers[0].clear();
      setState(() {});
      return;
    }
    setState(() {
      _controllers.removeAt(index).dispose();
    });
  }

  Future<void> _save() async {
    if (_unitKey.isEmpty) {
      setState(() => _error = 'لا توجد وحدة مخصّصة لحسابك');
      return;
    }
    setState(() {
      _saving = true;
      _error = null;
      _okMsg = null;
    });
    try {
      final bodies = _controllers.map((c) => c.text).toList();
      final bundle = await TabletRepository.instance.replaceGeneralPolarityNotes(
        polarity: _filter,
        bodies: bodies,
        unitLevelKey: _unitKey,
      );
      if (!mounted) return;
      setState(() {
        _notes = bundle.notes;
        _posCount = bundle.posCount;
        _negCount = bundle.negCount;
        _fromCache = false;
        _saving = false;
        _okMsg = 'تم حفظ القائمة.';
        _rebuildControllers(
          _notesFor(_filter).map((n) => n.body).toList(),
        );
      });
      Future<void>.delayed(const Duration(seconds: 2), () {
        if (mounted) setState(() => _okMsg = null);
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _error = '$e';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final session = AuthService.instance.session;
    final placeholder =
        _filter == 'positive' ? 'نص الإيجابية' : 'نص السلبية';
    final addLabel =
        _filter == 'positive' ? 'إضافة سطر إيجابية' : 'إضافة سطر سلبية';

    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppHeader(
        pageTitle: 'الإيجابيات والسلبيات',
        pageSubtitle: _unitLabel.isNotEmpty
            ? _unitLabel
            : (session?.unitLabel ?? ''),
        onBack: () => Navigator.of(context).maybePop(),
      ),
      body: _loading
          ? const LoadingView()
          : _error != null && _notes.isEmpty && _controllers.isEmpty
              ? ErrorView(message: _error!, onRetry: _load)
              : Column(
                  children: [
                    if (_fromCache) const CachedDataBanner(),
                    if (_okMsg != null)
                      Material(
                        color: AppColors.doneGreen.withValues(alpha: 0.12),
                        child: Padding(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 16,
                            vertical: 10,
                          ),
                          child: Row(
                            children: [
                              const Icon(
                                Icons.check_circle,
                                color: AppColors.doneGreen,
                                size: 18,
                              ),
                              const SizedBox(width: 8),
                              Text(
                                _okMsg!,
                                style: AppTextStyles.cairo(
                                  color: AppColors.doneGreen,
                                  fontWeight: FontWeight.w700,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                    if (_error != null)
                      Material(
                        color: AppColors.notDoneRed.withValues(alpha: 0.1),
                        child: Padding(
                          padding: const EdgeInsets.all(12),
                          child: Text(
                            _error!,
                            style: AppTextStyles.cairo(
                              color: AppColors.notDoneRed,
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                        ),
                      ),
                    Padding(
                      padding: DeviceLayout.pagePadding(context).copyWith(
                        bottom: 8,
                        top: 12,
                      ),
                      child: _UnitBar(label: _unitLabel.isNotEmpty ? _unitLabel : '—'),
                    ),
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 16),
                      child: Row(
                        children: [
                          Expanded(
                            child: _FilterTab(
                              label: 'إيجابيات ($_posCount)',
                              active: _filter == 'positive',
                              activeColor: AppColors.doneGreen,
                              onTap: () => _switchFilter('positive'),
                            ),
                          ),
                          const SizedBox(width: 8),
                          Expanded(
                            child: _FilterTab(
                              label: 'سلبيات ($_negCount)',
                              active: _filter == 'negative',
                              activeColor: AppColors.notDoneRed,
                              onTap: () => _switchFilter('negative'),
                            ),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 8),
                    Expanded(
                      child: _unitKey.isEmpty
                          ? Center(
                              child: Padding(
                                padding: const EdgeInsets.all(24),
                                child: Text(
                                  'لا توجد وحدة مخصّصة لحسابك في قائمة المحكمين لهذا التمرين.',
                                  textAlign: TextAlign.center,
                                  style: AppTextStyles.body,
                                ),
                              ),
                            )
                          : ListView(
                              padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
                              children: [
                                Container(
                                  padding: const EdgeInsets.all(12),
                                  decoration: BoxDecoration(
                                    color: AppColors.cardWhite,
                                    borderRadius: BorderRadius.circular(12),
                                    border: Border.all(
                                      color: AppColors.divider,
                                    ),
                                  ),
                                  child: Column(
                                    children: [
                                      for (var i = 0;
                                          i < _controllers.length;
                                          i++)
                                        Padding(
                                          padding: const EdgeInsets.only(
                                            bottom: 8,
                                          ),
                                          child: Row(
                                            crossAxisAlignment:
                                                CrossAxisAlignment.start,
                                            children: [
                                              SizedBox(
                                                width: 28,
                                                child: Padding(
                                                  padding:
                                                      const EdgeInsets.only(
                                                    top: 12,
                                                  ),
                                                  child: Text(
                                                    '${i + 1}',
                                                    textAlign: TextAlign.center,
                                                    style:
                                                        AppTextStyles.cairo(
                                                      fontWeight:
                                                          FontWeight.w800,
                                                      color: AppColors.muted,
                                                    ),
                                                  ),
                                                ),
                                              ),
                                              Expanded(
                                                child: TextField(
                                                  controller: _controllers[i],
                                                  maxLines: null,
                                                  minLines: 1,
                                                  enabled: !_saving,
                                                  maxLength: 4000,
                                                  decoration: InputDecoration(
                                                    hintText: placeholder,
                                                    counterText: '',
                                                    filled: true,
                                                    fillColor:
                                                        AppColors.panelBeige,
                                                    border:
                                                        OutlineInputBorder(
                                                      borderRadius:
                                                          BorderRadius
                                                              .circular(8),
                                                    ),
                                                  ),
                                                ),
                                              ),
                                              IconButton(
                                                tooltip: 'حذف',
                                                onPressed: _saving
                                                    ? null
                                                    : () => _removeRow(i),
                                                icon: const Icon(
                                                  Icons.delete_outline,
                                                  size: 20,
                                                ),
                                              ),
                                            ],
                                          ),
                                        ),
                                      Align(
                                        alignment: AlignmentDirectional.centerStart,
                                        child: TextButton.icon(
                                          onPressed: _saving ? null : _addRow,
                                          icon: const Icon(Icons.add, size: 18),
                                          label: Text(addLabel),
                                        ),
                                      ),
                                    ],
                                  ),
                                ),
                                const SizedBox(height: 16),
                                SizedBox(
                                  width: double.infinity,
                                  child: ElevatedButton.icon(
                                    onPressed: _saving ? null : _save,
                                    style: ElevatedButton.styleFrom(
                                      backgroundColor: AppColors.buttonBrown,
                                      foregroundColor: AppColors.white,
                                      padding: const EdgeInsets.symmetric(
                                        vertical: 14,
                                      ),
                                    ),
                                    icon: _saving
                                        ? const SizedBox(
                                            width: 18,
                                            height: 18,
                                            child: CircularProgressIndicator(
                                              strokeWidth: 2,
                                              color: AppColors.white,
                                            ),
                                          )
                                        : const Icon(Icons.save_outlined),
                                    label: Text(
                                      _saving ? 'جاري الحفظ…' : 'حفظ',
                                      style: AppTextStyles.cairo(
                                        fontWeight: FontWeight.w800,
                                        color: AppColors.white,
                                      ),
                                    ),
                                  ),
                                ),
                              ],
                            ),
                    ),
                  ],
                ),
    );
  }
}

class _UnitBar extends StatelessWidget {
  const _UnitBar({required this.label});
  final String label;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: AppColors.panelBeige,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppColors.divider),
      ),
      child: Row(
        children: [
          const Icon(Icons.account_tree_outlined, size: 18),
          const SizedBox(width: 8),
          Text(
            'مستوى الوحدة',
            style: AppTextStyles.cairo(
              fontWeight: FontWeight.w700,
              color: AppColors.muted,
              fontSize: 12,
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              label,
              style: AppTextStyles.cairo(fontWeight: FontWeight.w800),
            ),
          ),
        ],
      ),
    );
  }
}

class _FilterTab extends StatelessWidget {
  const _FilterTab({
    required this.label,
    required this.active,
    required this.activeColor,
    required this.onTap,
  });
  final String label;
  final bool active;
  final Color activeColor;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: active ? activeColor : AppColors.cardWhite,
      borderRadius: BorderRadius.circular(10),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(10),
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 12),
          alignment: Alignment.center,
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(10),
            border: Border.all(
              color: active ? activeColor : AppColors.divider,
            ),
          ),
          child: Text(
            label,
            style: AppTextStyles.cairo(
              fontWeight: FontWeight.w800,
              color: active ? AppColors.white : AppColors.darkText,
            ),
          ),
        ),
      ),
    );
  }
}

void openPositivesNegativesScreen(BuildContext context) {
  context.push('/positives-negatives');
}
