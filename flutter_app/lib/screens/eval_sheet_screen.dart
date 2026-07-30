import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../models/eval_sheet.dart';
import '../services/api_client.dart';
import '../services/tablet_repository.dart';
import '../theme/app_theme.dart';
import '../widgets/app_header.dart';
import '../widgets/async_state_views.dart';
import '../widgets/figma_ui.dart';

enum EvalSheetMode { actionEval, evaluationList }

class EvalSheetScreen extends StatefulWidget {
  const EvalSheetScreen.actionEval({super.key, required this.slot, this.fallbackTitle})
      : mode = EvalSheetMode.actionEval,
        unitKey = null,
        itemId = null;

  const EvalSheetScreen.evaluationList({
    super.key,
    required this.unitKey,
    required this.itemId,
    this.fallbackTitle,
  })  : mode = EvalSheetMode.evaluationList,
        slot = null;

  final EvalSheetMode mode;
  final int? slot;
  final String? unitKey;
  final int? itemId;
  final String? fallbackTitle;

  @override
  State<EvalSheetScreen> createState() => _EvalSheetScreenState();
}

const _nonApprovableGrades = {'راسب', 'مقبول', 'متوسط'};

class _EvalSheetScreenState extends State<EvalSheetScreen> {
  EvalSheetDetail? _detail;
  List<EvalRowInput> _rows = [];
  bool _loading = true;
  bool _fromCache = false;
  String? _error;
  bool _saving = false;
  bool _approving = false;
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
      final result = widget.mode == EvalSheetMode.actionEval
          ? await TabletRepository.instance.fetchActionEvalDetail(widget.slot!)
          : await TabletRepository.instance.fetchEvaluationListDetail(widget.unitKey!, widget.itemId!);
      var rows = List<EvalRowInput>.from(result.data.savedRows);
      // Safety net: never show an empty sheet when the template has rows.
      if (rows.isEmpty && result.data.evalRows.isNotEmpty) {
        rows = result.data.evalRows.map(EvalRowInput.fromEvalRow).toList();
      }
      setState(() {
        _detail = result.data;
        _rows = rows;
        _fromCache = result.fromCache;
      });
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  double? _parseNum(String s) {
    final t = s.trim().replaceAll(',', '.');
    if (t.isEmpty) return null;
    return double.tryParse(t);
  }

  double? _templateMax(int index) {
    final rows = _detail?.evalRows ?? const [];
    if (index < 0 || index >= rows.length) return null;
    final m = rows[index].maxNum;
    return (m != null && m > 0) ? m : null;
  }

  double? _rowPercent(int index) {
    final input = _rows[index];
    if (input.rowKind == 'section') return null;
    if (input.acquired.isEmpty || input.acquired == 'na') return null;
    final n = _parseNum(input.acquired);
    if (n == null) return null;
    final mx = _templateMax(index);
    if (mx != null && n > mx + 1e-6) return null;
    return (n / (mx ?? 5)) * 100;
  }

  String _gradeFromPct(double? p) {
    if (p == null) return 'غير محسوب';
    if (p < 60) return 'راسب';
    if (p < 70) return 'مقبول';
    if (p < 80) return 'جيد';
    if (p < 90) return 'جيد جداً';
    return 'ممتاز';
  }

  ({double sumMax, double sumAcq, bool anyAcq}) _totalsRaw() {
    double sumMax = 0, sumAcq = 0;
    bool anyAcq = false;
    for (var i = 0; i < _rows.length; i++) {
      if (_rows[i].rowKind == 'section') continue;
      final mx = _templateMax(i);
      if (mx != null) sumMax += mx;
      final acq = _rows[i].acquired;
      if (acq.isNotEmpty && acq != 'na') {
        final n = _parseNum(acq);
        if (n != null) {
          sumAcq += n;
          anyAcq = true;
        }
      }
    }
    return (sumMax: sumMax, sumAcq: sumAcq, anyAcq: anyAcq);
  }

  double? get _totalPct {
    final t = _totalsRaw();
    if (t.sumMax <= 0 || !t.anyAcq) return null;
    return (t.sumAcq / t.sumMax) * 100;
  }

  bool get _hasAnyNotes => _rows.any((r) => r.rowKind != 'section' && r.notes.trim().isNotEmpty);

