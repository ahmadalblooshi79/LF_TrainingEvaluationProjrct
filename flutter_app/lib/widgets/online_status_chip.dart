import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../services/sync_service.dart';
import '../theme/app_theme.dart';

/// مؤشر واضح لحالة الاتصال والمزامنة.
class OnlineStatusChip extends StatelessWidget {
  const OnlineStatusChip({super.key});

  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<SyncUiState>(
      valueListenable: SyncService.instance.uiState,
      builder: (context, state, _) {
        return ValueListenableBuilder<int>(
          valueListenable: SyncService.instance.pendingCount,
          builder: (context, pending, __) {
            final (label, color) = _labelAndColor(state, pending);
            return InkWell(
              onTap: () => context.push('/sync-status'),
              borderRadius: BorderRadius.circular(20),
              child: Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                decoration: BoxDecoration(
                  color: color.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(20),
                  border: Border.all(color: color, width: 1),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    if (state == SyncUiState.syncing)
                      SizedBox(
                        width: 10,
                        height: 10,
                        child: CircularProgressIndicator(
                          strokeWidth: 1.5,
                          color: color,
                        ),
                      )
                    else
                      Container(
                        width: 8,
                        height: 8,
                        decoration:
                            BoxDecoration(color: color, shape: BoxShape.circle),
                      ),
                    const SizedBox(width: 6),
                    Text(
                      label,
                      style: AppTextStyles.cairo(
                        fontSize: 12,
                        color: color,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ],
                ),
              ),
            );
          },
        );
      },
    );
  }

  (String, Color) _labelAndColor(SyncUiState state, int pending) {
    switch (state) {
      case SyncUiState.online:
        return ('متصل بالسيرفر', AppColors.doneGreen);
      case SyncUiState.offline:
        return ('Offline Mode', AppColors.goldDark);
      case SyncUiState.pending:
        return ('بانتظار المزامنة • $pending', AppColors.goldDark);
      case SyncUiState.syncing:
        return ('جارٍ المزامنة • $pending', AppColors.olive);
      case SyncUiState.synced:
        return ('متصل بالسيرفر', AppColors.doneGreen);
      case SyncUiState.failed:
        return ('فشل المزامنة • $pending', AppColors.notDoneRed);
    }
  }
}
