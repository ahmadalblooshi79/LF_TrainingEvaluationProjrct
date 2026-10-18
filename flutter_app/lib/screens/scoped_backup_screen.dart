import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../services/auth_service.dart';
import '../services/scoped_backup_models.dart';
import '../services/scoped_backup_paths.dart';
import '../services/scoped_backup_service.dart';
import '../theme/app_theme.dart';
import '../widgets/app_header.dart';

class ScopedBackupScreen extends StatefulWidget {
  final bool deviceManager;

  const ScopedBackupScreen({super.key, this.deviceManager = false});

  @override
  State<ScopedBackupScreen> createState() => _ScopedBackupScreenState();
}

class _ScopedBackupScreenState extends State<ScopedBackupScreen> {
  bool _loading = true;
  bool _busy = false;
  String? _error;
  String? _okMsg;
  ScopedBackupExercise? _exercise;
  List<Map<String, dynamic>> _users = [];
  int? _selectedUserId;
  ScopedBackupProgress? _progress;
  ScopedBackupResult? _result;
  RestorePreview? _preview;
  String? _importPath;
  String _userSearch = '';

  bool get _isAdmin => widget.deviceManager;

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
      final exercise = await ScopedBackupService.instance.currentExercise();
      final users = await ScopedBackupService.instance.provisionedUsersSafe();
      int? selected = _selectedUserId;
      if (!_isAdmin) {
        selected = AuthService.instance.currentUserId;
      } else {
        selected ??= users.isNotEmpty ? users.first['user_id'] as int? : null;
      }
      if (!mounted) return;
      setState(() {
        _exercise = exercise;
        _users = users;
        _selectedUserId = selected;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = '$e';
      });
    }
  }

  String _userLabel(Map<String, dynamic> u) {
    final name = '${u['display_name'] ?? ''}'.trim();
    final username = '${u['username'] ?? ''}'.trim();
    final mil = '${u['military_number'] ?? ''}'.trim();
    final id = u['user_id'];
    final parts = <String>[
      if (name.isNotEmpty) name,
      if (username.isNotEmpty) username,
      if (mil.isNotEmpty) mil,
      'رقم $id',
    ];
    return parts.join(' — ');
  }

  Future<void> _create() async {
    final userId = _selectedUserId;
    if (userId == null) {
      setState(() => _error = 'اختر مستخدماً');
      return;
    }
    if (_isAdmin) {
      final visible = filterUsersByDisplayName(_users, _userSearch);
      if (visible.isEmpty) {
        setState(() => _error = kNoMatchingUserMessage);
        return;
      }
      if (!visible.any((u) => u['user_id'] == userId)) {
        setState(() => _error = 'اختر مستخدماً');
        return;
      }
    }
    if (!_isAdmin && userId != AuthService.instance.currentUserId) {
      setState(() => _error = 'لا يمكن نسخ بيانات مستخدم آخر');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
      _okMsg = null;
      _result = null;
      _progress = const ScopedBackupProgress(stage: 'جارٍ إنشاء النسخة الاحتياطية');
    });
    ScopedBackupService.instance.resetCancel();
    final result = await ScopedBackupService.instance.createBackupForUser(
      userId: userId,
      onProgress: (p) {
        if (mounted) setState(() => _progress = p);
      },
    );
    if (!mounted) return;
    setState(() {
      _busy = false;
      _result = result;
      if (result.savedToPublicDownloads) {
        _okMsg = backupSuccessMessage(
          result.publicDisplayPath!,
          procedureExcelCount: result.procedureExcelCount,
          dilemmaExcelCount: result.dilemmaExcelCount,
          evaluationImageCount: result.evaluationImageCount,
          evaluationVideoCount: result.evaluationVideoCount,
        );
      } else if (result.verified) {
        _error = 'تعذر حفظ النسخة الاحتياطية في مجلد التنزيلات';
      } else if (result.status == ScopedBackupStatus.cancelled) {
        _error = 'تم إلغاء النسخة الاحتياطية';
      } else if (result.status == ScopedBackupStatus.corrupt) {
        _error = 'النسخة الاحتياطية غير صالحة';
      } else {
        _error = result.error ?? 'فشل إنشاء النسخة الاحتياطية';
      }
    });
  }

  Future<void> _cancel() async {
    ScopedBackupService.instance.requestCancel();
  }

  Future<void> _openSavedFolder() async {
    final relative = _result?.publicRelativeDir;
    if (relative == null || relative.isEmpty || kIsWeb) return;
    await ScopedBackupService.instance.openPublicBackupFolder(relative);
  }

  Future<void> _pickRestore() async {
    setState(() {
      _busy = true;
      _error = null;
      _preview = null;
      _okMsg = null;
    });
    try {
      final path = await ScopedBackupService.instance.importPackageFromUserLocation();
      if (!mounted) return;
      if (path == null || path.isEmpty) {
        setState(() => _busy = false);
        return;
      }
      final userId = _selectedUserId;
      if (userId == null) {
        setState(() {
          _busy = false;
          _error = 'اختر مستخدماً';
        });
        return;
      }
      final preview = await ScopedBackupService.instance.previewRestore(
        packageDir: Directory(path),
        selectedUserId: userId,
      );
      if (!mounted) return;
      setState(() {
        _busy = false;
        _importPath = path;
        _preview = preview;
        if (!preview.canRestore) {
          _error = preview.blockers.isEmpty
              ? 'النسخة الاحتياطية غير صالحة'
              : preview.blockers.first;
        }
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = '$e';
      });
    }
  }

  Future<void> _confirmRestore() async {
    final preview = _preview;
    final path = _importPath;
    final userId = _selectedUserId;
    if (preview == null || path == null || userId == null || !preview.canRestore) {
      return;
    }
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('استعادة نسخة احتياطية'),
        content: Text(
          'سيتم استعادة بيانات المستخدم ${_preview?.manifest.user.displayName.isNotEmpty == true ? _preview!.manifest.user.displayName : userId} '
          'للتمرين الحالي فقط. لن تُمس بيانات المستخدمين الآخرين.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('إلغاء'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('تأكيد الاستعادة'),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    setState(() {
      _busy = true;
      _error = null;
      _okMsg = null;
    });
    final result = await ScopedBackupService.instance.restorePackage(
      packageDir: Directory(path),
      selectedUserId: userId,
      preview: preview,
      onProgress: (p) {
        if (mounted) setState(() => _progress = p);
      },
    );
    if (!mounted) return;
    setState(() {
      _busy = false;
      if (result.ok) {
        _okMsg = 'تمت الاستعادة';
        _preview = null;
      } else {
        _error = result.rollbackFailed
            ? 'فشلت الاستعادة وفشل التراجع: ${result.error}'
            : (result.error ?? 'فشلت الاستعادة');
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final exercise = _exercise;
    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppHeader(
        pageTitle: 'النسخ الاحتياطي والاستعادة',
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
                if (_error != null)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: Text(
                      _error!,
                      style: AppTextStyles.body.copyWith(color: AppColors.notDoneRed),
                    ),
                  ),
                if (_okMsg != null)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: Text(
                      _okMsg!,
                      style: AppTextStyles.body.copyWith(color: AppColors.doneGreen),
                    ),
                  ),
                _card([
                  Text('التمرين الحالي', style: AppTextStyles.subtitle),
                  const SizedBox(height: 8),
                  Text(
                    exercise == null
                        ? 'لا يوجد تمرين حالي'
                        : (exercise.name.isNotEmpty
                            ? '${exercise.name} (${exercise.exerciseId})'
                            : 'تمرين ${exercise.exerciseId}'),
                  ),
                ]),
                const SizedBox(height: 12),
                _card([
                  Text('المستخدم', style: AppTextStyles.subtitle),
                  const SizedBox(height: 8),
                  if (_isAdmin)
                    BackupUserSelectPanel(
                      users: _users,
                      selectedUserId: _selectedUserId,
                      searchQuery: _userSearch,
                      enabled: !_busy,
                      userLabel: _userLabel,
                      onSearchChanged: (q) => setState(() => _userSearch = q),
                      onSelected: (v) => setState(() {
                        _selectedUserId = v;
                        _result = null;
                        _preview = null;
                      }),
                    )
                  else
                    Text(
                      _users
                          .where((u) => u['user_id'] == _selectedUserId)
                          .map(_userLabel)
                          .followedBy(['المستخدم الحالي'])
                          .first,
                    ),
                ]),
                const SizedBox(height: 16),
                if (_busy && _progress != null) ...[
                  Text(_progress!.stage, textAlign: TextAlign.center),
                  if (_progress!.currentFile.isNotEmpty)
                    Text(
                      _progress!.currentFile,
                      style: AppTextStyles.small,
                      textAlign: TextAlign.center,
                    ),
                  const SizedBox(height: 8),
                  LinearProgressIndicator(
                    value: _progress!.totalBytes > 0
                        ? (_progress!.bytesProcessed / _progress!.totalBytes)
                            .clamp(0.0, 1.0)
                        : null,
                    color: AppColors.gold,
                  ),
                  const SizedBox(height: 8),
                  if (_progress!.totalBytes > 0)
                    Text(
                      '${_progress!.bytesProcessed} / ${_progress!.totalBytes}  (${_progress!.percent}%)',
                      textAlign: TextAlign.center,
                      style: AppTextStyles.small,
                    ),
                  const SizedBox(height: 8),
                  OutlinedButton(
                    onPressed: _cancel,
                    child: const Text('إلغاء'),
                  ),
                  const SizedBox(height: 16),
                ],
                ElevatedButton(
                  onPressed: _busy ? null : _create,
                  style: ElevatedButton.styleFrom(
                    backgroundColor: AppColors.buttonBrown,
                    foregroundColor: AppColors.white,
                    padding: const EdgeInsets.symmetric(vertical: 14),
                  ),
                  child: Text(
                    _busy ? 'جارٍ إنشاء النسخة الاحتياطية' : 'إنشاء نسخة احتياطية',
                  ),
                ),
                if (_result?.savedToPublicDownloads == true &&
                    (_result?.publicRelativeDir ?? '').isNotEmpty) ...[
                  const SizedBox(height: 8),
                  OutlinedButton(
                    onPressed: _busy ? null : _openSavedFolder,
                    child: const Text('فتح المجلد'),
                  ),
                ],
                const SizedBox(height: 24),
                Text('استعادة نسخة احتياطية', style: AppTextStyles.subtitle),
                const SizedBox(height: 8),
                OutlinedButton(
                  onPressed: _busy ? null : _pickRestore,
                  child: const Text('التحقق من النسخة الاحتياطية'),
                ),
                if (_preview != null) ...[
                  const SizedBox(height: 12),
                  _card([
                    Text('المستخدم: ${_preview!.manifest.user.displayName.isNotEmpty ? _preview!.manifest.user.displayName : _preview!.manifest.user.username}'),
                    Text('التمرين: ${_preview!.manifest.exercise.exerciseId}'),
                    Text('السجلات: ${_preview!.manifest.recordCounts}'),
                    Text('الوسائط: ${_preview!.manifest.mediaCount}'),
                    if (_preview!.warnings.isNotEmpty)
                      Text('تحذيرات: ${_preview!.warnings.length}'),
                    if (_preview!.blockers.isNotEmpty)
                      Text(
                        _preview!.blockers.join('\n'),
                        style: AppTextStyles.small.copyWith(color: AppColors.notDoneRed),
                      ),
                  ]),
                  if (_preview!.canRestore) ...[
                    const SizedBox(height: 8),
                    ElevatedButton(
                      onPressed: _busy ? null : _confirmRestore,
                      style: ElevatedButton.styleFrom(
                        backgroundColor: AppColors.buttonBrown,
                        foregroundColor: AppColors.white,
                      ),
                      child: const Text('استعادة نسخة احتياطية'),
                    ),
                  ],
                ],
              ],
            ),
    );
  }

  Widget _card(List<Widget> children) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.cardWhite,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.goldBorder),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: children,
      ),
    );
  }
}

