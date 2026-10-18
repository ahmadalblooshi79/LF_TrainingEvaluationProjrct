import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../services/api_client.dart';
import '../services/auth_service.dart';
import '../services/device_reset_service.dart';
import '../services/sync_preferences.dart';
import '../services/sync_service.dart';
import '../theme/app_theme.dart';
import '../widgets/app_header.dart';
import '../widgets/online_status_chip.dart';

/// إعدادات — server address (LAN IP:port), connection test, sync status,
/// logout.
class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final _serverCtrl = TextEditingController();
  bool _testing = false;
  String? _testResult;
  bool _testOk = false;

  @override
  void initState() {
    super.initState();
    _serverCtrl.text = ApiClient.instance.baseUrl;
  }

  @override
  void dispose() {
    _serverCtrl.dispose();
    super.dispose();
  }

  Future<void> _applyServerUrl() async {
    final server = _serverCtrl.text.trim();
    if (server.isNotEmpty) {
      await ApiClient.instance.setBaseUrl(server);
    } else if (kIsWeb) {
      await ApiClient.instance.setBaseUrl(Uri.base.origin);
    } else {
      await ApiClient.instance.setBaseUrl(server);
    }
  }

  Future<void> _confirmDeviceReset(BuildContext context) async {
    final preview = await DeviceResetService.instance.preview();
    if (!context.mounted) return;
    final pendingNote = preview.hasUnsyncedWork
        ? '\n\nيوجد على الجهاز أعمال لم تتم مزامنتها مع السيرفر.\n'
            'إعادة ضبط الجهاز ستؤدي إلى حذف هذه الأعمال المحلية.'
        : '';
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('إعادة ضبط بيانات الجهاز'),
        content: Text(
          'سيتم حذف جميع البيانات المحلية الخاصة بالنظام من هذا الجهاز،\n'
          'بما في ذلك المستخدمون والبيانات المحفوظة وبيانات المزامنة المحلية.\n\n'
          'لن يتم حذف البيانات الموجودة على السيرفر أو النسخ الاحتياطية\n'
          'المحفوظة في Downloads.$pendingNote',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('إلغاء'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: Text(
              'إعادة ضبط الجهاز',
              style: AppTextStyles.small.copyWith(
                color: AppColors.notDoneRed,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
        ],
      ),
    );
    if (ok != true || !context.mounted) return;
    final result = await DeviceResetService.instance.resetLocalDevice();
    if (!context.mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(result.message)),
    );
    if (result.ok) context.go('/login');
  }

  Future<void> _save() async {
    await _applyServerUrl();
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('تم حفظ عنوان الخادم')));
  }

  Future<void> _test() async {
    setState(() {
      _testing = true;
      _testResult = null;
    });
    await _applyServerUrl();
    final target = ApiClient.instance.baseUrl;
    if (!mounted) return;
    setState(() => _serverCtrl.text = target);
    final ok = await ApiClient.instance.ping(
      timeout: const Duration(seconds: 10),
    );
    final detail = ApiClient.instance.lastPingDetail;
    if (!mounted) return;
    setState(() {
      _testing = false;
      _testOk = ok;
      _testResult = ok
          ? 'تم الاتصال بالخادم بنجاح ($target)'
          : 'تعذّر الاتصال بـ $target\n${detail.isNotEmpty ? detail : 'تحقّق من العنوان والشبكة والمنفذ'}';
    });
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthService>();
    return Scaffold(
      appBar: AppHeader(
        pageTitle: 'الإعدادات',
        showSettings: false,
        showLogout: false,
        onBack: () => Navigator.of(context).maybePop(),
      ),
      backgroundColor: AppColors.background,
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              kIsWeb ? 'عنوان الخادم (اختياري في PWA)' : 'عنوان الخادم',
              style: AppTextStyles.subtitle,
            ),
            const SizedBox(height: 8),
            TextField(
              controller: _serverCtrl,
              textDirection: TextDirection.ltr,
              decoration: const InputDecoration(
                hintText: kIsWeb ? 'فارغ = نفس السيرفر' : 'مثال: 192.168.1.10:8005',
              ),
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: _testing ? null : _test,
                    child: _testing
                        ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                        : const Text('اختبار الاتصال'),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(child: ElevatedButton(onPressed: _save, child: const Text('حفظ'))),
              ],
            ),
            if (_testResult != null) ...[
              const SizedBox(height: 10),
              Text(
                _testResult!,
                style: AppTextStyles.cairo(
                  color: _testOk ? AppColors.doneGreen : AppColors.notDoneRed,
                  fontWeight: FontWeight.w600,
                ),
                textAlign: TextAlign.center,
              ),
            ],
            const SizedBox(height: 28),
            Text('طريقة المزامنة', style: AppTextStyles.subtitle),
            const SizedBox(height: 8),
            ValueListenableBuilder<TabletSyncMode>(
              valueListenable: SyncPreferences.instance.mode,
              builder: (context, mode, _) {
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    RadioListTile<TabletSyncMode>(
                      contentPadding: EdgeInsets.zero,
                      title: Text(
                        'تلقائية (Wi‑Fi / Ethernet)',
                        style: AppTextStyles.body,
                      ),
                      subtitle: Text(
                        'عند الاتصال بشبكة محلية والوصول للسيرفر: رفع الأعمال وتنزيل التحديثات تلقائياً.',
                        style: AppTextStyles.small,
                      ),
                      value: TabletSyncMode.automatic,
                      groupValue: mode,
                      onChanged: (v) async {
                        if (v == null) return;
                        await SyncPreferences.instance.setMode(v);
                        if (v == TabletSyncMode.automatic) {
                          unawaited(SyncService.instance.runFullSync(silent: true));
                        }
                      },
                    ),
                    RadioListTile<TabletSyncMode>(
                      contentPadding: EdgeInsets.zero,
                      title: Text(
                        'يدوية',
                        style: AppTextStyles.body,
                      ),
                      subtitle: Text(
                        'لا مزامنة تلقائية — استخدم «إدارة المزامنة» عند الحاجة.',
                        style: AppTextStyles.small,
                      ),
                      value: TabletSyncMode.manual,
                      groupValue: mode,
                      onChanged: (v) async {
                        if (v == null) return;
                        await SyncPreferences.instance.setMode(v);
                      },
                    ),
                  ],
                );
              },
            ),
            const SizedBox(height: 28),
            Text('التوقيع الإلكتروني', style: AppTextStyles.subtitle),
            const SizedBox(height: 8),
            ElevatedButton.icon(
              onPressed: () => context.push('/signature'),
              icon: const Icon(Icons.draw_outlined, size: 20),
              label: const Text('التوقيع الإلكتروني'),
              style: ElevatedButton.styleFrom(
                backgroundColor: AppColors.buttonBrown,
                foregroundColor: AppColors.white,
                padding: const EdgeInsets.symmetric(vertical: 12),
              ),
            ),
            const SizedBox(height: 28),
            Text('حالة الاتصال والمزامنة', style: AppTextStyles.subtitle),
            const SizedBox(height: 12),
            const Align(alignment: Alignment.centerRight, child: OnlineStatusChip()),
            const SizedBox(height: 12),
            ValueListenableBuilder<int>(
              valueListenable: SyncService.instance.pendingCount,
              builder: (context, count, _) => Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text(
                    'عمليات بانتظار الرفع: $count',
                    style: AppTextStyles.body,
                  ),
                  const SizedBox(height: 10),
                  ElevatedButton.icon(
                    onPressed: () => context.push('/sync-status'),
                    icon: const Icon(Icons.sync, size: 20),
                    label: const Text('إدارة المزامنة'),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: AppColors.buttonBrown,
                      foregroundColor: AppColors.white,
                      padding: const EdgeInsets.symmetric(vertical: 12),
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 28),
            Text('النسخ الاحتياطي والاستعادة', style: AppTextStyles.subtitle),
            const SizedBox(height: 8),
            Text(
              'نسخة احتياطية للتمرين الحالي للمستخدم الحالي فقط.',
              style: AppTextStyles.small,
            ),
            const SizedBox(height: 10),
            OutlinedButton.icon(
              onPressed: () => context.push('/scoped-backup'),
              icon: const Icon(Icons.backup_outlined),
              label: const Text('النسخ الاحتياطي والاستعادة'),
            ),
            const SizedBox(height: 28),
            Text('إعادة ضبط بيانات الجهاز', style: AppTextStyles.subtitle),
            const SizedBox(height: 8),
            Text(
              'حذف البيانات المحلية لهذا الجهاز فقط. لا يُحذف شيء من السيرفر ولا من Downloads.',
              style: AppTextStyles.small,
            ),
            const SizedBox(height: 10),
            OutlinedButton.icon(
              key: const Key('device_reset_button'),
              onPressed: () => _confirmDeviceReset(context),
              icon: const Icon(Icons.restart_alt),
              label: const Text('إعادة ضبط بيانات الجهاز'),
            ),
            const SizedBox(height: 28),
            if (auth.session != null) ...[
              Text('الحساب', style: AppTextStyles.subtitle),
              const SizedBox(height: 8),
              Text(auth.session!.user.judgeDisplayName, style: AppTextStyles.body),
              Text(auth.session!.user.roleLabel, style: AppTextStyles.small),
              const SizedBox(height: 16),
              OutlinedButton.icon(
                onPressed: () async {
                  await context.read<AuthService>().logout();
                  if (context.mounted) context.go('/login');
                },
                icon: const Icon(Icons.logout),
                label: const Text('تسجيل الخروج'),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
