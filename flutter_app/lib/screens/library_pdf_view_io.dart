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
  final UniqueKey _viewKey = UniqueKey();

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
    final data = Uint8List.fromList(widget.bytes);
    return ColoredBox(
      color: AppColors.oliveDark,
      child: Row(
        textDirection: TextDirection.rtl,
        children: [
          PdfNavSidebar(
            pageCount: _pageCount,
            currentPage: _currentPage,
            onPageTap: _goTo,
            pagePreviewBuilder: (page, selected) => _PdfContentThumb(
              bytes: data,
              page: page,
              selected: selected,
            ),
          ),
          Expanded(
            child: Center(
              child: PDFView(
                key: _viewKey,
                pdfData: data,
                enableSwipe: true,
                swipeHorizontal: false,
                autoSpacing: true,
                pageFling: true,
                pageSnap: true,
                fitPolicy: FitPolicy.BOTH,
                fitEachPage: true,
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
          ),
        ],
      ),
    );
  }
}

class _PdfContentThumb extends StatelessWidget {
  const _PdfContentThumb({
    required this.bytes,
    required this.page,
    required this.selected,
  });

  final Uint8List bytes;
  final int page;
  final bool selected;

  @override
  Widget build(BuildContext context) {
    return AnimatedContainer(
      duration: const Duration(milliseconds: 150),
      width: 76,
      height: 102,
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(4),
        border: Border.all(
          color: selected ? AppColors.gold : const Color(0xFF3A4F44),
          width: selected ? 2.5 : 1,
        ),
      ),
      clipBehavior: Clip.antiAlias,
      child: IgnorePointer(
        child: PDFView(
          pdfData: bytes,
          defaultPage: page - 1,
          swipeHorizontal: false,
          enableSwipe: false,
          autoSpacing: false,
          pageFling: false,
          fitPolicy: FitPolicy.BOTH,
          fitEachPage: true,
          backgroundColor: Colors.white,
        ),
      ),
    );
  }
}
