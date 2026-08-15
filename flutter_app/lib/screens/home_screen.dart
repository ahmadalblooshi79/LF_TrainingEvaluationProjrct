import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../models/home_data.dart';
import '../models/list_row.dart';
import '../services/api_client.dart';
import '../services/auth_service.dart';
import '../services/tablet_repository.dart';
import '../theme/app_theme.dart';
import '../theme/device_layout.dart';
import '../widgets/app_header.dart';
import '../widgets/async_state_views.dart';
import '../widgets/figma_ui.dart';

/// Dashboard — Figma: 4 horizontal menu cards + incomplete table + right sidebar.
class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  HomeData? _data;
  bool _loading = true;
  bool _fromCache = false;
  String? _error;

  static const _icons = <String, IconData>{
    'flow': Icons.timeline,
    'action_eval': Icons.fact_check_outlined,
    'evaluation_lists': Icons.checklist_rtl,
    'positives_negatives': Icons.thumbs_up_down_outlined,
    'objectives': Icons.flag_outlined,
  };

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
      final r = await TabletRepository.instance.fetchHome();
      setState(() {
        _data = r.data;
        _fromCache = r.fromCache;
      });
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final session = AuthService.instance.session;
    final ex = session?.exercise;
    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppHeader(
        pageTitle: 'التمرين',
        pageSubtitle: session?.unitLabel.isNotEmpty == true
            ? session!.unitLabel
            : (ex?.name ?? 'القائمة الرئيسية'),
        showLogout: true,
        showOnlineChip: false,
      ),
      body: _loading
          ? const LoadingView()
          : _error != null
              ? ErrorView(message: _error!, onRetry: _load)
              : _body(),
    );
  }

  Widget _body() {
    final data = _data;
    if (data == null) return const EmptyView(message: 'لا توجد بيانات');

    return RefreshIndicator(
      onRefresh: _load,
      color: AppColors.gold,
      child: LayoutBuilder(
        builder: (context, c) {
          final wide = c.maxWidth >= 960;
          final sidebar = _Sidebar(data: data);
          final main = _Main(data: data, fromCache: _fromCache, icons: _icons);
          if (!wide) {
            return ListView(
              padding: DeviceLayout.pagePadding(context),
              children: [
                sidebar,
                SizedBox(height: DeviceLayout.listSpacing(context) + 4),
                main,
              ],
            );
          }
          // RTL: first child appears on the right → sidebar first.
          return ListView(
            padding: DeviceLayout.pagePadding(context),
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  SizedBox(width: 300, child: sidebar),
                  const SizedBox(width: 16),
                  Expanded(child: main),
                ],
              ),
            ],
          );
        },
      ),
    );
  }
}

class _Sidebar extends StatelessWidget {
  const _Sidebar({required this.data});
  final HomeData data;

