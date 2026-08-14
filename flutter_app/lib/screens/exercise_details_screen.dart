import 'package:flutter/material.dart';

import '../services/api_client.dart';
import '../theme/app_theme.dart';
import '../widgets/app_header.dart';
import '../widgets/figma_ui.dart';

/// معلومات التمرين — قراءة فقط، مطابقة لأقسام صفحة النظام.
class ExerciseDetailsScreen extends StatefulWidget {
  const ExerciseDetailsScreen({super.key});

  @override
  State<ExerciseDetailsScreen> createState() => _ExerciseDetailsScreenState();
}

class _ExerciseDetailsScreenState extends State<ExerciseDetailsScreen> {
  bool _loading = true;
  String? _error;
  String _tab = 'info';
  List<({String key, String label})> _tabs = const [];
  Map<String, dynamic> _ex = {};

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
      final data = await ApiClient.instance.get('/api/tablet/exercise-details');
      final tabsRaw = (data['tabs'] as List?) ?? const [];
      final ex = (data['exercise'] as Map?)?.cast<String, dynamic>() ?? {};
      if (!mounted) return;
      setState(() {
        _tabs = tabsRaw
            .whereType<Map>()
            .map(
              (m) => (
                key: (m['key'] ?? '').toString(),
                label: (m['label'] ?? '').toString(),
              ),
            )
            .where((t) => t.key.isNotEmpty)
            .toList();
        _ex = ex;
        _tab = _tabs.isNotEmpty ? _tabs.first.key : 'info';
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = e.toString().replaceFirst('ApiException: ', '');
      });
    }
  }

  String _s(String key) {
    final v = (_ex[key] ?? '').toString().trim();
    return v.isEmpty ? '—' : v;
  }

  List<String> _paras(String key) {
    final raw = _ex[key];
    if (raw is! List) return const [];
    return raw.map((e) => e.toString().trim()).where((e) => e.isNotEmpty).toList();
  }

  List<Map<String, dynamic>> _objectives() {
    final raw = _ex['objectives'];
    if (raw is! List) return const [];
    return raw.whereType<Map>().map((m) => Map<String, dynamic>.from(m)).toList();
  }

  @override
  Widget build(BuildContext context) {
    final name = _s('name');
    final code = (_ex['code'] ?? '').toString().trim();

    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppHeader(
        pageTitle: 'معلومات التمرين',
        brandLine3: name == '—' ? null : name,
        onBack: () => Navigator.of(context).maybePop(),
        showOnlineChip: false,
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator(color: AppColors.goldDark))
          : _error != null
              ? Center(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(_error!, textAlign: TextAlign.center),
                      TextButton(onPressed: _load, child: const Text('إعادة المحاولة')),
                    ],
                  ),
                )
              : Column(
                  children: [
                    Padding(
                      padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
                      child: Row(
                        children: [
                          Expanded(
                            child: Text(
                              name,
                              style: AppTextStyles.cairo(
                                fontSize: 17,
                                fontWeight: FontWeight.w800,
                              ),
                            ),
                          ),
                          if (code.isNotEmpty)
                            Container(
                              padding: const EdgeInsets.symmetric(
                                horizontal: 10,
                                vertical: 4,
                              ),
                              decoration: BoxDecoration(
                                color: AppColors.headerCream,
                                borderRadius: BorderRadius.circular(20),
                                border: Border.all(color: AppColors.divider),
                              ),
                              child: Text(
                                code,
                                style: AppTextStyles.cairo(
                                  fontSize: 12,
                                  fontWeight: FontWeight.w700,
                                ),
                              ),
                            ),
                        ],
                      ),
                    ),
                    SingleChildScrollView(
                      scrollDirection: Axis.horizontal,
                      reverse: true,
                      padding: const EdgeInsets.symmetric(horizontal: 12),
                      child: Row(
                        children: _tabs.map((t) {
                          final selected = t.key == _tab;
                          return Padding(
                            padding: const EdgeInsets.symmetric(horizontal: 4),
                            child: Material(
                              color: selected ? AppColors.goldDark : AppColors.headerCream,
                              borderRadius: BorderRadius.circular(8),
                              child: InkWell(
                                borderRadius: BorderRadius.circular(8),
                                onTap: () => setState(() => _tab = t.key),
                                child: Padding(
                                  padding: const EdgeInsets.symmetric(
                                    horizontal: 14,
                                    vertical: 9,
                                  ),
                                  child: Text(
                                    t.label,
                                    style: AppTextStyles.cairo(
                                      fontWeight: FontWeight.w700,
                                      color: selected ? Colors.white : AppColors.olive,
                                    ),
                                  ),
                                ),
                              ),
                            ),
                          );
                        }).toList(),
                      ),
                    ),
                    const SizedBox(height: 8),
                    Expanded(
                      child: ListView(
                        padding: const EdgeInsets.fromLTRB(16, 0, 16, 20),
                        children: [
                          if (_tab == 'info') ..._buildInfoTab(),
                          if (_tab == 'general')
                            _IdeaPanel(
                              title: 'الفكرة العامة',
                              paragraphs: _paras('general_idea_paragraphs'),
                            ),
                          if (_tab == 'specific')
                            _IdeaPanel(
                              title: 'الفكرة الخاصة',
                              paragraphs: _paras('specific_idea_paragraphs'),
                            ),
                          if (_tab == 'program')
                            FigmaPanel(
                              padding: const EdgeInsets.all(16),
                              child: Text(
                                (_ex['has_program'] == true)
                                    ? 'البرنامج متوفر في النظام على الكمبيوتر (عرض فقط من صفحة التمرين).'
                                    : 'لا يوجد برنامج مسجّل بعد.',
                                style: AppTextStyles.cairo(color: AppColors.muted),
                              ),
                            ),
                          if (_tab == 'map')
                            FigmaPanel(
                              padding: const EdgeInsets.all(16),
                              child: Text(
                                (_ex['has_map'] == true)
                                    ? 'الخريطة متوفرة في النظام على الكمبيوتر (عرض فقط من صفحة التمرين).'
                                    : 'لا توجد خريطة مسجّلة بعد.',
                                style: AppTextStyles.cairo(color: AppColors.muted),
                              ),
                            ),
                        ],
                      ),
                    ),
                  ],
                ),
    );
  }

  List<Widget> _buildInfoTab() {
    final objectives = _objectives();
    return [
      LayoutBuilder(
        builder: (context, c) {
          final wide = c.maxWidth > 720;
          final info = _InfoCard(
            title: 'معلومات التمرين',
            rows: [
              ('اسم التمرين', _s('name')),
              ('الوحدة المتدربة', _s('trained_unit')),
              ('مكان التمرين', _s('location')),
              ('نوع التمرين', _s('type_label')),
              ('مستوى التمرين', _s('level_label')),
              ('تاريخ التمرين', _s('period_label')),
              ('المهمة', _s('mission_label')),
            ],
          );
          final purpose = _TextCard(
            title: 'القصد',
            text: (_ex['exercise_purpose'] ?? '').toString(),
            empty: 'لا يوجد قصد مسجّل بعد.',
          );
          final typeLevel = _TextCard(
            title: 'نوع ومستوى التمرين',
            text: (_ex['exercise_type_level_text'] ?? '').toString(),
            empty: 'لا يوجد نوع ومستوى مسجّلان بعد.',
          );
          final participants = _TextCard(
            title: 'المشاركون في التمرين',
            text: (_ex['exercise_participants'] ?? '').toString(),
            empty: 'لا يوجد مشاركون مسجّلون بعد.',
          );
          final objectivesCard = FigmaPanel(
            padding: const EdgeInsets.all(14),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(
                  'الأهداف التدريبية',
                  style: AppTextStyles.cairo(fontSize: 15, fontWeight: FontWeight.w800),
                ),
                const Divider(height: 14),
                if (objectives.isEmpty)
                  Text(
                    'لا توجد أهداف مسجّلة بعد.',
                    style: AppTextStyles.cairo(color: AppColors.muted),
                  )
                else
                  ...objectives.asMap().entries.map((e) {
                    final text = (e.value['text'] ?? '').toString();
                    return Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: Text(
                        '${e.key + 1}. $text',
                        style: AppTextStyles.body,
                      ),
                    );
                  }),
                const SizedBox(height: 6),
                Text(
                  'تعديل الأهداف التدريبية من مساحة إدارة النظام',
                  style: AppTextStyles.cairo(fontSize: 11, color: AppColors.muted),
                ),
              ],
            ),
          );

          if (!wide) {
            return Column(
              children: [
                info,
                const SizedBox(height: 10),
                purpose,
                const SizedBox(height: 10),
                typeLevel,
                const SizedBox(height: 10),
                participants,
                const SizedBox(height: 10),
                objectivesCard,
              ],
            );
          }
          return Column(
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(child: info),
                  const SizedBox(width: 10),
                  Expanded(child: purpose),
                  const SizedBox(width: 10),
                  Expanded(child: typeLevel),
                ],
              ),
              const SizedBox(height: 10),
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(flex: 2, child: participants),
                  const SizedBox(width: 10),
                  Expanded(flex: 3, child: objectivesCard),
                ],
              ),
            ],
          );
        },
      ),
    ];
  }
}

