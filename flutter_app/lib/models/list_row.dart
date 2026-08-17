/// Generic row used for incomplete tasks, action-eval lists and evaluation lists
/// (mirrors `_safe_row` on the backend).
class ListRow {
  final dynamic id;
  final int? slotIndex;
  final int? slotId;
  final int? itemId;
  final String title;
  final String date;
  final dynamic seq;
  final String gradeLabel;
  final String deliveryDt;
  final bool statusDone;
  final String statusLabel;
  final String unitKey;
  final String unitLabel;
  final String phaseKey;
  final String listType;
  final String listTypeLabel;
  final String openHref;
  final String workflowLabel;
  final String dispatchLabel;
  final String rowTone;
  final dynamic dilemmaNo;
  final dynamic nodeId;

  const ListRow({
    required this.id,
    this.slotIndex,
    this.slotId,
    this.itemId,
    required this.title,
    required this.date,
    this.seq,
    required this.gradeLabel,
    required this.deliveryDt,
    required this.statusDone,
    required this.statusLabel,
    required this.unitKey,
    required this.unitLabel,
    required this.phaseKey,
    required this.listType,
    this.listTypeLabel = '',
    required this.openHref,
    required this.workflowLabel,
    this.dispatchLabel = '',
    this.rowTone = '',
    this.dilemmaNo,
    this.nodeId,
  });

  /// تسمية عمود إرسال للاعتماد (معاد للتعديل / مرسل / …).
  String get displayDispatch {
    final d = dispatchLabel.trim();
    if (d.isNotEmpty) return d;
    return workflowLabel.trim();
  }

  /// تسمية عربية لعمود نوع القائمة.
  String get displayListType {
    final labeled = listTypeLabel.trim();
    if (labeled.isNotEmpty) {
      if (labeled.contains('إجراءات') || labeled.contains('المجرى')) {
        return 'قائمة المعاضل';
      }
      if (labeled.contains('التقييم')) return 'قائمة التقييم';
      return labeled;
    }
    final t = listType.toLowerCase();
    if (t.contains('planner') || t.contains('action')) return 'قائمة المعاضل';
    if (t.contains('judge') || t.contains('eval')) return 'قائمة التقييم';
    return '—';
  }

  factory ListRow.fromJson(Map<String, dynamic> json) {
    int? asInt(dynamic v) {
      if (v == null) return null;
      if (v is num) return v.toInt();
      return int.tryParse(v.toString().trim());
    }
    final dispatch = (json['dispatch_label'] ?? json['workflow_label'] ?? '')
        .toString();
    return ListRow(
      id: json['id'],
      slotIndex: asInt(json['slot_index']),
      slotId: asInt(json['slot_id']),
      itemId: asInt(json['item_id']),
      title: (json['title'] ?? '').toString(),
      date: (json['date'] ?? '').toString(),
      seq: json['seq'],
      gradeLabel: (json['grade_label'] ?? '').toString(),
      deliveryDt: (json['delivery_dt'] ?? '').toString(),
      statusDone: json['status_done'] == true,
      statusLabel: (json['status_label'] ?? '').toString(),
      unitKey: (json['unit_key'] ?? '').toString(),
      unitLabel: (json['unit_label'] ?? '').toString(),
      phaseKey: (json['phase_key'] ?? '').toString(),
      listType: (json['list_type'] ?? '').toString(),
      listTypeLabel: (json['list_type_label'] ?? '').toString(),
      openHref: (json['open_href'] ?? '').toString(),
      workflowLabel: (json['workflow_label'] ?? dispatch).toString(),
      dispatchLabel: dispatch,
      rowTone: (json['row_tone'] ?? '').toString(),
      dilemmaNo: json['dilemma_no'],
      nodeId: json['node_id'],
    );
  }
}