  @override
  Widget build(BuildContext context) {
    final ex = data.bundle.exercise;
    final stats = data.stats;
    final pct = stats.completionPct.clamp(0, 100) / 100.0;

    return Column(
      children: [
        FigmaPanel(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  const Icon(Icons.workspace_premium_outlined, color: AppColors.goldDark, size: 20),
                  const SizedBox(width: 8),
                  Text(
                    'معلومات التمرين',
                    style: AppTextStyles.cairo(fontWeight: FontWeight.w800, fontSize: 15),
                  ),
                ],
              ),
              const SizedBox(height: 14),
              _line(Icons.emoji_events_outlined, 'اسم التمرين', ex?.name ?? '—'),
              _line(Icons.calendar_month_outlined, 'فترة التمرين',
                  ex?.periodLabel.isNotEmpty == true ? ex!.periodLabel : '—'),
              _line(Icons.place_outlined, 'موقع التمرين',
                  ex?.location.isNotEmpty == true ? ex!.location : '—'),
              const SizedBox(height: 12),
              OutlinedButton(
                onPressed: () => context.push('/exercise-details'),
                style: OutlinedButton.styleFrom(
                  foregroundColor: AppColors.goldDark,
                  side: const BorderSide(color: AppColors.gold),
                  backgroundColor: AppColors.headerCream,
                ),
                child: const Text('عرض التفاصيل'),
              ),
            ],
          ),
        ),
        const SizedBox(height: 14),
        Container(
          width: double.infinity,
          padding: const EdgeInsets.fromLTRB(16, 20, 16, 18),
          decoration: BoxDecoration(
            color: AppColors.oliveDark,
            borderRadius: BorderRadius.circular(14),
            boxShadow: const [
              BoxShadow(color: AppColors.cardShadow, blurRadius: 8, offset: Offset(0, 3)),
            ],
          ),
          child: Column(
            children: [
              Text(
                'مؤشر الإنجاز العام',
                style: AppTextStyles.cairo(
                  color: AppColors.white,
                  fontWeight: FontWeight.w700,
                  fontSize: 14,
                ),
              ),
              const SizedBox(height: 18),
              SizedBox(
                width: 132,
                height: 132,
                child: Stack(
                  alignment: Alignment.center,
                  children: [
                    SizedBox(
                      width: 132,
                      height: 132,
                      child: CircularProgressIndicator(
                        value: pct,
                        strokeWidth: 11,
                        backgroundColor: AppColors.oliveMid,
                        color: AppColors.gold,
                      ),
                    ),
                    Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(
                          '${stats.completionPct}%',
                          style: AppTextStyles.cairo(
                            fontSize: 28,
                            fontWeight: FontWeight.w800,
                            color: AppColors.white,
                          ),
                        ),
                        Text(
                          'مكتملة',
                          style: AppTextStyles.cairo(fontSize: 12, color: AppColors.goldLight),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 16),
              Text(
                'المهام المكتملة',
                style: AppTextStyles.cairo(fontSize: 12, color: AppColors.goldLight),
              ),
              Text(
                '${stats.completedCount} من أصل ${stats.totalCount} مهمة',
                style: AppTextStyles.cairo(fontSize: 13, color: AppColors.white, fontWeight: FontWeight.w600),
                textAlign: TextAlign.center,
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _line(IconData icon, String label, String value) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 18, color: AppColors.goldDark),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(label, style: AppTextStyles.cairo(fontSize: 11, color: AppColors.muted)),
                Text(value, style: AppTextStyles.cairo(fontSize: 13, fontWeight: FontWeight.w600)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _Main extends StatelessWidget {
  const _Main({required this.data, required this.fromCache, required this.icons});
  final HomeData data;
  final bool fromCache;
  final Map<String, IconData> icons;

  @override
  Widget build(BuildContext context) {
    final menu = data.menu;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (fromCache) const CachedDataBanner(),
        Row(
          children: [
            const Icon(Icons.grid_view_rounded, color: AppColors.goldDark, size: 18),
            const SizedBox(width: 6),
            Text(
              'القائمة الرئيسية',
              style: AppTextStyles.cairo(fontSize: 16, fontWeight: FontWeight.w800),
            ),
          ],
        ),
        const SizedBox(height: 12),
        LayoutBuilder(
          builder: (context, c) {
            final wide = c.maxWidth >= 700;
            final cards = menu
                .map(
                  (m) => _MenuCard(
                    title: m.title,
                    icon: icons[m.id] ?? Icons.apps,
                    onTap: () => context.push(m.route),
                  ),
                )
                .toList();
            if (wide) {
              return Row(
                children: cards
                    .map((w) => Expanded(child: Padding(padding: const EdgeInsets.symmetric(horizontal: 5), child: w)))
                    .toList(),
              );
            }
            return Column(
              children: cards
                  .map((w) => Padding(padding: const EdgeInsets.only(bottom: 8), child: w))
                  .toList(),
            );
          },
        ),
        const SizedBox(height: 18),
        Row(
          children: [
            const Icon(Icons.schedule, color: AppColors.goldDark, size: 18),
            const SizedBox(width: 6),
            Text(
              'المهام غير المكتملة',
              style: AppTextStyles.cairo(fontSize: 16, fontWeight: FontWeight.w800),
            ),
          ],
        ),
        const SizedBox(height: 10),
        FigmaPanel(child: _IncompleteTable(rows: data.incompleteTasks)),
      ],
    );
  }
}

class _MenuCard extends StatelessWidget {
  const _MenuCard({required this.title, required this.icon, required this.onTap});
  final String title;
  final IconData icon;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: AppColors.cardWhite,
      borderRadius: BorderRadius.circular(12),
      elevation: 1,
      shadowColor: AppColors.cardShadow,
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: onTap,
        child: Container(
          constraints: const BoxConstraints(minHeight: 110),
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 16),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: AppColors.divider),
          ),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(icon, color: AppColors.goldDark, size: 26),
              const SizedBox(height: 10),
              Text(
                title,
                textAlign: TextAlign.center,
                style: AppTextStyles.cairo(fontSize: 14, fontWeight: FontWeight.w700),
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
              ),
              const SizedBox(height: 8),
              const Icon(Icons.keyboard_arrow_down, color: AppColors.goldDark, size: 22),
            ],
          ),
        ),
      ),
    );
  }
}

