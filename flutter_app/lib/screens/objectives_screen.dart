import 'package:flutter/material.dart';

import '../models/objective.dart';
import '../services/api_client.dart';
import '../services/tablet_repository.dart';
import '../theme/app_theme.dart';
import '../widgets/app_header.dart';
import '../widgets/async_state_views.dart';

class ObjectivesScreen extends StatefulWidget {
  const ObjectivesScreen({super.key});

  @override
  State<ObjectivesScreen> createState() => _ObjectivesScreenState();
}

class _ObjectivesScreenState extends State<ObjectivesScreen> {
  ObjectivesData? _data;
  bool _loading = true;
  bool _fromCache = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final r = await TabletRepository.instance.fetchObjectives();
      setState(() {
        _data = r.data;
        _fromCache = r.fromCache;
      });
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppHeader(
        pageTitle: 'قوائم تقييم الإجراءات',
        pageSubtitle: 'الأهداف التدريبية',
        onBack: () => Navigator.of(context).maybePop(),
        showOnlineChip: false,
      ),
      body: _loading
          ? const LoadingView()
          : _error != null
              ? ErrorView(message: _error!, onRetry: _load)
              : _body(),
    );
  }

  Widget _body() {
    final data = _data;
    if (data == null) return const EmptyView(message: 'لا توجد بيانات');
    return Column(
      children: [
        if (_fromCache) const CachedDataBanner(),
        Expanded(
          child: Padding(
            padding: const EdgeInsets.all(20),
            child: Container(
              decoration: BoxDecoration(
                color: AppColors.panelBeige,
                borderRadius: BorderRadius.circular(16),
                border: Border.all(color: AppColors.white, width: 2),
                boxShadow: const [
                  BoxShadow(color: AppColors.cardShadow, blurRadius: 8, offset: Offset(0, 3)),
                ],
              ),
              child: Column(
                children: [
                  const SizedBox(height: 18),
                  const Icon(Icons.schedule, color: AppColors.goldDark, size: 26),
                  const SizedBox(height: 6),
                  Text(
                    'الأهداف التدريبية',
                    style: AppTextStyles.cairo(fontSize: 18, fontWeight: FontWeight.w800),
                  ),
                  const SizedBox(height: 10),
                  const Divider(color: AppColors.white, thickness: 1.5),
                  Expanded(
                    child: data.objectives.isEmpty
                        ? const EmptyView(message: 'لا توجد أهداف تدريبية مسجّلة')
                        : RefreshIndicator(
                            onRefresh: _load,
                            color: AppColors.gold,
                            child: ListView.separated(
                              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                              itemCount: data.objectives.length,
                              separatorBuilder: (_, __) =>
                                  const Divider(color: AppColors.white, thickness: 1.2, height: 1),
                              itemBuilder: (context, index) {
                                final o = data.objectives[index];
                                return Padding(
                                  padding: const EdgeInsets.symmetric(vertical: 16, horizontal: 12),
                                  child: Row(
                                    children: [
                                      SizedBox(
                                        width: 40,
                                        child: Text(
                                          '${index + 1}',
                                          textAlign: TextAlign.center,
                                          style: AppTextStyles.cairo(
                                            fontWeight: FontWeight.w800,
                                            fontSize: 15,
                                          ),
                                        ),
                                      ),
                                      Container(width: 1.5, height: 28, color: AppColors.white),
                                      const SizedBox(width: 14),
                                      Expanded(
                                        child: Text(o.text, style: AppTextStyles.body),
                                      ),
                                    ],
                                  ),
                                );
                              },
                            ),
                          ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ],
    );
  }
}
