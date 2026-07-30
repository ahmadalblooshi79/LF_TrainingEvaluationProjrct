import 'list_row.dart';
import 'menu_item.dart';
import 'stats.dart';
import 'user.dart';

class HomeData {
  final SessionBundle bundle;
  final StatsModel stats;
  final List<ListRow> incompleteTasks;
  final List<MenuItem> menu;

  const HomeData({
    required this.bundle,
    required this.stats,
    required this.incompleteTasks,
    required this.menu,
  });

  factory HomeData.fromJson(Map<String, dynamic> json) {
    return HomeData(
      bundle: SessionBundle.fromJson(json),
      stats: StatsModel.fromJson((json['stats'] as Map?)?.cast<String, dynamic>()),
      incompleteTasks: ((json['incomplete_tasks'] as List?) ?? [])
          .whereType<Map>()
          .map((e) => ListRow.fromJson(e.cast<String, dynamic>()))
          .toList(),
      menu: ((json['menu'] as List?) ?? [])
          .whereType<Map>()
          .map((e) => MenuItem.fromJson(e.cast<String, dynamic>()))
          .toList(),
    );
  }

  Map<String, dynamic> toCacheJson(Map<String, dynamic> raw) => raw;
}
