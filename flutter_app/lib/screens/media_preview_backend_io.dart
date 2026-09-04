import 'dart:io';

import 'package:flutter/material.dart';
import 'package:video_player/video_player.dart';

import '../theme/app_theme.dart';

Widget buildMediaPreview({required String path, required bool isVideo}) {
  if (path.isEmpty) {
    return Center(
      child: Text('الملف غير متوفر', style: AppTextStyles.cairo(color: AppColors.white)),
    );
  }
  if (isVideo) {
    return _VideoPreview(path: path);
  }
  return InteractiveViewer(
    child: Center(
      child: Image.file(File(path), fit: BoxFit.contain),
    ),
  );
}

class _VideoPreview extends StatefulWidget {
  const _VideoPreview({required this.path});
  final String path;

  @override
  State<_VideoPreview> createState() => _VideoPreviewState();
}

class _VideoPreviewState extends State<_VideoPreview> {
  late final VideoPlayerController _ctrl;
  bool _ready = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _ctrl = VideoPlayerController.file(File(widget.path));
    _ctrl.initialize().then((_) {
      if (!mounted) return;
      setState(() => _ready = true);
      _ctrl.play();
    }).catchError((e) {
      if (!mounted) return;
      setState(() => _error = '$e');
    });
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (_error != null) {
      return Center(
        child: Text(_error!, style: AppTextStyles.cairo(color: AppColors.white)),
      );
    }
    if (!_ready) {
      return const Center(child: CircularProgressIndicator(color: AppColors.gold));
    }
    return GestureDetector(
      onTap: () {
        setState(() {
          if (_ctrl.value.isPlaying) {
            _ctrl.pause();
          } else {
            _ctrl.play();
          }
        });
      },
      child: Center(
        child: AspectRatio(
          aspectRatio: _ctrl.value.aspectRatio == 0 ? 16 / 9 : _ctrl.value.aspectRatio,
          child: VideoPlayer(_ctrl),
        ),
      ),
    );
  }
}
