import 'package:flutter/material.dart';

import '../theme/app_theme.dart';

/// Body layout used by every table-like screen (flow, action-eval lists,
/// evaluation lists, eval sheet): an optional fixed top bar (e.g. day
/// tabs), a fixed column-header row, a scrollable row area, and an
/// optional fixed footer (totals + save/approve). When [minTableWidth] is
/// given the header and rows scroll horizontally together so wide tables
/// stay readable on tablets in portrait mode.
class StickyEvalScaffold extends StatelessWidget {
  const StickyEvalScaffold({
    super.key,
    this.topBar,
    required this.columnHeader,
    required this.rows,
    this.footer,
    this.minTableWidth,
  });

  final Widget? topBar;
  final Widget columnHeader;
  final Widget rows;
  final Widget? footer;
  final double? minTableWidth;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        if (topBar != null) topBar!,
        Expanded(
          child: LayoutBuilder(
            builder: (context, constraints) {
              final table = Column(
                children: [columnHeader, Expanded(child: rows)],
              );
              final minWidth = minTableWidth;
              if (minWidth == null || minWidth <= constraints.maxWidth) {
                return table;
              }
              return SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: SizedBox(
                  width: minWidth,
                  height: constraints.maxHeight,
                  child: table,
                ),
              );
            },
          ),
        ),
        if (footer != null) footer!,
      ],
    );
  }
}

/// Styled fixed header row for a table (gold background, bold text cells).
class TableHeaderRow extends StatelessWidget {
  const TableHeaderRow({super.key, required this.cells});

  final List<TableHeaderCell> cells;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: const BoxDecoration(
        color: AppColors.tableHeader,
        boxShadow: [
          BoxShadow(color: AppColors.cardShadow, blurRadius: 3, offset: Offset(0, 1)),
        ],
      ),
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 10),
      child: Row(
        children: cells
            .map(
              (c) => Expanded(
                flex: c.flex,
                child: Text(
                  c.label,
                  style: AppTextStyles.cairo(
                    fontSize: 13,
                    fontWeight: FontWeight.w700,
                    color: AppColors.white,
                  ),
                  textAlign: TextAlign.center,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            )
            .toList(),
      ),
    );
  }
}

class TableHeaderCell {
  final String label;
  final int flex;
  const TableHeaderCell(this.label, {this.flex = 1});
}

/// Fixed footer bar (totals text on one side, action buttons on the other).
class StickyFooterBar extends StatelessWidget {
  const StickyFooterBar({super.key, this.left, this.right});

  final Widget? left;
  final Widget? right;

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      top: false,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
        decoration: const BoxDecoration(
          color: AppColors.headerCream,
          border: Border(top: BorderSide(color: AppColors.divider, width: 1)),
        ),
        child: Wrap(
          alignment: WrapAlignment.spaceBetween,
          crossAxisAlignment: WrapCrossAlignment.center,
          runSpacing: 8,
          spacing: 12,
          children: [
            if (left != null) left!,
            if (right != null) right!,
          ],
        ),
      ),
    );
  }
}

/// Done / not-done pill — delegates to Figma status pill.
class StatusBadge extends StatelessWidget {
  const StatusBadge({super.key, required this.done, this.label});

  final bool done;
  final String? label;

  @override
  Widget build(BuildContext context) {
    final color = done ? AppColors.doneGreen : AppColors.notDoneRed;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: color),
      ),
      child: Text(
        label ?? (done ? 'منجز' : 'غير منجز'),
        style: AppTextStyles.cairo(fontSize: 12, fontWeight: FontWeight.w700, color: color),
      ),
    );
  }
}