  List<int> get _emptyAcquiredIndexes => [
        for (var i = 0; i < _rows.length; i++)
          if (_rows[i].rowKind != 'section' && _rows[i].acquired.trim().isEmpty) i,
      ];

  bool get _canApproveNow {
    final detail = _detail;
    if (detail == null || !detail.canApprove) return false;
    if (_emptyAcquiredIndexes.isNotEmpty) return false;
    final grade = _gradeFromPct(_totalPct);
    if (!_nonApprovableGrades.contains(grade)) return true;
    return _hasAnyNotes;
  }

  String _scoreKey(double n) {
    if (n == n.roundToDouble()) return '${n.round()}';
    var s = n.toStringAsFixed(2);
    if (s.endsWith('0')) s = s.substring(0, s.length - 1);
    if (s.endsWith('.')) s = s.substring(0, s.length - 1);
    return s;
  }

  /// Options up to the row max (0.25 steps), matching the web judge sheet.
  List<AcquiredOption> _optionsFor(int index) {
    final mx = _templateMax(index) ?? 5.0;
    final steps = (mx * 4).round().clamp(0, 200);
    final opts = <AcquiredOption>[
      const AcquiredOption('', '—'),
      const AcquiredOption('na', 'لا ينطبق'),
    ];
    for (var step = 0; step <= steps; step++) {
      final key = _scoreKey(step * 0.25);
      opts.add(AcquiredOption(key, key));
    }
    final cur = index < _rows.length ? _rows[index].acquired.trim() : '';
    if (cur.isNotEmpty && cur != 'na' && !opts.any((o) => o.value == cur)) {
      opts.add(AcquiredOption(cur, cur));
    }
    return opts;
  }

