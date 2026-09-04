import 'package:flutter/material.dart';

import '../models/flow.dart';
import '../services/api_client.dart';
import '../services/tablet_repository.dart';
import '../theme/app_theme.dart';
import '../widgets/app_header.dart';
import '../widgets/async_state_views.dart';
import '../widgets/figma_ui.dart';
import 'library_pdf_screen.dart';

const _flowCols = <({String label, int flex})>[
  (label: 'ت', flex: 1),
  (label: 'التوقيت الحقيقي', flex: 2),
  (label: 'توقيت نظام كورا', flex: 2),
  (label: 'من', flex: 1),
  (label: 'إلى', flex: 1),
  (label: 'أنظمة التبليغ', flex: 2),
  (label: 'وصف المعضلة/الحدث', flex: 3),
  (label: 'المكلف بالإجراء والمتابعة', flex: 2),
  (label: 'رد الفعل المتوقع', flex: 2),
  (label: 'الملاحظات', flex: 2),
];

class FlowScreen extends StatefulWidget {
  const FlowScreen({super.key});

  @override
  State<FlowScreen> createState() => _FlowScreenState();
}

class _FlowScreenState extends State<FlowScreen> {
  FlowData? _data;
  bool _loading = true;
  bool _fromCache = false;
  String? _error;
  String? _activeDay;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load({String? day}) async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final r = await TabletRepository.instance.fetchFlow(day: day ?? _activeDay);
      setState(() {
        _data = r.data;
        _fromCache = r.fromCache;
        _activeDay = r.data.activeDayId;
      });
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _openDayPdf() {
    final data = _data;
    if (data == null) return;
    final dayId = (_activeDay ?? data.activeDayId).trim();
    if (dayId.isEmpty) return;
    final label = data.days
        .where((d) => d.id == dayId)
        .map((d) => d.label)
        .firstWhere((n) => n.isNotEmpty, orElse: () => dayId);
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => LibraryPdfScreen(
          flowDayId: dayId,
          title: 'PDF — $label',
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppHeader(
        pageTitle: 'مجرى الأحداث والمعاضل',
        onBack: () => Navigator.of(context).maybePop(),
        showOnlineChip: false,
      ),
      body: _loading
          ? const LoadingView()
          : _error != null
              ? ErrorView(message: _error!, onRetry: () => _load())
              : _body(),
    );
  }

