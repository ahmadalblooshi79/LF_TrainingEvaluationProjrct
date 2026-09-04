import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import 'media_preview_backend.dart';

/// معاينة صورة أو فيديو توثيق داخل التطبيق.
class MediaPreviewScreen extends StatelessWidget {
  const MediaPreviewScreen({
    super.key,
    required this.path,
    required this.isVideo,
    this.title = 'معاينة التوثيق',
  });

  final String path;
  final bool isVideo;
  final String title;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.oliveDark,
      appBar: AppBar(
        backgroundColor: AppColors.headerBar,
        foregroundColor: AppColors.olive,
        elevation: 0.5,
        title: Text(
          title,
          style: AppTextStyles.cairo(
            fontWeight: FontWeight.w800,
            color: AppColors.olive,
            fontSize: 15,
          ),
        ),
        leading: IconButton(
          icon: const Icon(Icons.close),
          tooltip: 'إغلاق',
          onPressed: () => Navigator.of(context).maybePop(),
        ),
      ),
      body: buildMediaPreview(path: path, isVideo: isVideo),
    );
  }
}
