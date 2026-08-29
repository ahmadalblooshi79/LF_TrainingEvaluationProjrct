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

    return LayoutBuilder(
      builder: (context, c) {
        final wide = c.maxWidth >= 960;
        final portrait =
            MediaQuery.orientationOf(context) == Orientation.portrait;
        final sidebar = _Sidebar(data: data, portraitRow: portrait && !wide);
        final pad = DeviceLayout.pagePadding(context);
        final incompleteRows = data.incompleteTasks
            .where(
              (r) =>
                  !r.statusDone &&
                  !r.statusLabel.contains('معتمد') &&
                  r.statusLabel != 'منجز' &&
                  r.statusLabel != 'ينجز',
            )
            .toList();

        final menuBlock = _MainMenuBlock(
          data: data,
          fromCache: _fromCache,
          icons: _icons,
        );
        final table = _IncompleteTable(
          rows: incompleteRows,
          onRefresh: _load,
          scrollable: true,
        );

        if (!wide) {
          return Padding(
            padding: pad,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                sidebar,
                SizedBox(height: DeviceLayout.listSpacing(context) + 4),
                menuBlock,
                const SizedBox(height: 10),
                Expanded(child: FigmaPanel(child: table)),
              ],
            ),
          );
        }

        return Padding(
          padding: pad,
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              SizedBox(
                width: 300,
                child: SingleChildScrollView(child: sidebar),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    menuBlock,
                    const SizedBox(height: 10),
                    Expanded(child: FigmaPanel(child: table)),
                  ],
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}

class _Sidebar extends StatelessWidget {
  const _Sidebar({required this.data, this.portraitRow = false});
  final HomeData data;
  final bool portraitRow;

  @override
  Widget build(BuildContext context) {
    final exercise = _ExerciseInfoCard(data: data);
    final progress = _ProgressCard(data: data);

    if (portraitRow) {
      return IntrinsicHeight(
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Expanded(child: exercise),
            const SizedBox(width: 12),
            Expanded(child: progress),
          ],
        ),
      );
    }

    return Column(
      children: [
        exercise,
        const SizedBox(height: 14),
        progress,
      ],
    );
  }
}

class _ExerciseInfoCard extends StatelessWidget {
  const _ExerciseInfoCard({required this.data});
  final HomeData data;

  @override
  Widget build(BuildContext context) {
    final ex = data.bundle.exercise;
    return FigmaPanel(
      padding: const EdgeInsets.all(16),
      child: Align(
        alignment: Alignment.centerRight,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.workspace_premium_outlined,
                    color: AppColors.goldDark, size: 20),
                const SizedBox(width: 8),
                Text(
                  'معلومات التمرين',
                  style: AppTextStyles.cairo(fontWeight: FontWeight.w800, fontSize: 15),
                ),
              ],
            ),
            const SizedBox(height: 14),
            _InfoLine(Icons.emoji_events_outlined, 'اسم التمرين', ex?.name ?? '—'),
            _InfoLine(
              Icons.calendar_month_outlined,
              'فترة التمرين',
              ex?.periodLabel.isNotEmpty == true ? ex!.periodLabel : '—',
            ),
            _InfoLine(
              Icons.place_outlined,
              'موقع التمرين',
              ex?.location.isNotEmpty == true ? ex!.location : '—',
            ),
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
    );
  }
}

class _ProgressCard extends StatelessWidget {
  const _ProgressCard({required this.data});
  final HomeData data;

  @override
  Widget build(BuildContext context) {
    final stats = data.stats;
    final pct = stats.completionPct.clamp(0, 100) / 100.0;

    return Container(
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
        mainAxisAlignment: MainAxisAlignment.center,
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
            style: AppTextStyles.cairo(
              fontSize: 13,
              color: AppColors.white,
              fontWeight: FontWeight.w600,
            ),
            textAlign: TextAlign.center,
          ),
        ],
      ),
    );
  }
}

class _InfoLine extends StatelessWidget {
  const _InfoLine(this.icon, this.label, this.value);
  final IconData icon;
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
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
                Text(
                  label,
                  style: AppTextStyles.cairo(fontSize: 11, color: AppColors.muted),
                  textAlign: TextAlign.right,
                ),
                Text(
                  value,
                  style: AppTextStyles.cairo(fontSize: 13, fontWeight: FontWeight.w600),
                  textAlign: TextAlign.right,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _MainMenuBlock extends StatelessWidget {
  const _MainMenuBlock({
    required this.data,
    required this.fromCache,
    required this.icons,
  });
  final HomeData data;
  final bool fromCache;
  final Map<String, IconData> icons;

  @override
  Widget build(BuildContext context) {
    final menu = data.menu;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: MainAxisSize.min,
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
        OrientationBuilder(
          builder: (context, orientation) {
            final cards = menu
                .map(
                  (m) => _MenuCard(
                    title: m.title,
                    icon: icons[m.id] ?? Icons.apps,
                    onTap: () => context.push(m.route),
                  ),
                )
                .toList();
            return _MenuGrid(cards: cards, portrait: orientation == Orientation.portrait);
          },
        ),
        const SizedBox(height: 14),
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
      ],
    );
  }
}

