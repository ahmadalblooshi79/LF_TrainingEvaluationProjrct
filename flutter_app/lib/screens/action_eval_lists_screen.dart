import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../models/action_eval.dart';
import '../models/list_row.dart';
import '../services/api_client.dart';
import '../services/tablet_repository.dart';
import '../theme/app_theme.dart';
import '../widgets/app_header.dart';
import '../widgets/async_state_views.dart';
import '../widgets/figma_ui.dart';

class ActionEvalListsScreen extends StatefulWidget {
  const ActionEvalListsScreen({super.key});

  @override
  State<ActionEvalListsScreen> createState() => _ActionEvalListsScreenState();
}

class _ActionEvalListsScreenState extends State<ActionEvalListsScreen> {
  ActionEvalListsData? _data;
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
      final r = await TabletRepository.instance.fetchActionEvalLists(day: day ?? _activeDay);
      setState(() {
        _data = r.data;
        _fromCache = r.fromCache;
        _activeDay = r.data.dayId;
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
        pageTitle: 'قوائم تقييم الإجراءات',
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
    return Column(
      children: [
        if (_fromCache) const CachedDataBanner(),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 10, 16, 4),
          child: Align(
            alignment: Alignment.centerRight,
            child: Text(
              'قوائم التقييم — ${data.unitKey.isNotEmpty ? data.unitKey : 'قيادة مجموعة اللواء'}',
              style: AppTextStyles.cairo(fontSize: 15, fontWeight: FontWeight.w800),
            ),
          ),
        ),
        if (data.dayTabs.isNotEmpty)
          FigmaDayChips(
            labels: data.dayTabs.map((d) => (id: d.id, label: d.label)).toList(),
            activeId: _activeDay ?? data.dayId,
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
                  const FigmaTableHeader(
                    cells: [
                      (label: 'ت', flex: 1),
                      (label: 'قائمة التقييم', flex: 5),
                      (label: 'التقرير العام', flex: 2),
                      (label: 'توقيت التسليم', flex: 2),
                      (label: 'الموقف', flex: 2),
                      (label: 'فتح القائمة', flex: 2),
                    ],
                  ),
                  Expanded(
                    child: data.lists.isEmpty
                        ? const EmptyView(message: 'لا توجد قوائم تقييم إجراءات لهذا اليوم')
                        : ListView.builder(
                            itemCount: data.lists.length,
                            itemBuilder: (_, i) => _Row(index: i + 1, row: data.lists[i]),
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
  const _Row({required this.index, required this.row});
  final int index;
  final ListRow row;

  @override
  Widget build(BuildContext context) {
    final slot = row.slotIndex ?? row.slotId;
    void open() {
      if (slot == null) return;
      context.push('/action-eval/$slot', extra: row.title);
    }

    return InkWell(
      onTap: slot == null ? null : open,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 11),
        decoration: const BoxDecoration(
          border: Border(bottom: BorderSide(color: AppColors.divider)),
        ),
        child: Row(
          children: [
            Expanded(flex: 1, child: Text('$index', textAlign: TextAlign.center, style: AppTextStyles.small)),
            Expanded(
              flex: 5,
              child: Text(row.title, style: AppTextStyles.body, maxLines: 2, overflow: TextOverflow.ellipsis),
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
              child: Center(child: FigmaStatusPill(done: row.statusDone, label: row.statusLabel)),
            ),
            Expanded(
              flex: 2,
              child: Center(child: FigmaOpenButton(onPressed: slot == null ? null : open)),
            ),
          ],
        ),
      ),
    );
  }
}
