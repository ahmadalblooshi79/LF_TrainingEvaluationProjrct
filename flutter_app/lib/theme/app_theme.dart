import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

/// Figma tokens — Soft Judging tablet PWA.
class AppColors {
  AppColors._();

  static const Color background = Color(0xFFF4F1E6);
  static const Color headerBar = Color(0xFFEDE6D6);
  static const Color headerCream = Color(0xFFF7F2E6);
  static const Color cardWhite = Color(0xFFFFFFFF);
  static const Color panelBeige = Color(0xFFE8DFC8);

  static const Color gold = Color(0xFFBD9E62);
  static const Color goldDark = Color(0xFFA8842E);
  static const Color goldLight = Color(0xFFD4B56A);
  static const Color goldBorder = Color(0xFFC9A24A);

  static const Color olive = Color(0xFF0B2421);
  static const Color oliveMid = Color(0xFF1F2A24);
  static const Color oliveDark = Color(0xFF11241C);

  static const Color darkText = Color(0xFF2A2A28);
  static const Color muted = Color(0xFF6B6B66);

  static const Color loginCard = Color(0xFF4F545B);
  static const Color loginBg = Color(0xFFC8C1A9);

  static const Color eventRow = Color(0xFFFFF3A8);
  static const Color dilemmaRow = Color(0xFFF8D7DA);

  static const Color doneGreen = Color(0xFF2E8B3A);
  static const Color doneGreenBg = Color(0xFFE8F5E9);
  static const Color notDoneRed = Color(0xFFC62828);
  static const Color notDoneRedBg = Color(0xFFFDECEC);

  static const Color resultBlue = Color(0xFF3B6EA5);
  static const Color resultBlueBg = Color(0xFFE3F0FB);

  static const Color tableHeader = Color(0xFF5C5346);
  static const Color titleBar = Color(0xFFC4B48A);

  static const Color buttonBrown = Color(0xFF8D7763);
  static const Color buttonBrownDark = Color(0xFF3D3D33);

  static const Color cardShadow = Color(0x22000000);
  static const Color white = Color(0xFFFFFFFF);
  static const Color divider = Color(0xFFD9D2B8);
  static const Color openBtn = Color(0xFFECE7DC);
}

class AppTextStyles {
  AppTextStyles._();

  static TextStyle cairo({
    double fontSize = 16,
    FontWeight fontWeight = FontWeight.w400,
    Color color = AppColors.darkText,
    double? height,
  }) {
    return GoogleFonts.cairo(
      fontSize: fontSize,
      fontWeight: fontWeight,
      color: color,
      height: height,
    );
  }

  static TextStyle title = cairo(fontSize: 22, fontWeight: FontWeight.w700);
  static TextStyle subtitle = cairo(fontSize: 16, fontWeight: FontWeight.w600);
  static TextStyle body = cairo(fontSize: 14, fontWeight: FontWeight.w400);
  static TextStyle small = cairo(fontSize: 12, fontWeight: FontWeight.w400);
  static TextStyle button = cairo(fontSize: 16, fontWeight: FontWeight.w700, color: AppColors.white);
}

class AppTheme {
  AppTheme._();

  static ThemeData light({bool compact = false}) {
    final base = ThemeData(
      useMaterial3: true,
      visualDensity:
          compact ? VisualDensity.compact : VisualDensity.standard,
      colorScheme: ColorScheme.fromSeed(
        seedColor: AppColors.gold,
        primary: AppColors.gold,
        secondary: AppColors.goldLight,
        surface: AppColors.background,
      ),
      scaffoldBackgroundColor: AppColors.background,
      textTheme: GoogleFonts.cairoTextTheme(),
      fontFamily: GoogleFonts.cairo().fontFamily,
    );
    return base.copyWith(
      appBarTheme: base.appBarTheme.copyWith(
        backgroundColor: AppColors.headerBar,
        foregroundColor: AppColors.darkText,
        elevation: 0,
        toolbarHeight: compact ? 48 : null,
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: AppColors.gold,
          foregroundColor: AppColors.darkText,
          textStyle: AppTextStyles.cairo(
            fontSize: compact ? 14 : 16,
            fontWeight: FontWeight.w700,
          ),
          padding: EdgeInsets.symmetric(
            horizontal: compact ? 14 : 22,
            vertical: compact ? 10 : 14,
          ),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
        ),
      ),
      listTileTheme: ListTileThemeData(
        dense: compact,
        visualDensity:
            compact ? VisualDensity.compact : VisualDensity.standard,
        contentPadding: EdgeInsets.symmetric(
          horizontal: compact ? 10 : 16,
          vertical: compact ? 2 : 4,
        ),
      ),
      cardTheme: CardThemeData(
        margin: EdgeInsets.symmetric(
          horizontal: compact ? 4 : 8,
          vertical: compact ? 4 : 6,
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: AppColors.white,
        isDense: compact,
        contentPadding: EdgeInsets.symmetric(
          horizontal: compact ? 10 : 14,
          vertical: compact ? 10 : 12,
        ),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: BorderSide.none,
        ),
      ),
      dividerTheme: const DividerThemeData(color: AppColors.divider, thickness: 1),
    );
  }
}
