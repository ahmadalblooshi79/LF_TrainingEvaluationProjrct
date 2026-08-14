import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../models/evaluation_lists.dart';
import '../models/list_row.dart';
import '../services/api_client.dart';
import '../services/tablet_repository.dart';
import '../theme/app_theme.dart';
import '../widgets/app_header.dart';
import '../widgets/async_state_views.dart';
import '../widgets/figma_ui.dart';

class EvaluationListsScreen extends StatefulWidget {
  const EvaluationListsScreen({super.key});

  @override
  State<EvaluationListsScreen> createState() => _EvaluationListsScreenState();
}

class _EvaluationListsScreenState extends State<EvaluationListsScreen> {
  EvaluationListsData? _data;
  bool _loading = true;
  bool _fromCache = false;
  String? _error;
  String? _unitKey;
  String? _phase;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load({String? unitKey, String? phase}) async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final r = await TabletRepository.instance.fetchEvaluationLists(
        unitKey: unitKey ?? _unitKey,
        phase: phase ?? _phase,
      );
      if (!mounted) return;
      setState(() {
        _data = r.data;
        _fromCache = r.fromCache;
        _unitKey = r.data.unitKey;
        _phase = r.data.phaseKey;
      });
    } on ApiException catch (e) {
      if (!mounted) return;
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
        pageTitle: 'قوائم التقييم',
        onBack: () => Navigator.of(context).maybePop(),
      ),
      body: _loading
          ? const LoadingView()
          : _error != null
              ? ErrorView(message: _error!, onRetry: () => _load())
              : RefreshIndicator(
                  color: AppColors.goldDark,
                  onRefresh: () => _load(),
                  child: _body(),
                ),
    );
  }

  Widget _body() {
    final data = _data;
    if (data == null) {
      return ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        children: const [
          SizedBox(height: 120),
          EmptyView(message: 'لا توجد بيانات'),
        ],
      );
    }
    final unitLabel = data.unitLevels
        .where((u) => u.key == (_unitKey ?? data.unitKey))
        .map((u) => u.label)
        .firstWhere((s) => s.isNotEmpty, orElse: () => data.unitKey);

    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      children: [
        if (_fromCache) const CachedDataBanner(),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 10, 16, 4),
          child: Align(
            alignment: Alignment.centerRight,
            child: Text(
              'قوائم التقييم — ${unitLabel.isNotEmpty ? unitLabel : 'قيادة مجموعة اللواء'}',
              style: AppTextStyles.cairo(fontSize: 15, fontWeight: FontWeight.w800),
            ),
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
          child: Wrap(
            spacing: 10,
            runSpacing: 6,
            children: const [
              _LegendDot(color: Color(0xFFFFE0B2), label: 'بانتظار الإعتماد'),
              _LegendDot(color: Color(0xFFC8E6C9), label: 'مرسل'),
              _LegendDot(color: Color(0xFFFFCDD2), label: 'معاد للتعديل'),
            ],
          ),
        ),
        if (data.unitLevels.length > 1)
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Align(
              alignment: Alignment.centerRight,
              child: DropdownButton<String>(
                value: data.unitLevels.any((u) => u.key == (_unitKey ?? data.unitKey))
                    ? (_unitKey ?? data.unitKey)
                    : null,
                hint: const Text('اختر الوحدة'),
                items: data.unitLevels
                    .map((u) => DropdownMenuItem(value: u.key, child: Text(u.label)))
                    .toList(),
                onChanged: (v) {
                  if (v == null) return;
                  setState(() => _unitKey = v);
                  _load(unitKey: v);
                },
              ),
            ),
          ),
        if (data.phaseTabs.isNotEmpty)
          FigmaDayChips(
            labels: data.phaseTabs.map((p) => (id: p.key, label: p.label)).toList(),
            activeId: _phase ?? data.phaseKey,
            onSelect: (k) {
              setState(() => _phase = k);
              _load(phase: k);
            },
          ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 16),
          child: FigmaPanel(
            child: Column(
              children: [
                const FigmaTableHeader(
                  cells: [
                    (label: 'ت', flex: 1),
                    (label: 'قائمة التقييم', flex: 4),
                    (label: 'التقرير العام', flex: 2),
                    (label: 'توقيت التسليم', flex: 2),
                    (label: 'الموقف', flex: 2),
                    (label: 'إرسال للاعتماد', flex: 2),
                    (label: 'فتح', flex: 2),
                  ],
                ),
                if (data.lists.isEmpty)
                  const Padding(
                    padding: EdgeInsets.all(24),
                    child: EmptyView(message: 'لا توجد قوائم تقييم'),
                  )
                else
                  ...List.generate(
                    data.lists.length,
                    (i) => _Row(
                      index: i + 1,
                      row: data.lists[i],
                      unitKey: _unitKey ?? data.unitKey,
                    ),
                  ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class _LegendDot extends StatelessWidget {
  const _LegendDot({required this.color, required this.label});
  final Color color;
  final String label;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 14,
          height: 14,
          decoration: BoxDecoration(
            color: color,
            borderRadius: BorderRadius.circular(3),
            border: Border.all(color: AppColors.divider),
          ),
        ),
        const SizedBox(width: 4),
        Text(label, style: AppTextStyles.cairo(fontSize: 11)),
      ],
    );
  }
}

