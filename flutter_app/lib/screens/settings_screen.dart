import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../services/api_client.dart';
import '../services/auth_service.dart';
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
            Text('حالة الاتصال والمزامنة', style: AppTextStyles.subtitle),
            const SizedBox(height: 12),
            const Align(alignment: Alignment.centerRight, child: OnlineStatusChip()),
            const SizedBox(height: 12),
            ValueListenableBuilder<int>(
              valueListenable: SyncService.instance.pendingCount,
              builder: (context, count, _) => Row(
                children: [
                  Expanded(
                    child: Text(
                      'عمليات بانتظار الرفع: $count',
                      style: AppTextStyles.body,
                    ),
                  ),
                  TextButton(
                    onPressed: () => context.push('/sync-status'),
                    child: const Text('إدارة المزامنة'),
                  ),
                ],
              ),
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
