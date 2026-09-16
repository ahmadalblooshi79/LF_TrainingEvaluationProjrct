import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../services/auth_service.dart';
import '../services/signature_png.dart';
import '../services/signature_store.dart';
import '../theme/app_theme.dart';
import '../widgets/app_header.dart';

class SignatureScreen extends StatefulWidget {
  const SignatureScreen({super.key});

  @override
  State<SignatureScreen> createState() => _SignatureScreenState();
}

class _SignatureScreenState extends State<SignatureScreen> {
  final _strokes = <List<Offset>>[];
  List<Offset>? _current;
  bool _saving = false;
  bool _loading = true;
  JudgeSignatureRecord? _stored;
  String? _error;
  Size _canvasSize = const Size(640, 240);

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final uid = AuthService.instance.currentUserId;
    if (uid != null) {
      await SignatureStore.instance.pullIfMissing(uid);
    }
    final rec = await SignatureStore.instance.loadForCurrentUser();
    if (!mounted) return;
    setState(() {
      _stored = rec;
      _loading = false;
    });
  }

  void _clear() {
    setState(() {
      _strokes.clear();
      _current = null;
      _error = null;
    });
  }

  void _undo() {
    if (_strokes.isEmpty) return;
    setState(() {
      _strokes.removeLast();
      _error = null;
    });
  }

  Future<void> _save() async {
    final auth = context.read<AuthService>();
    final uid = auth.currentUserId;
    if (uid == null || uid <= 0) {
      setState(() => _error = 'تعذّر التحقق من الحساب الحالي.');
      return;
    }
    final existing = await SignatureStore.instance.loadForUser(uid);
    if (!mounted) return;
    if (existing != null && existing.isRegistered) {
      final replace = await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: const Text('استبدال التوقيع'),
          content: const Text(
            'يوجد توقيع إلكتروني مسجل مسبقاً.\nهل تريد استبداله؟',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('إلغاء'),
            ),
            ElevatedButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('استبدال التوقيع'),
            ),
          ],
        ),
      );
      if (replace != true) return;
    }
    if (_strokes.where((s) => s.length >= 2).isEmpty) {
      setState(() => _error = 'ارسم التوقيع أولاً.');
      return;
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final png = await exportSignatureStrokesToPng(
        strokes: List<List<Offset>>.from(_strokes),
        logicalSize: _canvasSize,
      );
      final rec = await SignatureStore.instance.saveApproved(
        userId: uid,
        png: png,
        replace: existing != null && existing.isRegistered,
      );
      if (!mounted) return;
      setState(() {
        _stored = rec;
        _saving = false;
        _strokes.clear();
      });
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('تم حفظ واعتماد التوقيع الإلكتروني')),
      );
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _error = 'تعذّر حفظ التوقيع. أعد المحاولة.';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthService>();
    final session = auth.session;
    final registered = _stored != null && _stored!.isRegistered;
    return Scaffold(
      appBar: AppHeader(
        pageTitle: 'التوقيع الإلكتروني',
        showSettings: false,
        onBack: () {
          if (context.canPop()) {
            context.pop();
          } else {
            context.go('/settings');
          }
        },
      ),
      backgroundColor: AppColors.background,
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : SingleChildScrollView(
              padding: const EdgeInsets.all(20),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text(
                    session?.user.judgeDisplayName ?? '—',
                    style: AppTextStyles.subtitle,
                  ),
                  const SizedBox(height: 4),
                  Text(
                    session?.unitLabel.isNotEmpty == true
                        ? session!.unitLabel
                        : '—',
                    style: AppTextStyles.body,
                  ),
                  const SizedBox(height: 12),
                  Text(
                    registered ? 'مسجل ومعتمد' : 'غير مسجل',
                    style: AppTextStyles.cairo(
                      fontWeight: FontWeight.w700,
                      color: registered
                          ? AppColors.doneGreen
                          : AppColors.notDoneRed,
                    ),
                  ),
                  if (registered && _stored?.pngBytes != null) ...[
                    const SizedBox(height: 12),
                    Container(
                      height: 90,
                      alignment: Alignment.center,
                      color: Colors.transparent,
                      child: Image.memory(
                        _stored!.pngBytes!,
                        fit: BoxFit.contain,
                        filterQuality: FilterQuality.high,
                      ),
                    ),
                  ],
                  const SizedBox(height: 16),
                  Text('منطقة التوقيع', style: AppTextStyles.small),
                  const SizedBox(height: 8),
                  LayoutBuilder(
                    builder: (context, constraints) {
                      final w = constraints.maxWidth;
                      final h = (w * 0.38).clamp(160.0, 280.0);
                      _canvasSize = Size(w, h);
                      return Container(
                        height: h,
                        decoration: BoxDecoration(
                          color: const Color(0xFFFBF8F0),
                          border: Border.all(color: AppColors.goldBorder),
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: ClipRRect(
                          borderRadius: BorderRadius.circular(8),
                          child: Listener(
                            behavior: HitTestBehavior.opaque,
                            onPointerDown: (e) {
                              setState(() {
                                _current = [e.localPosition];
                                _strokes.add(_current!);
                              });
                            },
                            onPointerMove: (e) {
                              if (_current == null) return;
                              setState(() => _current!.add(e.localPosition));
                            },
                            onPointerUp: (_) => _current = null,
                            onPointerCancel: (_) => _current = null,
                            child: CustomPaint(
                              painter: _SignaturePainter(_strokes),
                              child: const SizedBox.expand(),
                            ),
                          ),
                        ),
                      );
                    },
                  ),
                  if (_error != null) ...[
                    const SizedBox(height: 10),
                    Text(
                      _error!,
                      style: AppTextStyles.cairo(color: AppColors.notDoneRed),
                    ),
                  ],
                  const SizedBox(height: 16),
                  Row(
                    children: [
                      Expanded(
                        child: OutlinedButton(
                          onPressed: _saving ? null : _clear,
                          child: const Text('مسح'),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: OutlinedButton(
                          onPressed: _saving ? null : _undo,
                          child: const Text('إعادة'),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 10),
                  ElevatedButton(
                    onPressed: _saving ? null : _save,
                    style: ElevatedButton.styleFrom(
                      backgroundColor: AppColors.buttonBrown,
                      foregroundColor: AppColors.white,
                      padding: const EdgeInsets.symmetric(vertical: 14),
                    ),
                    child: _saving
                        ? const SizedBox(
                            width: 18,
                            height: 18,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              color: Colors.white,
                            ),
                          )
                        : const Text('حفظ واعتماد التوقيع'),
                  ),
                ],
              ),
            ),
    );
  }
}

class _SignaturePainter extends CustomPainter {
  _SignaturePainter(this.strokes);

  final List<List<Offset>> strokes;

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = kSignatureInkColor
      ..style = PaintingStyle.stroke
      ..strokeWidth = kSignatureLogicalStrokeWidth
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round
      ..isAntiAlias = true;
    for (final stroke in strokes) {
      if (stroke.isEmpty) continue;
      if (stroke.length == 1) {
        canvas.drawCircle(stroke.first, 1.4, paint);
        continue;
      }
      final path = Path()..moveTo(stroke.first.dx, stroke.first.dy);
      for (var i = 1; i < stroke.length; i++) {
        path.lineTo(stroke[i].dx, stroke[i].dy);
      }
      canvas.drawPath(path, paint);
    }
  }

  @override
  bool shouldRepaint(covariant _SignaturePainter oldDelegate) => true;
}
