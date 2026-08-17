import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../services/api_client.dart';
import '../services/health_service.dart';
import '../services/package_sync_service.dart';
import '../theme/app_theme.dart';
import '../widgets/app_header.dart';

/// تهيئة الجهاز: دخول فني للسيرفر ثم تنزيل Exercise Package.
class DeviceSetupScreen extends StatefulWidget {
  const DeviceSetupScreen({super.key});

  @override
  State<DeviceSetupScreen> createState() => _DeviceSetupScreenState();
}

class _DeviceSetupScreenState extends State<DeviceSetupScreen> {
  final _formKey = GlobalKey<FormState>();
  final _userCtrl = TextEditingController();
  final _passCtrl = TextEditingController();
  bool _busy = false;
  String? _error;
  String? _info;

  @override
  void dispose() {
    _userCtrl.dispose();
    _passCtrl.dispose();
    super.dispose();
  }

  Future<void> _run() async {
    if (_busy) return;
    if (!(_formKey.currentState?.validate() ?? false)) return;
    await ApiClient.instance.init();
    if (ApiClient.instance.baseUrl.trim().isEmpty) {
      setState(() => _error = 'اضبط عنوان السيرفر أولاً من شاشة إدارة الجهاز');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
      _info = 'جارٍ اختبار الاتصال...';
    });
    final reachable = await HealthService.instance.check(force: true);
    if (!reachable) {
      setState(() {
        _busy = false;
        _error = 'السيرفر غير متاح';
        _info = null;
      });
      return;
    }
    setState(() => _info = 'جارٍ تسجيل الدخول لتهيئة الجهاز...');
    final logged = await PackageSyncService.instance.setupLogin(
      _userCtrl.text.trim(),
      _passCtrl.text,
    );
    if (!logged) {
      setState(() {
        _busy = false;
        _error = PackageSyncService.instance.lastError ?? 'فشل الدخول';
        _info = null;
      });
      return;
    }
    setState(() => _info = 'جارٍ تنزيل حزمة التمرين...');
    final ok = await PackageSyncService.instance.downloadAndStorePackage();
    if (!mounted) return;
    if (!ok) {
      setState(() {
        _busy = false;
        _error = PackageSyncService.instance.lastError ?? 'فشل تنزيل الحزمة';
        _info = null;
      });
      return;
    }
    setState(() {
      _busy = false;
      _info =
          'الجهاز جاهز — تم تخزين ${PackageSyncService.instance.lastJudgeCount} محكم محلياً.';
    });
    await Future<void>.delayed(const Duration(milliseconds: 800));
    if (mounted) context.pop(true);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppHeader(
        pageTitle: 'تهيئة الجهاز',
        showSettings: false,
        onBack: () => Navigator.of(context).maybePop(),
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Form(
          key: _formKey,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                'أدخل حساب فني من النظام الرئيسي (صلاحية تهيئة الأجهزة) '
                'لتنزيل حزمة التمرين إلى قاعدة البيانات المحلية.',
                style: AppTextStyles.body,
              ),
              const SizedBox(height: 16),
              TextFormField(
                controller: _userCtrl,
                decoration: const InputDecoration(labelText: 'اسم المستخدم (السيرفر)'),
                validator: (v) =>
                    (v == null || v.trim().isEmpty) ? 'مطلوب' : null,
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: _passCtrl,
                obscureText: true,
                decoration: const InputDecoration(labelText: 'كلمة المرور'),
                validator: (v) => (v == null || v.isEmpty) ? 'مطلوب' : null,
              ),
              const SizedBox(height: 20),
              ElevatedButton(
                onPressed: _busy ? null : _run,
                style: ElevatedButton.styleFrom(
                  backgroundColor: AppColors.buttonBrown,
                  foregroundColor: AppColors.white,
                  padding: const EdgeInsets.symmetric(vertical: 14),
                ),
                child: _busy
                    ? const SizedBox(
                        width: 22,
                        height: 22,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          color: AppColors.white,
                        ),
                      )
                    : const Text('اتصال وتنزيل الحزمة'),
              ),
              if (_info != null) ...[
                const SizedBox(height: 12),
                Text(
                  _info!,
                  style: AppTextStyles.cairo(
                    color: AppColors.olive,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
              if (_error != null) ...[
                const SizedBox(height: 12),
                Text(
                  _error!,
                  style: AppTextStyles.cairo(
                    color: AppColors.notDoneRed,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
