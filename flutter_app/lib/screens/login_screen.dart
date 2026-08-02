import 'dart:async';
import 'dart:ui' as ui show TextDirection;

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../services/api_client.dart';
import '../services/auth_service.dart';
import '../services/connectivity_service.dart';
import '../services/health_service.dart';
import '../services/tablet_repository.dart';
import '../theme/app_theme.dart';

const String kDisplayedAppVersion = '2.4.0';

enum _ConnBadge { connected, offlineMode, unreachable }

/// Login — Figma split: branding left, dark card right + IP button.
class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _formKey = GlobalKey<FormState>();
  final _userCtrl = TextEditingController();
  final _passCtrl = TextEditingController();
  bool _obscure = true;
  bool _submitting = false;
  bool _testingConn = false;
  String? _error;
  String? _info;
  String? _testHint;
  String _serverHint = '';
  bool _offlineReady = false;
  DateTime? _lastSyncAt;

  @override
  void initState() {
    super.initState();
    _refreshServerHint();
    _loadMeta();
    unawaited(HealthService.instance.start());
    HealthService.instance.serverReachable.addListener(_onHealthChanged);
    ConnectivityService.instance.hasNetwork.addListener(_onHealthChanged);
  }

  void _onHealthChanged() {
    if (mounted) setState(() {});
  }

  Future<void> _loadMeta() async {
    final sync = await AuthService.loadLastSyncAt();
    final offline = await AuthService.instance.hasOfflineCredentials();
    if (!mounted) return;
    setState(() {
      _lastSyncAt = sync;
      _offlineReady = offline;
    });
  }

  Future<void> _refreshServerHint() async {
    await ApiClient.instance.init();
    if (!mounted) return;
    final u = ApiClient.instance.baseUrl.trim();
    setState(() {
      _serverHint = u.isEmpty
          ? (kIsWeb ? 'نفس السيرفر (PWA)' : 'لم يُضبط عنوان السيرفر')
          : u;
    });
  }

  _ConnBadge get _badge {
    if (HealthService.instance.serverReachable.value) {
      return _ConnBadge.connected;
    }
    if (_offlineReady) return _ConnBadge.offlineMode;
    return _ConnBadge.unreachable;
  }

  @override
  void dispose() {
    HealthService.instance.serverReachable.removeListener(_onHealthChanged);
    ConnectivityService.instance.hasNetwork.removeListener(_onHealthChanged);
    _userCtrl.dispose();
    _passCtrl.dispose();
    super.dispose();
  }

  Future<void> _openServerConnect() async {
    final changed = await context.push<bool>('/server-connect');
    if (changed == true) {
      await _refreshServerHint();
      await HealthService.instance.check(force: true);
      await _loadMeta();
    }
  }

  Future<void> _testConnection() async {
    if (_testingConn) return;
    setState(() {
      _testingConn = true;
      _testHint = null;
    });
    await ApiClient.instance.init();
    final ok = await HealthService.instance.check(force: true);
    if (!mounted) return;
    setState(() {
      _testingConn = false;
      _testHint = ok ? '✅ تم الاتصال بالخادم' : '⚠️ سيتم العمل بوضع offline';
    });
  }

  Future<void> _submit() async {
    if (_submitting) return;
    if (!(_formKey.currentState?.validate() ?? false)) return;
    final auth = context.read<AuthService>();
    await ApiClient.instance.init();
    if (!kIsWeb && ApiClient.instance.baseUrl.trim().isEmpty) {
      final offlineOk =
          await AuthService.instance.canOfflineLoginAs(_userCtrl.text.trim());
      if (!offlineOk) {
        if (!mounted) return;
        setState(() => _error = 'اضبط عنوان السيرفر أولاً عبر زر «ربط السيرفر»');
        return;
      }
    }
    if (kIsWeb && ApiClient.instance.baseUrl.trim().isEmpty) {
      await ApiClient.instance.setBaseUrl(Uri.base.origin);
    }
    if (!mounted) return;
    setState(() {
      _submitting = true;
      _error = null;
      _info = null;
      _testHint = null;
    });
    final ok = await auth.login(_userCtrl.text.trim(), _passCtrl.text);
    if (!mounted) return;
    if (ok) {
      if (!auth.lastLoginWasOffline) {
        try {
          await TabletRepository.instance.prefetchForOffline();
        } catch (_) {}
      }
      if (!mounted) return;
      await _loadMeta();
      if (!mounted) return;
      setState(() => _submitting = false);
      context.go('/home');
      return;
    }
    var err = auth.lastError ?? 'تعذر الاتصال بالخادم.';
    if (err.contains('مهلة')) {
      final offline = await AuthService.instance
          .canOfflineLoginAs(_userCtrl.text.trim());
      err = offline
          ? 'تعذر الاتصال بالخادم.\nسيتم العمل باستخدام البيانات المحلية.'
          : 'تعذر الاتصال بالخادم.';
    }
    setState(() {
      _submitting = false;
      _error = err;
    });
  }

  String _formatSync(DateTime? at) {
    if (at == null) return 'لم تتم أي مزامنة بعد';
    return 'آخر مزامنة:\n${DateFormat('dd-MM-yyyy HH:mm').format(at)}';
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.loginBg,
      body: SafeArea(
        child: OrientationBuilder(
          builder: (context, orientation) {
            final card = _LoginCard(
              formKey: _formKey,
              userCtrl: _userCtrl,
              passCtrl: _passCtrl,
              obscure: _obscure,
              onToggleObscure: () => setState(() => _obscure = !_obscure),
              submitting: _submitting,
              testingConn: _testingConn,
              error: _error,
              info: _info,
              testHint: _testHint,
              serverHint: _serverHint,
              badge: _badge,
              versionLabel: 'Version $kDisplayedAppVersion',
              syncLabel: _formatSync(_lastSyncAt),
              onSubmit: _submit,
              onServerConnect: _openServerConnect,
              onTestConnection: _testConnection,
            );
            if (orientation == Orientation.landscape) {
              return Row(
                children: [
                  const Expanded(flex: 5, child: _Branding()),
                  Expanded(flex: 5, child: Center(child: card)),
                ],
              );
            }
            return SingleChildScrollView(
              child: Column(
                children: [
                  const SizedBox(height: 210, child: _Branding()),
                  Padding(
                    padding: const EdgeInsets.fromLTRB(20, 8, 20, 24),
                    child: card,
                  ),
                ],
              ),
            );
          },
        ),
      ),
    );
  }
}

