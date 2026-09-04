class MenuItem {
  final String id;
  final String title;
  final String route;

  const MenuItem({required this.id, required this.title, required this.route});

  factory MenuItem.fromJson(Map<String, dynamic> json) {
    final id = (json['id'] ?? '').toString();
    var title = (json['title'] ?? '').toString();
    if (id == 'action_eval') {
      title = 'قوائم تقييم المعاضل';
    }
    return MenuItem(
      id: id,
      title: title,
      route: (json['route'] ?? '').toString(),
    );
  }

  Map<String, dynamic> toJson() => {'id': id, 'title': title, 'route': route};
}