  Future<void> _pickMedia(int index, {required bool video}) async {
    final picker = ImagePicker();
    try {
      final XFile? file = video
          ? await picker.pickVideo(source: ImageSource.camera)
          : await picker.pickImage(source: ImageSource.camera, imageQuality: 82);
      if (file == null) return;
      setState(() => _rows[index].localMediaPaths.add(file.path));
      final detail = _detail;
      if (detail == null) return;
      try {
        await ApiClient.instance.uploadCriterionMedia(
          filePath: file.path,
          rowIndex: index,
          mediaKind: video ? 'video' : 'photo',
          evaluationListItemId: widget.mode == EvalSheetMode.evaluationList ? detail.itemId : null,
          bundleActionEvalId: widget.mode == EvalSheetMode.actionEval ? detail.slotId : null,
        );
      } catch (_) {}
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('تعذّر التقاط الوسائط: $e')));
    }
  }

  Future<void> _save() async {
    final detail = _detail;
    if (detail == null || _saving || !detail.canEdit) return;
    setState(() {
      _saving = true;
      _hint = null;
    });
    try {
      final sentLive = widget.mode == EvalSheetMode.actionEval
          ? await TabletRepository.instance.saveActionEvalResults(widget.slot!, _rows)
          : await TabletRepository.instance.saveEvaluationListResults(
              widget.unitKey!,
              widget.itemId!,
              _rows,
            );
      if (!mounted) return;
      setState(() {
        _saving = false;
        _hint = sentLive ? 'تم حفظ نتائج التقييم بنجاح' : 'حُفظ محلياً — سيُزامن عند الاتصال';
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _hint = e.message;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _hint = 'تعذّر الحفظ: $e';
      });
    }
  }

  Future<void> _approve() async {
    final detail = _detail;
    if (detail == null || _approving || !_canApproveNow) return;
    setState(() {
      _approving = true;
      _hint = null;
    });
    try {
      // Persist current scores first so approve has a canonical saved row.
      if (detail.canEdit) {
        await (widget.mode == EvalSheetMode.actionEval
            ? TabletRepository.instance.saveActionEvalResults(widget.slot!, _rows)
            : TabletRepository.instance.saveEvaluationListResults(
                widget.unitKey!,
                widget.itemId!,
                _rows,
              ));
      }
      final sentLive = widget.mode == EvalSheetMode.actionEval
          ? await TabletRepository.instance.approveActionEval(widget.slot!)
          : await TabletRepository.instance.approveEvaluationList(widget.unitKey!, widget.itemId!);
      if (!mounted) return;
      setState(() {
        _approving = false;
        _hint = sentLive ? 'تم اعتماد التقييم' : 'طلب الاعتماد محفوظ محلياً';
        if (sentLive) {
          _detail = EvalSheetDetail(
            kind: detail.kind,
            slot: detail.slot,
            slotId: detail.slotId,
            itemId: detail.itemId,
            title: detail.title,
            unitKey: detail.unitKey,
            unitLabel: detail.unitLabel,
            phaseKey: detail.phaseKey,
            evalRows: detail.evalRows,
            evalStructured: detail.evalStructured,
            acquiredOptions: detail.acquiredOptions,
            savedRows: detail.savedRows,
            canEdit: false,
            canApprove: false,
            isApproved: true,
            workflow: detail.workflow,
          );
        }
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _approving = false;
        _hint = e.message;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _approving = false;
        _hint = 'تعذّر الاعتماد: $e';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final pageTitle = widget.mode == EvalSheetMode.actionEval ? 'قوائم تقييم الإجراءات' : 'قوائم التقييم';
    final sheetTitle =
        _detail?.title.isNotEmpty == true ? _detail!.title : (widget.fallbackTitle ?? 'ورقة التقييم');

    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppHeader(
        pageTitle: pageTitle,
        onBack: () => Navigator.of(context).maybePop(),
      ),
      body: _loading
          ? const LoadingView()
          : _error != null
              ? ErrorView(message: _error!, onRetry: _load)
              : _buildBody(sheetTitle),
    );
  }

  Widget _buildBody(String sheetTitle) {
    final detail = _detail;
    if (detail == null) return const EmptyView(message: 'لا توجد بيانات');
    if (!detail.evalStructured || detail.evalRows.isEmpty) {
      return Column(
        children: [
          if (_fromCache) const CachedDataBanner(),
          Expanded(
            child: EmptyView(
              message: detail.evalRows.isEmpty ? 'لا توجد بنود تقييم' : 'تعذّر قراءة قالب التقييم',
            ),
          ),
        ],
      );
    }

    final totals = _totalsRaw();
    final pct = _totalPct;
    final grade = _gradeFromPct(pct);

    return Column(
      children: [
        if (_fromCache) const CachedDataBanner(),
        Container(
          width: double.infinity,
          color: AppColors.titleBar,
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
          child: Text(
            sheetTitle,
            textAlign: TextAlign.center,
            style: AppTextStyles.cairo(fontSize: 15, fontWeight: FontWeight.w800, color: AppColors.olive),
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
          child: FigmaTableHeader(
            cells: const [
              (label: 'ت', flex: 1),
              (label: 'عناصر التقييم القيادي والعملياتي', flex: 5),
              (label: 'العلامة القصوى', flex: 2),
              (label: 'المكتسبة', flex: 2),
              (label: 'النسبة', flex: 2),
              (label: 'النتيجة', flex: 2),
              (label: 'التوثيق', flex: 2),
            ],
          ),
        ),
        Expanded(
          child: ListView.builder(
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 8),
            itemCount: _rows.length,
            itemBuilder: (context, index) {
              if (_rows[index].rowKind == 'section') {
                return Container(
                  margin: const EdgeInsets.only(bottom: 8),
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: AppColors.gold.withValues(alpha: 0.2),
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: Text(_rows[index].element, style: AppTextStyles.subtitle),
                );
              }
              return _CriterionCard(
                index: index,
                input: _rows[index],
                canEdit: detail.canEdit,
                options: _optionsFor(index),
                percent: _rowPercent(index),
                grade: _gradeFromPct(_rowPercent(index)),
                onAcquiredChanged: (v) => setState(() => _rows[index].acquired = v),
                onNotesChanged: (v) => setState(() => _rows[index].notes = v),
                onCapture: (video) => _pickMedia(index, video: video),
              );
            },
          ),
        ),
        _FooterBar(
          sumMax: totals.sumMax,
          sumAcq: totals.anyAcq ? totals.sumAcq : null,
          totalPct: pct,
          totalGrade: grade,
          canEdit: detail.canEdit,
          canApprove: _canApproveNow,
          alreadyApproved: detail.isApproved,
          saving: _saving,
          approving: _approving,
          hint: _hint,
          onSave: _save,
          onApprove: _approve,
        ),
      ],
    );
  }
}

class _CriterionCard extends StatefulWidget {
  const _CriterionCard({
    required this.index,
    required this.input,
    required this.canEdit,
    required this.options,
    required this.percent,
    required this.grade,
    required this.onAcquiredChanged,
    required this.onNotesChanged,
    required this.onCapture,
  });

  final int index;
  final EvalRowInput input;
  final bool canEdit;
  final List<AcquiredOption> options;
  final double? percent;
  final String grade;
  final ValueChanged<String> onAcquiredChanged;
  final ValueChanged<String> onNotesChanged;
  final ValueChanged<bool> onCapture;

  @override
  State<_CriterionCard> createState() => _CriterionCardState();
}

class _CriterionCardState extends State<_CriterionCard> {
  late final TextEditingController _notesCtrl;

  @override
  void initState() {
    super.initState();
    _notesCtrl = TextEditingController(text: widget.input.notes);
  }

  @override
  void didUpdateWidget(covariant _CriterionCard oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.input.notes != widget.input.notes && _notesCtrl.text != widget.input.notes) {
      _notesCtrl.text = widget.input.notes;
    }
  }

  @override
  void dispose() {
    _notesCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final acquiredValue = widget.options.any((o) => o.value == widget.input.acquired)
        ? widget.input.acquired
        : null;

    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.cardWhite,
        borderRadius: BorderRadius.circular(12),
        boxShadow: const [BoxShadow(color: AppColors.cardShadow, blurRadius: 5, offset: Offset(0, 2))],
        border: Border.all(color: AppColors.divider),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 36,
            child: Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(
                '${widget.index + 1}',
                textAlign: TextAlign.center,
                style: AppTextStyles.cairo(fontWeight: FontWeight.w800),
              ),
            ),
          ),
          Expanded(
            flex: 5,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(widget.input.element, style: AppTextStyles.body),
                const SizedBox(height: 8),
                TextField(
                  controller: _notesCtrl,
                  enabled: widget.canEdit,
                  minLines: 1,
                  maxLines: 3,
                  style: AppTextStyles.small,
                  decoration: InputDecoration(
                    hintText: 'اكتب ملاحظاتك هنا (اختياري)',
                    filled: true,
                    fillColor: AppColors.headerCream,
                    isDense: true,
                    contentPadding: const EdgeInsets.symmetric(horizontal: 10, vertical: 10),
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(8),
                      borderSide: BorderSide.none,
                    ),
                  ),
                  onChanged: widget.onNotesChanged,
                ),
              ],
            ),
          ),
          const SizedBox(width: 8),
          SizedBox(
            width: 70,
            child: Padding(
              padding: const EdgeInsets.only(top: 10),
              child: Text(widget.input.maxVal, textAlign: TextAlign.center, style: AppTextStyles.small),
            ),
          ),
          SizedBox(
            width: 96,
            child: DecoratedBox(
              decoration: BoxDecoration(
                color: AppColors.headerCream,
                borderRadius: BorderRadius.circular(8),
              ),
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 6),
                child: DropdownButtonHideUnderline(
                  child: DropdownButton<String>(
                    isExpanded: true,
                    value: acquiredValue,
                    hint: Text('—', style: AppTextStyles.small),
                    items: widget.options
                        .map(
                          (o) => DropdownMenuItem(
                            value: o.value,
                            child: Text(o.label, style: AppTextStyles.small),
                          ),
                        )
                        .toList(),
                    onChanged: widget.canEdit
                        ? (v) => widget.onAcquiredChanged(v ?? '')
                        : null,
                  ),
                ),
              ),
            ),
          ),
          SizedBox(
            width: 70,
            child: Padding(
              padding: const EdgeInsets.only(top: 10),
              child: Text(
                widget.percent == null ? '—' : '${widget.percent!.round()}%',
                textAlign: TextAlign.center,
                style: AppTextStyles.small,
              ),
            ),
          ),
          SizedBox(
            width: 88,
            child: Container(
              margin: const EdgeInsets.only(top: 6),
              padding: const EdgeInsets.symmetric(vertical: 6, horizontal: 6),
              decoration: BoxDecoration(
                color: AppColors.resultBlueBg,
                borderRadius: BorderRadius.circular(16),
                border: Border.all(color: AppColors.resultBlue.withValues(alpha: 0.3)),
              ),
              child: Text(
                widget.grade,
                textAlign: TextAlign.center,
                style: AppTextStyles.cairo(fontSize: 12, color: AppColors.resultBlue, fontWeight: FontWeight.w700),
              ),
            ),
          ),
          SizedBox(
            width: 88,
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                if (widget.canEdit)
                  _DocBtn(icon: Icons.camera_alt_outlined, onTap: () => widget.onCapture(false)),
                if (widget.canEdit)
                  _DocBtn(icon: Icons.videocam_outlined, onTap: () => widget.onCapture(true)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _DocBtn extends StatelessWidget {
  const _DocBtn({required this.icon, required this.onTap});
  final IconData icon;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 2),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(8),
        child: Container(
          width: 36,
          height: 36,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: AppColors.goldDark),
          ),
          child: Icon(icon, size: 18, color: AppColors.goldDark),
        ),
      ),
    );
  }
}

