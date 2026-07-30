import 'package:flutter/material.dart';

import '../services/api_client.dart';
import '../services/connectivity_service.dart';
import '../services/sync_service.dart';
import '../theme/app_theme.dart';

/// Reachability pill: prefers live API status over OS connectivity hint.
class OnlineStatusChip extends StatelessWidget {
  const OnlineStatusChip({super.key});

  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<bool>(
      valueListenable: ApiClient.instance.online,
      builder: (context, apiOnline, _) {
        return ValueListenableBuilder<bool>(
          valueListenable: ConnectivityService.instance.hasNetwork,
          builder: (context, hasNetwork, __) {
            return ValueListenableBuilder<int>(
              valueListenable: SyncService.instance.pendingCount,
              builder: (context, pending, ___) {
                final online = apiOnline && hasNetwork;
                final color = online ? AppColors.doneGreen : AppColors.notDoneRed;
                final label = online ? 'متصل' : 'غير متصل';
                return Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                  decoration: BoxDecoration(
                    color: color.withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(20),
                    border: Border.all(color: color, width: 1),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Container(
                        width: 8,
                        height: 8,
                        decoration: BoxDecoration(color: color, shape: BoxShape.circle),
                      ),
                      const SizedBox(width: 6),
                      Text(
                        pending > 0 ? '$label • $pending' : label,
                        style: AppTextStyles.cairo(
                          fontSize: 12,
                          color: color,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ],
                  ),
                );
              },
            );
          },
        );
      },
    );
  }
}
