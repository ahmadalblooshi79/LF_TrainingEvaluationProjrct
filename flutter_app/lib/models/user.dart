class UserModel {
  final int id;
  final String username;
  final String fullName;
  final String judgeDisplayName;
  final String roleKey;
  final String roleLabel;
  final bool isChiefJudge;
  final bool isAdmin;

  const UserModel({
    required this.id,
    required this.username,
    required this.fullName,
    required this.judgeDisplayName,
    required this.roleKey,
    required this.roleLabel,
    required this.isChiefJudge,
    required this.isAdmin,
  });

  factory UserModel.fromJson(Map<String, dynamic> json) {
    return UserModel(
      id: (json['id'] as num?)?.toInt() ?? 0,
      username: (json['username'] ?? '').toString(),
      fullName: (json['full_name'] ?? '').toString(),
      judgeDisplayName: (json['judge_display_name'] ?? '').toString(),
      roleKey: (json['role_key'] ?? '').toString(),
      roleLabel: (json['role_label'] ?? '').toString(),
      isChiefJudge: json['is_chief_judge'] == true,
      isAdmin: json['is_admin'] == true,
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'username': username,
        'full_name': fullName,
        'judge_display_name': judgeDisplayName,
        'role_key': roleKey,
        'role_label': roleLabel,
        'is_chief_judge': isChiefJudge,
        'is_admin': isAdmin,
      };
}

class ExerciseModel {
  final int id;
  final String name;
  final String code;
  final String location;
  final String startDate;
  final String endDate;
  final String periodLabel;
  final String typeLabel;
  final String levelLabel;
  final String trainedUnit;
  final String missionLabel;

  const ExerciseModel({
    required this.id,
    required this.name,
    required this.code,
    required this.location,
    required this.startDate,
    required this.endDate,
    required this.periodLabel,
    required this.typeLabel,
    this.levelLabel = '',
    this.trainedUnit = '',
    this.missionLabel = '',
  });

  factory ExerciseModel.fromJson(Map<String, dynamic> json) {
    return ExerciseModel(
      id: (json['id'] as num?)?.toInt() ?? 0,
      name: (json['name'] ?? '').toString(),
      code: (json['code'] ?? '').toString(),
      location: (json['location'] ?? '').toString(),
      startDate: (json['start_date'] ?? '').toString(),
      endDate: (json['end_date'] ?? '').toString(),
      periodLabel: (json['period_label'] ?? '').toString(),
      typeLabel: (json['type_label'] ?? '').toString(),
      levelLabel: (json['level_label'] ?? '').toString(),
      trainedUnit: (json['trained_unit'] ?? '').toString(),
      missionLabel: (json['mission_label'] ?? '').toString(),
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
        'code': code,
        'location': location,
        'start_date': startDate,
        'end_date': endDate,
        'period_label': periodLabel,
        'type_label': typeLabel,
        'level_label': levelLabel,
        'trained_unit': trainedUnit,
        'mission_label': missionLabel,
      };
}

/// Common bundle returned by /me, /home, /bootstrap, /auth/login.
class SessionBundle {
  final UserModel user;
  final ExerciseModel? exercise;
  final String unitKey;
  final String unitLabel;
  final String serverTime;

  const SessionBundle({
    required this.user,
    required this.exercise,
    required this.unitKey,
    required this.unitLabel,
    required this.serverTime,
  });

  factory SessionBundle.fromJson(Map<String, dynamic> json) {
    final exJson = json['exercise'];
    return SessionBundle(
      user: UserModel.fromJson((json['user'] as Map?)?.cast<String, dynamic>() ?? {}),
      exercise: exJson is Map
          ? ExerciseModel.fromJson(exJson.cast<String, dynamic>())
          : null,
      unitKey: (json['unit_key'] ?? '').toString(),
      unitLabel: (json['unit_label'] ?? '').toString(),
      serverTime: (json['server_time'] ?? '').toString(),
    );
  }

  Map<String, dynamic> toJson() => {
        'user': user.toJson(),
        'exercise': exercise?.toJson(),
        'unit_key': unitKey,
        'unit_label': unitLabel,
        'server_time': serverTime,
      };
}