class _Branding extends StatelessWidget {
  const _Branding();

  @override
  Widget build(BuildContext context) {
    return Stack(
      alignment: Alignment.center,
      children: [
        Positioned(
          bottom: 40,
          child: Icon(Icons.star_border, size: 64, color: AppColors.gold.withValues(alpha: 0.35)),
        ),
        Padding(
          padding: const EdgeInsets.all(28),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Image.asset(
                'assets/images/uae_mod.png',
                width: 170,
                fit: BoxFit.contain,
                errorBuilder: (_, __, ___) =>
                    const Icon(Icons.shield, size: 100, color: AppColors.gold),
              ),
              const SizedBox(height: 22),
              Text(
                'نظام إدارة التمارين',
                style: AppTextStyles.cairo(
                  fontSize: 28,
                  fontWeight: FontWeight.w800,
                  color: AppColors.darkText,
                ),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 4),
              Text(
                'التحكيم الذكي',
                style: AppTextStyles.cairo(
                  fontSize: 26,
                  fontWeight: FontWeight.w800,
                  color: AppColors.goldDark,
                ),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 12),
              Text(
                'نحو تقييم دقيق واحترافي لدعم الجاهزية القتالية',
                style: AppTextStyles.cairo(fontSize: 13, color: AppColors.muted),
                textAlign: TextAlign.center,
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _LoginCard extends StatelessWidget {
  const _LoginCard({
    required this.formKey,
    required this.userCtrl,
    required this.passCtrl,
    required this.obscure,
    required this.onToggleObscure,
    required this.submitting,
    required this.testingConn,
    required this.error,
    required this.info,
    required this.testHint,
    required this.serverHint,
    required this.badge,
    required this.versionLabel,
    required this.syncLabel,
    required this.onSubmit,
    required this.onServerConnect,
    required this.onTestConnection,
  });

  final GlobalKey<FormState> formKey;
  final TextEditingController userCtrl;
  final TextEditingController passCtrl;
  final bool obscure;
  final VoidCallback onToggleObscure;
  final bool submitting;
  final bool testingConn;
  final String? error;
  final String? info;
  final String? testHint;
  final String serverHint;
  final _ConnBadge badge;
  final String versionLabel;
  final String syncLabel;
  final VoidCallback onSubmit;
  final VoidCallback onServerConnect;
  final VoidCallback onTestConnection;

  @override
  Widget build(BuildContext context) {
    return ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 400),
      child: Container(
        padding: const EdgeInsets.fromLTRB(28, 28, 28, 20),
        decoration: BoxDecoration(
          color: AppColors.loginCard,
          borderRadius: BorderRadius.circular(18),
          boxShadow: const [
            BoxShadow(color: AppColors.cardShadow, blurRadius: 20, offset: Offset(0, 10)),
          ],
        ),
        child: Form(
          key: formKey,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _ConnectionBadge(badge: badge),
              const SizedBox(height: 14),
              Container(
                width: 54,
                height: 54,
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  border: Border.all(color: AppColors.gold, width: 1.5),
                ),
                child: const Icon(Icons.person_outline, color: AppColors.gold, size: 28),
              ),
              const SizedBox(height: 10),
              Text(
                'تسجيل الدخول',
                textAlign: TextAlign.center,
                style: AppTextStyles.cairo(
                  fontSize: 22,
                  fontWeight: FontWeight.w700,
                  color: AppColors.white,
                ),
              ),
              const SizedBox(height: 22),
              _field(
                controller: userCtrl,
                hint: 'اسم المستخدم',
                icon: Icons.person_outline,
                validator: (v) => (v == null || v.trim().isEmpty) ? 'مطلوب' : null,
              ),
              const SizedBox(height: 12),
              _field(
                controller: passCtrl,
                hint: 'كلمة المرور',
                icon: Icons.lock_outline,
                obscure: obscure,
                suffix: IconButton(
                  tooltip: obscure ? 'إظهار كلمة المرور' : 'إخفاء كلمة المرور',
                  iconSize: 24,
                  constraints: const BoxConstraints(minWidth: 48, minHeight: 48),
                  padding: const EdgeInsets.all(12),
                  splashRadius: 26,
                  icon: Icon(
                    obscure ? Icons.visibility_off : Icons.visibility,
                    color: AppColors.muted,
                    size: 24,
                  ),
                  onPressed: onToggleObscure,
                ),
                validator: (v) => (v == null || v.isEmpty) ? 'مطلوب' : null,
                onSubmit: onSubmit,
              ),
              const SizedBox(height: 14),
              OutlinedButton.icon(
                onPressed: submitting ? null : onServerConnect,
                icon: const Icon(Icons.dns_outlined, color: AppColors.gold, size: 18),
                label: Text(
                  'ربط السيرفر (IP Address)',
                  style: AppTextStyles.cairo(
                    color: AppColors.gold,
                    fontWeight: FontWeight.w700,
                    fontSize: 14,
                  ),
                ),
                style: OutlinedButton.styleFrom(
                  side: const BorderSide(color: AppColors.gold, width: 1.2),
                  padding: const EdgeInsets.symmetric(vertical: 12),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                ),
              ),
              const SizedBox(height: 6),
              Text(
                serverHint,
                textAlign: TextAlign.center,
                textDirection: ui.TextDirection.ltr,
                style: AppTextStyles.cairo(fontSize: 11, color: AppColors.goldLight),
              ),
              Align(
                alignment: Alignment.center,
                child: TextButton(
                  onPressed: (submitting || testingConn) ? null : onTestConnection,
                  style: TextButton.styleFrom(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                    minimumSize: Size.zero,
                    tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                  ),
                  child: testingConn
                      ? const SizedBox(
                          width: 14,
                          height: 14,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: AppColors.goldLight,
                          ),
                        )
                      : Text(
                          'اختبار الاتصال',
                          style: AppTextStyles.cairo(
                            fontSize: 12,
                            color: AppColors.goldLight,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                ),
              ),
              if (testHint != null) ...[
                const SizedBox(height: 4),
                Text(
                  testHint!,
                  textAlign: TextAlign.center,
                  style: AppTextStyles.cairo(
                    fontSize: 12,
                    color: AppColors.goldLight,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
              if (error != null) ...[
                const SizedBox(height: 10),
                Text(
                  error!,
                  textAlign: TextAlign.center,
                  style: AppTextStyles.cairo(
                    fontSize: 13,
                    color: const Color(0xFFFF8A80),
                    fontWeight: FontWeight.w600,
                    height: 1.35,
                  ),
                ),
              ],
              if (info != null) ...[
                const SizedBox(height: 8),
                Text(
                  info!,
                  textAlign: TextAlign.center,
                  style: AppTextStyles.cairo(
                    fontSize: 12,
                    color: AppColors.goldLight,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
              const SizedBox(height: 16),
              ElevatedButton(
                onPressed: submitting ? null : onSubmit,
                style: ElevatedButton.styleFrom(
                  backgroundColor: AppColors.gold,
                  foregroundColor: AppColors.darkText,
                  disabledBackgroundColor: AppColors.gold.withValues(alpha: 0.7),
                  disabledForegroundColor: AppColors.darkText,
                  padding: const EdgeInsets.symmetric(vertical: 14),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                ),
                child: submitting
                    ? Row(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          const SizedBox(
                            width: 18,
                            height: 18,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              color: AppColors.darkText,
                            ),
                          ),
                          const SizedBox(width: 10),
                          Text(
                            'جاري تسجيل الدخول...',
                            style: AppTextStyles.cairo(
                              fontWeight: FontWeight.w800,
                              color: AppColors.darkText,
                              fontSize: 14,
                            ),
                          ),
                        ],
                      )
                    : Row(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          const Icon(Icons.login, size: 20),
                          const SizedBox(width: 8),
                          Text(
                            'تسجيل الدخول',
                            style: AppTextStyles.cairo(
                              fontWeight: FontWeight.w800,
                              color: AppColors.darkText,
                            ),
                          ),
                        ],
                      ),
              ),
              const SizedBox(height: 14),
              Text(
                versionLabel,
                textAlign: TextAlign.center,
                style: AppTextStyles.cairo(
                  fontSize: 11,
                  color: AppColors.goldLight.withValues(alpha: 0.85),
                ),
              ),
              const SizedBox(height: 4),
              Text(
                syncLabel,
                textAlign: TextAlign.center,
                style: AppTextStyles.cairo(
                  fontSize: 11,
                  color: AppColors.goldLight.withValues(alpha: 0.75),
                  height: 1.3,
                ),
              ),
              const SizedBox(height: 16),
              const Row(
                mainAxisAlignment: MainAxisAlignment.spaceAround,
                children: [
                  _Feat(Icons.verified_user_outlined, 'أمن وموثوق'),
                  _Feat(Icons.bar_chart_outlined, 'تقييم احترافي'),
                  _Feat(Icons.schedule_outlined, 'تقارير فورية'),
                  _Feat(Icons.support_outlined, 'دعم القرار'),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _field({
    required TextEditingController controller,
    required String hint,
    required IconData icon,
    bool obscure = false,
    Widget? suffix,
    String? Function(String?)? validator,
    VoidCallback? onSubmit,
  }) {
    return TextFormField(
      controller: controller,
      obscureText: obscure,
      textAlign: TextAlign.right,
      style: AppTextStyles.body,
      validator: validator,
      onFieldSubmitted: (_) => onSubmit?.call(),
      decoration: InputDecoration(
        hintText: hint,
        prefixIcon: Icon(icon, color: AppColors.muted),
        suffixIcon: suffix,
        filled: true,
        fillColor: AppColors.white,
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide.none,
        ),
      ),
    );
  }
}

class _ConnectionBadge extends StatelessWidget {
  const _ConnectionBadge({required this.badge});
  final _ConnBadge badge;

  @override
  Widget build(BuildContext context) {
    late final Color color;
    late final String label;
    switch (badge) {
      case _ConnBadge.connected:
        color = const Color(0xFF4CAF50);
        label = '🟢 متصل بالسيرفر';
        break;
      case _ConnBadge.offlineMode:
        color = const Color(0xFFFF9800);
        label = '🟠 وضع Offline';
        break;
      case _ConnBadge.unreachable:
        color = const Color(0xFFE53935);
        label = '🔴 الخادم غير متاح';
        break;
    }
    return Center(
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.16),
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: color.withValues(alpha: 0.7)),
        ),
        child: Text(
          label,
          style: AppTextStyles.cairo(
            fontSize: 12,
            color: AppColors.white,
            fontWeight: FontWeight.w700,
          ),
        ),
      ),
    );
  }
}

class _Feat extends StatelessWidget {
  const _Feat(this.icon, this.label);
  final IconData icon;
  final String label;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Icon(icon, color: AppColors.gold, size: 18),
        const SizedBox(height: 4),
        Text(label, style: AppTextStyles.cairo(fontSize: 9, color: AppColors.goldLight)),
      ],
    );
  }
}
