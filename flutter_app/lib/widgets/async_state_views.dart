import 'package:flutter/material.dart';

import '../theme/app_theme.dart';

class LoadingView extends StatelessWidget {
  const LoadingView({super.key});

  @override
  Widget build(BuildContext context) {
    return const Center(child: CircularProgressIndicator(color: AppColors.gold));
  }
}

class ErrorView extends StatelessWidget {
  const ErrorView({super.key, required this.message, this.onRetry});

  final String message;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.error_outline, color: AppColors.notDoneRed, size: 40),
            const SizedBox(height: 12),
            Text(
              message,
              style: AppTextStyles.body,
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 8),
            Text(
              'إن كنت بدون اتصال: افتح الشاشة مرة وأنت متصل ليُخزَّن المحتوى محلياً.',
              style: AppTextStyles.small,
              textAlign: TextAlign.center,
            ),
            if (onRetry != null) ...[
              const SizedBox(height: 16),
              ElevatedButton(onPressed: onRetry, child: const Text('إعادة المحاولة')),
            ],
          ],
        ),
      ),
    );
  }
}

class EmptyView extends StatelessWidget {
  const EmptyView({super.key, required this.message, this.icon});

  final String message;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon ?? Icons.inbox_outlined, color: AppColors.darkText.withValues(alpha: 0.4), size: 44),
            const SizedBox(height: 12),
            Text(message, style: AppTextStyles.body, textAlign: TextAlign.center),
          ],
        ),
      ),
    );
  }
}

/// Small banner shown at the top of a screen when data was served from the
/// offline cache instead of a live network call.
class CachedDataBanner extends StatelessWidget {
  const CachedDataBanner({super.key});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      color: AppColors.notDoneRed.withValues(alpha: 0.12),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
      child: Text(
        'بيانات مخزّنة محلياً — لا يوجد اتصال حالياً بالخادم',
        style: AppTextStyles.small.copyWith(color: AppColors.notDoneRed, fontWeight: FontWeight.w600),
        textAlign: TextAlign.center,
      ),
    );
  }
}
