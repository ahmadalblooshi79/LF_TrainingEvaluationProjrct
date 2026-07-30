import 'list_row.dart';

class DayTab {
  final String id;
  final String label;

  const DayTab({required this.id, required this.label});

  factory DayTab.fromJson(Map<String, dynamic> json) {
    return DayTab(
      id: (json['id'] ?? '').toString(),
      label: (json['label'] ?? json['id'] ?? '').toString(),
    );
  }
}

class ActionEvalListsData {
  final String dayId;
  final List<DayTab> dayTabs;
  final String unitKey;
  final List<ListRow> lists;

  const ActionEvalListsData({
    required this.dayId,
    required this.dayTabs,
    required this.unitKey,
    required this.lists,
  });

  factory ActionEvalListsData.fromJson(Map<String, dynamic> json) {
    return ActionEvalListsData(
      dayId: (json['day_id'] ?? '').toString(),
      dayTabs: ((json['day_tabs'] as List?) ?? [])
          .whereType<Map>()
          .map((e) => DayTab.fromJson(e.cast<String, dynamic>()))
          .toList(),
      unitKey: (json['unit_key'] ?? '').toString(),
      lists: ((json['lists'] as List?) ?? [])
          .whereType<Map>()
          .map((e) => ListRow.fromJson(e.cast<String, dynamic>()))
          .toList(),
    );
  }
}
