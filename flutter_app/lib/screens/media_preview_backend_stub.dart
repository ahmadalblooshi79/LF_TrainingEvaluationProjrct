import 'package:flutter/material.dart';

import '../theme/app_theme.dart';

Widget buildMediaPreview({required String path, required bool isVideo}) {
  return Center(
    child: Text(
      isVideo ? 'تعذّر عرض الفيديو' : 'تعذّر عرض الصورة',
      style: AppTextStyles.cairo(color: AppColors.white),
    ),
  );
}
