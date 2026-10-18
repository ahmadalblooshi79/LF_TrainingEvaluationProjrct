import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../models/home_data.dart';
import '../services/api_client.dart';
import '../services/home_progress.dart';
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
    'evaluation_lists': Icons.checklist_rtl,
    'action_eval': Icons.fact_check_outlined,
    'flow': Icons.timeline,
    'positives_negatives': Icons.thumbs_up_down_outlined,
    'incomplete': Icons.assignment_late_outlined,
    'objectives': Icons.flag_outlined,
    'exercise_papers': Icons.folder_copy_outlined,
    'program': Icons.event_note_outlined,
    'map': Icons.map_outlined,
    'library': Icons.menu_book_outlined,
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
    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: const AppHeader(
        pageTitle: 'الصفحة الرئيسية',
        showLogout: false,
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
        final menuBlock = _MainMenuBlock(
          fromCache: _fromCache,
          icons: _icons,
        );

        Widget content;
        if (!wide) {
          content = Padding(
            padding: pad,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                sidebar,
                SizedBox(height: DeviceLayout.listSpacing(context) + 4),
                Expanded(child: SingleChildScrollView(child: menuBlock)),
              ],
            ),
          );
        } else {
          content = Padding(
            padding: pad,
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                SizedBox(
                  width: 300,
                  child: SingleChildScrollView(child: sidebar),
                ),
                const SizedBox(width: 16),
                Expanded(child: SingleChildScrollView(child: menuBlock)),
              ],
            ),
          );
        }
        return Stack(
          children: [
            content,
            const Positioned(
              right: 16,
              bottom: 16,
              child: _HomeSettingsButton(),
            ),
          ],
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
    required this.fromCache,
    required this.icons,
  });
  final bool fromCache;
  final Map<String, IconData> icons;

  @override
  Widget build(BuildContext context) {
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
            final cards = [
              for (final m in kHomeFunctionsExact)
                _MenuCard(
                  title: m.title,
                  icon: icons[m.id] ?? Icons.apps,
                  onTap: () {
                    if (m.tab != null && m.tab!.isNotEmpty) {
                      context.push('${m.route}?tab=${m.tab}');
                    } else {
                      context.push(m.route);
                    }
                  },
                ),
            ];
            return _MenuGrid(cards: cards, portrait: orientation == Orientation.portrait);
          },
        ),
        const SizedBox(height: 88),
      ],
    );
  }
}

class _HomeSettingsButton extends StatelessWidget {
  const _HomeSettingsButton();

  @override
  Widget build(BuildContext context) {
    return Material(
      color: AppColors.headerCream,
      borderRadius: BorderRadius.circular(12),
      elevation: 2,
      shadowColor: AppColors.cardShadow,
      child: InkWell(
        key: const Key('home_settings_button'),
        borderRadius: BorderRadius.circular(12),
        onTap: () => context.push('/settings'),
        child: Container(
          width: 80,
          height: 80,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: AppColors.divider),
          ),
          child: const Icon(Icons.settings_outlined, size: 40, color: AppColors.olive),
        ),
      ),
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
      final rows = <Widget>[];
      for (var i = 0; i < cards.length; i += 2) {
        if (rows.isNotEmpty) rows.add(const SizedBox(height: _gap));
        final slice = cards.skip(i).take(2).toList();
        rows.add(_row(slice));
      }
      return Column(children: rows);
    }

    final rows = <Widget>[];
    for (var i = 0; i < cards.length; i += 3) {
      if (rows.isNotEmpty) rows.add(const SizedBox(height: _gap));
      final end = i + 3 > cards.length ? cards.length : i + 3;
      rows.add(_row(cards.sublist(i, end)));
    }
    return Column(children: rows);
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


