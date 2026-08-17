import 'package:flutter/material.dart';

import '../theme/device_layout.dart';

/// تكبير/تصغير بإصبعين (pinch) لبناء الهاتف فقط — بدون أزرار.
/// عند المقياس 1: التمرير العمودي يعمل كالمعتاد.
/// عند التكبير: يُفعَّل السحب لرؤية المحتوى خارج الإطار.
class PhoneZoomShell extends StatefulWidget {
  const PhoneZoomShell({super.key, required this.child});

  final Widget child;

  @override
  State<PhoneZoomShell> createState() => _PhoneZoomShellState();
}

class _PhoneZoomShellState extends State<PhoneZoomShell> {
  final TransformationController _controller = TransformationController();
  bool _zoomed = false;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _onInteractionUpdate(ScaleUpdateDetails _) {
    final scale = _controller.value.getMaxScaleOnAxis();
    final zoomed = scale > 1.02 || scale < 0.98;
    if (zoomed != _zoomed) {
      setState(() => _zoomed = zoomed);
    }
  }

  void _onInteractionEnd(ScaleEndDetails _) {
    final scale = _controller.value.getMaxScaleOnAxis();
    setState(() => _zoomed = scale > 1.02 || scale < 0.98);
  }

  @override
  Widget build(BuildContext context) {
    if (!DeviceLayout.isPhoneBuild) {
      return widget.child;
    }

    return InteractiveViewer(
      transformationController: _controller,
      minScale: DeviceLayout.phoneMinZoom,
      maxScale: DeviceLayout.phoneMaxZoom,
      // إصبع واحد = تمرير الصفحات؛ إصبعان = تكبير
      panEnabled: _zoomed,
      scaleEnabled: true,
      clipBehavior: Clip.hardEdge,
      boundaryMargin: const EdgeInsets.all(48),
      onInteractionUpdate: _onInteractionUpdate,
      onInteractionEnd: _onInteractionEnd,
      child: widget.child,
    );
  }
}