class _InfoCard extends StatelessWidget {
  const _InfoCard({required this.title, required this.rows});
  final String title;
  final List<(String, String)> rows;

  @override
  Widget build(BuildContext context) {
    return FigmaPanel(
      padding: const EdgeInsets.all(14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(title, style: AppTextStyles.cairo(fontSize: 15, fontWeight: FontWeight.w800)),
          const Divider(height: 14),
          ...rows.map(
            (r) => Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  SizedBox(
                    width: 120,
                    child: Text(
                      '${r.$1}:',
                      style: AppTextStyles.cairo(
                        fontSize: 12,
                        color: AppColors.muted,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                  Expanded(
                    child: Text(
                      r.$2,
                      style: AppTextStyles.cairo(fontWeight: FontWeight.w700),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _TextCard extends StatelessWidget {
  const _TextCard({
    required this.title,
    required this.text,
    required this.empty,
  });
  final String title;
  final String text;
  final String empty;

  @override
  Widget build(BuildContext context) {
    final t = text.trim();
    return FigmaPanel(
      padding: const EdgeInsets.all(14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(title, style: AppTextStyles.cairo(fontSize: 15, fontWeight: FontWeight.w800)),
          const Divider(height: 14),
          Text(
            t.isEmpty ? empty : t,
            style: AppTextStyles.cairo(
              color: t.isEmpty ? AppColors.muted : AppColors.darkText,
              fontWeight: t.isEmpty ? FontWeight.w600 : FontWeight.w500,
            ),
          ),
        ],
      ),
    );
  }
}

class _IdeaPanel extends StatelessWidget {
  const _IdeaPanel({required this.title, required this.paragraphs});
  final String title;
  final List<String> paragraphs;

  @override
  Widget build(BuildContext context) {
    return FigmaPanel(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(title, style: AppTextStyles.cairo(fontSize: 16, fontWeight: FontWeight.w800)),
          const Divider(height: 16),
          if (paragraphs.isEmpty)
            Text('—', style: AppTextStyles.cairo(color: AppColors.muted))
          else
            ...paragraphs.asMap().entries.map(
                  (e) => Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '${e.key + 1}.',
                          style: AppTextStyles.cairo(fontWeight: FontWeight.w800),
                        ),
                        const SizedBox(width: 8),
                        Expanded(child: Text(e.value, style: AppTextStyles.body)),
                      ],
                    ),
                  ),
                ),
        ],
      ),
    );
  }
}