class _MenuGrid extends StatelessWidget {
  const _MenuGrid({required this.cards, required this.portrait});
  final List<_MenuCard> cards;
  final bool portrait;

  static const _gap = 8.0;

  Widget _cell(_MenuCard card, {int flex = 1}) {
    return Expanded(
      flex: flex,
      child: Padding(
        padding: const EdgeInsets.all(_gap / 2),
        child: card,
      ),
    );
  }

  Widget _row(List<_MenuCard> rowCards, {List<int>? flexes}) {
    return IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          for (var i = 0; i < rowCards.length; i++)
            _cell(rowCards[i], flex: flexes != null && i < flexes.length ? flexes[i] : 1),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (cards.isEmpty) return const SizedBox.shrink();

    if (portrait) {
      return Column(
        children: [
          if (cards.isNotEmpty) _row(cards.take(2).toList()),
          if (cards.length > 2) ...[
            const SizedBox(height: _gap),
            _row(cards.skip(2).take(2).toList()),
          ],
          if (cards.length > 4) ...[
            const SizedBox(height: _gap),
            IntrinsicHeight(
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Expanded(child: SizedBox()),
                  Expanded(
                    child: Padding(
                      padding: const EdgeInsets.all(_gap / 2),
                      child: cards[4],
                    ),
                  ),
                  const Expanded(child: SizedBox()),
                ],
              ),
            ),
          ],
        ],
      );
    }

    final top = cards.length > 3 ? cards.sublist(0, 3) : cards;
    final bottom = cards.length > 3 ? cards.sublist(3) : <_MenuCard>[];
    return Column(
      children: [
        if (top.isNotEmpty) _row(top),
        if (bottom.isNotEmpty) ...[
          const SizedBox(height: _gap),
          _row(bottom.length >= 2 ? bottom.sublist(0, 2) : bottom),
        ],
      ],
    );
  }
}

class _MenuCard extends StatelessWidget {
  const _MenuCard({required this.title, required this.icon, required this.onTap});
  final String title;
  final IconData icon;
  final VoidCallback onTap;

  static const _height = 56.0;

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
          height: _height,
          padding: const EdgeInsets.symmetric(horizontal: 12),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: AppColors.divider),
          ),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(icon, color: AppColors.goldDark, size: 22),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  title,
                  textAlign: TextAlign.center,
                  style: AppTextStyles.cairo(fontSize: 13, fontWeight: FontWeight.w700),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _IncompleteTable extends StatelessWidget {
  const _IncompleteTable({
    required this.rows,
    this.onRefresh,
    this.scrollable = false,
  });
  final List<ListRow> rows;
  final Future<void> Function()? onRefresh;
  final bool scrollable;

  @override
  Widget build(BuildContext context) {
    final header = Container(
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
    );

    final footer = Align(
      alignment: Alignment.centerRight,
      child: Padding(
        padding: const EdgeInsets.all(10),
        child: TextButton(
          onPressed: () => context.push('/incomplete'),
          child: Text(
            'عرض جميع المهام',
            style: AppTextStyles.cairo(
              color: AppColors.goldDark,
              fontWeight: FontWeight.w700,
            ),
          ),
        ),
      ),
    );

    Widget rowAt(int i) {
      final r = rows[i];
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
                  done: false,
                  label: r.statusLabel.isNotEmpty ? r.statusLabel : 'لم ينجز',
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
    }

    if (!scrollable) {
      return Column(
        children: [
          header,
          if (rows.isEmpty)
            const Padding(
              padding: EdgeInsets.all(28),
              child: Text('لا توجد مهام غير مكتملة'),
            )
          else
            ...List.generate(rows.length, rowAt),
          footer,
        ],
      );
    }

    return Column(
      children: [
        header,
        Expanded(
          child: RefreshIndicator(
            onRefresh: onRefresh ?? () async {},
            color: AppColors.gold,
            child: rows.isEmpty
                ? ListView(
                    physics: const AlwaysScrollableScrollPhysics(),
                    children: const [
                      Padding(
                        padding: EdgeInsets.all(28),
                        child: Center(child: Text('لا توجد مهام غير مكتملة')),
                      ),
                    ],
                  )
                : ListView.builder(
                    physics: const AlwaysScrollableScrollPhysics(),
                    itemCount: rows.length,
                    itemBuilder: (context, i) => rowAt(i),
                  ),
          ),
        ),
        footer,
      ],
    );
  }

  static final _h = AppTextStyles.cairo(fontSize: 13, fontWeight: FontWeight.w700, color: AppColors.olive);

  void _open(BuildContext context, ListRow r) {
    void onReturn(_) {
      onRefresh?.call();
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

    final itemId = r.itemId ?? (r.id is int ? r.id as int : int.tryParse('${r.id}'));
    final uk = r.unitKey.trim();
    if (itemId != null && uk.isNotEmpty) {
      context.push('/evaluation-lists/$uk/$itemId', extra: r.title).then(onReturn);
      return;
    }
    if (itemId != null) {
      context.push('/evaluation-lists/_/$itemId', extra: r.title).then(onReturn);
    }
  }
}

