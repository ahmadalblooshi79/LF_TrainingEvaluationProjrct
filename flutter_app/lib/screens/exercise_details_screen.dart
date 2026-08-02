import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../services/auth_service.dart';
import '../theme/app_theme.dart';
import '../widgets/app_header.dart';
import '../widgets/figma_ui.dart';

/// صفحة تفاصيل التمرين — من زر «عرض التفاصيل».
class ExerciseDetailsScreen extends StatelessWidget {
  const ExerciseDetailsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final session = context.watch<AuthService>().session;
    final ex = session?.exercise;
    final dash = '—';

    String v(String? s) => (s != null && s.trim().isNotEmpty) ? s.trim() : dash;

    final dateLabel = () {
      if (ex == null) return dash;
      if (ex.periodLabel.trim().isNotEmpty) return ex.periodLabel.trim();
      if (ex.startDate.isNotEmpty && ex.endDate.isNotEmpty) {
        return '${ex.startDate} — ${ex.endDate}';
      }
      return v(ex.startDate.isNotEmpty ? ex.startDate : ex.endDate);
    }();

    final rows = <(IconData, String, String)>[
      (Icons.emoji_events_outlined, 'اسم التمرين', v(ex?.name)),
      (Icons.groups_outlined, 'الوحدة المتدربة', v(ex?.trainedUnit)),
      (Icons.place_outlined, 'مكان التمرين', v(ex?.location)),
      (Icons.category_outlined, 'نوع التمرين', v(ex?.typeLabel)),
      (Icons.stacked_bar_chart, 'مستوى التمرين', v(ex?.levelLabel)),
      (Icons.calendar_month_outlined, 'تاريخ التمرين', dateLabel),
      (Icons.flag_outlined, 'المهمة', v(ex?.missionLabel)),
    ];

    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppHeader(
        pageTitle: 'معلومات التمرين',
        pageSubtitle: session?.unitLabel,
        onBack: () => Navigator.of(context).maybePop(),
        showOnlineChip: false,
      ),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          FigmaPanel(
            padding: const EdgeInsets.fromLTRB(20, 18, 20, 12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Row(
                  children: [
                    const Icon(Icons.info_outline, color: AppColors.goldDark, size: 22),
                    const SizedBox(width: 8),
                    Text(
                      'تفاصيل التمرين',
                      style: AppTextStyles.cairo(fontSize: 17, fontWeight: FontWeight.w800),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                const Divider(color: AppColors.divider),
                ...rows.map((r) => _DetailLine(icon: r.$1, label: r.$2, value: r.$3)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _DetailLine extends StatelessWidget {
  const _DetailLine({
    required this.icon,
    required this.label,
    required this.value,
  });

  final IconData icon;
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 12),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 20, color: AppColors.goldDark),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  label,
                  style: AppTextStyles.cairo(fontSize: 12, color: AppColors.muted),
                ),
                const SizedBox(height: 4),
                Text(
                  value,
                  style: AppTextStyles.cairo(fontSize: 15, fontWeight: FontWeight.w700),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
