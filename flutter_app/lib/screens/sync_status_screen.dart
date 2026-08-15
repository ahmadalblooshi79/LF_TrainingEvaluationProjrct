import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';

import '../services/auth_service.dart';
import '../services/health_service.dart';
import '../services/media_upload_service.dart';
import '../services/offline_store.dart';
import '../services/package_sync_service.dart';
import '../services/sync_service.dart';
import '../theme/app_theme.dart';
import '../widgets/app_header.dart';

/// مركز المزامنة الشخصية للمحكم (Manual Sync Only).
class SyncStatusScreen extends StatefulWidget {
  const SyncStatusScreen({super.key});

  @override
  State<SyncStatusScreen> createState() => _SyncStatusScreenState();
}

class _SyncStatusScreenState extends State<SyncStatusScreen> {
  List<PendingOp> _ops = [];
  bool _loading = true;
  bool _busy = false;
  String? _actionMsg;
  bool _actionOk = false;
  DateTime? _lastSync;
  String _exerciseName = '—';
  Map<String, int> _mediaStats = const {};

  String _fmtBytes(int b) {
    if (b < 1024) return '$b B';
    if (b < 1024 * 1024) return '${(b / 1024).toStringAsFixed(1)} KB';
    if (b < 1024 * 1024 * 1024) {
      return '${(b / (1024 * 1024)).toStringAsFixed(1)} MB';
    }
    return '${(b / (1024 * 1024 * 1024)).toStringAsFixed(2)} GB';
  }

  @override
  void initState() {
    super.initState();
    MediaUploadService.instance.fileProgress.addListener(_onProg);
    MediaUploadService.instance.overallUploaded.addListener(_onProg);
    MediaUploadService.instance.overallTotal.addListener(_onProg);
    _reload();
  }

