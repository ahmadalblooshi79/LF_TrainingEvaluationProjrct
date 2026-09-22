import 'dart:typed_data';

import 'package:flutter/material.dart';

import '../services/api_client.dart';
import '../services/tablet_repository.dart';
import '../theme/app_theme.dart';
import '../widgets/app_header.dart';
import '../widgets/async_state_views.dart';
import '../widgets/figma_ui.dart';

/// معلومات التمرين — قراءة فقط، شبكة المربعات مطابقة لصفحة النظام.
class ExerciseDetailsScreen extends StatefulWidget {
  const ExerciseDetailsScreen({super.key});

  @override
  State<ExerciseDetailsScreen> createState() => _ExerciseDetailsScreenState();
}

class _ExerciseDetailsScreenState extends State<ExerciseDetailsScreen> {
  bool _loading = true;
  bool _fromCache = false;
  String? _error;
  String _tab = 'info';
  List<({String key, String label})> _tabs = const [];
  Map<String, dynamic> _ex = {};

  static const double _gap = 10;

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
      final fetched = await TabletRepository.instance.fetchExerciseDetails();
      final data = fetched.data;
      final tabsRaw = (data['tabs'] as List?) ?? const [];
      final ex = (data['exercise'] as Map?)?.cast<String, dynamic>() ?? {};
      if (!mounted) return;
      setState(() {
        _fromCache = fetched.fromCache;
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
                    if (_fromCache) const CachedDataBanner(),
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
                        padding: const EdgeInsets.fromLTRB(12, 0, 12, 16),
                        children: [
                          if (_tab == 'info') _buildInfoTab(),
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
                            _WorkspaceImagePane(
                              kind: 'program',
                              hasImage: _ex['has_program'] == true,
                              emptyLabel: 'لا توجد صورة برنامج مدرجة بعد.',
                            ),
                          if (_tab == 'map')
                            _WorkspaceImagePane(
                              kind: 'map',
                              hasImage: _ex['has_map'] == true,
                              emptyLabel: 'لا توجد صورة خريطة مدرجة بعد.',
                            ),
                        ],
                      ),
                    ),
                  ],
                ),
    );
  }

  Widget _buildInfoTab() {
    final objectives = _objectives();
    final info = _InfoBox(
      title: 'معلومات التمرين',
      minHeight: 220,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          for (final r in [
            ('اسم التمرين', _s('name')),
            ('الوحدة المتدربة', _s('trained_unit')),
            ('مكان التمرين', _s('location')),
            ('نوع التمرين', _s('type_label')),
            ('مستوى التمرين', _s('level_label')),
            ('تاريخ التمرين', _s('period_label')),
            ('المهمة', _s('mission_label')),
          ])
            Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: Text.rich(
                TextSpan(
                  style: AppTextStyles.cairo(fontSize: 13, height: 1.45),
                  children: [
                    TextSpan(
                      text: '${r.$1}: ',
                      style: const TextStyle(
                        fontWeight: FontWeight.w800,
                        color: AppColors.olive,
                      ),
                    ),
                    TextSpan(
                      text: r.$2,
                      style: const TextStyle(
                        fontWeight: FontWeight.w600,
                        color: AppColors.darkText,
                      ),
                    ),
                  ],
                ),
              ),
            ),
        ],
      ),
    );
    final purpose = _InfoBox(
      title: 'القصد',
      minHeight: 220,
      child: _EmptyOrText(
        text: (_ex['exercise_purpose'] ?? '').toString(),
        empty: 'لا يوجد قصد مسجّل بعد.',
      ),
    );
    final typeLevel = _InfoBox(
      title: 'نوع ومستوى التمرين',
      minHeight: 220,
      child: _EmptyOrText(
        text: (_ex['exercise_type_level_text'] ?? '').toString(),
        empty: 'لا يوجد نوع ومستوى مسجّلان بعد.',
      ),
    );
    final participants = _InfoBox(
      title: 'المشاركون في التمرين',
      minHeight: 190,
      child: _EmptyOrText(
        text: (_ex['exercise_participants'] ?? '').toString(),
        empty: 'لا يوجد مشاركون مسجّلون بعد.',
      ),
    );
    final objectivesCard = _InfoBox(
      title: 'الأهداف التدريبية',
      minHeight: 190,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (objectives.isEmpty)
            Text(
              'لا توجد أهداف مسجّلة بعد.',
              style: AppTextStyles.cairo(color: AppColors.muted, fontWeight: FontWeight.w600),
            )
          else
            ...objectives.asMap().entries.map((e) {
              final text = (e.value['text'] ?? '').toString();
              return Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Text(
                  '${e.key + 1}. $text',
                  style: AppTextStyles.cairo(fontSize: 13, height: 1.45),
                ),
              );
            }),
          const SizedBox(height: 4),
          Text(
            'تعديل الأهداف التدريبية من مساحة إدارة النظام',
            style: AppTextStyles.cairo(fontSize: 11, color: const Color(0xFF2F6FED)),
          ),
        ],
      ),
    );

    return LayoutBuilder(
      builder: (context, c) {
        final wide = c.maxWidth >= 780;
        if (!wide) {
          return Column(
            children: [
              info,
              const SizedBox(height: _gap),
              purpose,
              const SizedBox(height: _gap),
              typeLevel,
              const SizedBox(height: _gap),
              participants,
              const SizedBox(height: _gap),
              objectivesCard,
            ],
          );
        }
        // مثل النظام: صف علوي 3 متساوية، صف سفلي ≈ 0.9 : 1.6 مع تمدد الارتفاع.
        return Column(
          children: [
            IntrinsicHeight(
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Expanded(child: info),
                  const SizedBox(width: _gap),
                  Expanded(child: purpose),
                  const SizedBox(width: _gap),
                  Expanded(child: typeLevel),
                ],
              ),
            ),
            const SizedBox(height: _gap),
            IntrinsicHeight(
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Expanded(flex: 9, child: participants),
                  const SizedBox(width: _gap),
                  Expanded(flex: 16, child: objectivesCard),
                ],
              ),
            ),
          ],
        );
      },
    );
  }
}

