import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_pdfview/flutter_pdfview.dart';

import '../theme/app_theme.dart';

Widget buildLibraryPdfView({
  String? webUrl,
  List<int>? bytes,
  required String title,
}) {
  if (bytes == null || bytes.isEmpty) {
    return Center(
      child: Text(
        'تعذّر تحميل الملف',
        style: AppTextStyles.cairo(color: AppColors.white),
      ),
    );
  }
  return ColoredBox(
    color: AppColors.oliveDark,
    child: PDFView(
      pdfData: Uint8List.fromList(bytes),
      enableSwipe: true,
      swipeHorizontal: false,
      autoSpacing: true,
      pageFling: true,
      backgroundColor: const Color(0xFF11241C),
    ),
  );
}