class _Row extends StatelessWidget {
  const _Row({required this.index, required this.row, required this.unitKey});
  final int index;
  final ListRow row;
  final String unitKey;

  Color? get _rowBg {
    switch (row.rowTone) {
      case 'returned':
        return const Color(0xFFFFCDD2);
      case 'sent':
        return const Color(0xFFC8E6C9);
      case 'pending':
        return const Color(0xFFFFE0B2);
      default:
        return null;
    }
  }

  @override
  Widget build(BuildContext context) {
    final itemId =
        row.itemId ?? (row.id is int ? row.id as int : int.tryParse('${row.id}'));
    final uk = row.unitKey.isNotEmpty ? row.unitKey : unitKey;
    void open() {
      if (itemId == null) return;
      context.push('/evaluation-lists/$uk/$itemId', extra: row.title);
    }

    final dispatch = row.displayDispatch;

    return InkWell(
      onTap: itemId == null ? null : open,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 11),
        decoration: BoxDecoration(
          color: _rowBg,
          border: const Border(bottom: BorderSide(color: AppColors.divider)),
        ),
        child: Row(
          children: [
            Expanded(
              flex: 1,
              child: Text('$index', textAlign: TextAlign.center, style: AppTextStyles.small),
            ),
            Expanded(
              flex: 4,
              child: Text(
                row.title,
                style: AppTextStyles.body,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
              ),
            ),
            Expanded(
              flex: 2,
              child: Text(
                row.gradeLabel.isNotEmpty ? row.gradeLabel : '—',
                textAlign: TextAlign.center,
                style: AppTextStyles.small,
              ),
            ),
            Expanded(
              flex: 2,
              child: Text(
                row.deliveryDt.isNotEmpty ? row.deliveryDt : '—',
                textAlign: TextAlign.center,
                style: AppTextStyles.small,
              ),
            ),
            Expanded(
              flex: 2,
              child: Center(
                child: FigmaStatusPill(
                  done: row.statusDone,
                  label: row.statusLabel.isNotEmpty
                      ? row.statusLabel
                      : (row.statusDone ? 'ينجز' : 'لم ينجز'),
                ),
              ),
            ),
            Expanded(
              flex: 2,
              child: Center(
                child: Text(
                  dispatch.isNotEmpty ? dispatch : 'لم يُرسل',
                  textAlign: TextAlign.center,
                  style: AppTextStyles.cairo(
                    fontSize: 12,
                    fontWeight: FontWeight.w800,
                    color: row.rowTone == 'returned'
                        ? AppColors.notDoneRed
                        : AppColors.olive,
                  ),
                ),
              ),
            ),
            Expanded(
              flex: 2,
              child: Center(
                child: FigmaOpenButton(onPressed: itemId == null ? null : open),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
