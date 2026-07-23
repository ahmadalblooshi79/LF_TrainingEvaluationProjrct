import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

/// MainPage — Figma node `1:2` ("Android Expanded - 1") on page MainPage.
/// Design canvas: 1280 × 800. Positions match Figma exactly.
class MainPage extends StatelessWidget {
  const MainPage({
    super.key,
    this.exerciseTypeLabel = 'تمرين لعبات الحرب',
    this.userGreeting = 'مرحبا. وكيل/1 أحمد عبدالله مبارك البلوشي',
    this.exerciseNameLabel = 'تمرين رياح الصحراء / 1',
    this.roleLabel = 'محكم قيادة مجموعة اللواء',
    this.onEvalListsPressed,
  });

  static const Size designSize = Size(1280, 800);

  static const Color backgroundColor = Color(0xFFEFE7CE);
  static const Color barColor = Color(0xFFD4BD97);

  final String exerciseTypeLabel;
  final String userGreeting;
  final String exerciseNameLabel;
  final String roleLabel;
  final VoidCallback? onEvalListsPressed;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: backgroundColor,
      body: SafeArea(
        child: LayoutBuilder(
          builder: (context, constraints) {
            final scaleW = constraints.maxWidth / designSize.width;
            final scaleH = constraints.maxHeight / designSize.height;
            final scale = scaleW < scaleH ? scaleW : scaleH;
            return ColoredBox(
              color: backgroundColor,
              child: Center(
                child: SizedBox(
                  width: designSize.width * scale,
                  height: designSize.height * scale,
                  child: FittedBox(
                    fit: BoxFit.contain,
                    child: SizedBox(
                      width: designSize.width,
                      height: designSize.height,
                      child: Stack(
                        children: [
                          const Positioned.fill(
                            child: ColoredBox(color: backgroundColor),
                          ),
                          // Rectangle 1
                          Positioned(
                            left: 27,
                            top: 21,
                            width: 1229,
                            height: 42,
                            child: DecoratedBox(
                              decoration: BoxDecoration(
                                color: barColor,
                                borderRadius: BorderRadius.circular(7),
                              ),
                            ),
                          ),
                          Positioned(
                            left: 40,
                            top: 21,
                            width: 292,
                            height: 42,
                            child: _CairoText(
                              text: exerciseTypeLabel,
                              fontSize: 20,
                              align: TextAlign.left,
                            ),
                          ),
                          Positioned(
                            left: 836,
                            top: 21,
                            width: 410,
                            height: 42,
                            child: _CairoText(
                              text: userGreeting,
                              fontSize: 20,
                              align: TextAlign.right,
                            ),
                          ),
                          // Rectangle 2
                          Positioned(
                            left: 27,
                            top: 67,
                            width: 1229,
                            height: 42,
                            child: DecoratedBox(
                              decoration: BoxDecoration(
                                color: barColor,
                                borderRadius: BorderRadius.circular(7),
                              ),
                            ),
                          ),
                          Positioned(
                            left: 40,
                            top: 67,
                            width: 292,
                            height: 42,
                            child: _CairoText(
                              text: exerciseNameLabel,
                              fontSize: 20,
                              align: TextAlign.left,
                            ),
                          ),
                          Positioned(
                            left: 836,
                            top: 67,
                            width: 410,
                            height: 42,
                            child: _CairoText(
                              text: roleLabel,
                              fontSize: 20,
                              align: TextAlign.right,
                            ),
                          ),
                          // uae-mod 1
                          const Positioned(
                            left: 518,
                            top: 176,
                            width: 245,
                            height: 288,
                            child: Image(
                              image: AssetImage('assets/images/uae_mod.png'),
                              fit: BoxFit.cover,
                            ),
                          ),
                          // Button_EvalList
                          Positioned(
                            left: 515,
                            top: 565,
                            width: 250,
                            height: 92,
                            child: GestureDetector(
                              onTap: onEvalListsPressed,
                              child: DecoratedBox(
                                decoration: BoxDecoration(
                                  color: barColor,
                                  borderRadius: BorderRadius.circular(5),
                                  boxShadow: const [
                                    BoxShadow(
                                      color: Color(0x40000000),
                                      offset: Offset(0, 4),
                                      blurRadius: 4,
                                    ),
                                  ],
                                ),
                                child: const Center(
                                  child: _CairoText(
                                    text: 'قوائم التقييم',
                                    fontSize: 32,
                                    align: TextAlign.center,
                                  ),
                                ),
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
            );
          },
        ),
      ),
    );
  }
}

class _CairoText extends StatelessWidget {
  const _CairoText({
    required this.text,
    required this.fontSize,
    required this.align,
  });

  final String text;
  final double fontSize;
  final TextAlign align;

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: switch (align) {
        TextAlign.left => Alignment.centerLeft,
        TextAlign.right => Alignment.centerRight,
        _ => Alignment.center,
      },
      child: Text(
        text,
        textAlign: align,
        textDirection: TextDirection.rtl,
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: GoogleFonts.cairo(
          fontSize: fontSize,
          fontWeight: FontWeight.w400,
          color: Colors.black,
          height: 1.0,
        ),
      ),
    );
  }
}
