import 'list_row.dart';

class UnitLevelOption {
  final String key;
  final String label;

  const UnitLevelOption({required this.key, required this.label});

  factory UnitLevelOption.fromJson(Map<String, dynamic> json) {
    return UnitLevelOption(
      key: (json['key'] ?? '').toString(),
      label: (json['label'] ?? json['key'] ?? '').toString(),
    );
  }
}

class PhaseTab {
  final String key;
  final String label;

  const PhaseTab({required this.key, required this.label});

  factory PhaseTab.fromJson(Map<String, dynamic> json) {
    return PhaseTab(
      key: (json['key'] ?? '').toString(),
      label: (json['label'] ?? json['key'] ?? '').toString(),
    );
  }
}

class EvaluationListsData {
  final String unitKey;
  final List<UnitLevelOption> unitLevels;
  final String phaseKey;
  final List<PhaseTab> phaseTabs;
  final List<ListRow> lists;

  const EvaluationListsData({
    required this.unitKey,
    required this.unitLevels,
    required this.phaseKey,
    required this.phaseTabs,
    required this.lists,
  });

  factory EvaluationListsData.fromJson(Map<String, dynamic> json) {
    return EvaluationListsData(
      unitKey: (json['unit_key'] ?? '').toString(),
      unitLevels: ((json['unit_levels'] as List?) ?? [])
          .whereType<Map>()
          .map((e) => UnitLevelOption.fromJson(e.cast<String, dynamic>()))
          .toList(),
      phaseKey: (json['phase_key'] ?? '').toString(),
      phaseTabs: ((json['phase_tabs'] as List?) ?? [])
          .whereType<Map>()
          .map((e) => PhaseTab.fromJson(e.cast<String, dynamic>()))
          .toList(),
      lists: ((json['lists'] as List?) ?? (json['rows'] as List?) ?? [])
          .whereType<Map>()
          .map((e) => ListRow.fromJson(e.cast<String, dynamic>()))
          .toList(),
    );
  }
}
