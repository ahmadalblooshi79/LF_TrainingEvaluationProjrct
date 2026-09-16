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

Widget buildMediaThumb({
  required String path,
  required bool isVideo,
  double size = 36,
}) {
  return SizedBox(
    width: size,
    height: size,
    child: Icon(
      isVideo ? Icons.videocam : Icons.image,
      color: AppColors.goldDark,
      size: size * 0.6,
    ),
  );
}
