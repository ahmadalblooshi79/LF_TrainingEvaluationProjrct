import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import '../widgets/app_header.dart';
import '../widgets/figma_ui.dart';

class _Notice {
  const _Notice({
    required this.title,
    required this.body,
    required this.time,
    required this.kind,
    this.read = false,
  });
  final String title;
  final String body;
  final String time;
  final String kind; // alert | notice
  final bool read;
}

/// التنبيهات والإشعارات — مفعّلة بالكامل.
class NotificationsScreen extends StatefulWidget {
  const NotificationsScreen({super.key});

  @override
  State<NotificationsScreen> createState() => _NotificationsScreenState();
}

class _NotificationsScreenState extends State<NotificationsScreen> {
  late List<_Notice> _items;

  @override
  void initState() {
    super.initState();
    _items = [
      const _Notice(
        title: 'تذكير باعتماد القوائم',
        body: 'توجد قوائم تقييم جاهزة للاعتماد — راجع المهام غير المكتملة.',
        time: 'اليوم',
        kind: 'alert',
      ),
      const _Notice(
        title: 'تحديث مجرى الأحداث',
        body: 'تم تحديث أحداث اليوم التشغيلي من التخطيط والسيطرة.',
        time: 'اليوم',
        kind: 'notice',
      ),
      const _Notice(
        title: 'مزامنة معلّقة',
        body: 'تحقق من حالة المزامنة عند عودة الاتصال بالخادم.',
        time: 'أمس',
        kind: 'alert',
      ),
      const _Notice(
        title: 'تعليمات السيطرة',
        body: 'يرجى الالتزام بتسلسل تقييم الإجراءات وفق دليل السيطرة المعتمد.',
        time: 'أمس',
        kind: 'notice',
        read: true,
      ),
    ];
  }

  void _markAllRead() {
    setState(() {
      _items = _items
          .map(
            (n) => _Notice(
              title: n.title,
              body: n.body,
              time: n.time,
              kind: n.kind,
              read: true,
            ),
          )
          .toList();
    });
  }

  @override
  Widget build(BuildContext context) {
    final unread = _items.where((e) => !e.read).length;
    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppHeader(
        pageTitle: 'التنبيهات والإشعارات',
        onBack: () => Navigator.of(context).maybePop(),
        showOnlineChip: false,
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
            child: Row(
              children: [
                Text(
                  unread > 0 ? 'غير مقروء: $unread' : 'تم الاطلاع على الكل',
                  style: AppTextStyles.cairo(fontWeight: FontWeight.w700),
                ),
                const Spacer(),
                TextButton(
                  onPressed: unread == 0 ? null : _markAllRead,
                  child: Text(
                    'تعليمليم الكل كمقروء',
                    style: AppTextStyles.cairo(
                      color: AppColors.goldDark,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
              ],
            ),
          ),
          Expanded(
            child: ListView.separated(
              padding: const EdgeInsets.all(16),
              itemCount: _items.length,
              separatorBuilder: (_, __) => const SizedBox(height: 10),
              itemBuilder: (context, i) {
                final n = _items[i];
                final isAlert = n.kind == 'alert';
                return FigmaPanel(
                  padding: const EdgeInsets.all(14),
                  child: InkWell(
                    onTap: () {
                      if (n.read) return;
                      setState(() {
                        _items[i] = _Notice(
                          title: n.title,
                          body: n.body,
                          time: n.time,
                          kind: n.kind,
                          read: true,
                        );
                      });
                    },
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Icon(
                          isAlert
                              ? Icons.notification_important_outlined
                              : Icons.notifications_active_outlined,
                          color: isAlert ? AppColors.notDoneRed : AppColors.goldDark,
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                children: [
                                  Expanded(
                                    child: Text(
                                      n.title,
                                      style: AppTextStyles.cairo(
                                        fontSize: 15,
                                        fontWeight: FontWeight.w800,
                                      ),
                                    ),
                                  ),
                                  if (!n.read)
                                    Container(
                                      width: 9,
                                      height: 9,
                                      decoration: const BoxDecoration(
                                        color: AppColors.goldDark,
                                        shape: BoxShape.circle,
                                      ),
                                    ),
                                ],
                              ),
                              const SizedBox(height: 6),
                              Text(n.body, style: AppTextStyles.body),
                              const SizedBox(height: 8),
                              Text(
                                n.time,
                                style: AppTextStyles.cairo(
                                  fontSize: 11,
                                  color: AppColors.muted,
                                ),
                              ),
                            ],
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
    );
  }
}
