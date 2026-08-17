import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../services/api_client.dart';
import '../services/device_admin_service.dart';
import '../services/health_service.dart';
import '../services/media_upload_service.dart';
import '../services/offline_store.dart';
import '../services/package_sync_service.dart';
import '../theme/app_theme.dart';
import '../widgets/app_header.dart';
import '../widgets/online_status_chip.dart';

/// مركز إدارة الجهاز لـ Local Device Admin فقط.
class DeviceAdminHubScreen extends StatefulWidget {
  const DeviceAdminHubScreen({super.key});

  @override
  State<DeviceAdminHubScreen> createState() => _DeviceAdminHubScreenState();
}

class _DeviceAdminHubScreenState extends State<DeviceAdminHubScreen> {
  bool _busy = false;
  String? _msg;
  bool _msgOk = false;
  int _userCount = 0;
  int _pendingAll = 0;
  String? _lastPackage;
  String _serverHint = '';

  @override
  void initState() {
    super.initState();
    _reload();
  }

  Future<void> _reload() async {
    await ApiClient.instance.init();
    final users = await OfflineStore.instance.allLocalUsers();
    final pending = await OfflineStore.instance.pendingOpsCount();
    final last = await DeviceAdminService.instance.lastPackageAt();
    if (!mounted) return;
    setState(() {
      _userCount = users.length;
      _pendingAll = pending;
      _lastPackage = last;
      _serverHint = ApiClient.instance.baseUrl.trim().isEmpty
          ? 'لم يُضبط'
          : ApiClient.instance.baseUrl;
    });
  }

  Future<void> _testConn() async {
    setState(() {
      _busy = true;
      _msg = null;
    });
    final ok = await HealthService.instance.check(force: true);
    if (!mounted) return;
    setState(() {
      _busy = false;
      _msgOk = ok;
      _msg = ok ? 'السيرفر متاح' : 'السيرفر غير متاح';
    });
  }

  Future<void> _logout() async {
    await DeviceAdminService.instance.logout();
    if (mounted) context.go('/login');
  }