class BackupUserSelectPanel extends StatefulWidget {
  final List<Map<String, dynamic>> users;
  final int? selectedUserId;
  final String searchQuery;
  final bool enabled;
  final String Function(Map<String, dynamic>) userLabel;
  final ValueChanged<String> onSearchChanged;
  final ValueChanged<int?> onSelected;

  const BackupUserSelectPanel({
    super.key,
    required this.users,
    required this.selectedUserId,
    required this.searchQuery,
    required this.enabled,
    required this.userLabel,
    required this.onSearchChanged,
    required this.onSelected,
  });

  @override
  State<BackupUserSelectPanel> createState() => _BackupUserSelectPanelState();
}

class _BackupUserSelectPanelState extends State<BackupUserSelectPanel> {
  late final TextEditingController _searchController;

  @override
  void initState() {
    super.initState();
    _searchController = TextEditingController(text: widget.searchQuery);
  }

  @override
  void didUpdateWidget(BackupUserSelectPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.searchQuery != _searchController.text) {
      _searchController.value = TextEditingValue(
        text: widget.searchQuery,
        selection: TextSelection.collapsed(offset: widget.searchQuery.length),
      );
    }
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final filtered = filterUsersByDisplayName(widget.users, widget.searchQuery);
    final selectedVisible =
        filtered.any((u) => u['user_id'] == widget.selectedUserId);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        TextField(
          key: const Key('backup_user_search'),
          controller: _searchController,
          enabled: widget.enabled,
          onChanged: widget.onSearchChanged,
          decoration: const InputDecoration(
            hintText: kUserNameSearchHint,
            labelText: kUserNameSearchHint,
            border: OutlineInputBorder(),
          ),
        ),
        const SizedBox(height: 8),
        DropdownButtonFormField<int>(
          key: const Key('backup_user_dropdown'),
          value: selectedVisible ? widget.selectedUserId : null,
          items: [
            for (final u in filtered)
              DropdownMenuItem(
                value: u['user_id'] as int,
                child: Text(widget.userLabel(u)),
              ),
          ],
          onChanged: widget.enabled ? widget.onSelected : null,
          decoration: const InputDecoration(
            border: OutlineInputBorder(),
          ),
        ),
        if (filtered.isEmpty) ...[
          const SizedBox(height: 8),
          Text(
            kNoMatchingUserMessage,
            style: AppTextStyles.small.copyWith(color: AppColors.notDoneRed),
          ),
        ],
      ],
    );
  }
}
