import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import '../widgets/app_header.dart';
import '../widgets/figma_ui.dart';

/// المكتبة — التخطيط والسيطرة.
class LibraryScreen extends StatelessWidget {
  const LibraryScreen({super.key});

  static const _sections = <({IconData icon, String title, String body})>[
    (
      icon: Icons.map_outlined,
      title: 'مراجع التخطيط',
      body: 'خرائط التمرين، أوامر العمليات، وجداول المخطط المعتمدة من التخطيط والسيطرة.',
    ),
    (
      icon: Icons.rule_folder_outlined,
      title: 'أدلة السيطرة',
      body: 'إجراءات السيطرة والتوجيهات الفنية للمحكمين أثناء تنفيذ التمرين.',
    ),
    (
      icon: Icons.description_outlined,
      title: 'نماذج التقييم',
      body: 'قوالب قوائم التقييم وقوائم تقييم الإجراءات المعتمدة للوحدة.',
    ),
    (
      icon: Icons.menu_book_outlined,
      title: 'المراجع التنظيمية',
      body: 'اللوائح والتعليمات ذات الصلة بتقييم الجاهزية القتالية.',
    ),
  ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppHeader(
        pageTitle: 'المكتبة',
        pageSubtitle: 'التخطيط والسيطرة',
        onBack: () => Navigator.of(context).maybePop(),
        showOnlineChip: false,
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          FigmaPanel(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(
                  'مكتبة التخطيط والسيطرة',
                  style: AppTextStyles.cairo(fontSize: 16, fontWeight: FontWeight.w800),
                ),
                const SizedBox(height: 6),
                Text(
                  'مرجعيات التشغيل المتاحة للمحكم أثناء التمرين.',
                  style: AppTextStyles.cairo(fontSize: 13, color: AppColors.muted),
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),
          ..._sections.map(
            (s) => Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: FigmaPanel(
                padding: const EdgeInsets.all(14),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Icon(s.icon, color: AppColors.goldDark, size: 26),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            s.title,
                            style: AppTextStyles.cairo(
                              fontSize: 15,
                              fontWeight: FontWeight.w800,
                            ),
                          ),
                          const SizedBox(height: 6),
                          Text(s.body, style: AppTextStyles.body),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
