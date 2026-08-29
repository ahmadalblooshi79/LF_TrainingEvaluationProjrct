import 'package:flutter/material.dart';

/// ألوان النتيجة — مطابقة لمفتاح النظام (_CONTROL_REPORT_GRADE_COLORS).
class GradeStyle {
  GradeStyle._();

  static const Color fail = Color(0xFFEF4444);
  static const Color acceptable = Color(0xFFF97316);
  static const Color good = Color(0xFFEAB308);
  static const Color veryGood = Color(0xFF38BDF8);
  static const Color excellent = Color(0xFF22C55E);

  static ({Color fg, Color bg}) forPercent(double? pct) {
    if (pct == null) return (fg: const Color(0xFF6B6B66), bg: const Color(0xFFF0F0F0));
    if (pct >= 90) return (fg: excellent, bg: const Color(0xFFDCFCE7));
    if (pct >= 80) return (fg: veryGood, bg: const Color(0xFFE0F2FE));
    if (pct >= 70) return (fg: good, bg: const Color(0xFFFEF9C3));
    if (pct >= 60) return (fg: acceptable, bg: const Color(0xFFFFEDD5));
    return (fg: fail, bg: const Color(0xFFFEE2E2));
  }

  static ({Color fg, Color bg}) forLabel(String label) {
    final n = label.trim().replaceAll(' ', '');
    if (n.contains('ممتاز')) return (fg: excellent, bg: const Color(0xFFDCFCE7));
    if (n.contains('جيدجدا') || n.contains('جيداً') || n.contains('جيدجداً')) {
      return (fg: veryGood, bg: const Color(0xFFE0F2FE));
    }
    if (n == 'جيد' || n.startsWith('جيد')) {
      return (fg: good, bg: const Color(0xFFFEF9C3));
    }
    if (n.contains('مقبول')) return (fg: acceptable, bg: const Color(0xFFFFEDD5));
    if (n.contains('راسب') || n.contains('متوسط')) {
      return (fg: fail, bg: const Color(0xFFFEE2E2));
    }
    return (fg: const Color(0xFF6B6B66), bg: const Color(0xFFF0F0F0));
  }
}

class GradeLabelChip extends StatelessWidget {
  const GradeLabelChip({super.key, required this.label, this.fontSize = 12});
  final String label;
  final double fontSize;

  @override
  Widget build(BuildContext context) {
    final text = label.trim().isEmpty ? '—' : label.trim();
    if (text == '—') {
      return Text(text, textAlign: TextAlign.center);
    }
    final style = GradeStyle.forLabel(text);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: style.bg,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Text(
        text,
        style: TextStyle(
          fontSize: fontSize,
          fontWeight: FontWeight.w700,
          color: style.fg,
        ),
      ),
    );
  }
}