  Widget _body() {
    final data = _data;
    if (data == null) return const EmptyView(message: 'لا توجد بيانات');
    final dayNote = data.days
        .where((d) => d.id == (_activeDay ?? data.activeDayId))
        .map((d) => d.note)
        .firstWhere((n) => n.isNotEmpty, orElse: () => '');

    return Column(
      children: [
        if (_fromCache) const CachedDataBanner(),
        if (data.days.isNotEmpty)
          Row(
            children: [
              Expanded(
                child: FigmaDayChips(
                  labels: data.days.map((d) => (id: d.id, label: d.label)).toList(),
                  activeId: _activeDay ?? data.activeDayId,
                  onSelect: (id) {
                    setState(() => _activeDay = id);
                    _load(day: id);
                  },
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(4, 10, 12, 6),
                child: ElevatedButton.icon(
                  onPressed: _openDayPdf,
                  icon: const Icon(Icons.picture_as_pdf, size: 18),
                  label: const Text('PDF'),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: AppColors.buttonBrown,
                    foregroundColor: AppColors.white,
                    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                  ),
                ),
              ),
            ],
          ),
        Expanded(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 16),
            child: FigmaPanel(
              child: Column(
                children: [
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 14, 16, 8),
                    child: Column(
                      children: [
                        Text(
                          data.title.isNotEmpty ? data.title : 'مجرى الأحداث والمعاضل',
                          textAlign: TextAlign.center,
                          style: AppTextStyles.cairo(fontSize: 15, fontWeight: FontWeight.w800),
                        ),
                        if (dayNote.isNotEmpty) ...[
                          const SizedBox(height: 4),
                          Text(
                            dayNote,
                            textAlign: TextAlign.center,
                            style: AppTextStyles.cairo(fontSize: 12, color: AppColors.muted),
                          ),
                        ],
                      ],
                    ),
                  ),
                  Expanded(
                    child: LayoutBuilder(
                      builder: (context, constraints) {
                        final tableW = constraints.maxWidth < 1180 ? 1180.0 : constraints.maxWidth;
                        return SingleChildScrollView(
                          scrollDirection: Axis.horizontal,
                          child: SizedBox(
                            width: tableW,
                            height: constraints.maxHeight,
                            child: Column(
                              children: [
                                const _FlowHeader(),
                                Expanded(
                                  child: data.rows.isEmpty
                                      ? const EmptyView(message: 'لا توجد أحداث لهذا اليوم')
                                      : ListView.builder(
                                          itemCount: data.rows.length,
                                          itemBuilder: (_, i) => _Row(row: data.rows[i]),
                                        ),
                                ),
                              ],
                            ),
                          ),
                        );
                      },
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ],
    );
  }
}

class _FlowHeader extends StatelessWidget {
  const _FlowHeader();

  @override
  Widget build(BuildContext context) {
    return Container(
      color: AppColors.tableHeader,
      child: IntrinsicHeight(
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            for (var i = 0; i < _flowCols.length; i++) ...[
              if (i > 0)
                Container(width: 1.2, color: AppColors.white.withValues(alpha: 0.35)),
              Expanded(
                flex: _flowCols[i].flex,
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 8),
                  child: Text(
                    _flowCols[i].label,
                    textAlign: TextAlign.center,
                    maxLines: 2,
                    style: AppTextStyles.cairo(
                      fontSize: 11,
                      fontWeight: FontWeight.w700,
                      color: AppColors.white,
                    ),
                  ),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _Row extends StatelessWidget {
  const _Row({required this.row});
  final FlowRow row;

  Color get _bg {
    switch (row.tone) {
      case 'event':
        return AppColors.eventRow;
      case 'dilemma':
        return AppColors.dilemmaRow;
      default:
        return AppColors.cardWhite;
    }
  }

  static final _cellStyle = AppTextStyles.cairo(
    fontSize: 12,
    fontWeight: FontWeight.w600,
    color: AppColors.darkText,
  );

  Widget _cell(String text, {int flex = 1, TextAlign align = TextAlign.center}) {
    return Expanded(
      flex: flex,
      child: Container(
        alignment: Alignment.center,
        padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 8),
        decoration: const BoxDecoration(
          border: Border(left: BorderSide(color: AppColors.divider, width: 1)),
        ),
        child: Text(text, textAlign: align, style: _cellStyle),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final span = row.tone == 'event' || row.tone == 'dilemma';
    return Container(
      decoration: BoxDecoration(
        color: _bg,
        border: const Border(bottom: BorderSide(color: AppColors.divider, width: 1)),
      ),
      child: span
          ? Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
              child: Text(
                row.text,
                textAlign: TextAlign.center,
                style: AppTextStyles.cairo(fontSize: 14, fontWeight: FontWeight.w800),
              ),
            )
          : IntrinsicHeight(
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  _cell(row.seq > 0 ? '${row.seq}' : '', flex: 1),
                  _cell(row.time, flex: 2),
                  _cell(row.timeKora, flex: 2),
                  _cell(row.timeFrom, flex: 1),
                  _cell(row.timeTo, flex: 1),
                  _cell(row.reportSystems, flex: 2),
                  _cell(row.text, flex: 3, align: TextAlign.right),
                  _cell(row.assignee, flex: 2),
                  _cell(row.reaction, flex: 2, align: TextAlign.right),
                  _cell(row.notes, flex: 2, align: TextAlign.right),
                ],
              ),
            ),
    );
  }
}
