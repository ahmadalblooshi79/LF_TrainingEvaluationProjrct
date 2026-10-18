import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../services/api_client.dart';
import '../services/device_eval_manager_models.dart';
import '../services/device_eval_manager_service.dart';
import '../services/scoped_backup_models.dart';
import '../theme/app_theme.dart';
import '../widgets/app_header.dart';
import 'device_eval_inspect_screen.dart';

class DeviceEvalManagerScreen extends StatefulWidget {
  const DeviceEvalManagerScreen({super.key});

  @override
  State<DeviceEvalManagerScreen> createState() => _DeviceEvalManagerScreenState();
}

class _DeviceEvalManagerScreenState extends State<DeviceEvalManagerScreen> {
  bool _loading = true;
  bool _busy = false;
  String? _error;
  ScopedBackupExercise? _exercise;
  List<Map<String, dynamic>> _users = [];
  String _userSearch = '';
  int? _selectedUserId;
  DeviceEvalKind _kind = DeviceEvalKind.procedure;
  DeviceEvalListsLoad _lists = const DeviceEvalListsLoad(
    dataAvailable: false,
    lists: [],
  );
  DeviceEvalListSummary? _selectedList;

  @override
  void initState() {
    super.initState();
    _reload();
  }

  DeviceEvalUser? get _selectedUser {
    if (_selectedUserId == null) return null;
    for (final row in _users) {
      if (row['user_id'] == _selectedUserId) {
        return DeviceEvalUser.fromLocalRow(row);
      }
    }
    return null;
  }

