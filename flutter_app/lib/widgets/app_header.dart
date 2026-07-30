import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../services/auth_service.dart';
import '../services/sync_service.dart';
import '../theme/app_theme.dart';
import 'online_status_chip.dart';

/// Figma shell header — brand | page title | square utility tiles.
class AppHeader extends StatelessWidget implements PreferredSizeWidget {
  const AppHeader({
    super.key,
    required this.pageTitle,
    this.pageSubtitle,
    this.onBack,
    this.showLogout = true,
    this.showSettings = true,
    this.showOnlineChip = true,
    this.brandLine3,
  });

  final String pageTitle;
  final String? pageSubtitle;
  final VoidCallback? onBack;
  final bool showLogout;
  final bool showSettings;
  final bool showOnlineChip;
  /// Optional third brand line under system name (e.g. exercise short name).
  final String? brandLine3;

  @override
  Size get preferredSize => const Size.fromHeight(92);

  @override
  Widget build(BuildContext context) {
    final session = context.watch<AuthService>().session;
    final unit = (pageSubtitle ?? session?.unitLabel ?? '').trim();
    final line3 = (brandLine3 ?? session?.exercise?.name ?? '').trim();

    return Material(
      color: AppColors.headerBar,
      elevation: 0.5,
      child: SafeArea(
        bottom: false,
        child: Container(
          height: 84,
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
          decoration: const BoxDecoration(
            border: Border(bottom: BorderSide(color: AppColors.divider, width: 1)),
          ),
          child: Row(
            children: [
              if (onBack != null)
                IconButton(
                  onPressed: onBack,
                  tooltip: 'رجوع',
                  icon: const Icon(Icons.arrow_forward_ios, size: 18, color: AppColors.olive),
                ),
              Image.asset(
                'assets/images/uae_mod.png',
                height: 56,
                fit: BoxFit.contain,
                errorBuilder: (_, __, ___) =>
                    const Icon(Icons.shield, size: 44, color: AppColors.gold),
              ),
              const SizedBox(width: 10),
              Flexible(
                flex: 3,
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'التحكيم الذكي',
                      style: AppTextStyles.cairo(
                        fontSize: 20,
                        fontWeight: FontWeight.w800,
                        color: AppColors.goldDark,
                      ),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                    Text(
                      'نظام إدارة التمارين',
                      style: AppTextStyles.cairo(
                        fontSize: 12,
                        fontWeight: FontWeight.w600,
                        color: AppColors.olive,
                      ),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                    if (line3.isNotEmpty)
                      Text(
                        line3,
                        style: AppTextStyles.cairo(fontSize: 10, color: AppColors.muted),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                flex: 4,
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Text(
                      pageTitle,
                      style: AppTextStyles.cairo(
                        fontSize: 18,
                        fontWeight: FontWeight.w800,
                        color: AppColors.olive,
                      ),
                      textAlign: TextAlign.center,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                    if (unit.isNotEmpty)
                      Text(
                        unit,
                        style: AppTextStyles.cairo(
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                          color: AppColors.goldDark,
                        ),
                        textAlign: TextAlign.center,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                  ],
                ),
              ),
              const SizedBox(width: 6),
              if (showOnlineChip) ...[
                const OnlineStatusChip(),
                const SizedBox(width: 6),
              ],
              ValueListenableBuilder<int>(
                valueListenable: SyncService.instance.pendingCount,
                builder: (_, count, __) {
                  if (count <= 0) return const SizedBox.shrink();
                  return Padding(
                    padding: const EdgeInsets.only(left: 4),
                    child: _SqIcon(
                      icon: Icons.cloud_upload_outlined,
                      badge: '$count',
                      tooltip: 'بانتظار المزامنة',
                      onTap: () => SyncService.instance.flush(),
                    ),
                  );
                },
              ),
              _SqIcon(icon: Icons.mail_outline, badge: '1', tooltip: 'الرسائل', onTap: () {}),
              _SqIcon(icon: Icons.notifications_none, badge: '2', tooltip: 'التنبيهات', onTap: () {}),
              _SqIcon(icon: Icons.menu_book_outlined, tooltip: 'الدليل', onTap: () {}),
              if (showSettings)
                _SqIcon(
                  icon: Icons.settings_outlined,
                  tooltip: 'الإعدادات',
                  onTap: () => context.push('/settings'),
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
                        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                        decoration: BoxDecoration(
                          borderRadius: BorderRadius.circular(8),
                          border: Border.all(color: AppColors.divider),
                        ),
                        child: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            const Icon(Icons.logout, size: 16, color: AppColors.olive),
                            const SizedBox(width: 4),
                            Text(
                              'خروج',
                              style: AppTextStyles.cairo(
                                fontSize: 13,
                                fontWeight: FontWeight.w700,
                                color: AppColors.olive,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),
                ),
            ],
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
  });

  final IconData icon;
  final String tooltip;
  final VoidCallback onTap;
  final String? badge;

  @override
  Widget build(BuildContext context) {
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
              width: 40,
              height: 40,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: AppColors.divider),
              ),
              child: Stack(
                clipBehavior: Clip.none,
                children: [
                  Icon(icon, size: 20, color: AppColors.olive),
                  if (badge != null)
                    Positioned(
                      left: -8,
                      top: -8,
                      child: Container(
                        padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 1),
                        decoration: BoxDecoration(
                          color: AppColors.gold,
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: Text(
                          badge!,
                          style: AppTextStyles.cairo(
                            fontSize: 9,
                            fontWeight: FontWeight.w800,
                            color: AppColors.darkText,
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
