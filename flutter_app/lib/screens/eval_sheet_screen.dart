import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../models/eval_sheet.dart';
import '../services/api_client.dart';
import '../services/tablet_repository.dart';
import '../theme/app_theme.dart';
import '../theme/device_layout.dart';
import '../widgets/app_header.dart';
import '../widgets/async_state_views.dart';
import '../widgets/sticky_eval_scaffold.dart';

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

  List<EvalRowInput> _rowsFromDetail(EvalSheetDetail detail) {
    // Template rows are the source of truth; savedRows is already seeded in fromJson.
    if (detail.savedRows.isNotEmpty) {
      return List<EvalRowInput>.from(detail.savedRows);
    }
    return detail.evalRows.map(EvalRowInput.fromEvalRow).toList();
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
      final rows = _rowsFromDetail(result.data);
      if (!mounted) return;
      setState(() {
        _detail = result.data;
        _rows = rows;
        _fromCache = result.fromCache;
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _error = e.message);
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = 'تعذّر تحميل ورقة التقييم: $e');
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
    return (m != null && m.isFinite && m > 0) ? m : null;
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
    var mx = _templateMax(index) ?? 5.0;
    if (!mx.isFinite || mx <= 0) mx = 5.0;
    final steps = (mx * 4).round().clamp(0, 200);
    final opts = <AcquiredOption>[
      const AcquiredOption('', '—'),
      const AcquiredOption('na', 'لا ينطبق'),
    ];
    final seen = <String>{'', 'na'};
    for (var step = 0; step <= steps; step++) {
      final key = _scoreKey(step * 0.25);
      if (!seen.add(key)) continue;
      opts.add(AcquiredOption(key, key));
    }
    final cur = index < _rows.length ? _rows[index].acquired.trim() : '';
    if (cur.isNotEmpty && seen.add(cur)) {
      opts.add(AcquiredOption(cur, cur));
    }
    return opts;
  }

  Future<void> _pickMedia(
    int index, {
    required bool video,
    ImageSource source = ImageSource.camera,
  }) async {
    final picker = ImagePicker();
    try {
      final XFile? file = video
          ? await picker.pickVideo(source: source)
          : await picker.pickImage(
              source: source,
              // لا نضغط الجودة بدون طلب المستخدم
            );
      if (file == null) return;
      final detail = _detail;
      if (detail == null) return;
      final sheetKey = widget.mode == EvalSheetMode.actionEval
          ? 'action_eval_detail:${widget.slot}'
          : 'evaluation_list_detail:${widget.unitKey}:${widget.itemId}';
      final localPath = await TabletRepository.instance.queueCriterionMedia(
        sourcePath: file.path,
        rowIndex: index,
        mediaKind: video ? 'video' : 'photo',
        sheetCacheKey: sheetKey,
        evaluationListItemId:
            widget.mode == EvalSheetMode.evaluationList ? detail.itemId : null,
        bundleActionEvalId:
            widget.mode == EvalSheetMode.actionEval ? detail.slotId : null,
      );
      if (!mounted) return;
      setState(() {
        _rows[index].localMediaPaths.add(localPath);
        _hint = 'حُفظت الوسائط محلياً — ستُرفع عند Sync My Work';
      });
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('$e')),
      );
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
      await (widget.mode == EvalSheetMode.actionEval
          ? TabletRepository.instance.saveActionEvalResults(widget.slot!, _rows)
          : TabletRepository.instance.saveEvaluationListResults(
              widget.unitKey!,
              widget.itemId!,
              _rows,
            ));
      if (!mounted) return;
      setState(() {
        _saving = false;
        _hint = 'حُفظت النتائج محلياً — ستُزامن مع الخادم';
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
      if (detail.canEdit) {
        await (widget.mode == EvalSheetMode.actionEval
            ? TabletRepository.instance.saveActionEvalResults(widget.slot!, _rows)
            : TabletRepository.instance.saveEvaluationListResults(
                widget.unitKey!,
                widget.itemId!,
                _rows,
              ));
      }
      await (widget.mode == EvalSheetMode.actionEval
          ? TabletRepository.instance.approveActionEval(widget.slot!)
          : TabletRepository.instance.approveEvaluationList(
              widget.unitKey!,
              widget.itemId!,
            ));
      if (!mounted) return;
      setState(() {
        _approving = false;
        _hint = 'معتمد محلياً – بانتظار المزامنة';
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
          savedRows: List<EvalRowInput>.from(_rows),
          canEdit: false,
          canApprove: false,
          isApproved: true,
          locallyApproved: true,
          approvalSyncStatus: 'pending',
          workflow: const EvalWorkflow(
            label: 'معتمد محلياً – بانتظار المزامنة',
            reopened: false,
          ),
        );
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
              message: detail.evalRows.isEmpty ? 'لا توجد بنود تقييم في هذا الملف' : 'تعذّر قراءة قالب التقييم',
            ),
          ),
        ],
      );
    }

    if (_rows.isEmpty && detail.evalRows.isNotEmpty) {
      // Safety: template parsed but editable buffer empty — refill once.
      _rows = _rowsFromDetail(detail);
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
        Expanded(
          child: StickyEvalScaffold(
            // على الهاتف لا نفرض عرض جدول عريض — صفوف متكدّسة بعرض 480
            minTableWidth: DeviceLayout.isPhoneWidth(context) ? null : 980,
            columnHeader: DeviceLayout.isPhoneWidth(context)
                ? const _EvalSheetColumnHeaderPhone()
                : const _EvalSheetColumnHeader(),
            rows: _rows.isEmpty
                ? EmptyView(
                    message: 'تعذّر عرض بنود التقييم (${detail.evalRows.length} في القالب)',
                    icon: Icons.table_rows_outlined,
                  )
                : ListView.builder(
                    padding: DeviceLayout.isPhoneWidth(context)
                        ? const EdgeInsets.fromLTRB(6, 6, 6, 6)
                        : const EdgeInsets.fromLTRB(10, 10, 10, 10),
                    itemCount: _rows.length,
                    itemBuilder: (context, index) {
                      final input = _rows[index];
                      if (input.rowKind == 'section') {
                        return Container(
                          margin: const EdgeInsets.only(bottom: 8),
                          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                          decoration: BoxDecoration(
                            color: const Color(0xFFE8DFC8),
                            borderRadius: BorderRadius.circular(6),
                            border: Border.all(color: const Color(0xFFD4CBB4)),
                          ),
                          child: Text(
                            input.element,
                            style: AppTextStyles.cairo(
                              fontSize: 14,
                              fontWeight: FontWeight.w700,
                              color: AppColors.olive,
                            ),
                          ),
                        );
                      }
                      return _CriterionRow(
                        index: index,
                        input: input,
                        canEdit: detail.canEdit,
                        options: _optionsFor(index),
                        percent: _rowPercent(index),
                        grade: _gradeFromPct(_rowPercent(index)),
                        phoneLayout: DeviceLayout.isPhoneWidth(context),
                        onAcquiredChanged: (v) => setState(() => _rows[index].acquired = v),
                        onNotesChanged: (v) => setState(() => _rows[index].notes = v),
                        onCapture: (video) => _pickMedia(index, video: video),
                        onPickGallery: (video) => _pickMedia(
                          index,
                          video: video,
                          source: ImageSource.gallery,
                        ),
                      );
                    },
                  ),
            footer: _FooterBar(
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
          ),
        ),
      ],
    );
  }
}