  Future<void> _reload() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final exercise =
          await DeviceEvalManagerService.instance.currentExercise();
      final users = await DeviceEvalManagerService.instance.provisionedUsers();
      if (!mounted) return;
      setState(() {
        _exercise = exercise;
        _users = users;
        _selectedUserId ??= users.isNotEmpty
            ? users.first['user_id'] as int?
            : null;
      });
      await _loadLists();
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = 'تعذر تحميل بيانات مدير الجهاز');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _loadLists() async {
    final userId = _selectedUserId;
    final exercise = _exercise;
    if (userId == null || exercise == null) {
      setState(() {
        _lists = const DeviceEvalListsLoad(dataAvailable: false, lists: []);
        _selectedList = null;
      });
      return;
    }
    setState(() => _busy = true);
    final loaded = await DeviceEvalManagerService.instance.loadListsForUser(
      userId: userId,
      kind: _kind,
      exerciseId: exercise.exerciseId,
    );
    if (!mounted) return;
    setState(() {
      _lists = loaded;
      _selectedList = loaded.lists.isEmpty
          ? null
          : loaded.lists.firstWhere(
              (e) => e.listId == _selectedList?.listId,
              orElse: () => loaded.lists.first,
            );
      _busy = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    final filtered = filterDeviceManagerUsers(_users, _userSearch);
    final selectedVisible =
        filtered.any((u) => u['user_id'] == _selectedUserId);
    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppHeader(
        pageTitle: kDeviceEvalManagerTitle,
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
                      style: AppTextStyles.body.copyWith(
                        color: AppColors.notDoneRed,
                      ),
                    ),
                  ),
                _card([
                  Text('التمرين الحالي', style: AppTextStyles.subtitle),
                  const SizedBox(height: 8),
                  Text(
                    _exercise == null
                        ? 'لا يوجد تمرين حالي'
                        : (_exercise!.name.trim().isNotEmpty
                            ? _exercise!.name
                            : 'تمرين ${_exercise!.exerciseId}'),
                    style: AppTextStyles.body.copyWith(
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ]),
                const SizedBox(height: 12),
                _card([
                  Text(kDeviceEvalUserLabel, style: AppTextStyles.subtitle),
                  const SizedBox(height: 8),
                  TextField(
                    key: const Key('device_eval_user_search'),
                    enabled: !_busy,
                    onChanged: (q) => setState(() => _userSearch = q),
                    decoration: const InputDecoration(
                      hintText: kDeviceEvalUserSearchHint,
                      labelText: kDeviceEvalUserSearchHint,
                      border: OutlineInputBorder(),
                    ),
                  ),
                  const SizedBox(height: 8),
                  DropdownButtonFormField<int>(
                    key: const Key('device_eval_user_dropdown'),
                    value: selectedVisible ? _selectedUserId : null,
                    items: [
                      for (final u in filtered)
                        DropdownMenuItem(
                          value: u['user_id'] as int,
                          child: Text(DeviceEvalUser.fromLocalRow(u).label),
                        ),
                    ],
                    onChanged: _busy
                        ? null
                        : (v) async {
                            setState(() {
                              _selectedUserId = v;
                              _selectedList = null;
                            });
                            await _loadLists();
                          },
                    decoration: const InputDecoration(
                      labelText: 'قائمة المستخدمين',
                      border: OutlineInputBorder(),
                    ),
                  ),
                  if (filtered.isEmpty) ...[
                    const SizedBox(height: 8),
                    Text(
                      'لا يوجد مستخدم مطابق',
                      style: AppTextStyles.small.copyWith(
                        color: AppColors.notDoneRed,
                      ),
                    ),
                  ],
                ]),
                const SizedBox(height: 12),
                SegmentedButton<DeviceEvalKind>(
                  segments: const [
                    ButtonSegment(
                      value: DeviceEvalKind.procedure,
                      label: Text(kDeviceEvalProcedureTab),
                    ),
                    ButtonSegment(
                      value: DeviceEvalKind.dilemma,
                      label: Text(kDeviceEvalDilemmaTab),
                    ),
                  ],
                  selected: {_kind},
                  onSelectionChanged: (s) async {
                    setState(() {
                      _kind = s.first;
                      _selectedList = null;
                    });
                    await _loadLists();
                  },
                ),
                const SizedBox(height: 12),
                Align(
                  alignment: Alignment.centerLeft,
                  child: OutlinedButton.icon(
                    onPressed: _busy ? null : _reload,
                    icon: const Icon(Icons.refresh),
                    label: const Text('تحديث'),
                  ),
                ),
                const SizedBox(height: 12),
                if (_busy)
                  const Padding(
                    padding: EdgeInsets.symmetric(vertical: 24),
                    child: Center(
                      child: CircularProgressIndicator(color: AppColors.gold),
                    ),
                  )
                else if (!_lists.dataAvailable || _lists.lists.isEmpty)
                  _card([
                    Text(
                      _lists.emptyMessage,
                      style: AppTextStyles.body.copyWith(
                        color: AppColors.muted,
                      ),
                    ),
                  ])
                else
                  ...[
                    for (final row in _lists.lists)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 8),
                        child: _listCard(row),
                      ),
                  ],
                if (_selectedList != null) ...[
                  const SizedBox(height: 8),
                  _actionsCard(_selectedList!),
                ],
              ],
            ),
    );
  }

  Widget _listCard(DeviceEvalListSummary row) {
    final selected = _selectedList?.listId == row.listId &&
        _selectedList?.kind == row.kind;
    return InkWell(
      onTap: () => setState(() => _selectedList = row),
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: AppColors.cardWhite,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
            color: selected ? AppColors.gold : AppColors.divider,
            width: selected ? 2 : 1,
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(row.title, style: AppTextStyles.subtitle),
            const SizedBox(height: 4),
            Text(
              [
                if (row.unitLabel.trim().isNotEmpty) row.unitLabel,
                if (row.phaseKey.trim().isNotEmpty) row.phaseKey,
                if (row.statusLabel.trim().isNotEmpty) row.statusLabel,
              ].join(' • '),
              style: AppTextStyles.small,
            ),
            if (row.lastUpdated != null)
              Text('آخر تحديث: ${row.lastUpdated}', style: AppTextStyles.small),
            Text(
              'الصور: ${row.imageCount}  الفيديوهات: ${row.videoCount}',
              style: AppTextStyles.small.copyWith(color: AppColors.muted),
            ),
          ],
        ),
      ),
    );
  }

  Widget _actionsCard(DeviceEvalListSummary row) {
    return _card([
      Text('إجراءات القائمة', style: AppTextStyles.subtitle),
      const SizedBox(height: 8),
      Wrap(
        spacing: 8,
        runSpacing: 8,
        children: [
          ElevatedButton(
            onPressed: () {
              final user = _selectedUser;
              if (user == null) return;
              context.push(
                '/device-eval-inspect',
                extra: DeviceEvalInspectArgs(
                  user: user,
                  summary: row,
                  exerciseName: _exercise?.name ?? '',
                ),
              );
            },
            child: const Text('فتح القائمة'),
          ),
          OutlinedButton(
            onPressed: () => _runDownload((online) {
              return DeviceEvalManagerService.instance.downloadExcel(
                user: _selectedUser!,
                summary: row,
                exerciseName: _exercise?.name ?? '',
                online: online,
              );
            }),
            child: const Text('تنزيل Excel'),
          ),
          OutlinedButton(
            onPressed: () => _runDownload((_) {
              return DeviceEvalManagerService.instance.downloadAttachments(
                user: _selectedUser!,
                summary: row,
                exerciseName: _exercise?.name ?? '',
              );
            }),
            child: const Text('تنزيل المرفقات'),
          ),
          OutlinedButton(
            onPressed: () => _runDownload((online) {
              return DeviceEvalManagerService.instance
                  .downloadListWithAttachments(
                user: _selectedUser!,
                summary: row,
                exerciseName: _exercise?.name ?? '',
                online: online,
              );
            }),
            child: const Text('تنزيل القائمة مع المرفقات'),
          ),
        ],
      ),
    ]);
  }

  Future<void> _runDownload(
    Future<DeviceEvalDownloadResult> Function(bool online) action,
  ) async {
    if (_selectedUser == null) return;
    final result = await action(ApiClient.instance.online.value);
    if (!mounted) return;
    final path = result.displayPath;
    final text = [
      result.message,
      if (path != null && path.isNotEmpty) 'مكان الحفظ:\n$path',
      ...result.warnings,
    ].join('\n');
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));
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
