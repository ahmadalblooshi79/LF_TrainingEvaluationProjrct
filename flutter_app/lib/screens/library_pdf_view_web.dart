// ignore_for_file: avoid_web_libraries_in_flutter, deprecated_member_use

import 'dart:html' as html;
import 'dart:typed_data';
import 'dart:ui_web' as ui_web;

import 'package:flutter/material.dart';

import '../theme/app_theme.dart';

Widget buildLibraryPdfView({
  String? webUrl,
  List<int>? bytes,
  required String title,
}) {
  if (bytes != null && bytes.isNotEmpty) {
    return _BlobPdfView(bytes: bytes, title: title);
  }
  final url = (webUrl ?? '').trim();
  if (url.isEmpty) {
    return Center(
      child: Text(
        'لا يوجد ملف للعرض',
        style: AppTextStyles.cairo(color: AppColors.white),
      ),
    );
  }
  return _UrlPdfView(url: url);
}

class _BlobPdfView extends StatefulWidget {
  const _BlobPdfView({required this.bytes, required this.title});

  final List<int> bytes;
  final String title;

  @override
  State<_BlobPdfView> createState() => _BlobPdfViewState();
}

class _BlobPdfViewState extends State<_BlobPdfView> {
  late final String _viewType;
  String? _objectUrl;

  @override
  void initState() {
    super.initState();
    final data = Uint8List.fromList(widget.bytes);
    final blob = html.Blob([data], 'application/pdf');
    _objectUrl = html.Url.createObjectUrlFromBlob(blob);
    _viewType =
        'lf-library-pdf-blob-${identityHashCode(this)}-${DateTime.now().microsecondsSinceEpoch}';
    final src = _objectUrl!;
    ui_web.platformViewRegistry.registerViewFactory(_viewType, (int viewId) {
      final iframe = html.IFrameElement()
        ..src = src
        ..style.border = 'none'
        ..style.width = '100%'
        ..style.height = '100%'
        ..allowFullscreen = true;
      return iframe;
    });
  }

  @override
  void dispose() {
    final u = _objectUrl;
    if (u != null) {
      html.Url.revokeObjectUrl(u);
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return HtmlElementView(viewType: _viewType);
  }
}

class _UrlPdfView extends StatelessWidget {
  const _UrlPdfView({required this.url});

  final String url;

  @override
  Widget build(BuildContext context) {
    final viewType =
        'lf-library-pdf-url-${url.hashCode}-${DateTime.now().microsecondsSinceEpoch}';
    ui_web.platformViewRegistry.registerViewFactory(viewType, (int viewId) {
      final iframe = html.IFrameElement()
        ..src = url
        ..style.border = 'none'
        ..style.width = '100%'
        ..style.height = '100%'
        ..allowFullscreen = true;
      return iframe;
    });
    return HtmlElementView(viewType: viewType);
  }
}
