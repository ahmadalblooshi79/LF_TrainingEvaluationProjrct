class MenuItem {
  final String id;
  final String title;
  final String route;

  const MenuItem({required this.id, required this.title, required this.route});

  factory MenuItem.fromJson(Map<String, dynamic> json) {
    return MenuItem(
      id: (json['id'] ?? '').toString(),
      title: (json['title'] ?? '').toString(),
      route: (json['route'] ?? '').toString(),
    );
  }

  Map<String, dynamic> toJson() => {'id': id, 'title': title, 'route': route};
}
