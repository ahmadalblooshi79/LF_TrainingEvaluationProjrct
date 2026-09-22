import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:image_picker/image_picker.dart';

import '../models/eval_sheet.dart';
import '../models/eval_sheet_scoring.dart';
import '../services/api_client.dart';
import '../services/auth_service.dart';
import '../services/signature_store.dart';
import '../services/tablet_repository.dart';
import '../theme/app_theme.dart';
import '../theme/device_layout.dart';
import '../theme/grade_style.dart';
import '../widgets/async_state_views.dart';
import '../widgets/sticky_eval_scaffold.dart';
import 'media_preview_backend.dart';
import 'media_preview_screen.dart';

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

class _EvalSheetScreenState extends State<EvalSheetScreen> {
  EvalSheetDetail? _detail;
  List<EvalRowInput> _rows = [];
  bool _loading = true;
  bool _fromCache = false;
  String? _error;
  bool _saving = false;
  bool _approving = false;
  bool _savedThisSession = false;
  String? _hint;
  bool _hintIsError = false;
  final _dilemmaDescCtrl = TextEditingController();
  final _dilemmaReqCtrl = TextEditingController();

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _dilemmaDescCtrl.dispose();
    _dilemmaReqCtrl.dispose();
    super.dispose();
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
      final sheetKey = widget.mode == EvalSheetMode.actionEval
          ? 'action_eval_detail:${widget.slot}'
          : 'evaluation_list_detail:${widget.unitKey}:${widget.itemId}';
      await TabletRepository.instance.overlayLocalMediaOnRows(
        sheetCacheKey: sheetKey,
        rows: rows,
      );
      if (!mounted) return;
      setState(() {
        _detail = result.data;
        _rows = rows;
        _fromCache = result.fromCache;
        _savedThisSession = result.data.canApprove;
        _dilemmaDescCtrl.text = result.data.dilemmaDescription;
        _dilemmaReqCtrl.text = result.data.dilemmaRequirements;
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

  double? _templateMax(int index) {
    final rows = _detail?.evalRows ?? const [];
    if (index < 0 || index >= rows.length) return null;
    final m = rows[index].maxNum;
    return (m != null && m.isFinite && m > 0) ? m : null;
  }

  double? _rowPercent(int index) {
    if (index < 0 || index >= _rows.length) return null;
    return rowPercent(input: _rows[index], templateMax: _templateMax(index));
  }

  ({double sumMax, double sumAcq, bool anyAcq}) _totalsRaw() {
    return evalSheetTotals(rows: _rows, templateMax: _templateMax);
  }

  double? get _totalPct {
    final t = _totalsRaw();
    if (t.sumMax <= 0 || !t.anyAcq) return null;
    return (t.sumAcq / t.sumMax) * 100;
  }

  List<int> get _emptyAcquiredIndexes => [
        for (var i = 0; i < _rows.length; i++)
          if (_rows[i].rowKind != 'section' && _rows[i].acquired.trim().isEmpty) i,
      ];

  List<int> get _rowsMissingRequiredNotes => rowsMissingRequiredNotes(
        rows: _rows,
        percentOf: _rowPercent,
      );

  bool get _canApproveNow {
    final detail = _detail;
    if (detail == null || detail.isApproved) return false;
    // بعد الحفظ المحلي يُفعَّل الاعتماد حتى لو السيرفر لم يُعلّم can_approve بعد
    if (!detail.canEdit && !detail.canApprove && !_savedThisSession) return false;
    if (!_savedThisSession) return false;
    if (_emptyAcquiredIndexes.isNotEmpty) return false;
    if (_rowsMissingRequiredNotes.isNotEmpty) return false;
    final grade = gradeFromPct(_totalPct);
    return grade.isNotEmpty && grade != 'غير محسوب';
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
      final slot = docSlotFor(
        video: video,
        fromGallery: source == ImageSource.gallery,
      );
      final localPath = await TabletRepository.instance.queueCriterionMedia(
        sourcePath: file.path,
        rowIndex: index,
        mediaKind: video ? 'video' : 'photo',
        sheetCacheKey: sheetKey,
        docSlot: slot,
        evaluationListItemId:
            widget.mode == EvalSheetMode.evaluationList ? detail.itemId : null,
        bundleActionEvalId:
            widget.mode == EvalSheetMode.actionEval ? detail.slotId : null,
      );
      if (!mounted) return;
      setState(() {
        _rows[index].addMedia(slot, localPath);
        _hint = 'حُفظت الوسائط محلياً — ستُرفع عند رفع أعمالي';
      });
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('$e')),
      );
    }
  }

  Future<void> _removeDoc(int index, String path) async {
    if (index < 0 || index >= _rows.length) return;
    if (path.isEmpty) return;
    final sheetKey = widget.mode == EvalSheetMode.actionEval
        ? 'action_eval_detail:${widget.slot}'
        : 'evaluation_list_detail:${widget.unitKey}:${widget.itemId}';
    try {
      await TabletRepository.instance.removeLastCriterionMedia(
        sheetCacheKey: sheetKey,
        rowIndex: index,
        localPath: path,
      );
      if (!mounted) return;
      setState(() {
        _rows[index].removeMediaPath(path);
      });
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('$e')),
      );
    }
  }

  void _previewDoc(int index, String path, {required bool isVideo}) {
    if (index < 0 || index >= _rows.length) return;
    if (path.isEmpty) return;
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => MediaPreviewScreen(
          path: path,
          isVideo: isVideo,
          title: isVideo ? 'معاينة الفيديو' : 'معاينة الصورة',
        ),
      ),
    );
  }

  Future<void> _save() async {
    final detail = _detail;
    if (detail == null || _saving || !detail.canEdit) return;
    if (_rowsMissingRequiredNotes.isNotEmpty) {
      setState(() {
        _hint =
            'لا يمكن الحفظ: أدخل ملاحظات في الصفوف ذات النتيجة راسب أو مقبول.';
        _hintIsError = true;
      });
      return;
    }
    setState(() {
      _saving = true;
      _hint = null;
      _hintIsError = false;
    });
    try {
      await (widget.mode == EvalSheetMode.actionEval
          ? TabletRepository.instance.saveActionEvalResults(
              widget.slot!,
              _rows,
              dilemmaDescription: _dilemmaDescCtrl.text,
              dilemmaRequirements: _dilemmaReqCtrl.text,
            )
          : TabletRepository.instance.saveEvaluationListResults(
              widget.unitKey!,
              widget.itemId!,
              _rows,
              dilemmaDescription: _dilemmaDescCtrl.text,
              dilemmaRequirements: _dilemmaReqCtrl.text,
            ));
      if (!mounted) return;
      setState(() {
        _saving = false;
        _savedThisSession = true;
        final d = _detail;
        if (d != null && !d.isApproved) {
          _detail = d.copyWith(
            savedRows: List<EvalRowInput>.from(_rows),
            canEdit: true,
            canApprove: true,
            isApproved: false,
            dilemmaDescription: _dilemmaDescCtrl.text,
            dilemmaRequirements: _dilemmaReqCtrl.text,
          );
        }
        _hint = 'تم الحفظ';
        _hintIsError = false;
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _hint = e.message;
        _hintIsError = true;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _hint = 'تعذّر الحفظ: $e';
        _hintIsError = true;
      });
    }
  }

  Future<void> _approve() async {
    final detail = _detail;
    if (detail == null || _approving || !_canApproveNow) return;
    final uid = AuthService.instance.currentUserId;
    if (uid == null || uid <= 0) {
      setState(() => _hint = 'تعذّر التحقق من الحساب الحالي.');
      return;
    }
    final rec = await SignatureStore.instance.loadForUser(uid);
    if (!mounted) return;
    if (rec == null || !rec.isRegistered || rec.userId != uid || rec.pngB64.isEmpty) {
      await showDialog<void>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: const Text('لا يوجد توقيع إلكتروني'),
          content: const Text(
            'لا يوجد توقيع إلكتروني مسجل لهذا الحساب.\nيرجى تسجيل التوقيع قبل اعتماد القائمة.',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('إلغاء'),
            ),
            ElevatedButton(
              onPressed: () {
                Navigator.pop(ctx);
                context.push('/signature');
              },
              child: const Text('تسجيل التوقيع'),
            ),
          ],
        ),
      );
      return;
    }
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('اعتماد وتوقيع قائمة التقييم'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('المحكم: ${AuthService.instance.session?.user.judgeDisplayName ?? '—'}'),
            Text('الوحدة: ${detail.unitLabel}'),
            Text('اسم القائمة: ${detail.title}'),
            const SizedBox(height: 12),
            const Text(
              'أقر بأنني راجعت نتائج التقييم وأعتمد البيانات الواردة في هذه القائمة.',
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('إلغاء'),
          ),
          ElevatedButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('توقيع واعتماد'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    final recAgain = await SignatureStore.instance.loadForUser(uid);
    if (!mounted) return;
    if (recAgain == null ||
        recAgain.userId != uid ||
        !recAgain.isRegistered ||
        recAgain.pngB64.isEmpty) {
      setState(() => _hint = 'تعذّر الاعتماد: التوقيع لا يخص الحساب الحالي.');
      return;
    }

    setState(() {
      _approving = true;
      _hint = null;
    });
    try {
      if (detail.canEdit) {
        await (widget.mode == EvalSheetMode.actionEval
            ? TabletRepository.instance.saveActionEvalResults(
                widget.slot!,
                _rows,
                dilemmaDescription: _dilemmaDescCtrl.text,
                dilemmaRequirements: _dilemmaReqCtrl.text,
              )
            : TabletRepository.instance.saveEvaluationListResults(
                widget.unitKey!,
                widget.itemId!,
                _rows,
                dilemmaDescription: _dilemmaDescCtrl.text,
                dilemmaRequirements: _dilemmaReqCtrl.text,
              ));
      }
      final grade = gradeFromPct(_totalPct);
      await (widget.mode == EvalSheetMode.actionEval
          ? TabletRepository.instance.approveActionEval(
              widget.slot!,
              gradeLabel: grade == 'غير محسوب' ? null : grade,
              signatureUserId: uid,
              signatureVersion: recAgain.version,
              signaturePngB64: recAgain.pngB64,
            )
          : TabletRepository.instance.approveEvaluationList(
              widget.unitKey!,
              widget.itemId!,
              gradeLabel: grade == 'غير محسوب' ? null : grade,
              signatureUserId: uid,
              signatureVersion: recAgain.version,
              signaturePngB64: recAgain.pngB64,
            ));
      if (!mounted) return;
      setState(() {
        _approving = false;
        _hint = null;
        _detail = detail.copyWith(
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
          approvalSignaturePng: recAgain.pngBytes,
          approvalSignatureVersion: recAgain.version,
          approvalSignatureAt: DateTime.now().toIso8601String(),
          approvalSignatureUserId: uid,
          dilemmaDescription: _dilemmaDescCtrl.text,
          dilemmaRequirements: _dilemmaReqCtrl.text,
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
    final sheetTitle =
        _detail?.title.isNotEmpty == true ? _detail!.title : (widget.fallbackTitle ?? 'ورقة التقييم');

    return Scaffold(
      backgroundColor: AppColors.background,
      body: SafeArea(
        child: _loading
            ? Column(
                children: [
                  const Expanded(child: LoadingView()),
                  _EvalSheetCloseButton(onPressed: () => Navigator.of(context).maybePop()),
                ],
              )
            : _error != null
                ? Column(
                    children: [
                      Expanded(child: ErrorView(message: _error!, onRetry: _load)),
                      _EvalSheetCloseButton(onPressed: () => Navigator.of(context).maybePop()),
                    ],
                  )
                : _buildBody(sheetTitle),
      ),
    );
  }

  Widget _buildBody(String sheetTitle) {
    final detail = _detail;
    if (detail == null) {
      return Column(
        children: [
          const Expanded(child: EmptyView(message: 'لا توجد بيانات')),
          _EvalSheetCloseButton(onPressed: () => Navigator.of(context).maybePop()),
        ],
      );
    }
    if (!detail.evalStructured || detail.evalRows.isEmpty) {
      return Column(
        children: [
          if (_fromCache) const CachedDataBanner(),
          Expanded(
            child: EmptyView(
              message: detail.evalRows.isEmpty ? 'لا توجد بنود تقييم في هذا الملف' : 'تعذّر قراءة قالب التقييم',
            ),
          ),
          _EvalSheetCloseButton(onPressed: () => Navigator.of(context).maybePop()),
        ],
      );
    }

    if (_rows.isEmpty && detail.evalRows.isNotEmpty) {
      // Safety: template parsed but editable buffer empty — refill once.
      _rows = _rowsFromDetail(detail);
    }

    final totals = _totalsRaw();
    final pct = _totalPct;
    final grade = gradeFromPct(pct);

    return Column(
      children: [
        if (_fromCache) const CachedDataBanner(),
        Container(
          width: double.infinity,
          color: AppColors.titleBar,
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
          child: Column(
            children: [
              Text(
                detail.evalDocTitle.isNotEmpty ? detail.evalDocTitle : sheetTitle,
                textAlign: TextAlign.center,
                style: AppTextStyles.cairo(fontSize: 15, fontWeight: FontWeight.w800, color: AppColors.olive),
              ),
              if (detail.evalDocSubtitle.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Text(
                    detail.evalDocSubtitle,
                    textAlign: TextAlign.center,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: AppTextStyles.cairo(
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      color: AppColors.olive,
                    ),
                  ),
                ),
            ],
          ),
        ),
        _EvalNarrativeBlock(
          descCtrl: _dilemmaDescCtrl,
          reqCtrl: _dilemmaReqCtrl,
          canEdit: detail.canEdit,
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
                    itemCount: _rows.length +
                        (detail.isApproved && detail.approvalSignaturePng != null ? 1 : 0),
                    itemBuilder: (context, index) {
                      if (index >= _rows.length) {
                        return _JudgeEsignBlock(detail: detail);
                      }
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
                        grade: gradeFromPct(_rowPercent(index)),
                        notesRequired: _rowsMissingRequiredNotes.contains(index),
                        phoneLayout: DeviceLayout.isPhoneWidth(context),
                        onAcquiredChanged: (v) => setState(() => _rows[index].acquired = v),
                        onNotesChanged: (v) => setState(() => _rows[index].notes = v),
                        onCapture: (video) => _pickMedia(index, video: video),
                        onPickGallery: (video) => _pickMedia(
                          index,
                          video: video,
                          source: ImageSource.gallery,
                        ),
                        onRemoveDoc: detail.canEdit
                            ? (path) => _removeDoc(index, path)
                            : null,
                        onPreviewDoc: (path, isVideo) =>
                            _previewDoc(index, path, isVideo: isVideo),
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
              savedThisSession: _savedThisSession,
              alreadyApproved: detail.isApproved,
              saving: _saving,
              approving: _approving,
              hint: _hint,
              hintIsError: _hintIsError,
              blockMessage: _rowsMissingRequiredNotes.isEmpty
                  ? null
                  : 'لا يمكن اعتماد نتائج التقييم النهائي إلا بعد إدخال ملاحظات في الصفوف ذات النتيجة راسب أو مقبول.',
              onSave: _save,
              onApprove: _approve,
              onClose: () => Navigator.of(context).maybePop(),
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
  static const double docs = 168;
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
    this.onRemoveDoc,
    this.onPreviewDoc,
    this.phoneLayout = false,
    this.notesRequired = false,
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
  final ValueChanged<String>? onRemoveDoc;
  final void Function(String path, bool isVideo)? onPreviewDoc;
  final bool phoneLayout;
  final bool notesRequired;

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

  InputDecoration get _notesDecoration {
    final requiredNotes = widget.notesRequired;
    final side = requiredNotes
        ? const BorderSide(color: Color(0xFFB42318), width: 1.4)
        : BorderSide.none;
    return InputDecoration(
      hintText: requiredNotes
          ? 'ملاحظات إلزامية للنتيجة راسب أو مقبول'
          : 'اكتب ملاحظاتك هنا (اختياري)',
      hintStyle: AppTextStyles.cairo(
        fontSize: 12.5,
        color: requiredNotes ? const Color(0xFFB42318) : AppColors.muted,
      ),
      filled: true,
      fillColor: requiredNotes ? const Color(0xFFFDECEC) : _EvalSheetCol.notesFill,
      isDense: true,
      contentPadding: const EdgeInsets.symmetric(
        horizontal: 12,
        vertical: 10,
      ),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(6),
        borderSide: side,
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(6),
        borderSide: side,
      ),
      disabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(6),
        borderSide: side,
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(6),
        borderSide: BorderSide(
          color: requiredNotes ? const Color(0xFFB42318) : AppColors.goldBorder,
          width: 1.4,
        ),
      ),
    );
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

    final gradeStyle = GradeStyle.forLabel(gradeLabel);

    if (widget.phoneLayout) {
      return _buildPhoneCard(displayAcquired, gradeLabel, gradeStyle);
    }
    return _buildTabletRow(displayAcquired, gradeLabel, gradeStyle);
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

  Widget _buildPhoneCard(
    String displayAcquired,
    String gradeLabel,
    ({Color fg, Color bg}) gradeStyle,
  ) {
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
              _DocActionsColumn(
                input: widget.input,
                canEdit: widget.canEdit,
                onCapture: widget.onCapture,
                onPickGallery: widget.onPickGallery,
                onRemoveDoc: widget.onRemoveDoc,
                onPreviewDoc: widget.onPreviewDoc,
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
                    color: gradeStyle.bg,
                    borderRadius: BorderRadius.circular(14),
                  ),
                  child: Text(
                    gradeLabel,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: AppTextStyles.cairo(
                      fontSize: 11,
                      color: gradeStyle.fg,
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
            decoration: _notesDecoration,
            onChanged: widget.onNotesChanged,
          ),
        ],
      ),
    );
  }

  Widget _buildTabletRow(
    String displayAcquired,
    String gradeLabel,
    ({Color fg, Color bg}) gradeStyle,
  ) {
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
                                color: gradeStyle.bg,
                                borderRadius: BorderRadius.circular(14),
                              ),
                              child: Text(
                                gradeLabel,
                                textAlign: TextAlign.center,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: AppTextStyles.cairo(
                                  fontSize: 12,
                                  color: gradeStyle.fg,
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
                      decoration: _notesDecoration,
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
              child: _DocActionsColumn(
                input: widget.input,
                canEdit: widget.canEdit,
                onCapture: widget.onCapture,
                onPickGallery: widget.onPickGallery,
                onRemoveDoc: widget.onRemoveDoc,
                onPreviewDoc: widget.onPreviewDoc,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _DocActionsColumn extends StatelessWidget {
  const _DocActionsColumn({
    required this.input,
    required this.canEdit,
    required this.onCapture,
    this.onPickGallery,
    this.onRemoveDoc,
    this.onPreviewDoc,
  });

  final EvalRowInput input;
  final bool canEdit;
  final ValueChanged<bool> onCapture;
  final ValueChanged<bool>? onPickGallery;
  final ValueChanged<String>? onRemoveDoc;
  final void Function(String path, bool isVideo)? onPreviewDoc;

  static bool _isVideoSlot(String slot) =>
      slot == kDocSlotCameraVideo || slot == kDocSlotGalleryVideo;

  Widget _addBtn({
    required IconData icon,
    required VoidCallback onAdd,
    required bool addEnabled,
  }) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 4, left: 4),
      child: _DocBtn(
        icon: icon,
        enabled: addEnabled,
        onTap: onAdd,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final items = <({String slot, String path, bool video})>[];
    input.mediaBySlot.forEach((slot, paths) {
      for (final path in paths) {
        if (path.isEmpty) continue;
        items.add((slot: slot, path: path, video: _isVideoSlot(slot)));
      }
    });
    return Column(
      mainAxisAlignment: MainAxisAlignment.center,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Wrap(
          children: [
            _addBtn(
              icon: Icons.camera_alt_outlined,
              addEnabled: canEdit,
              onAdd: () => onCapture(false),
            ),
            _addBtn(
              icon: Icons.photo_library_outlined,
              addEnabled: canEdit && onPickGallery != null,
              onAdd: () => onPickGallery?.call(false),
            ),
            _addBtn(
              icon: Icons.videocam_outlined,
              addEnabled: canEdit,
              onAdd: () => onCapture(true),
            ),
            _addBtn(
              icon: Icons.video_library_outlined,
              addEnabled: canEdit && onPickGallery != null,
              onAdd: () => onPickGallery?.call(true),
            ),
          ],
        ),
        if (items.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Wrap(
              spacing: 4,
              runSpacing: 4,
              children: [
                for (final item in items)
                  Container(
                    width: 72,
                    padding: const EdgeInsets.all(3),
                    decoration: BoxDecoration(
                      color: AppColors.cardWhite,
                      borderRadius: BorderRadius.circular(6),
                      border: Border.all(color: AppColors.goldDark, width: 1),
                    ),
                    child: Column(
                      children: [
                        ClipRRect(
                          borderRadius: BorderRadius.circular(3),
                          child: SizedBox(
                            width: 64,
                            height: 48,
                            child: buildMediaThumb(
                              path: item.path,
                              isVideo: item.video,
                              size: 48,
                            ),
                          ),
                        ),
                        const SizedBox(height: 2),
                        Row(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            _DocBtn(
                              icon: Icons.visibility_outlined,
                              enabled: true,
                              onTap: () =>
                                  onPreviewDoc?.call(item.path, item.video),
                            ),
                            const SizedBox(width: 2),
                            _DocBtn(
                              icon: Icons.close,
                              enabled: canEdit && onRemoveDoc != null,
                              onTap: () => onRemoveDoc?.call(item.path),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
              ],
            ),
          ),
      ],
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

class _JudgeEsignBlock extends StatelessWidget {
  const _JudgeEsignBlock({required this.detail});

  final EvalSheetDetail detail;

  @override
  Widget build(BuildContext context) {
    final png = detail.approvalSignaturePng;
    if (png == null) return const SizedBox.shrink();
    String date = '—';
    String time = '—';
    final raw = detail.approvalSignatureAt ?? '';
    final parsed = DateTime.tryParse(raw);
    if (parsed != null) {
      final local = parsed.toLocal();
      date =
          '${local.day.toString().padLeft(2, '0')}/${local.month.toString().padLeft(2, '0')}/${local.year}';
      time =
          '${local.hour.toString().padLeft(2, '0')}:${local.minute.toString().padLeft(2, '0')}';
    }
    return Padding(
      padding: const EdgeInsets.fromLTRB(8, 16, 8, 24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text('المحكم: ${AuthService.instance.session?.user.judgeDisplayName ?? '—'}'),
          Text('الوحدة: ${detail.unitLabel}'),
          const SizedBox(height: 6),
          const Text('التوقيع:'),
          Align(
            alignment: Alignment.centerRight,
            child: ColoredBox(
              color: Colors.transparent,
              child: Image.memory(
                png,
                height: 72,
                fit: BoxFit.contain,
                filterQuality: FilterQuality.high,
              ),
            ),
          ),
          Text('تاريخ الاعتماد: $date'),
          Text('الوقت: $time'),
          Text(
            'حالة القائمة: معتمدة إلكترونياً',
            style: AppTextStyles.cairo(
              fontWeight: FontWeight.w700,
              color: AppColors.doneGreen,
            ),
          ),
        ],
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
    required this.savedThisSession,
    required this.alreadyApproved,
    required this.saving,
    required this.approving,
    required this.hint,
    required this.hintIsError,
    this.blockMessage,
    required this.onSave,
    required this.onApprove,
    required this.onClose,
  });

  final double sumMax;
  final double? sumAcq;
  final double? totalPct;
  final String totalGrade;
  final bool canEdit;
  final bool canApprove;
  final bool savedThisSession;
  final bool alreadyApproved;
  final bool saving;
  final bool approving;
  final String? hint;
  final bool hintIsError;
  final String? blockMessage;
  final VoidCallback onSave;
  final VoidCallback onApprove;
  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) {
    final gradeStyle = GradeStyle.forLabel(
      totalGrade == 'غير محسوب' ? '' : totalGrade,
    );
    final approveEnabled = savedThisSession && canApprove && !approving;

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
            fg: gradeStyle.fg,
            bg: gradeStyle.bg,
          ),
        ],
      ),
      right: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.min,
        children: [
          if (blockMessage != null && canEdit)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Text(
                blockMessage!,
                style: AppTextStyles.cairo(
                  fontSize: 12,
                  color: const Color(0xFFB42318),
                  fontWeight: FontWeight.w700,
                ),
                textAlign: TextAlign.center,
              ),
            ),
          if (hint != null && canEdit && hint != blockMessage)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Text(
                hint!,
                style: AppTextStyles.cairo(
                  fontSize: 12,
                  color: hintIsError ? const Color(0xFFB42318) : AppColors.doneGreen,
                  fontWeight: FontWeight.w600,
                ),
                textAlign: TextAlign.center,
              ),
            ),
          if (canEdit)
            LayoutBuilder(
              builder: (context, constraints) {
                final sideBySide = constraints.maxWidth >= 420;
                final saveBtn = ElevatedButton.icon(
                  style: ElevatedButton.styleFrom(
                    backgroundColor: AppColors.buttonBrown,
                    foregroundColor: AppColors.white,
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 12),
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
                );
                final approveBtn = ElevatedButton.icon(
                  style: ElevatedButton.styleFrom(
                    backgroundColor: AppColors.buttonBrownDark,
                    foregroundColor: AppColors.white,
                    disabledBackgroundColor: AppColors.buttonBrownDark.withValues(alpha: 0.45),
                    disabledForegroundColor: AppColors.white.withValues(alpha: 0.7),
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 12),
                  ),
                  onPressed: approveEnabled ? onApprove : null,
                  icon: approving
                      ? const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                        )
                      : const Icon(Icons.check_circle_outline, size: 18),
                  label: const Text('اعتماد نتائج التقييم النهائي'),
                );
                if (sideBySide) {
                  return Row(
                    children: [
                      Expanded(child: saveBtn),
                      const SizedBox(width: 8),
                      Expanded(child: approveBtn),
                    ],
                  );
                }
                // حتى في العرض الضيق نعرضهما جنباً إلى جنب قدر الإمكان
                return Row(
                  children: [
                    Expanded(child: saveBtn),
                    const SizedBox(width: 8),
                    Expanded(child: approveBtn),
                  ],
                );
              },
            ),
          if (alreadyApproved && !canEdit)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Text(
                'معتمدة إلكترونياً',
                style: AppTextStyles.cairo(
                  fontSize: 20,
                  fontWeight: FontWeight.w800,
                  color: AppColors.doneGreen,
                ),
                textAlign: TextAlign.center,
              ),
            ),
          const SizedBox(height: 8),
          _EvalSheetCloseButton(onPressed: onClose),
        ],
      ),
    );
  }
}

class _StatBox extends StatelessWidget {
  const _StatBox({
    required this.label,
    required this.value,
    this.emphasize = false,
    this.fg,
    this.bg,
  });
  final String label;
  final String value;
  final bool emphasize;
  final Color? fg;
  final Color? bg;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 140,
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: bg ?? AppColors.cardWhite,
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
              color: fg ?? (emphasize ? AppColors.olive : AppColors.darkText),
            ),
          ),
        ],
      ),
    );
  }
}

