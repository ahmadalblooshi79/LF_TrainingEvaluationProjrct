import 'dart:convert';
import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../theme/app_theme.dart';

/// تقدير عدد صفحات PDF من البايتات (يُستبدل بعد onRender عند توفره).
int estimatePdfPageCount(List<int> bytes) {
  if (bytes.isEmpty) return 1;
  try {
    final s = latin1.decode(bytes, allowInvalid: true);
    var best = 0;
    for (final m in RegExp(r'/Type\s*/Pages\b').allMatches(s)) {
      final end = math.min(m.start + 500, s.length);
      final slice = s.substring(m.start, end);
      final c = RegExp(r'/Count\s+(\d+)').firstMatch(slice);
      if (c != null) {
        final n = int.tryParse(c.group(1)!) ?? 0;
        if (n > best && n < 20000) best = n;
      }
    }
    if (best > 0) return best;
    var pages = 0;
    for (final _ in RegExp(r'/Type\s*/Page\b').allMatches(s)) {
      pages += 1;
      if (pages > 20000) break;
    }
    return pages > 0 ? pages : 1;
  } catch (_) {
    return 1;
  }
}

/// شريط جانبي: مصغّرة شكل صفحة + رقم الصفحة، للانتقال المباشر.
class PdfNavSidebar extends StatelessWidget {
  const PdfNavSidebar({
    super.key,
    required this.pageCount,
    required this.currentPage,
    required this.onPageTap,
  });

  final int pageCount;
  final int currentPage;
  final ValueChanged<int> onPageTap;

  @override
  Widget build(BuildContext context) {
    final n = pageCount < 1 ? 1 : pageCount;
    return Container(
      width: 108,
      color: const Color(0xFF0C1A14),
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(6, 10, 6, 6),
            child: Text(
              'الصفحات',
              style: AppTextStyles.cairo(
                color: AppColors.goldLight,
                fontWeight: FontWeight.w800,
                fontSize: 12,
              ),
            ),
          ),
          Expanded(
            child: ListView.builder(
              padding: const EdgeInsets.fromLTRB(8, 0, 8, 12),
              itemCount: n,
              itemBuilder: (context, i) {
                final page = i + 1;
                final selected = page == currentPage;
                return Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: InkWell(
                    onTap: () => onPageTap(page),
                    borderRadius: BorderRadius.circular(6),
                    child: Column(
                      children: [
                        _PageThumb(page: page, selected: selected),
                        const SizedBox(height: 4),
                        Text(
                          '$page',
                          style: AppTextStyles.cairo(
                            fontSize: 11,
                            fontWeight: FontWeight.w800,
                            color: selected ? AppColors.gold : AppColors.white,
                          ),
                        ),
                      ],
                    ),
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

class _PageThumb extends StatelessWidget {
  const _PageThumb({required this.page, required this.selected});

  final int page;
  final bool selected;

  @override
  Widget build(BuildContext context) {
    return AnimatedContainer(
      duration: const Duration(milliseconds: 150),
      width: 76,
      height: 102,
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(4),
        border: Border.all(
          color: selected ? AppColors.gold : const Color(0xFF3A4F44),
          width: selected ? 2.5 : 1,
        ),
        boxShadow: [
          BoxShadow(
            color: selected
                ? AppColors.gold.withValues(alpha: 0.35)
                : Colors.black26,
            blurRadius: selected ? 6 : 3,
            offset: const Offset(0, 2),
          ),
        ],
      ),
      child: CustomPaint(
        painter: _PagePreviewPainter(page: page),
      ),
    );
  }
}

class _PagePreviewPainter extends CustomPainter {
  _PagePreviewPainter({required this.page});
  final int page;

  @override
  void paint(Canvas canvas, Size size) {
    final header = Paint()..color = const Color(0xFFE8EDE9);
    canvas.drawRect(Rect.fromLTWH(0, 0, size.width, 14), header);
    final line = Paint()
      ..color = const Color(0xFFB7C4BC)
      ..strokeWidth = 1;
    final rng = math.Random(page * 9176);
    var y = 22.0;
    while (y < size.height - 10) {
      final w = size.width * (0.45 + rng.nextDouble() * 0.4);
      canvas.drawLine(Offset(8, y), Offset(8 + w, y), line);
      y += 6 + rng.nextDouble() * 3;
    }
    final badge = Paint()..color = const Color(0xFF1B3A2C);
    final br = RRect.fromRectAndRadius(
      Rect.fromCenter(
        center: Offset(size.width / 2, size.height - 16),
        width: 28,
        height: 14,
      ),
      const Radius.circular(3),
    );
    canvas.drawRRect(br, badge);
  }

  @override
  bool shouldRepaint(covariant _PagePreviewPainter oldDelegate) =>
      oldDelegate.page != page;
}
