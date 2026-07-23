from app.models import User, RoleKey


def _rk(user: User) -> RoleKey:
    return RoleKey.from_value(getattr(user, "role_key", "judge"))


def is_system_admin(user: User) -> bool:
    return _rk(user) == RoleKey.SYSTEM_ADMIN


def is_analyst(user: User) -> bool:
    return _rk(user) == RoleKey.ANALYST


def is_planner(user: User) -> bool:
    return _rk(user) == RoleKey.PLANNER


def is_judge(user: User) -> bool:
    return _rk(user) == RoleKey.JUDGE


def is_chief_judge(user: User) -> bool:
    return _rk(user) == RoleKey.CHIEF_JUDGE


def is_standards(user: User) -> bool:
    return _rk(user) == RoleKey.STANDARDS_LIBRARY


def is_control(user: User) -> bool:
    return _rk(user) == RoleKey.CONTROL


def can_manage_users(user: User) -> bool:
    return is_system_admin(user)


def can_plan_exercises(user: User) -> bool:
    return is_system_admin(user) or is_planner(user) or is_control(user)


def can_manage_information_bank(user: User) -> bool:
    """بنك المعلومات ثابت في النظام وليس مرتبطاً بأي تمرين — الإضافة/التعديل/الحذف لإدارة النظام فقط."""
    return is_system_admin(user)


def can_view_information_bank(user: User) -> bool:
    """عرض بنك المعلومات وتنزيل الملفات (للاستعمال في التخطيط وتخصيص المحتوى للمحكمين/الوحدات)."""
    return can_manage_information_bank(user) or can_plan_exercises(user)


def can_access_analyst_hub(user: User) -> bool:
    """مساحة المحللين — المحلل أو إدارة النظام."""
    return is_analyst(user) or is_system_admin(user)


def can_access_planner_hub(user: User) -> bool:
    """مساحة التخطيط — المخطّط أو إدارة النظام."""
    return is_planner(user) or is_system_admin(user)


def can_access_judge_hub(user: User) -> bool:
    """مساحة المحكمين — المحكم، كبير المحكمين، أو إدارة النظام."""
    return is_judge(user) or is_chief_judge(user) or is_system_admin(user)


def can_oversee_judge_planner_flow_materials(user: User) -> bool:
    """إطلاع إدارة النظام وكبير المحكمين على حزمة «مجرى الأحداث وتقييم الإجراءات» المخصّصة لمحكم فردي (عبر judge_user_id في الرابط أو قائمة الاختيار)."""
    return is_system_admin(user) or is_chief_judge(user)


def can_access_chief_judge_hub(user: User) -> bool:
    """مساحة كبير المحكمين — الاعتماد الثاني وإعادة التقييم للمحكم."""
    return is_chief_judge(user) or is_system_admin(user)


def can_access_control_hub(user: User) -> bool:
    """مساحة السيطرة — السيطرة أو إدارة النظام."""
    return is_control(user) or is_system_admin(user)


def can_edit_references(user: User) -> bool:
    return is_system_admin(user) or is_standards(user)


def can_judge_exercise(user: User) -> bool:
    return is_system_admin(user) or is_judge(user) or is_chief_judge(user) or is_control(user)


def can_edit_event_flow(user: User) -> bool:
    return is_system_admin(user) or is_planner(user) or is_control(user)


def can_manage_problems(user: User) -> bool:
    return (
        is_system_admin(user)
        or is_planner(user)
        or is_judge(user)
        or is_chief_judge(user)
        or is_control(user)
        or is_analyst(user)
    )


def can_control_approve(user: User) -> bool:
    return is_system_admin(user) or is_control(user)


def can_save_evaluation_results(user: User) -> bool:
    """حفظ نتائج التقييم — إدارة النظام، المحكم، كبير المحكمين، المخطّط."""
    return is_system_admin(user) or is_judge(user) or is_chief_judge(user) or is_planner(user)


def can_approve_evaluation_results(user: User) -> bool:
    """اعتماد المحكم (المرحلة الأولى) — إدارة النظام، المحكم، وكبير المحكمين."""
    return is_system_admin(user) or is_judge(user) or is_chief_judge(user)