class _FooterBar extends StatelessWidget {
  const _FooterBar({
    required this.sumMax,
    required this.sumAcq,
    required this.totalPct,
    required this.totalGrade,
    required this.canEdit,
    required this.canApprove,
    required this.alreadyApproved,
    required this.saving,
    required this.approving,
    required this.hint,
    required this.onSave,
    required this.onApprove,
  });

  final double sumMax;
  final double? sumAcq;
  final double? totalPct;
  final String totalGrade;
  final bool canEdit;
  final bool canApprove;
  final bool alreadyApproved;
  final bool saving;
  final bool approving;
  final String? hint;
  final VoidCallback onSave;
  final VoidCallback onApprove;

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      top: false,
      child: Container(
        padding: const EdgeInsets.fromLTRB(14, 10, 14, 12),
        decoration: const BoxDecoration(
          color: AppColors.headerCream,
          border: Border(top: BorderSide(color: AppColors.divider)),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (hint != null)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Text(
                  hint!,
                  style: AppTextStyles.cairo(fontSize: 12, color: AppColors.doneGreen, fontWeight: FontWeight.w600),
                ),
              ),
            Row(
              children: [
                Expanded(
                  child: Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: [
                      _StatBox(label: 'مجموع العلامات القصوى', value: sumMax > 0 ? '${sumMax.round()}' : '—'),
                      _StatBox(label: 'العلامات المكتسبة', value: sumAcq == null ? '—' : '${sumAcq!.round()}'),
                      _StatBox(label: 'النسبة المئوية النهائية', value: totalPct == null ? '—' : '${totalPct!.round()}%'),
                      _StatBox(label: 'النتيجة النهائية', value: totalGrade == 'غير محسوب' ? '—' : totalGrade, emphasize: true),
                    ],
                  ),
                ),
                const SizedBox(width: 10),
                Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    if (canEdit)
                      ElevatedButton.icon(
                        style: ElevatedButton.styleFrom(
                          backgroundColor: AppColors.buttonBrown,
                          foregroundColor: AppColors.white,
                          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                        ),
                        onPressed: saving ? null : onSave,
                        icon: saving
                            ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                            : const Icon(Icons.save_outlined, size: 18),
                        label: const Text('حفظ نتائج التقييم النهائي'),
                      ),
                    if (alreadyApproved && !canEdit)
                      Text('معتمد', style: AppTextStyles.small),
                    if (canApprove) ...[
                      const SizedBox(height: 8),
                      ElevatedButton.icon(
                        style: ElevatedButton.styleFrom(
                          backgroundColor: AppColors.buttonBrownDark,
                          foregroundColor: AppColors.white,
                          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                        ),
                        onPressed: approving ? null : onApprove,
                        icon: approving
                            ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                            : const Icon(Icons.check_circle_outline, size: 18),
                        label: const Text('اعتماد نتائج التقييم النهائي'),
                      ),
                    ],
                  ],
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _StatBox extends StatelessWidget {
  const _StatBox({required this.label, required this.value, this.emphasize = false});
  final String label;
  final String value;
  final bool emphasize;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 140,
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: AppColors.cardWhite,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppColors.divider),
      ),
      child: Column(
        children: [
          Text(label, textAlign: TextAlign.center, style: AppTextStyles.cairo(fontSize: 10, color: AppColors.muted)),
          const SizedBox(height: 4),
          Text(
            value,
            textAlign: TextAlign.center,
            style: AppTextStyles.cairo(
              fontSize: emphasize ? 18 : 16,
              fontWeight: FontWeight.w800,
              color: emphasize ? AppColors.olive : AppColors.darkText,
            ),
          ),
        ],
      ),
    );
  }
}
