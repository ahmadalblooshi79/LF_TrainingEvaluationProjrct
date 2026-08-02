import 'package:flutter/material.dart';

import '../models/flow.dart';
import '../services/api_client.dart';
import '../services/tablet_repository.dart';
import '../theme/app_theme.dart';
import '../widgets/app_header.dart';
import '../widgets/async_state_views.dart';
import '../widgets/figma_ui.dart';

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
          FigmaDayChips(
            labels: data.days.map((d) => (id: d.id, label: d.label)).toList(),
            activeId: _activeDay ?? data.activeDayId,
            onSelect: (id) {
              setState(() => _activeDay = id);
              _load(day: id);
            },
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
                  const FigmaTableHeader(
                    cells: [
                      (label: 'ت', flex: 1),
                      (label: 'الوقت', flex: 2),
                      (label: 'وصف الحدث / المعضلة', flex: 5),
                      (label: 'المكلف بالإجراء والمتابعة', flex: 2),
                      (label: 'أسلوب فرض المعضلة', flex: 2),
                      (label: 'رد الفعل المتوقع', flex: 3),
                    ],
                  ),
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
          ),
        ),
      ],
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

  static final _whiteCell = AppTextStyles.cairo(
    fontSize: 15,
    fontWeight: FontWeight.w600,
    color: AppColors.darkText,
  );

  Widget _cell(String text, {int flex = 1, TextAlign align = TextAlign.center}) {
    return Expanded(
      flex: flex,
      child: Container(
        alignment: Alignment.center,
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 10),
        decoration: const BoxDecoration(
          border: Border(left: BorderSide(color: AppColors.divider, width: 1)),
        ),
        child: Text(
          text,
          textAlign: align,
          style: _whiteCell,
        ),
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
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 14),
              child: Row(
                children: [
                  SizedBox(
                    width: 36,
                    child: Text(
                      '${row.seq}',
                      textAlign: TextAlign.center,
                      style: AppTextStyles.cairo(fontSize: 15, fontWeight: FontWeight.w800),
                    ),
                  ),
                  Expanded(
                    child: Text(
                      row.text,
                      textAlign: TextAlign.center,
                      style: AppTextStyles.cairo(fontSize: 16, fontWeight: FontWeight.w800),
                    ),
                  ),
                ],
              ),
            )
          : IntrinsicHeight(
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  _cell('${row.seq}', flex: 1),
                  _cell(row.time, flex: 2),
                  Expanded(
                    flex: 5,
                    child: Container(
                      alignment: Alignment.centerRight,
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 10),
                      decoration: const BoxDecoration(
                        border: Border(left: BorderSide(color: AppColors.divider, width: 1)),
                      ),
                      child: Text(row.text, style: _whiteCell, textAlign: TextAlign.right),
                    ),
                  ),
                  _cell(row.assignee, flex: 2),
                  _cell(row.method, flex: 2),
                  Expanded(
                    flex: 3,
                    child: Container(
                      alignment: Alignment.centerRight,
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 10),
                      decoration: const BoxDecoration(
                        border: Border(left: BorderSide(color: AppColors.divider, width: 1)),
                      ),
                      child: Text(row.expected, style: _whiteCell, textAlign: TextAlign.right),
                    ),
                  ),
                ],
              ),
            ),
    );
  }
}
