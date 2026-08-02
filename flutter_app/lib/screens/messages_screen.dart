import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import '../widgets/app_header.dart';
import '../widgets/figma_ui.dart';

/// الرسائل — تكليف مهمة خاصة (التخطيط والسيطرة).
class MessagesScreen extends StatefulWidget {
  const MessagesScreen({super.key});

  @override
  State<MessagesScreen> createState() => _MessagesScreenState();
}

class _MessagesScreenState extends State<MessagesScreen> {
  final _titleCtrl = TextEditingController();
  final _bodyCtrl = TextEditingController();
  final _list = <({String title, String body, String at})>[];

  @override
  void dispose() {
    _titleCtrl.dispose();
    _bodyCtrl.dispose();
    super.dispose();
  }

  void _submit() {
    final title = _titleCtrl.text.trim();
    final body = _bodyCtrl.text.trim();
    if (title.isEmpty || body.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('أدخل عنوان التكليف ونصه')),
      );
      return;
    }
    setState(() {
      _list.insert(0, (
        title: title,
        body: body,
        at: TimeOfDay.now().format(context),
      ));
      _titleCtrl.clear();
      _bodyCtrl.clear();
    });
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('تم تسجيل تكليف المهمة الخاصة محلياً')),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppHeader(
        pageTitle: 'الرسائل',
        pageSubtitle: 'تكليف مهمة خاصة — التخطيط والسيطرة',
        onBack: () => Navigator.of(context).maybePop(),
        showOnlineChip: false,
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          FigmaPanel(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(
                  'تكليف مهمة خاصة',
                  style: AppTextStyles.cairo(fontSize: 16, fontWeight: FontWeight.w800),
                ),
                const SizedBox(height: 6),
                Text(
                  'أرسل تكليفاً مرتبطاً بالتخطيط والسيطرة ليُحفظ مع سجل المحكم.',
                  style: AppTextStyles.cairo(fontSize: 13, color: AppColors.muted),
                ),
                const SizedBox(height: 14),
                TextField(
                  controller: _titleCtrl,
                  decoration: const InputDecoration(
                    labelText: 'عنوان التكليف',
                    filled: true,
                    fillColor: AppColors.headerCream,
                  ),
                ),
                const SizedBox(height: 10),
                TextField(
                  controller: _bodyCtrl,
                  minLines: 3,
                  maxLines: 5,
                  decoration: const InputDecoration(
                    labelText: 'نص المهمة',
                    filled: true,
                    fillColor: AppColors.headerCream,
                  ),
                ),
                const SizedBox(height: 12),
                ElevatedButton.icon(
                  onPressed: _submit,
                  icon: const Icon(Icons.send_outlined, size: 18),
                  label: const Text('إرسال التكليف'),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: AppColors.buttonBrown,
                    foregroundColor: AppColors.white,
                    padding: const EdgeInsets.symmetric(vertical: 12),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 16),
          Text(
            'التكليفات المسجّلة',
            style: AppTextStyles.cairo(fontSize: 15, fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 10),
          if (_list.isEmpty)
            FigmaPanel(
              padding: const EdgeInsets.all(24),
              child: Center(
                child: Text(
                  'لا توجد تكليفات بعد',
                  style: AppTextStyles.cairo(color: AppColors.muted),
                ),
              ),
            )
          else
            ..._list.map(
              (m) => Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: FigmaPanel(
                  padding: const EdgeInsets.all(14),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Row(
                        children: [
                          const Icon(Icons.assignment_outlined, color: AppColors.goldDark),
                          const SizedBox(width: 8),
                          Expanded(
                            child: Text(
                              m.title,
                              style: AppTextStyles.cairo(
                                fontWeight: FontWeight.w800,
                                fontSize: 15,
                              ),
                            ),
                          ),
                          Text(
                            m.at,
                            style: AppTextStyles.cairo(fontSize: 11, color: AppColors.muted),
                          ),
                        ],
                      ),
                      const SizedBox(height: 8),
                      Text(m.body, style: AppTextStyles.body),
                    ],
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}
