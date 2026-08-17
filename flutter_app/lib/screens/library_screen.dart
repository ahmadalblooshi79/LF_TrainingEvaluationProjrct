import 'package:flutter/material.dart';

import '../services/api_client.dart';
import '../theme/app_theme.dart';
import '../widgets/app_header.dart';
import '../widgets/figma_ui.dart';
import 'library_pdf_screen.dart';

/// المكتبة — مطابقة لصفحة النظام (تبويبات + شجرة) — قراءة فقط.
class LibraryScreen extends StatefulWidget {
  const LibraryScreen({super.key});

  @override
  State<LibraryScreen> createState() => _LibraryScreenState();
}

class _LibraryScreenState extends State<LibraryScreen> {
  bool _loading = true;
  String? _error;
  List<_LibTab> _tabs = const [];
  Map<String, List<_LibNode>> _trees = {};
  String _activeKind = '';

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
      final data = await ApiClient.instance.get('/api/tablet/library');
      final tabsRaw = (data['tabs'] as List?) ?? const [];
      final treesRaw = (data['trees'] as Map?) ?? const {};
      final tabs = tabsRaw
          .whereType<Map>()
          .map((m) => _LibTab.fromJson(Map<String, dynamic>.from(m)))
          .toList();
      final trees = <String, List<_LibNode>>{};
      treesRaw.forEach((k, v) {
        final list = (v as List?) ?? const [];
        trees[k.toString()] = list
            .whereType<Map>()
            .map((m) => _LibNode.fromJson(Map<String, dynamic>.from(m)))
            .toList();
      });
      if (!mounted) return;
      setState(() {
        _tabs = tabs;
        _trees = trees;
        _activeKind = tabs.isNotEmpty ? tabs.first.kind : '';
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

  @override
  Widget build(BuildContext context) {
    final activeTab = _tabs.cast<_LibTab?>().firstWhere(
          (t) => t?.kind == _activeKind,
          orElse: () => _tabs.isEmpty ? null : _tabs.first,
        );
    final nodes = _trees[_activeKind] ?? const <_LibNode>[];

    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppHeader(
        pageTitle: 'المكتبة',
        onBack: () => Navigator.of(context).maybePop(),
        showOnlineChip: false,
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator(color: AppColors.goldDark))
          : _error != null
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(_error!, style: AppTextStyles.body, textAlign: TextAlign.center),
                        const SizedBox(height: 12),
                        TextButton(onPressed: _load, child: const Text('إعادة المحاولة')),
                      ],
                    ),
                  ),
                )
              : Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Padding(
                      padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
                      child: Row(
                        children: [
                          const Icon(Icons.menu_book_outlined, color: AppColors.goldDark),
                          const SizedBox(width: 8),
                          Text(
                            'المكتبة',
                            style: AppTextStyles.cairo(
                              fontSize: 18,
                              fontWeight: FontWeight.w800,
                            ),
                          ),
                          const Spacer(),
                          Text(
                            'عرض وتنزيل فقط',
                            style: AppTextStyles.cairo(fontSize: 12, color: AppColors.muted),
                          ),
                        ],
                      ),
                    ),
                    const Divider(height: 16),
                    SingleChildScrollView(
                      scrollDirection: Axis.horizontal,
                      padding: const EdgeInsets.symmetric(horizontal: 12),
                      reverse: true,
                      child: Row(
                        children: _tabs.map((t) {
                          final selected = t.kind == _activeKind;
                          return Padding(
                            padding: const EdgeInsets.symmetric(horizontal: 4),
                            child: Material(
                              color: selected ? AppColors.cardWhite : AppColors.headerCream,
                              borderRadius: const BorderRadius.vertical(top: Radius.circular(8)),
                              child: InkWell(
                                onTap: () => setState(() => _activeKind = t.kind),
                                child: Container(
                                  padding: const EdgeInsets.symmetric(
                                    horizontal: 14,
                                    vertical: 10,
                                  ),
                                  decoration: BoxDecoration(
                                    border: Border(
                                      bottom: BorderSide(
                                        color: selected
                                            ? AppColors.goldDark
                                            : Colors.transparent,
                                        width: 2,
                                      ),
                                    ),
                                  ),
                                  child: Text(
                                    t.title,
                                    style: AppTextStyles.cairo(
                                      fontWeight: selected
                                          ? FontWeight.w800
                                          : FontWeight.w600,
                                      color: AppColors.olive,
                                    ),
                                  ),
                                ),
                              ),
                            ),
                          );
                        }).toList(),
                      ),
                    ),
                    Expanded(
                      child: Padding(
                        padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
                        child: FigmaPanel(
                          padding: const EdgeInsets.all(14),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.stretch,
                            children: [
                              Row(
                                children: [
                                  const Icon(Icons.folder_outlined, color: AppColors.goldDark),
                                  const SizedBox(width: 8),
                                  Text(
                                    activeTab?.title ?? 'المكتبة',
                                    style: AppTextStyles.cairo(
                                      fontSize: 15,
                                      fontWeight: FontWeight.w800,
                                    ),
                                  ),
                                ],
                              ),
                              const Divider(height: 16),
                              Expanded(
                                child: nodes.isEmpty
                                    ? Center(
                                        child: Text(
                                          'لا توجد عناصر في هذا التبويب بعد.',
                                          style: AppTextStyles.cairo(color: AppColors.muted),
                                        ),
                                      )
                                    : ListView(
                                        children: nodes
                                            .map((n) => _TreeTile(node: n, depth: 0))
                                            .toList(),
                                      ),
                              ),
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

class _LibTab {
  const _LibTab({required this.tabId, required this.kind, required this.title});
  final String tabId;
  final String kind;
  final String title;

  factory _LibTab.fromJson(Map<String, dynamic> j) => _LibTab(
        tabId: (j['tab_id'] ?? '').toString(),
        kind: (j['kind'] ?? '').toString(),
        title: (j['title'] ?? '').toString(),
      );
}

class _LibNode {
  const _LibNode({
    required this.id,
    required this.name,
    required this.isFolder,
    required this.hasFile,
    required this.children,
  });
  final int id;
  final String name;
  final bool isFolder;
  final bool hasFile;
  final List<_LibNode> children;

  factory _LibNode.fromJson(Map<String, dynamic> j) {
    final kids = (j['children'] as List?) ?? const [];
    return _LibNode(
      id: (j['id'] as num?)?.toInt() ?? 0,
      name: (j['name'] ?? '').toString(),
      isFolder: j['is_folder'] == true,
      hasFile: j['file_url'] == true,
      children: kids
          .whereType<Map>()
          .map((m) => _LibNode.fromJson(Map<String, dynamic>.from(m)))
          .toList(),
    );
  }
}

class _TreeTile extends StatefulWidget {
  const _TreeTile({required this.node, required this.depth});
  final _LibNode node;
  final int depth;

  @override
  State<_TreeTile> createState() => _TreeTileState();
}

class _TreeTileState extends State<_TreeTile> {
  bool _open = false;

  @override
  Widget build(BuildContext context) {
    final n = widget.node;
    if (n.isFolder) {
      return Column(
        children: [
          ListTile(
            contentPadding: EdgeInsets.only(right: 8.0 + widget.depth * 14, left: 4),
            leading: Icon(
              _open ? Icons.folder_open : Icons.folder,
              color: AppColors.goldDark,
            ),
            title: Text(n.name, style: AppTextStyles.cairo(fontWeight: FontWeight.w700)),
            trailing: Icon(_open ? Icons.expand_less : Icons.expand_more),
            onTap: () => setState(() => _open = !_open),
          ),
          if (_open)
            ...n.children.map((c) => _TreeTile(node: c, depth: widget.depth + 1)),
        ],
      );
    }
    return ListTile(
      contentPadding: EdgeInsets.only(right: 8.0 + widget.depth * 14, left: 4),
      leading: const Icon(Icons.insert_drive_file_outlined, color: AppColors.olive),
      title: Text(n.name, style: AppTextStyles.cairo(fontWeight: FontWeight.w600)),
      subtitle: Text(
        'قراءة فقط',
        style: AppTextStyles.cairo(fontSize: 11, color: AppColors.muted),
      ),
      onTap: n.hasFile
          ? () {
              Navigator.of(context).push(
                MaterialPageRoute<void>(
                  builder: (_) => LibraryPdfScreen(
                    nodeId: n.id,
                    title: n.name,
                  ),
                ),
              );
            }
          : null,
    );
  }
}