class _IncompleteTable extends StatelessWidget {
  const _IncompleteTable({required this.rows});
  final List<ListRow> rows;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Container(
          color: AppColors.headerCream,
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 10),
          child: Row(
            children: [
              Expanded(flex: 1, child: Text('ت', style: _h, textAlign: TextAlign.center)),
              Expanded(flex: 4, child: Text('مسمى التقييم', style: _h, textAlign: TextAlign.right)),
              Expanded(flex: 2, child: Text('نوع القائمة', style: _h, textAlign: TextAlign.center)),
              Expanded(flex: 2, child: Text('الموقف', style: _h, textAlign: TextAlign.center)),
              Expanded(flex: 2, child: Text('الإجراء', style: _h, textAlign: TextAlign.center)),
            ],
          ),
        ),
        if (rows.isEmpty)
          const Padding(
            padding: EdgeInsets.all(28),
            child: Text('لا توجد مهام غير مكتملة'),
          )
        else
          ...rows.asMap().entries.map((e) {
            final i = e.key;
            final r = e.value;
            return Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 10),
              decoration: const BoxDecoration(
                border: Border(top: BorderSide(color: AppColors.divider)),
              ),
              child: Row(
                children: [
                  Expanded(
                    flex: 1,
                    child: Text('${i + 1}', textAlign: TextAlign.center, style: AppTextStyles.small),
                  ),
                  Expanded(
                    flex: 4,
                    child: Text(
                      r.title,
                      style: AppTextStyles.body,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                  Expanded(
                    flex: 2,
                    child: Text(
                      r.displayListType,
                      textAlign: TextAlign.center,
                      style: AppTextStyles.cairo(
                        fontSize: 12,
                        fontWeight: FontWeight.w700,
                        color: AppColors.olive,
                      ),
                    ),
                  ),
                  Expanded(
                    flex: 2,
                    child: Center(
                      child: FigmaStatusPill(
                        done: r.statusDone,
                        label: r.statusLabel.isNotEmpty
                            ? r.statusLabel
                            : (r.statusDone ? 'منجزة' : 'غير منجزة'),
                        outlineOnly: true,
                      ),
                    ),
                  ),
                  Expanded(
                    flex: 2,
                    child: Center(
                      child: FigmaOpenButton(onPressed: () => _open(context, r)),
                    ),
                  ),
                ],
              ),
            );
          }),
        Align(
          alignment: Alignment.centerRight,
          child: Padding(
            padding: const EdgeInsets.all(10),
            child: TextButton(
              onPressed: () => context.push('/evaluation-lists'),
              child: Text(
                'عرض جميع المهام',
                style: AppTextStyles.cairo(
                  color: AppColors.goldDark,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
          ),
        ),
      ],
    );
  }

  static final _h = AppTextStyles.cairo(fontSize: 13, fontWeight: FontWeight.w700, color: AppColors.olive);

  void _open(BuildContext context, ListRow r) {
    // قوائم تقييم الإجراءات من المخطط
    final href = r.openHref;
    final actionMatch = RegExp(r'/action/(\d+)/evaluate').firstMatch(href);
    final listType = r.listType.toLowerCase();
    final isAction = listType.contains('action') ||
        listType.contains('planner') ||
        actionMatch != null ||
        href.contains('action-eval') ||
        href.contains('planner-flow');

    if (isAction) {
      final slot = r.slotIndex ??
          (actionMatch != null ? int.tryParse(actionMatch.group(1)!) : null) ??
          r.slotId;
      if (slot != null) {
        context.push('/action-eval/$slot', extra: r.title);
        return;
      }
    }

    final itemId = r.itemId ?? (r.id is int ? r.id as int : int.tryParse('${r.id}'));
    final uk = r.unitKey.trim();
    if (itemId != null && uk.isNotEmpty) {
      context.push('/evaluation-lists/$uk/$itemId', extra: r.title);
      return;
    }
    if (itemId != null) {
      context.push('/evaluation-lists/_/$itemId', extra: r.title);
    }
  }
}