def can_chief_approve_evaluation_results(user: User) -> bool:
    """اعتماد كبير المحكمين (المرحلة الثانية)."""
    return is_system_admin(user) or is_chief_judge(user)


def can_chief_reopen_evaluation_for_judge(user: User) -> bool:
    """إعادة القائمة للمحكم لإعادة التقييم."""
    return is_system_admin(user) or is_chief_judge(user)


def can_manage_chat_rooms(user: User) -> bool:
    """إنشاء غرف المحادثة وإدارة الأعضاء — إدارة النظام."""
    return is_system_admin(user)


def can_view_notifications_log(user: User) -> bool:
    """سجل الإشعارات — المحكم، كبير المحكمين، السيطرة، التخطيط، إدارة النظام."""
    return (
        is_system_admin(user)
        or is_judge(user)
        or is_chief_judge(user)
        or is_control(user)
        or is_planner(user)
    )


def can_use_chat_rooms(user: User) -> bool:
    """استخدام غرف المحادثة (الدخول للغرف المسموحة) — أدوار المنصة الأساسية."""
    return (
        is_system_admin(user)
        or is_judge(user)
        or is_chief_judge(user)
        or is_planner(user)
        or is_control(user)
        or is_analyst(user)
    )


def can_use_visual_documentation(user: User) -> bool:
    """التوثيق المرئي — المحكم/كبير المحكمين/السيطرة/إدارة النظام (والتخطيط عند الحاجة)."""
    return (
        is_system_admin(user)
        or is_judge(user)
        or is_chief_judge(user)
        or is_control(user)
        or is_planner(user)
    )


# —— مركز الذكاء الاصطناعي المحلي ——


def can_access_ai_center(user: User) -> bool:
    """ai.center.view — افتراضياً إدارة النظام فقط."""
    return is_system_admin(user)


def can_view_ai_settings(user: User) -> bool:
    """ai.settings.view"""
    return can_access_ai_center(user)


def can_edit_ai_settings(user: User) -> bool:
    """ai.settings.edit"""
    return is_system_admin(user)


def can_test_ai_connection(user: User) -> bool:
    """ai.connection.test"""
    return is_system_admin(user)


def can_view_ai_models(user: User) -> bool:
    """ai.models.view"""
    return can_access_ai_center(user)


# —— Agentic AI Foundation ——


def can_ai_center_view(user: User) -> bool:
    """AI_CENTER_VIEW"""
    return can_access_ai_center(user)


def can_ai_agent_manage(user: User) -> bool:
    """AI_AGENT_MANAGE"""
    return is_system_admin(user)


def can_ai_workflow_run(user: User) -> bool:
    """AI_WORKFLOW_RUN"""
    return is_system_admin(user)


def can_ai_workflow_manage(user: User) -> bool:
    """AI_WORKFLOW_MANAGE"""
    return is_system_admin(user)


def can_ai_prompt_manage(user: User) -> bool:
    """AI_PROMPT_MANAGE"""
    return is_system_admin(user)


def can_ai_knowledge_manage(user: User) -> bool:
    """AI_KNOWLEDGE_MANAGE"""
    return is_system_admin(user)


def can_ai_audit_view(user: User) -> bool:
    """AI_AUDIT_VIEW"""
    return is_system_admin(user)


# —— مكتبة التقارير الذكية ——


def can_view_ai_reports(user: User) -> bool:
    return is_system_admin(user)


def can_upload_ai_reports(user: User) -> bool:
    return is_system_admin(user)


def can_edit_ai_reports(user: User) -> bool:
    return is_system_admin(user)


def can_process_ai_reports(user: User) -> bool:
    return is_system_admin(user)


def can_review_ai_reports(user: User) -> bool:
    return is_system_admin(user)


def can_approve_ai_reports(user: User) -> bool:
    return is_system_admin(user)


def can_exclude_ai_reports(user: User) -> bool:
    return is_system_admin(user)


def can_archive_ai_reports(user: User) -> bool:
    return is_system_admin(user)


def can_delete_ai_reports(user: User) -> bool:
    return is_system_admin(user)


def can_view_ai_report_text(user: User) -> bool:
    return is_system_admin(user)


def can_review_ai_report_units(user: User) -> bool:
    return is_system_admin(user)


def can_review_ai_report_findings(user: User) -> bool:
    return is_system_admin(user)
