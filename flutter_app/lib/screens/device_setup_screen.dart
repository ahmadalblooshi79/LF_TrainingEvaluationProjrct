import 'package:flutter/material.dart';

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
  bool _complete = false;
  double _progress = 0;
  String? _error;
  String? _info;

  @override
  void dispose() {
    _userCtrl.dispose();
    _passCtrl.dispose();
    super.dispose();
  }

  Future<void> _run() async {
    if (_busy || _complete) return;
    if (!(_formKey.currentState?.validate() ?? false)) return;
    await ApiClient.instance.init();
    if (ApiClient.instance.baseUrl.trim().isEmpty) {
      setState(() => _error = 'اضبط عنوان السيرفر أولاً من شاشة إدارة الجهاز');
      return;
    }
    setState(() {
      _busy = true;
      _complete = false;
      _progress = 0;
      _error = null;
      _info = 'جارٍ اختبار الاتصال...';
    });
    final reachable = await HealthService.instance.ensureReachableForSync();
    if (!reachable) {
      final detail = ApiClient.instance.lastPingDetail;
      setState(() {
        _busy = false;
        _error = detail.isNotEmpty
            ? 'تعذر الاتصال بالسيرفر. تحقق من كابل الشبكة وحاول مرة أخرى.\n$detail'
            : 'تعذر الاتصال بالسيرفر. تحقق من كابل الشبكة وحاول مرة أخرى.';
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
    setState(() {
      _info = 'الاتصال بالسيرفر';
      _progress = 0.02;
    });
    final ok = await PackageSyncService.instance.downloadAndStorePackage(
      onProgress: (m, {progress}) {
        if (!mounted) return;
        setState(() {
          _info = m;
          if (progress != null) _progress = progress;
        });
      },
    );
    if (!mounted) return;
    if (!ok) {
      setState(() {
        _busy = false;
        _error = PackageSyncService.instance.lastError ?? 'فشل تنزيل الحزمة';
      });
      return;
    }
    setState(() {
      _busy = false;
      _complete = true;
      _progress = 1;
      _info = 'اكتمال التهيئة';
    });
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
      body: Column(
        children: [
          Directionality(
            textDirection: TextDirection.rtl,
            child: LinearProgressIndicator(
              value: _busy || _complete ? _progress.clamp(0, 1) : 0,
              minHeight: 10,
              backgroundColor: const Color(0xFFE6DDCC),
              color: _complete ? AppColors.doneGreen : AppColors.goldDark,
            ),
          ),
          Expanded(
            child: SingleChildScrollView(
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
                      enabled: !_complete,
                      decoration: const InputDecoration(
                        labelText: 'اسم المستخدم (السيرفر)',
                      ),
                      validator: (v) =>
                          (v == null || v.trim().isEmpty) ? 'مطلوب' : null,
                    ),
                    const SizedBox(height: 12),
                    TextFormField(
                      controller: _passCtrl,
                      enabled: !_complete,
                      obscureText: true,
                      decoration: const InputDecoration(labelText: 'كلمة المرور'),
                      validator: (v) =>
                          (v == null || v.isEmpty) ? 'مطلوب' : null,
                    ),
                    const SizedBox(height: 20),
                    ElevatedButton(
                      onPressed: (_busy || _complete) ? null : _run,
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
                      const SizedBox(height: 16),
                      Text(
                        _info!,
                        textAlign: TextAlign.center,
                        style: AppTextStyles.cairo(
                          color: _complete
                              ? AppColors.doneGreen
                              : AppColors.olive,
                          fontWeight: FontWeight.w800,
                          fontSize: _complete ? 22 : 16,
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
          ),
        ],
      ),
    );
  }
}