  void _onProg() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    MediaUploadService.instance.fileProgress.removeListener(_onProg);
    MediaUploadService.instance.overallUploaded.removeListener(_onProg);
    MediaUploadService.instance.overallTotal.removeListener(_onProg);
    super.dispose();
  }

  Future<void> _reload() async {
    setState(() => _loading = true);
    final uid = AuthService.instance.currentUserId;
    final ops = await OfflineStore.instance.pendingOps(userId: uid);
    final last = await AuthService.loadLastSyncAt();
    final session = AuthService.instance.session;
    final ex = session?.exercise?.name;
    final stats = await OfflineStore.instance.mediaStorageStats();
    await MediaUploadService.instance.refreshOverallFromDb();
    if (!mounted) return;
    setState(() {
      _ops = ops;
      _loading = false;
      _lastSync = last ?? SyncService.instance.lastSuccessAt.value;
      _exerciseName = (ex != null && ex.isNotEmpty) ? ex : '—';
      _mediaStats = stats;
    });
    await SyncService.instance.refreshPendingCount();
  }

  Future<void> _updateMyData() async {
    setState(() {
      _busy = true;
      _actionMsg = null;
    });
    final ok = await PackageSyncService.instance.updateMyData();
    if (!mounted) return;
    setState(() {
      _busy = false;
      _actionOk = ok;
      _actionMsg = ok
          ? 'تم تحديث بياناتي من السيرفر'
          : (PackageSyncService.instance.lastError ?? 'فشل التحديث');
    });
    await _reload();
  }

  Future<void> _syncMyWork() async {
    setState(() {
      _busy = true;
      _actionMsg = null;
    });
    await HealthService.instance.check(force: true);
    await SyncService.instance.flush();
    if (!mounted) return;
    final err = SyncService.instance.lastError.value;
    setState(() {
      _busy = false;
      _actionOk = err == null || err.isEmpty;
      _actionMsg = _actionOk
          ? 'تم رفع أعمالي المعلقة'
          : (err ?? 'فشل الرفع');
    });
    await _reload();
  }

  Future<void> _syncAll() async {
    setState(() {
      _busy = true;
      _actionMsg = null;
    });
    await HealthService.instance.check(force: true);
    await SyncService.instance.flush();
    final upErr = SyncService.instance.lastError.value;
    final downOk = await PackageSyncService.instance.updateMyData();
    if (!mounted) return;
    final ok = (upErr == null || upErr.isEmpty) && downOk;
    setState(() {
      _busy = false;
      _actionOk = ok;
      _actionMsg = ok
          ? 'اكتملت المزامنة الكاملة (رفع ثم تنزيل)'
          : [
              if (upErr != null && upErr.isNotEmpty) 'رفع: $upErr',
              if (!downOk)
                'تنزيل: ${PackageSyncService.instance.lastError ?? 'فشل'}',
            ].join('\n');
    });
    await _reload();
  }

  String _fmt(DateTime? at) {
    if (at == null) return '—';
    return DateFormat('dd-MM-yyyy HH:mm').format(at);
  }

  @override
  Widget build(BuildContext context) {
    final online = HealthService.instance.serverReachable.value;
    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppHeader(
        pageTitle: 'إدارة المزامنة',
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
                            online ? 'Server Connected' : 'Offline',
                            style: AppTextStyles.cairo(
                              fontSize: 16,
                              fontWeight: FontWeight.w800,
                              color: AppColors.olive,
                            ),
                          ),
                          const SizedBox(height: 6),
                          Text(
                            'Connection: ${online ? 'Online' : 'Offline'}',
                            style: AppTextStyles.small,
                          ),
                          Text(
                            'Pending Uploads: $pending',
                            style: AppTextStyles.small,
                          ),
                          Text(
                            'Pending Images: ${_mediaStats['pending_images'] ?? 0}',
                            style: AppTextStyles.small,
                          ),
                          Text(
                            'Pending Videos: ${_mediaStats['pending_videos'] ?? 0}',
                            style: AppTextStyles.small,
                          ),
                          Text(
                            'Total Pending Size: ${_fmtBytes(_mediaStats['pending_bytes'] ?? 0)}',
                            style: AppTextStyles.small,
                          ),
                          ValueListenableBuilder<int>(
                            valueListenable:
                                MediaUploadService.instance.overallTotal,
                            builder: (_, tot, __) {
                              final up = MediaUploadService
                                  .instance.overallUploaded.value;
                              if (tot <= 0) return const SizedBox.shrink();
                              final pct = ((up / tot) * 100).clamp(0, 100);
                              return Padding(
                                padding: const EdgeInsets.only(top: 8),
                                child: Column(
                                  crossAxisAlignment:
                                      CrossAxisAlignment.stretch,
                                  children: [
                                    Text(
                                      'Overall Sync: ${_fmtBytes(up)} / ${_fmtBytes(tot)} (${pct.toStringAsFixed(0)}%)',
                                      style: AppTextStyles.cairo(
                                        fontSize: 12,
                                        fontWeight: FontWeight.w700,
                                      ),
                                    ),
                                    const SizedBox(height: 4),
                                    LinearProgressIndicator(
                                      value: tot == 0 ? 0 : up / tot,
                                      minHeight: 6,
                                      backgroundColor: AppColors.divider,
                                      color: AppColors.olive,
                                    ),
                                  ],
                                ),
                              );
                            },
                          ),
                          ValueListenableBuilder<List<MediaUploadProgress>>(
                            valueListenable:
                                MediaUploadService.instance.fileProgress,
                            builder: (_, items, __) {
                              if (items.isEmpty) {
                                return const SizedBox.shrink();
                              }
                              return Column(
                                children: items.take(5).map((it) {
                                  return Padding(
                                    padding: const EdgeInsets.only(top: 6),
                                    child: Column(
                                      crossAxisAlignment:
                                          CrossAxisAlignment.stretch,
                                      children: [
                                        Text(
                                          '${it.label}: ${_fmtBytes(it.uploadedBytes)} / ${_fmtBytes(it.totalBytes)} (${(it.fraction * 100).toStringAsFixed(0)}%)',
                                          style: AppTextStyles.cairo(
                                            fontSize: 11,
                                          ),
                                        ),
                                        LinearProgressIndicator(
                                          value: it.fraction,
                                          minHeight: 4,
                                        ),
                                      ],
                                    ),
                                  );
                                }).toList(),
                              );
                            },
                          ),
                          Text(
                            'Last Upload/Sync: ${_fmt(_lastSync)}',
                            style: AppTextStyles.small,
                          ),
                          Text(
                            'Current Exercise: $_exerciseName',
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
                          if (_actionMsg != null) ...[
                            const SizedBox(height: 8),
                            Text(
                              _actionMsg!,
                              style: AppTextStyles.cairo(
                                fontSize: 12,
                                color: _actionOk
                                    ? AppColors.doneGreen
                                    : AppColors.notDoneRed,
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                          ],
                          const SizedBox(height: 12),
                          ElevatedButton.icon(
                            onPressed: _busy ? null : _updateMyData,
                            icon: const Icon(Icons.cloud_download, size: 18),
                            label: const Text('Update My Data'),
                            style: ElevatedButton.styleFrom(
                              backgroundColor: AppColors.buttonBrown,
                              foregroundColor: AppColors.white,
                            ),
                          ),
                          const SizedBox(height: 8),
                          ElevatedButton.icon(
                            onPressed: _busy ? null : _syncMyWork,
                            icon: const Icon(Icons.cloud_upload, size: 18),
                            label: const Text('Sync My Work'),
                            style: ElevatedButton.styleFrom(
                              backgroundColor: AppColors.olive,
                              foregroundColor: AppColors.white,
                            ),
                          ),
                          const SizedBox(height: 8),
                          OutlinedButton.icon(
                            onPressed: _busy ? null : _syncAll,
                            icon: const Icon(Icons.sync, size: 18),
                            label: const Text('Sync All My Data'),
                          ),
                          const SizedBox(height: 8),
                          Row(
                            children: [
                              Expanded(
                                child: OutlinedButton(
                                  onPressed: () {
                                    MediaUploadService.instance.pause();
                                    setState(() {
                                      _actionMsg = 'تم طلب إيقاف الرفع مؤقتاً';
                                      _actionOk = true;
                                    });
                                  },
                                  child: const Text('Pause'),
                                ),
                              ),
                              const SizedBox(width: 8),
                              Expanded(
                                child: OutlinedButton(
                                  onPressed: _busy
                                      ? null
                                      : () async {
                                          MediaUploadService.instance
                                              .clearPauseFlags();
                                          await _syncMyWork();
                                        },
                                  child: const Text('Resume'),
                                ),
                              ),
                              const SizedBox(width: 8),
                              Expanded(
                                child: OutlinedButton(
                                  onPressed: () {
                                    MediaUploadService.instance.requestCancel();
                                    setState(() {
                                      _actionMsg =
                                          'تم طلب إلغاء الرفع الحالي (الملف المحلي يبقى)';
                                      _actionOk = true;
                                    });
                                  },
                                  child: const Text('Cancel'),
                                ),
                              ),
                            ],
                          ),
                          if (!kIsWeb)
                            Padding(
                              padding: const EdgeInsets.only(top: 8),
                              child: Text(
                                'لا يتم رفع أي تقييم تلقائياً عند عودة WiFi.',
                                style: AppTextStyles.cairo(
                                  fontSize: 11,
                                  color: AppColors.muted,
                                ),
                                textAlign: TextAlign.center,
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

void openSyncStatusScreen(BuildContext context) {
  context.push('/sync-status');
}
