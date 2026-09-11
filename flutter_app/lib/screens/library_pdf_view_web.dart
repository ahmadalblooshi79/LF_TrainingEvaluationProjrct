// ignore_for_file: avoid_web_libraries_in_flutter, deprecated_member_use

import 'dart:html' as html;
import 'dart:typed_data';
import 'dart:ui_web' as ui_web;

import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import '../widgets/pdf_nav_sidebar.dart';

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
  html.IFrameElement? _iframe;
  late int _pageCount;
  int _currentPage = 1;

  @override
  void initState() {
    super.initState();
    _pageCount = estimatePdfPageCount(widget.bytes);
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
      _iframe = iframe;
      return iframe;
    });
  }

  void _goTo(int page) {
    final url = _objectUrl;
    if (url == null) return;
    final target = page.clamp(1, _pageCount);
    final framed = _iframe;
    if (framed != null) {
      framed.src = '$url#page=$target';
    }
    setState(() => _currentPage = target);
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
    return ColoredBox(
      color: AppColors.oliveDark,
      child: Row(
        textDirection: TextDirection.rtl,
        children: [
          PdfNavSidebar(
            pageCount: _pageCount,
            currentPage: _currentPage,
            onPageTap: _goTo,
          ),
          Expanded(child: HtmlElementView(viewType: _viewType)),
        ],
      ),
    );
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