class _EmptyOrText extends StatelessWidget {
  const _EmptyOrText({required this.text, required this.empty});
  final String text;
  final String empty;

  @override
  Widget build(BuildContext context) {
    final t = text.trim();
    return Text(
      t.isEmpty ? empty : t,
      style: AppTextStyles.cairo(
        color: t.isEmpty ? AppColors.muted : AppColors.darkText,
        fontWeight: t.isEmpty ? FontWeight.w600 : FontWeight.w500,
        fontSize: 13,
        height: 1.5,
      ),
    );
  }
}

/// مربع معلومات بأسلوب صفحة النظام (حدود رفيعة + عنوان مركزي + خلفية كريمية).
class _InfoBox extends StatelessWidget {
  const _InfoBox({
    required this.title,
    required this.child,
    this.minHeight = 180,
  });

  final String title;
  final Widget child;
  final double minHeight;

  static const Color _border = Color(0xFF8FA8C7);

  @override
  Widget build(BuildContext context) {
    return Container(
      constraints: BoxConstraints(minHeight: minHeight),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: _border),
        gradient: const LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [Color(0xFFFFFDF8), Color(0xFFF7F2E8)],
        ),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.max,
        children: [
          Container(
            width: double.infinity,
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 9),
            decoration: BoxDecoration(
              color: Colors.white.withValues(alpha: 0.55),
              border: const Border(bottom: BorderSide(color: _border)),
            ),
            child: Text(
              title,
              textAlign: TextAlign.center,
              style: AppTextStyles.cairo(
                fontSize: 14,
                fontWeight: FontWeight.w800,
                color: AppColors.olive,
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 10, 12, 12),
            child: child,
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

class _WorkspaceImagePane extends StatefulWidget {
  const _WorkspaceImagePane({
    required this.kind,
    required this.hasImage,
    required this.emptyLabel,
  });

  final String kind;
  final bool hasImage;
  final String emptyLabel;

  @override
  State<_WorkspaceImagePane> createState() => _WorkspaceImagePaneState();
}

class _WorkspaceImagePaneState extends State<_WorkspaceImagePane> {
  Uint8List? _bytes;
  bool _loading = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(covariant _WorkspaceImagePane oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.kind != widget.kind || oldWidget.hasImage != widget.hasImage) {
      _load();
    }
  }

  Future<void> _load() async {
    if (!widget.hasImage) {
      setState(() {
        _bytes = null;
        _loading = false;
        _error = null;
      });
      return;
    }
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final bytes = await TabletRepository.instance.fetchExerciseWorkspaceImage(widget.kind);
      if (!mounted) return;
      setState(() {
        _bytes = bytes == null ? null : Uint8List.fromList(bytes);
        _loading = false;
        if (_bytes == null || _bytes!.isEmpty) {
          _error = widget.emptyLabel;
        }
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = 'تعذّر عرض الصورة.';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    if (!widget.hasImage) {
      return FigmaPanel(
        padding: const EdgeInsets.all(16),
        child: Text(widget.emptyLabel, style: AppTextStyles.cairo(color: AppColors.muted)),
      );
    }
    if (_loading) {
      return const Padding(
        padding: EdgeInsets.all(24),
        child: Center(child: CircularProgressIndicator(color: AppColors.goldDark)),
      );
    }
    if (_bytes == null || _bytes!.isEmpty) {
      return FigmaPanel(
        padding: const EdgeInsets.all(16),
        child: Text(_error ?? widget.emptyLabel, style: AppTextStyles.cairo(color: AppColors.muted)),
      );
    }
    return FigmaPanel(
      padding: const EdgeInsets.all(8),
      child: InteractiveViewer(
        minScale: 0.6,
        maxScale: 4,
        child: Image.memory(_bytes!, fit: BoxFit.contain),
      ),
    );
  }
}
