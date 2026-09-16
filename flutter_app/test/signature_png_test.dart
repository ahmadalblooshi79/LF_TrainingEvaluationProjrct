import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lf_training_evaluation/services/signature_png.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('exported signature png is RGBA with transparent background', () async {
    final png = await exportSignatureStrokesToPng(
      strokes: [
        [
          const Offset(24, 48),
          const Offset(48, 28),
          const Offset(90, 56),
          const Offset(140, 22),
          const Offset(170, 44),
        ],
      ],
      logicalSize: const Size(220, 80),
      pixelRatio: 2,
    );
    expect(pngHasRgbaHeader(png), isTrue);
    expect(png.length, greaterThan(80));
  });
}
