import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../services/health_service.dart';
import '../services/offline_store.dart';
import '../services/sync_service.dart';
import '../theme/app_theme.dart';
import '../widgets/app_header.dart';

/// نافذة حالة المزامنة والعمليات المعلقة.
class SyncStatusScreen extends StatefulWidget {
  const SyncStatusScreen({super.key});

  @override
  State<SyncStatusScreen> createState() => _SyncStatusScreenState();
}

class _SyncStatusScreenState extends State<SyncStatusScreen> {
  List<PendingOp> _ops = [];
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _reload();
  }

  Future<void> _reload() async {
    setState(() => _loading = true);
    final ops = await OfflineStore.instance.pendingOps();
    if (!mounted) return;
    setState(() {
      _ops = ops;
      _loading = false;
    });
  }

  Future<void> _retry() async {
    await HealthService.instance.check(force: true);
    await SyncService.instance.flush();
    await _reload();
  }

  String _statusLabel(SyncUiState s) {
    switch (s) {
      case SyncUiState.online:
        return 'متصل بالسيرفر';
      case SyncUiState.offline:
        return 'وضع عدم الاتصال';
      case SyncUiState.pending:
        return 'عمليات بانتظار المزامنة';
      case SyncUiState.syncing:
        return 'جارٍ المزامنة';
      case SyncUiState.synced:
        return 'تمت المزامنة';
      case SyncUiState.failed:
        return 'فشل المزامنة';
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppHeader(
        pageTitle: 'حالة المزامنة',
        showSettings: false,
        onBack: () => Navigator.of(context).maybePop(),
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(16),
            child: ValueListenableBuilder<SyncUiState>(
              valueListenable: SyncService.instance.uiState,
              builder: (_, state, __) {
                return ValueListenableBuilder<int>(
                  valueListenable: SyncService.instance.pendingCount,
                  builder: (_, pending, ___) {
                    return Container(
                      width: double.infinity,
                      padding: const EdgeInsets.all(14),
                      decoration: BoxDecoration(
                        color: AppColors.cardWhite,
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(color: AppColors.divider),
                      ),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          Text(
                            _statusLabel(state),
                            style: AppTextStyles.cairo(
                              fontSize: 16,
                              fontWeight: FontWeight.w800,
                              color: AppColors.olive,
                            ),
                          ),
                          const SizedBox(height: 6),
                          Text(
                            'عدد العمليات المعلقة: $pending',
                            style: AppTextStyles.small,
                          ),
                          ValueListenableBuilder<String?>(
                            valueListenable: SyncService.instance.lastError,
                            builder: (_, err, __) {
                              if (err == null || err.isEmpty) {
                                return const SizedBox.shrink();
                              }
                              return Padding(
                                padding: const EdgeInsets.only(top: 8),
                                child: Text(
                                  err,
                                  style: AppTextStyles.cairo(
                                    fontSize: 12,
                                    color: AppColors.notDoneRed,
                                  ),
                                ),
                              );
                            },
                          ),
                          const SizedBox(height: 12),
                          ElevatedButton.icon(
                            onPressed: _retry,
                            icon: const Icon(Icons.sync, size: 18),
                            label: const Text('إعادة المحاولة'),
                            style: ElevatedButton.styleFrom(
                              backgroundColor: AppColors.buttonBrown,
                              foregroundColor: AppColors.white,
                            ),
                          ),
                        ],
                      ),
                    );
                  },
                );
              },
            ),
          ),
          Expanded(
            child: _loading
                ? const Center(child: CircularProgressIndicator())
                : _ops.isEmpty
                    ? Center(
                        child: Text(
                          'لا توجد عمليات معلقة',
                          style: AppTextStyles.body,
                        ),
                      )
                    : ListView.separated(
                        padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
                        itemCount: _ops.length,
                        separatorBuilder: (_, __) => const SizedBox(height: 8),
                        itemBuilder: (_, i) {
                          final op = _ops[i];
                          return Container(
                            padding: const EdgeInsets.all(12),
                            decoration: BoxDecoration(
                              color: AppColors.cardWhite,
                              borderRadius: BorderRadius.circular(10),
                              border: Border.all(color: AppColors.divider),
                            ),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.stretch,
                              children: [
                                Text(
                                  op.kind.isNotEmpty ? op.kind : op.opType,
                                  style: AppTextStyles.cairo(
                                    fontWeight: FontWeight.w700,
                                  ),
                                ),
                                const SizedBox(height: 4),
                                Text(
                                  'الحالة: ${op.syncStatus} • محاولات: ${op.attempts}',
                                  style: AppTextStyles.small,
                                ),
                                Text(
                                  'الوقت: ${op.createdAt}',
                                  style: AppTextStyles.cairo(
                                    fontSize: 11,
                                    color: AppColors.muted,
                                  ),
                                ),
                                if (op.lastError != null &&
                                    op.lastError!.isNotEmpty)
                                  Padding(
                                    padding: const EdgeInsets.only(top: 6),
                                    child: Text(
                                      op.lastError!,
                                      style: AppTextStyles.cairo(
                                        fontSize: 11,
                                        color: AppColors.notDoneRed,
                                      ),
                                    ),
                                  ),
                              ],
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

/// اختصار للتنقل من الرأس.
void openSyncStatusScreen(BuildContext context) {
  context.push('/sync-status');
}
