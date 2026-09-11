import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_pdfview/flutter_pdfview.dart';

import '../theme/app_theme.dart';
import '../widgets/pdf_nav_sidebar.dart';

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
  return _IoPdfReader(bytes: bytes);
}

class _IoPdfReader extends StatefulWidget {
  const _IoPdfReader({required this.bytes});
  final List<int> bytes;

  @override
  State<_IoPdfReader> createState() => _IoPdfReaderState();
}

class _IoPdfReaderState extends State<_IoPdfReader> {
  PDFViewController? _controller;
  late int _pageCount;
  int _currentPage = 1;

  @override
  void initState() {
    super.initState();
    _pageCount = estimatePdfPageCount(widget.bytes);
  }

  Future<void> _goTo(int page) async {
    final c = _controller;
    if (c == null) return;
    final target = page.clamp(1, _pageCount);
    await c.setPage(target - 1);
    if (mounted) setState(() => _currentPage = target);
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
          Expanded(
            child: PDFView(
              pdfData: Uint8List.fromList(widget.bytes),
              enableSwipe: true,
              swipeHorizontal: false,
              autoSpacing: true,
              pageFling: true,
              defaultPage: 0,
              backgroundColor: const Color(0xFF11241C),
              onViewCreated: (controller) {
                _controller = controller;
              },
              onRender: (pages) {
                if (pages != null && pages > 0 && mounted) {
                  setState(() => _pageCount = pages);
                }
              },
              onPageChanged: (page, total) {
                if (!mounted) return;
                setState(() {
                  if (page != null) _currentPage = page + 1;
                  if (total != null && total > 0) _pageCount = total;
                });
              },
            ),
          ),
        ],
      ),
    );
  }
}
