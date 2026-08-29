import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../models/list_row.dart';
import '../services/api_client.dart';
import '../services/tablet_repository.dart';
import '../theme/app_theme.dart';
import '../widgets/app_header.dart';
import '../widgets/async_state_views.dart';
import '../widgets/figma_ui.dart';

/// صفحة المهام غير المكتملة فقط — لا تظهر المعتمدة/المنجزة.
class IncompleteTasksScreen extends StatefulWidget {
  const IncompleteTasksScreen({super.key});

  @override
  State<IncompleteTasksScreen> createState() => _IncompleteTasksScreenState();
}

class _IncompleteTasksScreenState extends State<IncompleteTasksScreen> {
  List<ListRow> _rows = const [];
  bool _loading = true;
  bool _fromCache = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  List<ListRow> _onlyIncomplete(List<ListRow> rows) {
    return rows
        .where(
          (r) =>
              !r.statusDone &&
              !r.statusLabel.contains('معتمد') &&
              r.statusLabel != 'منجز' &&
              r.statusLabel != 'ينجز',
        )
        .toList();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final r = await TabletRepository.instance.fetchIncomplete();
      if (!mounted) return;
      setState(() {
        _rows = _onlyIncomplete(r.data);
        _fromCache = r.fromCache;
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _open(ListRow r) {
    void onReturn(_) {
      if (mounted) _load();
    }

    final href = r.openHref;
    final actionMatch = RegExp(r'/action/(\d+)/evaluate').firstMatch(href);
    final listType = r.listType.toLowerCase();
    final isAction = listType.contains('action') ||
        listType.contains('planner') ||
        actionMatch != null ||
        href.contains('action-eval') ||
        href.contains('planner-flow');

    if (isAction) {
      final slot = r.slotId ??
          r.slotIndex ??
          (actionMatch != null ? int.tryParse(actionMatch.group(1)!) : null);
      if (slot != null) {
        context.push('/action-eval/$slot', extra: r.title).then(onReturn);
        return;
      }
    }

    final itemId =
        r.itemId ?? (r.id is int ? r.id as int : int.tryParse('${r.id}'));
    final uk = r.unitKey.trim();
    if (itemId != null && uk.isNotEmpty) {
      context.push('/evaluation-lists/$uk/$itemId', extra: r.title).then(onReturn);
      return;
    }
    if (itemId != null) {
      context.push('/evaluation-lists/_/$itemId', extra: r.title).then(onReturn);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppHeader(
        pageTitle: 'المهام غير المكتملة',
        onBack: () => Navigator.of(context).maybePop(),
      ),
      body: _loading
          ? const LoadingView()
          : _error != null
              ? ErrorView(message: _error!, onRetry: _load)
              : RefreshIndicator(
                  color: AppColors.goldDark,
                  onRefresh: _load,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      if (_fromCache) const CachedDataBanner(),
                      Padding(
                        padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
                        child: Text(
                          'المهام غير المكتملة فقط — المعتمدة لا تظهر هنا',
                          style: AppTextStyles.cairo(
                            fontSize: 13,
                            fontWeight: FontWeight.w600,
                            color: AppColors.muted,
                          ),
                          textAlign: TextAlign.right,
                        ),
                      ),
                      Expanded(
                        child: FigmaPanel(
                          margin: const EdgeInsets.fromLTRB(16, 0, 16, 16),
                          child: Column(
                            children: [
                              const FigmaTableHeader(
                                cells: [
                                  (label: 'ت', flex: 1),
                                  (label: 'مسمى التقييم', flex: 4),
                                  (label: 'نوع القائمة', flex: 2),
                                  (label: 'الموقف', flex: 2),
                                  (label: 'الإجراء', flex: 2),
                                ],
                              ),
                              Expanded(
                                child: _rows.isEmpty
                                    ? ListView(
                                        physics:
                                            const AlwaysScrollableScrollPhysics(),
                                        children: const [
                                          SizedBox(height: 80),
                                          EmptyView(
                                            message: 'لا توجد مهام غير مكتملة',
                                          ),
                                        ],
                                      )
                                    : ListView.builder(
                                        physics:
                                            const AlwaysScrollableScrollPhysics(),
                                        itemCount: _rows.length,
                                        itemBuilder: (context, i) {
                                          final r = _rows[i];
                                          return Container(
                                            padding: const EdgeInsets.symmetric(
                                              horizontal: 8,
                                              vertical: 10,
                                            ),
                                            decoration: const BoxDecoration(
                                              border: Border(
                                                top: BorderSide(
                                                  color: AppColors.divider,
                                                ),
                                              ),
                                            ),
                                            child: Row(
                                              children: [
                                                Expanded(
                                                  flex: 1,
                                                  child: Text(
                                                    '${i + 1}',
                                                    textAlign: TextAlign.center,
                                                    style: AppTextStyles.small,
                                                  ),
                                                ),
                                                Expanded(
                                                  flex: 4,
                                                  child: Text(
                                                    r.title,
                                                    style: AppTextStyles.body,
                                                    maxLines: 2,
                                                    overflow:
                                                        TextOverflow.ellipsis,
                                                  ),
                                                ),
                                                Expanded(
                                                  flex: 2,
                                                  child: Text(
                                                    r.displayListType,
                                                    textAlign: TextAlign.center,
                                                    style: AppTextStyles.cairo(
                                                      fontSize: 12,
                                                      fontWeight:
                                                          FontWeight.w700,
                                                    ),
                                                  ),
                                                ),
                                                Expanded(
                                                  flex: 2,
                                                  child: Center(
                                                    child: FigmaStatusPill(
                                                      done: false,
                                                      label: r.statusLabel
                                                              .isNotEmpty
                                                          ? r.statusLabel
                                                          : 'لم ينجز',
                                                      outlineOnly: true,
                                                    ),
                                                  ),
                                                ),
                                                Expanded(
                                                  flex: 2,
                                                  child: Center(
                                                    child: FigmaOpenButton(
                                                      onPressed: () =>
                                                          _open(r),
                                                    ),
                                                  ),
                                                ),
                                              ],
                                            ),
                                          );
                                        },
                                      ),
                              ),
                            ],
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
    );
  }
}