class _EvalSheetCloseButton extends StatelessWidget {
  const _EvalSheetCloseButton({required this.onPressed});
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
      child: SizedBox(
        width: double.infinity,
        child: OutlinedButton.icon(
          onPressed: onPressed,
          icon: const Icon(Icons.close),
          label: const Text('إغلاق قائمة التقييم'),
          style: OutlinedButton.styleFrom(
            foregroundColor: AppColors.olive,
            padding: const EdgeInsets.symmetric(vertical: 14),
            side: const BorderSide(color: AppColors.olive),
          ),
        ),
      ),
    );
  }
}

class _EvalNarrativeBlock extends StatelessWidget {
  const _EvalNarrativeBlock({
    required this.descCtrl,
    required this.reqCtrl,
    required this.canEdit,
  });

  final TextEditingController descCtrl;
  final TextEditingController reqCtrl;
  final bool canEdit;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      color: const Color(0xFFF7F2E8),
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
      child: Column(
        children: [
          _row('وصف المعضلة', descCtrl, 2),
          const SizedBox(height: 8),
          _row('متطلبات تنفيذ المعضلة', reqCtrl, 3),
        ],
      ),
    );
  }

  Widget _row(String label, TextEditingController ctrl, int lines) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 150,
          child: Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(
              label,
              style: AppTextStyles.cairo(
                fontSize: 13,
                fontWeight: FontWeight.w800,
                color: AppColors.olive,
              ),
            ),
          ),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: TextField(
            controller: ctrl,
            enabled: canEdit,
            minLines: lines,
            maxLines: 6,
            textAlign: TextAlign.right,
            style: AppTextStyles.cairo(fontSize: 13, height: 1.45),
            decoration: InputDecoration(
              hintText: 'أدخل $label',
              filled: true,
              fillColor: Colors.white,
              isDense: true,
              contentPadding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(6),
                borderSide: const BorderSide(color: AppColors.divider),
              ),
            ),
          ),
        ),
      ],
    );
  }
}