  Future<void> _resetDevice() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('إعادة ضبط بيانات الجهاز'),
        content: const Text(
          'سيتم مسح كل البيانات المحلية (المستخدمون، القوائم، الطابور، '
          'وحالة التهيئة). لا يمكن التراجع.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('إلغاء'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: Text(
              'مسح الكل',
              style: AppTextStyles.small.copyWith(
                color: AppColors.notDoneRed,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    await OfflineStore.instance.clearAll();
    await DeviceAdminService.instance.clearDeviceReady();
    await DeviceAdminService.instance.ensureDefaultAdmin();
    await _reload();
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('تم إعادة ضبط بيانات الجهاز')),
    );
  }

  @override
  Widget build(BuildContext context) {
    final admin = context.watch<DeviceAdminService>();
    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: const AppHeader(
        pageTitle: 'إدارة الجهاز',
        showSettings: false,
        showLogout: false,
        showUtilityActions: false,
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Row(
            children: [
              const OnlineStatusChip(),
              const Spacer(),
              Text(
                admin.isDeviceReady ? 'الجهاز جاهز' : 'يلزم تهيئة الجهاز',
                style: AppTextStyles.cairo(
                  fontWeight: FontWeight.w700,
                  color: admin.isDeviceReady
                      ? AppColors.doneGreen
                      : AppColors.notDoneRed,
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          _card(
            children: [
              Text('Device Sync', style: AppTextStyles.subtitle),
              const SizedBox(height: 8),
              Text('السيرفر: $_serverHint', style: AppTextStyles.small),
              Text('المستخدمون المحليون: $_userCount', style: AppTextStyles.small),
              Text('عمليات معلقة (الجهاز): $_pendingAll', style: AppTextStyles.small),
              Text(
                'آخر تنزيل حزمة: ${_lastPackage ?? '—'}',
                style: AppTextStyles.small,
              ),
              if (_msg != null) ...[
                const SizedBox(height: 8),
                Text(
                  _msg!,
                  style: AppTextStyles.cairo(
                    color: _msgOk ? AppColors.doneGreen : AppColors.notDoneRed,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
            ],
          ),
          const SizedBox(height: 12),
          ElevatedButton.icon(
            onPressed: _busy ? null : () => context.push('/server-connect'),
            icon: const Icon(Icons.dns_outlined),
            label: const Text('إعداد عنوان السيرفر'),
          ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            onPressed: _busy ? null : _testConn,
            icon: const Icon(Icons.wifi_tethering),
            label: const Text('اختبار الاتصال'),
          ),
          const SizedBox(height: 8),
          ElevatedButton.icon(
            onPressed: _busy
                ? null
                : () async {
                    await context.push('/device-setup');
                    await _reload();
                  },
            icon: const Icon(Icons.cloud_download_outlined),
            label: const Text('تهيئة الجهاز / تنزيل حزمة التمرين'),
            style: ElevatedButton.styleFrom(
              backgroundColor: AppColors.buttonBrown,
              foregroundColor: AppColors.white,
            ),
          ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            onPressed: _busy
                ? null
                : () async {
                    setState(() {
                      _busy = true;
                      _msg = null;
                    });
                    final ok =
                        await PackageSyncService.instance.downloadAndStorePackage();
                    if (!mounted) return;
                    setState(() {
                      _busy = false;
                      _msgOk = ok;
                      _msg = ok
                          ? 'تم تحديث الحزمة (${PackageSyncService.instance.lastJudgeCount} محكم)'
                          : (PackageSyncService.instance.lastError ?? 'فشل التحديث');
                    });
                    await _reload();
                  },
            icon: const Icon(Icons.sync),
            label: const Text('تحديث حزمة التمرين (Device Sync)'),
          ),
          const SizedBox(height: 24),
          Text(
            'مدير الجهاز لا يستطيع فتح تقييمات المحكمين أو تعديلها.',
            style: AppTextStyles.cairo(fontSize: 12, color: AppColors.muted),
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: 12),
          TextButton(
            onPressed: _busy ? null : _resetDevice,
            child: Text(
              'إعادة ضبط بيانات الجهاز',
              style: AppTextStyles.small.copyWith(color: AppColors.notDoneRed),
            ),
          ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            onPressed: _busy
                ? null
                : () async {
                    final stats =
                        await OfflineStore.instance.mediaStorageStats();
                    final free =
                        await MediaUploadService.instance.freeDiskBytes();
                    if (!mounted) return;
                    String fmt(int b) {
                      if (b < 1024 * 1024) {
                        return '${(b / 1024).toStringAsFixed(1)} KB';
                      }
                      if (b < 1024 * 1024 * 1024) {
                        return '${(b / (1024 * 1024)).toStringAsFixed(1)} MB';
                      }
                      return '${(b / (1024 * 1024 * 1024)).toStringAsFixed(2)} GB';
                    }
                    await showDialog<void>(
                      context: context,
                      builder: (ctx) => AlertDialog(
                        title: const Text('Manage Local Storage'),
                        content: Text(
                          'Pending Media: ${fmt(stats['pending_bytes'] ?? 0)}\n'
                          'Synced Media: ${fmt(stats['synced_bytes'] ?? 0)}\n'
                          'Available Storage: ${free == null ? '—' : fmt(free)}',
                        ),
                        actions: [
                          TextButton(
                            onPressed: () => Navigator.pop(ctx),
                            child: const Text('إغلاق'),
                          ),
                          TextButton(
                            onPressed: () async {
                              final n = await OfflineStore.instance
                                  .deleteSyncedMediaFiles();
                              if (ctx.mounted) Navigator.pop(ctx);
                              if (!mounted) return;
                              ScaffoldMessenger.of(context).showSnackBar(
                                SnackBar(
                                  content: Text(
                                    'تم حذف $n ملفاً متزامناً من الجهاز',
                                  ),
                                ),
                              );
                            },
                            child: const Text('Delete Synced Media'),
                          ),
                        ],
                      ),
                    );
                  },
            icon: const Icon(Icons.storage_outlined),
            label: const Text('Manage Local Storage'),
          ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            onPressed: _logout,
            icon: const Icon(Icons.logout),
            label: const Text('تسجيل خروج مدير الجهاز'),
          ),
          if (!kIsWeb) const SizedBox(height: 40),
        ],
      ),
    );
  }

  Widget _card({required List<Widget> children}) {
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
        children: children,
      ),
    );
  }
}
