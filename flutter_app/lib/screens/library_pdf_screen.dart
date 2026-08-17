import 'dart:async';

import 'package:flutter/material.dart';

import '../services/api_client.dart';
import '../theme/app_theme.dart';
import 'library_pdf_view_stub.dart'
    if (dart.library.html) 'library_pdf_view_web.dart'
    if (dart.library.io) 'library_pdf_view_io.dart' as pdf_view;

/// عرض ملف مكتبة PDF داخل التطبيق بملء الشاشة (دون تنزيل للمستخدم).
class LibraryPdfScreen extends StatefulWidget {
  const LibraryPdfScreen({
    super.key,
    required this.nodeId,
    required this.title,
  });

  final int nodeId;
  final String title;

  @override
  State<LibraryPdfScreen> createState() => _LibraryPdfScreenState();
}

class _LibraryPdfScreenState extends State<LibraryPdfScreen> {
  bool _loading = true;
  String? _error;
  List<int>? _bytes;

  String get _apiPath => '/api/tablet/library/nodes/${widget.nodeId}/file';

  @override
  void initState() {
    super.initState();
    _open();
  }

  Future<void> _open() async {
    setState(() {
      _loading = true;
      _error = null;
      _bytes = null;
    });
    try {
      // تحميل عبر الجلسة ثم عرض داخل التطبيق (ويب: blob/iframe، أصلي: pdfrx).
      final bytes = await ApiClient.instance.getBytes(
        _apiPath,
        timeout: const Duration(seconds: 120),
      );
      if (!mounted) return;
      if (bytes.isEmpty) {
        setState(() {
          _loading = false;
          _error = 'الملف فارغ أو تعذّر تحميله';
        });
        return;
      }
      setState(() {
        _bytes = bytes;
        _loading = false;
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = e.message;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = '$e';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.oliveDark,
      appBar: AppBar(
        backgroundColor: AppColors.headerBar,
        foregroundColor: AppColors.olive,
        elevation: 0.5,
        title: Text(
          widget.title,
          style: AppTextStyles.cairo(
            fontWeight: FontWeight.w800,
            color: AppColors.olive,
            fontSize: 15,
          ),
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
        ),
        leading: IconButton(
          icon: const Icon(Icons.close),
          tooltip: 'إغلاق',
          onPressed: () => Navigator.of(context).maybePop(),
        ),
      ),
      body: _loading
          ? const Center(
              child: CircularProgressIndicator(color: AppColors.gold),
            )
          : _error != null
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(
                          _error!,
                          textAlign: TextAlign.center,
                          style: AppTextStyles.cairo(color: AppColors.white),
                        ),
                        const SizedBox(height: 12),
                        TextButton(
                          onPressed: _open,
                          child: const Text('إعادة المحاولة'),
                        ),
                      ],
                    ),
                  ),
                )
              : pdf_view.buildLibraryPdfView(
                  bytes: _bytes,
                  title: widget.title,
                ),
    );
  }
}
