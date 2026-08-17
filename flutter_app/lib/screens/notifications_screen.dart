import 'package:flutter/material.dart';

import '../services/api_client.dart';
import '../services/notifications_badge_service.dart';
import '../theme/app_theme.dart';
import '../widgets/app_header.dart';
import '../widgets/figma_ui.dart';

class _Notice {
  const _Notice({
    required this.id,
    required this.typeLabel,
    required this.title,
    required this.body,
    required this.priorityLabel,
    required this.createdAt,
    required this.isRead,
  });

  final int id;
  final String typeLabel;
  final String title;
  final String body;
  final String priorityLabel;
  final String createdAt;
  final bool isRead;

  _Notice copyWith({bool? isRead}) => _Notice(
        id: id,
        typeLabel: typeLabel,
        title: title,
        body: body,
        priorityLabel: priorityLabel,
        createdAt: createdAt,
        isRead: isRead ?? this.isRead,
      );

  factory _Notice.fromJson(Map<String, dynamic> j) => _Notice(
        id: (j['id'] as num?)?.toInt() ?? 0,
        typeLabel: (j['type_label'] ?? 'نظام').toString(),
        title: (j['title'] ?? '').toString(),
        body: (j['body'] ?? '').toString(),
        priorityLabel: (j['priority_label'] ?? 'عادي').toString(),
        createdAt: (j['created_at'] ?? '').toString(),
        isRead: j['is_read'] == true,
      );
}

/// سجل الإشعارات — من السيرفر (تعليمليم كمقروء / تعليم الكل).
class NotificationsScreen extends StatefulWidget {
  const NotificationsScreen({super.key});

  @override
  State<NotificationsScreen> createState() => _NotificationsScreenState();
}

class _NotificationsScreenState extends State<NotificationsScreen> {
  bool _loading = true;
  String? _error;
  bool _hasExercise = true;
  List<_Notice> _items = const [];

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
      final data = await ApiClient.instance.get('/api/tablet/notifications');
      final list = (data['notifications'] as List?) ?? const [];
      if (!mounted) return;
      setState(() {
        _hasExercise = data['has_exercise'] != false;
        _items = list
            .whereType<Map>()
            .map((m) => _Notice.fromJson(Map<String, dynamic>.from(m)))
            .toList();
        _loading = false;
      });
      final unread = (data['unread_count'] as num?)?.toInt();
      if (unread != null) {
        NotificationsBadgeService.instance.setUnread(unread);
      } else {
        await NotificationsBadgeService.instance.refresh();
      }    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = e.toString().replaceFirst('ApiException: ', '');
      });
    }
  }

  Future<void> _markRead(int id) async {
    try {
      await ApiClient.instance.post('/api/tablet/notifications/$id/read');
      setState(() {
        _items = _items
            .map((n) => n.id == id ? n.copyWith(isRead: true) : n)
            .toList();
      });
      NotificationsBadgeService.instance.setUnread(
        _items.where((e) => !e.isRead).length,
      );
    } catch (_) {}
  }

  Future<void> _markAllRead() async {
    try {
      await ApiClient.instance.post('/api/tablet/notifications/read-all');
      setState(() {
        _items = _items.map((n) => n.copyWith(isRead: true)).toList();
      });
      NotificationsBadgeService.instance.setUnread(0);
    } catch (_) {}
  }

  @override
  Widget build(BuildContext context) {
    final unread = _items.where((e) => !e.isRead).length;

    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppHeader(
        pageTitle: 'سجل الإشعارات',
        onBack: () => Navigator.of(context).maybePop(),
        showOnlineChip: false,
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator(color: AppColors.goldDark))
          : _error != null
              ? Center(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(_error!, textAlign: TextAlign.center),
                      TextButton(onPressed: _load, child: const Text('إعادة المحاولة')),
                    ],
                  ),
                )
              : Column(
                  children: [
                    Padding(
                      padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
                      child: Row(
                        children: [
                          const Icon(Icons.notifications_none, color: AppColors.goldDark),
                          const SizedBox(width: 8),
                          Text(
                            'سجل الإشعارات',
                            style: AppTextStyles.cairo(
                              fontSize: 17,
                              fontWeight: FontWeight.w800,
                            ),
                          ),
                          const Spacer(),
                          if (_hasExercise && unread > 0)
                            TextButton(
                              onPressed: _markAllRead,
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
                    const Divider(height: 1),
                    Expanded(
                      child: !_hasExercise
                          ? const _EmptyCard(
                              text: 'لا يوجد تمرين حالي في نطاق عملك. أنشئ أو افتح تمريناً أولاً.',
                            )
                          : _items.isEmpty
                              ? const _EmptyCard(
                                  text: 'لا توجد إشعارات مسجّلة لهذا التمرين.',
                                )
                              : ListView.separated(
                                  padding: const EdgeInsets.all(16),
                                  itemCount: _items.length,
                                  separatorBuilder: (_, __) => const SizedBox(height: 10),
                                  itemBuilder: (context, i) {
                                    final n = _items[i];
                                    return FigmaPanel(
                                      padding: const EdgeInsets.all(14),
                                      child: InkWell(
                                        onTap: n.isRead ? null : () => _markRead(n.id),
                                        child: Column(
                                          crossAxisAlignment: CrossAxisAlignment.start,
                                          children: [
                                            Row(
                                              children: [
                                                Expanded(
                                                  child: Text(
                                                    n.title.isEmpty ? '—' : n.title,
                                                    style: AppTextStyles.cairo(
                                                      fontSize: 15,
                                                      fontWeight: FontWeight.w800,
                                                    ),
                                                  ),
                                                ),
                                                if (!n.isRead)
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
                                            Wrap(
                                              spacing: 8,
                                              runSpacing: 4,
                                              children: [
                                                _Chip(n.typeLabel),
                                                _Chip(n.priorityLabel),
                                                _Chip(n.isRead ? 'مقروء' : 'غير مقروء'),
                                              ],
                                            ),
                                            if (n.body.isNotEmpty) ...[
                                              const SizedBox(height: 8),
                                              Text(n.body, style: AppTextStyles.body),
                                            ],
                                            const SizedBox(height: 8),
                                            Text(
                                              n.createdAt.isEmpty ? '—' : n.createdAt,
                                              style: AppTextStyles.cairo(
                                                fontSize: 11,
                                                color: AppColors.muted,
                                              ),
                                            ),
                                            if (!n.isRead) ...[
                                              const SizedBox(height: 8),
                                              Align(
                                                alignment: Alignment.centerLeft,
                                                child: TextButton(
                                                  onPressed: () => _markRead(n.id),
                                                  child: Text(
                                                    'كمقروء',
                                                    style: AppTextStyles.cairo(
                                                      color: AppColors.goldDark,
                                                      fontWeight: FontWeight.w700,
                                                    ),
                                                  ),
                                                ),
                                              ),
                                            ],
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

class _EmptyCard extends StatelessWidget {
  const _EmptyCard({required this.text});
  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(16),
      child: FigmaPanel(
        padding: const EdgeInsets.all(18),
        child: Text(
          text,
          style: AppTextStyles.cairo(color: AppColors.muted, fontWeight: FontWeight.w600),
          textAlign: TextAlign.right,
        ),
      ),
    );
  }
}

class _Chip extends StatelessWidget {
  const _Chip(this.label);
  final String label;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: AppColors.headerCream,
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: AppColors.divider),
      ),
      child: Text(
        label,
        style: AppTextStyles.cairo(fontSize: 11, fontWeight: FontWeight.w700),
      ),
    );
  }
}
