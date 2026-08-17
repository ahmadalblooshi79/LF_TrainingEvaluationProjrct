import 'package:flutter/material.dart';

import '../theme/app_theme.dart';

Widget buildLibraryPdfView({
  String? webUrl,
  List<int>? bytes,
  required String title,
}) {
  return Center(
    child: Text(
      'عارض PDF غير متاح على هذه المنصة',
      style: AppTextStyles.cairo(color: AppColors.white),
    ),
  );
}
