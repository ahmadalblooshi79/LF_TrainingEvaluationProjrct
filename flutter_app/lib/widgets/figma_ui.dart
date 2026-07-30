import 'package:flutter/material.dart';

import '../theme/app_theme.dart';

/// Shared Figma UI pieces: day/phase chips, open button, status pills, white panel.
class FigmaPanel extends StatelessWidget {
  const FigmaPanel({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(0),
    this.margin = EdgeInsets.zero,
  });

  final Widget child;
  final EdgeInsets padding;
  final EdgeInsets margin;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: margin,
      padding: padding,
      decoration: BoxDecoration(
        color: AppColors.cardWhite,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.divider),
        boxShadow: const [
          BoxShadow(color: AppColors.cardShadow, blurRadius: 8, offset: Offset(0, 3)),
        ],
      ),
      clipBehavior: Clip.antiAlias,
      child: child,
    );
  }
}

class FigmaDayChips extends StatelessWidget {
  const FigmaDayChips({
    super.key,
    required this.labels,
    required this.activeId,
    required this.onSelect,
  });

  final List<({String id, String label})> labels;
  final String activeId;
  final ValueChanged<String> onSelect;

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.centerRight,
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.fromLTRB(12, 10, 12, 6),
        child: Row(
          children: labels.map((d) {
            final selected = d.id == activeId;
            return Padding(
              padding: const EdgeInsets.symmetric(horizontal: 4),
              child: Material(
                color: selected ? AppColors.goldDark : AppColors.headerCream,
                borderRadius: BorderRadius.circular(8),
                child: InkWell(
                  borderRadius: BorderRadius.circular(8),
                  onTap: () => onSelect(d.id),
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(
                        color: selected ? AppColors.goldDark : AppColors.divider,
                      ),
                    ),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        if (selected) ...[
                          const Icon(Icons.check, size: 14, color: AppColors.white),
                          const SizedBox(width: 4),
                        ],
                        Text(
                          d.label,
                          style: AppTextStyles.cairo(
                            fontSize: 13,
                            fontWeight: FontWeight.w700,
                            color: selected ? AppColors.white : AppColors.darkText,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            );
          }).toList(),
        ),
      ),
    );
  }
}

class FigmaOpenButton extends StatelessWidget {
  const FigmaOpenButton({super.key, required this.onPressed});

  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: AppColors.openBtn,
      borderRadius: BorderRadius.circular(6),
      child: InkWell(
        borderRadius: BorderRadius.circular(6),
        onTap: onPressed,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(6),
            border: Border.all(color: AppColors.divider),
          ),
          child: Text(
            'فتح',
            style: AppTextStyles.cairo(
              fontSize: 13,
              fontWeight: FontWeight.w700,
              color: AppColors.olive,
            ),
          ),
        ),
      ),
    );
  }
}

class FigmaStatusPill extends StatelessWidget {
  const FigmaStatusPill({
    super.key,
    required this.done,
    this.label,
    this.outlineOnly = false,
  });

  final bool done;
  final String? label;
  final bool outlineOnly;

  @override
  Widget build(BuildContext context) {
    final color = done ? AppColors.doneGreen : AppColors.notDoneRed;
    final bg = outlineOnly
        ? AppColors.white
        : (done ? AppColors.doneGreenBg : AppColors.notDoneRedBg);
    final text = (label != null && label!.isNotEmpty)
        ? label!
        : (done ? 'منجز' : 'غير منجز');
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: color, width: 1.2),
      ),
      child: Text(
        text,
        style: AppTextStyles.cairo(fontSize: 12, fontWeight: FontWeight.w700, color: color),
      ),
    );
  }
}

class FigmaTableHeader extends StatelessWidget {
  const FigmaTableHeader({super.key, required this.cells});

  final List<({String label, int flex})> cells;

  @override
  Widget build(BuildContext context) {
    return Container(
      color: AppColors.tableHeader,
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 11),
      child: Row(
        children: cells
            .map(
              (c) => Expanded(
                flex: c.flex,
                child: Text(
                  c.label,
                  textAlign: TextAlign.center,
                  style: AppTextStyles.cairo(
                    fontSize: 13,
                    fontWeight: FontWeight.w700,
                    color: AppColors.white,
                  ),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            )
            .toList(),
      ),
    );
  }
}
