import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';

/// حبر التوقيع الثابت — أزرق توقيع تقليدي.
const Color kSignatureInkColor = Color(0xFF17365D);

/// سماكة متوسطة عند دقة اللوحة المنطقية.
const double kSignatureLogicalStrokeWidth = 2.8;

bool pngHasRgbaHeader(Uint8List bytes) {
  if (bytes.length < 26) return false;
  const sig = [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A];
  for (var i = 0; i < sig.length; i++) {
    if (bytes[i] != sig[i]) return false;
  }
  return bytes[25] == 6;
}

bool rawRgbaHasTransparencyAndInk(Uint8List rgba) {
  if (rgba.length < 16 || rgba.length % 4 != 0) return false;
  var transparent = 0;
  var ink = 0;
  var opaqueWhite = 0;
  for (var i = 0; i < rgba.length; i += 4) {
    final r = rgba[i];
    final g = rgba[i + 1];
    final b = rgba[i + 2];
    final a = rgba[i + 3];
    if (a < 16) {
      transparent++;
      continue;
    }
    if (r > 240 && g > 240 && b > 240 && a > 200) {
      opaqueWhite++;
      continue;
    }
    if (a > 140) ink++;
  }
  final pixels = rgba.length ~/ 4;
  if (transparent < 8) return false;
  if (ink < 8) return false;
  if (opaqueWhite > (ink * 4).clamp(8, pixels)) return false;
  return true;
}

Rect? signatureInkBounds(List<List<Offset>> strokes) {
  double? minX, minY, maxX, maxY;
  for (final stroke in strokes) {
    for (final p in stroke) {
      minX = minX == null ? p.dx : (p.dx < minX ? p.dx : minX);
      minY = minY == null ? p.dy : (p.dy < minY ? p.dy : minY);
      maxX = maxX == null ? p.dx : (p.dx > maxX ? p.dx : maxX);
      maxY = maxY == null ? p.dy : (p.dy > maxY ? p.dy : maxY);
    }
  }
  if (minX == null || minY == null || maxX == null || maxY == null) {
    return null;
  }
  return Rect.fromLTRB(minX, minY, maxX, maxY);
}

/// يرسم الخطوط على Canvas شفاف (وليس لقطة للودجت ذي الخلفية الفاتحة).
Future<Uint8List> exportSignatureStrokesToPng({
  required List<List<Offset>> strokes,
  required Size logicalSize,
  double pixelRatio = 2.0,
}) async {
  final nonEmpty = strokes.where((s) => s.length >= 2).toList();
  if (nonEmpty.isEmpty) {
    throw StateError('empty_signature');
  }
  final pr = pixelRatio <= 0 ? 1.0 : pixelRatio;
  final bounds = signatureInkBounds(nonEmpty);
  if (bounds == null || bounds.width <= 0 || bounds.height <= 0) {
    throw StateError('empty_signature');
  }
  final margin = 12.0;
  final crop = Rect.fromLTRB(
    (bounds.left - margin).clamp(0, logicalSize.width),
    (bounds.top - margin).clamp(0, logicalSize.height),
    (bounds.right + margin).clamp(0, logicalSize.width),
    (bounds.bottom + margin).clamp(0, logicalSize.height),
  );
  final outW = (crop.width * pr).round().clamp(8, 2400);
  final outH = (crop.height * pr).round().clamp(8, 1600);

  final recorder = ui.PictureRecorder();
  final canvas = Canvas(recorder);
  canvas.scale(pr);
  canvas.translate(-crop.left, -crop.top);

  final paint = Paint()
    ..color = kSignatureInkColor
    ..style = PaintingStyle.stroke
    ..strokeWidth = kSignatureLogicalStrokeWidth
    ..strokeCap = StrokeCap.round
    ..strokeJoin = StrokeJoin.round
    ..isAntiAlias = true;

  for (final stroke in nonEmpty) {
    final path = Path()..moveTo(stroke.first.dx, stroke.first.dy);
    for (var i = 1; i < stroke.length; i++) {
      path.lineTo(stroke[i].dx, stroke[i].dy);
    }
    canvas.drawPath(path, paint);
  }

  final picture = recorder.endRecording();
  final image = await picture.toImage(outW, outH);
  picture.dispose();

  final raw = await image.toByteData(format: ui.ImageByteFormat.rawRgba);
  if (raw == null) {
    image.dispose();
    throw StateError('export_failed');
  }
  final rgba = raw.buffer.asUint8List();
  if (!rawRgbaHasTransparencyAndInk(rgba)) {
    image.dispose();
    throw StateError('not_transparent');
  }
  final png = await image.toByteData(format: ui.ImageByteFormat.png);
  image.dispose();
  if (png == null) {
    throw StateError('export_failed');
  }
  final bytes = png.buffer.asUint8List();
  if (!pngHasRgbaHeader(bytes)) {
    throw StateError('not_rgba_png');
  }
  return bytes;
}
