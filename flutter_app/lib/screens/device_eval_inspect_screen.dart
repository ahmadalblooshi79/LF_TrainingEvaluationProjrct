import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../models/eval_sheet.dart';
import '../services/api_client.dart';
import '../services/device_eval_manager_models.dart';
import '../services/device_eval_manager_service.dart';
import '../theme/app_theme.dart';
import '../widgets/app_header.dart';

class DeviceEvalInspectArgs {
  final DeviceEvalUser user;
  final DeviceEvalListSummary summary;
  final String exerciseName;

  const DeviceEvalInspectArgs({
    required this.user,
    required this.summary,
    required this.exerciseName,
  });
}

class DeviceEvalInspectScreen extends StatefulWidget {
  const DeviceEvalInspectScreen({super.key, required this.args});

  final DeviceEvalInspectArgs args;

  @override
  State<DeviceEvalInspectScreen> createState() =>
      _DeviceEvalInspectScreenState();
}

class _DeviceEvalInspectScreenState extends State<DeviceEvalInspectScreen> {
  bool _loading = true;
  bool _busy = false;
  String? _msg;
  bool _msgOk = false;
  DeviceEvalInspectData? _data;

  DeviceEvalListSummary get _summary => _data?.summary ?? widget.args.summary;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
    });
    final data = await DeviceEvalManagerService.instance.loadInspect(
      user: widget.args.user,
      summary: widget.args.summary,
      exerciseName: widget.args.exerciseName,
    );
    if (!mounted) return;
    setState(() {
      _data = data;
      _loading = false;
    });
  }

  Future<void> _download(
    Future<DeviceEvalDownloadResult> Function(bool online) action,
  ) async {
    setState(() {
      _busy = true;
      _msg = null;
    });
    final result = await action(ApiClient.instance.online.value);
    if (!mounted) return;
    setState(() {
      _busy = false;
      _msgOk = result.ok;
      _msg = [
        result.message,
        if (result.displayPath != null) 'مكان الحفظ:\n${result.displayPath}',
        ...result.warnings,
      ].join('\n');
    });
  }

  Future<void> _reopen() async {
    final summary = _summary;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('إعادة فتح القائمة'),
        content: Text(
          'هل تريد إعادة فتح هذه القائمة؟\n\n'
          'اسم المحكم: ${widget.args.user.displayName.isNotEmpty ? widget.args.user.displayName : widget.args.user.label}\n'
          'اسم القائمة: ${summary.title}\n'
          'الحالة الحالية: ${summary.statusLabel.isNotEmpty ? summary.statusLabel : '—'}',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('إلغاء'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('تأكيد'),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    setState(() {
      _busy = true;
      _msg = null;
    });
    final result = await DeviceEvalManagerService.instance.reopenApprovedList(
      summary: summary,
      online: ApiClient.instance.online.value,
    );
    if (!mounted) return;
    setState(() {
      _busy = false;
      _msgOk = result.ok;
      _msg = result.message;
    });
    if (result.ok) {
      await _load();
    }
  }

  @override
  Widget build(BuildContext context) {
    final user = widget.args.user;
    final summary = _summary;
    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppHeader(
        pageTitle: 'معاينة قائمة التقييم',
        onBack: () => Navigator.of(context).maybePop(),
        showSettings: false,
        showLogout: false,
        showUtilityActions: false,
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator(color: AppColors.gold))
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                _card([
                  Text('معاينة للقراءة فقط', style: AppTextStyles.subtitle),
                  const SizedBox(height: 8),
                  Text('المحكم: ${user.label}'),
                  Text('التمرين: ${widget.args.exerciseName}'),
                  Text('القائمة: ${summary.title}'),
                  if (summary.unitLabel.trim().isNotEmpty)
                    Text('الوحدة: ${summary.unitLabel}'),
                  if (summary.phaseKey.trim().isNotEmpty)
                    Text('المرحلة: ${summary.phaseKey}'),
                  Text(
                    'الحالة: ${summary.statusLabel.trim().isNotEmpty ? summary.statusLabel : (_data?.detail?.workflow.label ?? '—')}',
                  ),
                  Text(
                    summary.kind == DeviceEvalKind.procedure
                        ? 'النوع: قوائم تقييم الإجراءات'
                        : 'النوع: قوائم تقييم المعاضل',
                  ),
                ]),
                if (_msg != null) ...[
                  const SizedBox(height: 12),
                  Text(
                    _msg!,
                    style: AppTextStyles.body.copyWith(
                      color: _msgOk ? AppColors.doneGreen : AppColors.notDoneRed,
                    ),
                  ),
                ],
                const SizedBox(height: 12),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    OutlinedButton(
                      onPressed: _busy
                          ? null
                          : () => _download((online) {
                                return DeviceEvalManagerService.instance
                                    .downloadExcel(
                                  user: user,
                                  summary: summary,
                                  exerciseName: widget.args.exerciseName,
                                  online: online,
                                );
                              }),
                      child: const Text('تنزيل Excel'),
                    ),
                    OutlinedButton(
                      onPressed: _busy
                          ? null
                          : () => _download((_) {
                                return DeviceEvalManagerService.instance
                                    .downloadAttachments(
                                  user: user,
                                  summary: summary,
                                  exerciseName: widget.args.exerciseName,
                                );
                              }),
                      child: const Text('تنزيل المرفقات'),
                    ),
                    OutlinedButton(
                      onPressed: _busy
                          ? null
                          : () => _download((online) {
                                return DeviceEvalManagerService.instance
                                    .downloadListWithAttachments(
                                  user: user,
                                  summary: summary,
                                  exerciseName: widget.args.exerciseName,
                                  online: online,
                                );
                              }),
                      child: const Text('تنزيل القائمة مع المرفقات'),
                    ),
                    if (reopenButtonVisible(
                      approved: summary.isApproved ||
                          (_data?.detail?.isApproved ?? false),
                      inspectOnly: true,
                    ))
                      ElevatedButton(
                        onPressed: _busy ? null : _reopen,
                        child: const Text('إعادة فتح القائمة'),
                      ),
                  ],
                ),
                const SizedBox(height: 16),
                Text('بنود التقييم', style: AppTextStyles.subtitle),
                const SizedBox(height: 8),
                if ((_data?.rows ?? const []).isEmpty)
                  _card([
                    Text(
                      'لا توجد بنود محفوظة على الجهاز لهذه القائمة',
                      style: AppTextStyles.body.copyWith(color: AppColors.muted),
                    ),
                  ])
                else
                  for (var i = 0; i < _data!.rows.length; i++)
                    _rowCard(i, _data!.rows[i]),
                const SizedBox(height: 16),
                Text('المرفقات', style: AppTextStyles.subtitle),
                const SizedBox(height: 8),
                if ((_data?.media ?? const []).isEmpty)
                  _card([
                    Text(
                      'لا توجد مرفقات مرتبطة بهذه القائمة على الجهاز',
                      style: AppTextStyles.body.copyWith(color: AppColors.muted),
                    ),
                  ])
                else
                  for (final m in _data!.media) _mediaTile(m),
              ],
            ),
    );
  }

  Widget _rowCard(int index, EvalRowInput row) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: _card([
        Text(
          '${index + 1}. ${row.element}',
          style: AppTextStyles.body.copyWith(fontWeight: FontWeight.w700),
        ),
        const SizedBox(height: 4),
        Text('النتيجة: ${row.acquired.toString().trim().isEmpty ? '—' : row.acquired}'),
        Text('الملاحظات: ${row.notes.toString().trim().isEmpty ? '—' : row.notes}'),
      ]),
    );
  }

  Widget _mediaTile(DeviceEvalMediaRef media) {
    Widget preview;
    if (!kIsWeb &&
        !media.isVideo &&
        media.localPath.isNotEmpty &&
        File(media.localPath).existsSync()) {
      preview = Image.file(
        File(media.localPath),
        height: 96,
        fit: BoxFit.cover,
        cacheWidth: 240,
      );
    } else {
      preview = Icon(
        media.isVideo ? Icons.videocam_outlined : Icons.image_outlined,
        color: AppColors.goldDark,
      );
    }
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: _card([
        Row(
          children: [
            SizedBox(width: 72, height: 72, child: preview),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(media.downloadName),
                  Text(
                    media.isVideo ? 'فيديو' : 'صورة',
                    style: AppTextStyles.small,
                  ),
                ],
              ),
            ),
          ],
        ),
      ]),
    );
  }

  Widget _card(List<Widget> children) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.cardWhite,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.divider),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: children,
      ),
    );
  }
}
