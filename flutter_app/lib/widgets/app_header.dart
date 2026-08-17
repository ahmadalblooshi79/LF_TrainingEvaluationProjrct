import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../services/auth_service.dart';
import '../services/notifications_badge_service.dart';
import '../services/sync_service.dart';
import '../theme/app_theme.dart';
import '../theme/device_layout.dart';
import 'online_status_chip.dart';

/// ترويسة التطبيق — الأدوات دائماً أقصى اليسار:
/// خروج | Home | Back | إعدادات | مكتبة | تنبيهات | رسائل
class AppHeader extends StatelessWidget implements PreferredSizeWidget {
  const AppHeader({
    super.key,
    required this.pageTitle,
    this.pageSubtitle,
    this.onBack,
    this.showLogout = true,
    this.showSettings = true,
    this.showOnlineChip = true,
    this.showUtilityActions = true,
    this.brandLine3,
  });

  final String pageTitle;
  final String? pageSubtitle;
  final VoidCallback? onBack;
  final bool showLogout;
  final bool showSettings;
  final bool showOnlineChip;
  final bool showUtilityActions;
  final String? brandLine3;

  @override
  Size get preferredSize =>
      Size.fromHeight(DeviceLayout.isPhoneBuild ? 108 : 96);

  @override
  Widget build(BuildContext context) {
    final session = context.watch<AuthService>().session;
    final unit = (pageSubtitle ?? session?.unitLabel ?? '').trim();
    final line3 = (brandLine3 ?? session?.exercise?.name ?? '').trim();
    final judgeName = (session?.user.judgeDisplayName.trim().isNotEmpty == true
            ? session!.user.judgeDisplayName
            : (session?.user.fullName ?? ''))
        .trim();

    final canPop = onBack != null || Navigator.of(context).canPop();
    final loc = GoRouterState.of(context).matchedLocation;
    final onHome = loc == '/home';
    final phone = DeviceLayout.isCompactHeader(context);

    final actions = <Widget>[
      if (showOnlineChip) const OnlineStatusChip(),
      ValueListenableBuilder<int>(
        valueListenable: SyncService.instance.pendingCount,
        builder: (_, count, __) {
          if (count <= 0) return const SizedBox.shrink();
          return Padding(
            padding: const EdgeInsets.only(left: 2),
            child: _SqIcon(
              icon: Icons.cloud_upload_outlined,
              badge: '$count',
              tooltip: 'بانتظار المزامنة',
              compact: phone,
              onTap: () => context.push('/sync-status'),
            ),
          );
        },
      ),
      if (showUtilityActions) ...[
        _SqIcon(
          icon: Icons.mail_outline,
          tooltip: 'الرسائل',
          compact: phone,
          onTap: () => context.push('/messages'),
        ),
        ValueListenableBuilder<int>(
          valueListenable: NotificationsBadgeService.instance.unreadCount,
          builder: (_, unread, __) {
            final badge = unread > 0
                ? (unread > 99 ? '99+' : '$unread')
                : null;
            return _SqIcon(
              icon: Icons.notifications_none,
              tooltip: unread > 0
                  ? 'سجل الإشعارات ($unread غير مقروء)'
                  : 'سجل الإشعارات',
              badge: badge,
              badgeColor: AppColors.notDoneRed,
              compact: phone,
              onTap: () => context.push('/notifications'),
            );
          },
        ),
        _SqIcon(
          icon: Icons.menu_book_outlined,
          tooltip: 'المكتبة',
          compact: phone,
          onTap: () => context.push('/library'),
        ),
      ],
      if (showSettings)
        _SqIcon(
          icon: Icons.settings_outlined,
          tooltip: 'الإعدادات',
          compact: phone,
          onTap: () => context.push('/settings'),
        ),
      if (canPop)
        _SqIcon(
          icon: Icons.arrow_forward,
          tooltip: 'رجوع',
          compact: phone,
          onTap: onBack ?? () => Navigator.of(context).maybePop(),
        ),
      if (!onHome)
        _SqIcon(
          icon: Icons.home_outlined,
          tooltip: 'الصفحة الرئيسية',
          compact: phone,
          onTap: () => context.go('/home'),
        ),
      if (showLogout)
        Padding(
          padding: const EdgeInsets.only(right: 2),
          child: Material(
            color: AppColors.headerCream,
            borderRadius: BorderRadius.circular(8),
            child: InkWell(
              borderRadius: BorderRadius.circular(8),
              onTap: () => context.read<AuthService>().logout(),
              child: Container(
                padding: EdgeInsets.symmetric(
                  horizontal: phone ? 8 : 10,
                  vertical: phone ? 6 : 8,
                ),
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: AppColors.divider),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(Icons.logout, size: 16, color: AppColors.olive),
                    if (!phone) ...[
                      const SizedBox(width: 4),
                      Text(
                        'خروج',
                        style: AppTextStyles.cairo(
                          fontSize: 12,
                          fontWeight: FontWeight.w700,
                          color: AppColors.olive,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ),
          ),
        ),
    ];

    return Material(
      color: AppColors.headerBar,
      elevation: 0.5,
      child: SafeArea(
        bottom: false,
        child: Container(
          padding: EdgeInsets.symmetric(
            horizontal: phone ? 8 : 10,
            vertical: phone ? 6 : 8,
          ),
          decoration: const BoxDecoration(
            border:
                Border(bottom: BorderSide(color: AppColors.divider, width: 1)),
          ),
          child: phone
              ? Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Row(
                      children: [
                        Image.asset(
                          'assets/images/uae_mod.png',
                          height: 36,
                          fit: BoxFit.contain,
                          errorBuilder: (_, __, ___) => const Icon(
                            Icons.shield,
                            size: 32,
                            color: AppColors.gold,
                          ),
                        ),
                        const SizedBox(width: 6),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                'التحكيم الذكي',
                                style: AppTextStyles.cairo(
                                  fontSize: 15,
                                  fontWeight: FontWeight.w800,
                                  color: AppColors.goldDark,
                                ),
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                              ),
                              Text(
                                pageTitle,
                                style: AppTextStyles.cairo(
                                  fontSize: 13,
                                  fontWeight: FontWeight.w800,
                                  color: AppColors.olive,
                                ),
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                              ),
                              if (judgeName.isNotEmpty || unit.isNotEmpty)
                                Text(
                                  [
                                    if (judgeName.isNotEmpty) judgeName,
                                    if (unit.isNotEmpty) unit,
                                  ].join(' — '),
                                  style: AppTextStyles.cairo(
                                    fontSize: 11,
                                    fontWeight: FontWeight.w600,
                                    color: AppColors.muted,
                                  ),
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                ),
                            ],
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 4),
                    Align(
                      alignment: Alignment.centerLeft,
                      child: SingleChildScrollView(
                        scrollDirection: Axis.horizontal,
                        reverse: true,
                        child: Row(children: actions),
                      ),
                    ),
                  ],
                )
              : SizedBox(
                  height: 88,
                  child: Row(
                    children: [
                      Image.asset(
                        'assets/images/uae_mod.png',
                        height: 52,
                        fit: BoxFit.contain,
                        errorBuilder: (_, __, ___) => const Icon(
                          Icons.shield,
                          size: 40,
                          color: AppColors.gold,
                        ),
                      ),
                      const SizedBox(width: 8),
                      Flexible(
                        flex: 3,
                        child: Column(
                          mainAxisAlignment: MainAxisAlignment.center,
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              'التحكيم الذكي',
                              style: AppTextStyles.cairo(
                                fontSize: 18,
                                fontWeight: FontWeight.w800,
                                color: AppColors.goldDark,
                              ),
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                            ),
                            Text(
                              'نظام إدارة التمارين',
                              style: AppTextStyles.cairo(
                                fontSize: 11,
                                fontWeight: FontWeight.w600,
                                color: AppColors.olive,
                              ),
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                            ),
                            if (line3.isNotEmpty)
                              Text(
                                line3,
                                style: AppTextStyles.cairo(
                                  fontSize: 10,
                                  color: AppColors.muted,
                                ),
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                              ),
                          ],
                        ),
                      ),
                      const SizedBox(width: 6),
                      Expanded(
                        flex: 4,
                        child: Column(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            Text(
                              pageTitle,
                              style: AppTextStyles.cairo(
                                fontSize: 17,
                                fontWeight: FontWeight.w800,
                                color: AppColors.olive,
                              ),
                              textAlign: TextAlign.center,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                            ),
                            if (judgeName.isNotEmpty)
                              Text(
                                judgeName,
                                style: AppTextStyles.cairo(
                                  fontSize: 13,
                                  fontWeight: FontWeight.w700,
                                  color: AppColors.goldDark,
                                ),
                                textAlign: TextAlign.center,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                              ),
                            if (unit.isNotEmpty)
                              Text(
                                unit,
                                style: AppTextStyles.cairo(
                                  fontSize: 11,
                                  fontWeight: FontWeight.w600,
                                  color: AppColors.muted,
                                ),
                                textAlign: TextAlign.center,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                              ),
                          ],
                        ),
                      ),
                      ...actions,
                    ],
                  ),
                ),
        ),
      ),
    );
  }
}

