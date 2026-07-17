import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:lf_training_evaluation/screens/main_page.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const LfTrainingEvaluationApp());
}

class LfTrainingEvaluationApp extends StatelessWidget {
  const LfTrainingEvaluationApp({super.key});

  @override
  Widget build(BuildContext context) {
    return const MaterialApp(
      debugShowCheckedModeBanner: false,
      locale: Locale('ar'),
      supportedLocales: [Locale('ar')],
      localizationsDelegates: [
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      home: MainPage(),
    );
  }
}
