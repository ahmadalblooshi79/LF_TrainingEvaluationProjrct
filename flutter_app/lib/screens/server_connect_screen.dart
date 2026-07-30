import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../services/api_client.dart';
import '../theme/app_theme.dart';

/// Dedicated page to set LAN server IP:Port before login.
class ServerConnectScreen extends StatefulWidget {
  const ServerConnectScreen({super.key});

  @override
  State<ServerConnectScreen> createState() => _ServerConnectScreenState();
}

class _ServerConnectScreenState extends State<ServerConnectScreen> {
  final _ctrl = TextEditingController();
  bool _testing = false;
  String? _result;
  bool _ok = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    await ApiClient.instance.init();
    if (!mounted) return;
    setState(() => _ctrl.text = ApiClient.instance.baseUrl);
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  Future<void> _apply() async {
    var url = _ctrl.text.trim();
    if (url.isEmpty && kIsWeb) url = Uri.base.origin;
    await ApiClient.instance.setBaseUrl(url);
  }

  Future<void> _save() async {
    await _apply();
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('تم حفظ عنوان السيرفر')),
    );
    context.pop(true);
  }

  Future<void> _test() async {
    setState(() {
      _testing = true;
      _result = null;
    });
    await _apply();
    final ok = await ApiClient.instance.ping();
    if (!mounted) return;
    setState(() {
      _testing = false;
      _ok = ok;
      _result = ok
          ? 'تم الاتصال بالخادم بنجاح'
          : 'تعذّر الاتصال — تحقق من عنوان IP والمنفذ والشبكة';
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppBar(
        title: Text('ربط السيرفر', style: AppTextStyles.subtitle),
        leading: IconButton(
          icon: const Icon(Icons.arrow_forward),
          onPressed: () => context.pop(false),
        ),
      ),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 520),
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Container(
              padding: const EdgeInsets.all(24),
              decoration: BoxDecoration(
                color: AppColors.cardWhite,
                borderRadius: BorderRadius.circular(16),
                boxShadow: const [
                  BoxShadow(color: AppColors.cardShadow, blurRadius: 10, offset: Offset(0, 4)),
                ],
              ),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Icon(Icons.dns_outlined, size: 48, color: AppColors.goldDark),
                  const SizedBox(height: 12),
                  Text(
                    'عنوان السيرفر (IP Address)',
                    style: AppTextStyles.cairo(fontSize: 18, fontWeight: FontWeight.w800),
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 8),
                  Text(
                    'أدخل عنوان جهاز الخادم على الشبكة المحلية مع المنفذ، مثال:\n192.168.1.10:8005',
                    style: AppTextStyles.small,
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 20),
                  TextField(
                    controller: _ctrl,
                    textDirection: TextDirection.ltr,
                    textAlign: TextAlign.left,
                    decoration: InputDecoration(
                      hintText: kIsWeb ? 'فارغ = نفس منشأ PWA' : 'مثال: 192.168.1.10:8005',
                      prefixIcon: const Icon(Icons.lan_outlined),
                      border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
                      filled: true,
                      fillColor: AppColors.headerCream,
                    ),
                  ),
                  const SizedBox(height: 16),
                  Row(
                    children: [
                      Expanded(
                        child: OutlinedButton(
                          onPressed: _testing ? null : _test,
                          child: _testing
                              ? const SizedBox(
                                  width: 18,
                                  height: 18,
                                  child: CircularProgressIndicator(strokeWidth: 2),
                                )
                              : const Text('اختبار الاتصال'),
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: ElevatedButton(
                          onPressed: _save,
                          child: const Text('حفظ والرجوع'),
                        ),
                      ),
                    ],
                  ),
                  if (_result != null) ...[
                    const SizedBox(height: 14),
                    Text(
                      _result!,
                      textAlign: TextAlign.center,
                      style: AppTextStyles.cairo(
                        fontWeight: FontWeight.w700,
                        color: _ok ? AppColors.doneGreen : AppColors.notDoneRed,
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