/// عرض صف التقييم مطابق لواجهة النظام (الصورة المرجعية).
class _EvalSheetCol {
  static const double index = 42;
  static const double metric = 78;
  static const double docs = 52;
  static const Color cardBorder = Color(0xFFD5CFC0);
  static const Color notesFill = Color(0xFFEFECE4);
  static const Color indexTint = Color(0xFFF7F2E6);
  static const Color selectBorder = Color(0xFFC8C2B2);
}

class _EvalSheetColumnHeaderPhone extends StatelessWidget {
  const _EvalSheetColumnHeaderPhone();

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      color: AppColors.tableHeader,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      child: Text(
        'عناصر التقييم — القصوى / المكتسبة / النسبة / النتيجة / التوثيق',
        textAlign: TextAlign.center,
        style: AppTextStyles.cairo(
          fontSize: 12,
          fontWeight: FontWeight.w700,
          color: AppColors.white,
        ),
      ),
    );
  }
}

class _EvalSheetColumnHeader extends StatelessWidget {
  const _EvalSheetColumnHeader();

  @override
  Widget build(BuildContext context) {
    TextStyle style(double size) => AppTextStyles.cairo(
          fontSize: size,
          fontWeight: FontWeight.w700,
          color: AppColors.white,
        );
    Widget metric(String label) => SizedBox(
          width: _EvalSheetCol.metric,
          child: Text(label, textAlign: TextAlign.center, style: style(11)),
        );
    return Container(
      decoration: const BoxDecoration(
        color: AppColors.tableHeader,
        boxShadow: [
          BoxShadow(color: AppColors.cardShadow, blurRadius: 3, offset: Offset(0, 1)),
        ],
      ),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 10),
      child: Row(
        children: [
          SizedBox(
            width: _EvalSheetCol.index,
            child: Text('ت', textAlign: TextAlign.center, style: style(13)),
          ),
          Expanded(
            child: Row(
              children: [
                Expanded(
                  child: Text(
                    'عناصر التقييم القيادي والعملياتي',
                    textAlign: TextAlign.center,
                    style: style(13),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                metric('العلامة القصوى'),
                metric('المكتسبة'),
                metric('النسبة'),
                metric('النتيجة'),
              ],
            ),
          ),
          SizedBox(
            width: _EvalSheetCol.docs,
            child: Text('التوثيق', textAlign: TextAlign.center, style: style(12)),
          ),
        ],
      ),
    );
  }
}

/// صف بند تقييم — شكل مطابق للصورة المرجعية دون تغيير آلية الحفظ/الاعتماد.
class _CriterionRow extends StatefulWidget {
  const _CriterionRow({
    required this.index,
    required this.input,
    required this.canEdit,
    required this.options,
    required this.percent,
    required this.grade,
    required this.onAcquiredChanged,
    required this.onNotesChanged,
    required this.onCapture,
    this.onPickGallery,
    this.phoneLayout = false,
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
  final ValueChanged<bool>? onPickGallery;
  final bool phoneLayout;

  @override
  State<_CriterionRow> createState() => _CriterionRowState();
}

class _CriterionRowState extends State<_CriterionRow> {
  late final TextEditingController _notesCtrl;

  @override
  void initState() {
    super.initState();
    _notesCtrl = TextEditingController(text: widget.input.notes);
  }

  @override
  void didUpdateWidget(covariant _CriterionRow oldWidget) {
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

  Future<void> _pickScore() async {
    if (!widget.canEdit) return;
    final selected = await showModalBottomSheet<String>(
      context: context,
      isScrollControlled: true,
      backgroundColor: AppColors.cardWhite,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (ctx) {
        return SafeArea(
          child: SizedBox(
            height: MediaQuery.of(ctx).size.height * 0.55,
            child: Column(
              children: [
                Padding(
                  padding: const EdgeInsets.all(14),
                  child: Text('اختر العلامة المكتسبة', style: AppTextStyles.subtitle),
                ),
                const Divider(height: 1),
                Expanded(
                  child: ListView.builder(
                    itemCount: widget.options.length,
                    itemBuilder: (_, i) {
                      final o = widget.options[i];
                      final active = o.value == widget.input.acquired;
                      return ListTile(
                        title: Text(o.label, textAlign: TextAlign.center),
                        selected: active,
                        onTap: () => Navigator.pop(ctx, o.value),
                      );
                    },
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
    if (selected != null) widget.onAcquiredChanged(selected);
  }

  @override
  Widget build(BuildContext context) {
    var displayAcquired = '—';
    for (final o in widget.options) {
      if (o.value == widget.input.acquired) {
        displayAcquired = o.label.isEmpty ? '—' : o.label;
        break;
      }
    }
    if (displayAcquired == '—' && widget.input.acquired.isNotEmpty) {
      displayAcquired = widget.input.acquired;
    }

    final gradeLabel = widget.grade.trim().isEmpty || widget.grade == 'غير محسوب'
        ? '—'
        : widget.grade;

    if (widget.phoneLayout) {
      return _buildPhoneCard(displayAcquired, gradeLabel);
    }
    return _buildTabletRow(displayAcquired, gradeLabel);
  }

  Widget _metricChip(String label, Widget child) {
    return Expanded(
      child: Column(
        children: [
          Text(
            label,
            style: AppTextStyles.cairo(
              fontSize: 10,
              fontWeight: FontWeight.w700,
              color: AppColors.muted,
            ),
          ),
          const SizedBox(height: 4),
          child,
        ],
      ),
    );
  }

  Widget _buildPhoneCard(String displayAcquired, String gradeLabel) {
    return Container(
      margin: const EdgeInsets.only(bottom: 6),
      padding: const EdgeInsets.fromLTRB(8, 8, 8, 8),
      decoration: BoxDecoration(
        color: AppColors.cardWhite,
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: _EvalSheetCol.cardBorder),
        boxShadow: const [
          BoxShadow(
            color: Color(0x14000000),
            blurRadius: 3,
            offset: Offset(0, 1),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 28,
                height: 28,
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  color: _EvalSheetCol.indexTint,
                  borderRadius: BorderRadius.circular(6),
                  border: Border.all(color: _EvalSheetCol.cardBorder),
                ),
                child: Text(
                  '${widget.index + 1}',
                  style: AppTextStyles.cairo(
                    fontSize: 13,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  widget.input.element,
                  style: AppTextStyles.cairo(
                    fontSize: 13,
                    fontWeight: FontWeight.w500,
                    height: 1.35,
                  ),
                ),
              ),
              Column(
                children: [
                  _DocBtn(
                    icon: Icons.camera_alt_outlined,
                    enabled: widget.canEdit,
                    onTap: () => widget.onCapture(false),
                  ),
                  const SizedBox(height: 4),
                  _DocBtn(
                    icon: Icons.photo_library_outlined,
                    enabled: widget.canEdit && widget.onPickGallery != null,
                    onTap: () => widget.onPickGallery?.call(false),
                  ),
                  const SizedBox(height: 4),
                  _DocBtn(
                    icon: Icons.videocam_outlined,
                    enabled: widget.canEdit,
                    onTap: () => widget.onCapture(true),
                  ),
                  const SizedBox(height: 4),
                  _DocBtn(
                    icon: Icons.video_library_outlined,
                    enabled: widget.canEdit && widget.onPickGallery != null,
                    onTap: () => widget.onPickGallery?.call(true),
                  ),
                ],
              ),
            ],
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              _metricChip(
                'القصوى',
                Text(
                  widget.input.maxVal.isEmpty ? '—' : widget.input.maxVal,
                  style: AppTextStyles.cairo(
                    fontSize: 15,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ),
              _metricChip(
                'المكتسبة',
                Material(
                  color: AppColors.cardWhite,
                  borderRadius: BorderRadius.circular(6),
                  child: InkWell(
                    borderRadius: BorderRadius.circular(6),
                    onTap: widget.canEdit ? _pickScore : null,
                    child: Container(
                      width: double.infinity,
                      padding: const EdgeInsets.symmetric(vertical: 6),
                      decoration: BoxDecoration(
                        borderRadius: BorderRadius.circular(6),
                        border: Border.all(color: _EvalSheetCol.selectBorder),
                      ),
                      child: Row(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Text(
                            displayAcquired,
                            style: AppTextStyles.cairo(
                              fontSize: 13,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                          if (widget.canEdit)
                            const Icon(
                              Icons.keyboard_arrow_down,
                              size: 16,
                              color: AppColors.muted,
                            ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
              _metricChip(
                'النسبة',
                Text(
                  widget.percent == null ? '—' : '${widget.percent!.round()}%',
                  style: AppTextStyles.cairo(
                    fontSize: 13,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
              _metricChip(
                'النتيجة',
                Container(
                  padding:
                      const EdgeInsets.symmetric(vertical: 4, horizontal: 8),
                  decoration: BoxDecoration(
                    color: AppColors.resultBlueBg,
                    borderRadius: BorderRadius.circular(14),
                  ),
                  child: Text(
                    gradeLabel,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: AppTextStyles.cairo(
                      fontSize: 11,
                      color: AppColors.resultBlue,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          TextField(
            controller: _notesCtrl,
            enabled: widget.canEdit,
            minLines: 1,
            maxLines: 2,
            style: AppTextStyles.cairo(fontSize: 12.5),
            decoration: InputDecoration(
              hintText: 'اكتب ملاحظاتك هنا (اختياري)',
              hintStyle: AppTextStyles.cairo(
                fontSize: 12.5,
                color: AppColors.muted,
              ),
              filled: true,
              fillColor: _EvalSheetCol.notesFill,
              isDense: true,
              contentPadding: const EdgeInsets.symmetric(
                horizontal: 12,
                vertical: 10,
              ),
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(6),
                borderSide: BorderSide.none,
              ),
              enabledBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(6),
                borderSide: BorderSide.none,
              ),
              disabledBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(6),
                borderSide: BorderSide.none,
              ),
              focusedBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(6),
                borderSide: const BorderSide(
                  color: AppColors.goldBorder,
                  width: 1,
                ),
              ),
            ),
            onChanged: widget.onNotesChanged,
          ),
        ],
      ),
    );
  }

  Widget _buildTabletRow(String displayAcquired, String gradeLabel) {
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      decoration: BoxDecoration(
        color: AppColors.cardWhite,
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: _EvalSheetCol.cardBorder),
        boxShadow: const [
          BoxShadow(
            color: Color(0x14000000),
            blurRadius: 3,
            offset: Offset(0, 1),
          ),
        ],
      ),
      child: IntrinsicHeight(
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // ت
            Container(
              width: _EvalSheetCol.index,
              alignment: Alignment.topCenter,
              padding: const EdgeInsets.only(top: 14),
              decoration: const BoxDecoration(
                color: _EvalSheetCol.indexTint,
                border: Border(
                  left: BorderSide(color: _EvalSheetCol.cardBorder),
                ),
              ),
              child: Text(
                '${widget.index + 1}',
                textAlign: TextAlign.center,
                style: AppTextStyles.cairo(
                  fontSize: 14,
                  fontWeight: FontWeight.w800,
                  color: AppColors.darkText,
                ),
              ),
            ),
            // عنصر + مقاييس + ملاحظات تحتها بعرض المنطقة الوسطى
            Expanded(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(10, 10, 8, 10),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.center,
                      children: [
                        Expanded(
                          child: Text(
                            widget.input.element,
                            style: AppTextStyles.cairo(
                              fontSize: 13.5,
                              fontWeight: FontWeight.w500,
                              height: 1.35,
                            ),
                          ),
                        ),
                        SizedBox(
                          width: _EvalSheetCol.metric,
                          child: Text(
                            widget.input.maxVal.isEmpty ? '—' : widget.input.maxVal,
                            textAlign: TextAlign.center,
                            style: AppTextStyles.cairo(
                              fontSize: 16,
                              fontWeight: FontWeight.w800,
                            ),
                          ),
                        ),
                        SizedBox(
                          width: _EvalSheetCol.metric,
                          child: Padding(
                            padding: const EdgeInsets.symmetric(horizontal: 4),
                            child: Material(
                              color: AppColors.cardWhite,
                              borderRadius: BorderRadius.circular(6),
                              child: InkWell(
                                borderRadius: BorderRadius.circular(6),
                                onTap: widget.canEdit ? _pickScore : null,
                                child: Container(
                                  padding: const EdgeInsets.symmetric(
                                    vertical: 7,
                                    horizontal: 6,
                                  ),
                                  decoration: BoxDecoration(
                                    borderRadius: BorderRadius.circular(6),
                                    border: Border.all(
                                      color: _EvalSheetCol.selectBorder,
                                    ),
                                  ),
                                  child: Row(
                                    mainAxisAlignment: MainAxisAlignment.center,
                                    children: [
                                      Flexible(
                                        child: Text(
                                          displayAcquired,
                                          textAlign: TextAlign.center,
                                          style: AppTextStyles.cairo(
                                            fontSize: 14,
                                            fontWeight: FontWeight.w600,
                                          ),
                                          overflow: TextOverflow.ellipsis,
                                        ),
                                      ),
                                      if (widget.canEdit)
                                        const Icon(
                                          Icons.keyboard_arrow_down,
                                          size: 18,
                                          color: AppColors.muted,
                                        ),
                                    ],
                                  ),
                                ),
                              ),
                            ),
                          ),
                        ),
                        SizedBox(
                          width: _EvalSheetCol.metric,
                          child: Text(
                            widget.percent == null
                                ? '—'
                                : '${widget.percent!.round()}%',
                            textAlign: TextAlign.center,
                            style: AppTextStyles.cairo(
                              fontSize: 14,
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                        ),
                        SizedBox(
                          width: _EvalSheetCol.metric,
                          child: Center(
                            child: Container(
                              padding: const EdgeInsets.symmetric(
                                vertical: 5,
                                horizontal: 10,
                              ),
                              decoration: BoxDecoration(
                                color: AppColors.resultBlueBg,
                                borderRadius: BorderRadius.circular(14),
                              ),
                              child: Text(
                                gradeLabel,
                                textAlign: TextAlign.center,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: AppTextStyles.cairo(
                                  fontSize: 12,
                                  color: AppColors.resultBlue,
                                  fontWeight: FontWeight.w700,
                                ),
                              ),
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 8),
                    TextField(
                      controller: _notesCtrl,
                      enabled: widget.canEdit,
                      minLines: 1,
                      maxLines: 2,
                      style: AppTextStyles.cairo(fontSize: 12.5),
                      decoration: InputDecoration(
                        hintText: 'اكتب ملاحظاتك هنا (اختياري)',
                        hintStyle: AppTextStyles.cairo(
                          fontSize: 12.5,
                          color: AppColors.muted,
                        ),
                        filled: true,
                        fillColor: _EvalSheetCol.notesFill,
                        isDense: true,
                        contentPadding: const EdgeInsets.symmetric(
                          horizontal: 12,
                          vertical: 10,
                        ),
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(6),
                          borderSide: BorderSide.none,
                        ),
                        enabledBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(6),
                          borderSide: BorderSide.none,
                        ),
                        disabledBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(6),
                          borderSide: BorderSide.none,
                        ),
                        focusedBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(6),
                          borderSide: const BorderSide(
                            color: AppColors.goldBorder,
                            width: 1,
                          ),
                        ),
                      ),
                      onChanged: widget.onNotesChanged,
                    ),
                  ],
                ),
              ),
            ),
            // التوثيق — أزرار عمودية كما في الصورة
            Container(
              width: _EvalSheetCol.docs,
              alignment: Alignment.center,
              padding: const EdgeInsets.symmetric(vertical: 8),
              decoration: const BoxDecoration(
                border: Border(
                  right: BorderSide(color: _EvalSheetCol.cardBorder),
                ),
              ),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  _DocBtn(
                    icon: Icons.camera_alt_outlined,
                    enabled: widget.canEdit,
                    onTap: () => widget.onCapture(false),
                  ),
                  const SizedBox(height: 4),
                  _DocBtn(
                    icon: Icons.photo_library_outlined,
                    enabled: widget.canEdit && widget.onPickGallery != null,
                    onTap: () => widget.onPickGallery?.call(false),
                  ),
                  const SizedBox(height: 4),
                  _DocBtn(
                    icon: Icons.videocam_outlined,
                    enabled: widget.canEdit,
                    onTap: () => widget.onCapture(true),
                  ),
                  const SizedBox(height: 4),
                  _DocBtn(
                    icon: Icons.video_library_outlined,
                    enabled: widget.canEdit && widget.onPickGallery != null,
                    onTap: () => widget.onPickGallery?.call(true),
                  ),
                  if (widget.input.localMediaPaths.isNotEmpty) ...[
                    const SizedBox(height: 4),
                    Text(
                      '${widget.input.localMediaPaths.length}',
                      style: AppTextStyles.cairo(
                        fontSize: 10,
                        fontWeight: FontWeight.w700,
                        color: AppColors.goldDark,
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _DocBtn extends StatelessWidget {
  const _DocBtn({
    required this.icon,
    required this.onTap,
    this.enabled = true,
  });
  final IconData icon;
  final VoidCallback onTap;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    return Opacity(
      opacity: enabled ? 1 : 0.45,
      child: InkWell(
        onTap: enabled ? onTap : null,
        borderRadius: BorderRadius.circular(7),
        child: Container(
          width: 34,
          height: 34,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: AppColors.cardWhite,
            borderRadius: BorderRadius.circular(7),
            border: Border.all(color: AppColors.goldDark, width: 1.2),
          ),
          child: Icon(icon, size: 17, color: AppColors.goldDark),
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
    return StickyFooterBar(
      left: Wrap(
        spacing: 8,
        runSpacing: 8,
        children: [
          _StatBox(label: 'مجموع العلامات القصوى', value: sumMax > 0 ? '${sumMax.round()}' : '—'),
          _StatBox(label: 'العلامات المكتسبة', value: sumAcq == null ? '—' : '${sumAcq!.round()}'),
          _StatBox(label: 'النسبة المئوية النهائية', value: totalPct == null ? '—' : '${totalPct!.round()}%'),
          _StatBox(
            label: 'النتيجة النهائية',
            value: totalGrade == 'غير محسوب' ? '—' : totalGrade,
            emphasize: true,
          ),
        ],
      ),
      right: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.min,
        children: [
          if (hint != null)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Text(
                hint!,
                style: AppTextStyles.cairo(
                  fontSize: 12,
                  color: AppColors.doneGreen,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
          if (canEdit)
            ElevatedButton.icon(
              style: ElevatedButton.styleFrom(
                backgroundColor: AppColors.buttonBrown,
                foregroundColor: AppColors.white,
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
              ),
              onPressed: saving ? null : onSave,
              icon: saving
                  ? const SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                    )
                  : const Icon(Icons.save_outlined, size: 18),
              label: const Text('حفظ نتائج التقييم النهائي'),
            ),
          if (alreadyApproved && !canEdit)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                hint?.contains('بانتظار') == true
                    ? 'معتمد محلياً – بانتظار المزامنة'
                    : 'معتمد',
                style: AppTextStyles.small,
                textAlign: TextAlign.center,
              ),
            ),
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
                  ? const SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                    )
                  : const Icon(Icons.check_circle_outline, size: 18),
              label: const Text('اعتماد نتائج التقييم النهائي'),
            ),
          ],
        ],
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
