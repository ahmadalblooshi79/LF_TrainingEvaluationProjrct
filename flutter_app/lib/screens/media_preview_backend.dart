import 'media_preview_backend_stub.dart'
    if (dart.library.html) 'media_preview_backend_web.dart'
    if (dart.library.io) 'media_preview_backend_io.dart' as backend;

import 'package:flutter/material.dart';

Widget buildMediaPreview({required String path, required bool isVideo}) {
  return backend.buildMediaPreview(path: path, isVideo: isVideo);
}