class _SqIcon extends StatelessWidget {
  const _SqIcon({
    required this.icon,
    required this.tooltip,
    required this.onTap,
    this.badge,
    this.badgeColor,
    this.compact = false,
  });

  final IconData icon;
  final String tooltip;
  final VoidCallback onTap;
  final String? badge;
  final Color? badgeColor;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final size = compact ? 34.0 : 40.0;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 2),
      child: Tooltip(
        message: tooltip,
        child: Material(
          color: AppColors.headerCream,
          borderRadius: BorderRadius.circular(8),
          child: InkWell(
            borderRadius: BorderRadius.circular(8),
            onTap: onTap,
            child: Container(
              width: size,
              height: size,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: AppColors.divider),
              ),
              child: Stack(
                clipBehavior: Clip.none,
                children: [
                  Icon(icon, size: compact ? 18 : 20, color: AppColors.olive),
                  if (badge != null)
                    Positioned(
                      left: -8,
                      top: -8,
                      child: Container(
                        constraints: const BoxConstraints(minWidth: 16),
                        padding: const EdgeInsets.symmetric(
                          horizontal: 4,
                          vertical: 1,
                        ),
                        decoration: BoxDecoration(
                          color: badgeColor ?? AppColors.gold,
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: Text(
                          badge!,
                          textAlign: TextAlign.center,
                          style: AppTextStyles.cairo(
                            fontSize: 9,
                            fontWeight: FontWeight.w800,
                            color: AppColors.white,
                          ),
                        ),
                      ),
                    ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
