"""إنشاء إشعارات التمرين وتوزيعها على المستخدمين المعنيين."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import (
    ChatMessage,
    ChatRoom,
    ChatRoomMember,
    ExerciseNotification,
    JudgeTraineeAssignment,
    RoleKey,
    User,
)


class NotificationType:
    MESSAGE = "message"
    MEETING = "meeting"
    DOCUMENT = "document"
    TASK = "task"
    SYSTEM = "system"


class NotificationPriority:
    NORMAL = "normal"
    IMPORTANT = "important"
    URGENT = "urgent"


def create_notification(
    db: Session,
    *,
    exercise_id: int,
    user_id: int,
    type_: str,
    title: str,
    message: str = "",
    priority: str = NotificationPriority.NORMAL,
    related_file: str = "",
    related_room_id: int | None = None,
    action_url: str = "",
) -> ExerciseNotification:
    row = ExerciseNotification(
        exercise_id=int(exercise_id),
        user_id=int(user_id),
        type=(type_ or NotificationType.SYSTEM)[:32],
        title=(title or "")[:500],
        body=message or "",
        priority=(priority or NotificationPriority.NORMAL)[:32],
        related_file=(related_file or "")[:600],
        related_room_id=related_room_id,
        action_url=(action_url or "")[:500],
    )
    db.add(row)
    return row


def _judge_user_ids_for_unit(db: Session, exercise_id: int, unit_key: str) -> list[int]:
    uk = (unit_key or "").strip()
    if not uk:
        return []
    rows = (
        db.query(JudgeTraineeAssignment.judge_user_id)
        .filter(
            JudgeTraineeAssignment.exercise_id == int(exercise_id),
            JudgeTraineeAssignment.unit_level_key == uk,
        )
        .all()
    )
    out: list[int] = []
    seen: set[int] = set()
    for (uid,) in rows:
        if uid is None:
            continue
        i = int(uid)
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def _recipient_ids_for_unit(db: Session, exercise_id: int, unit_key: str) -> set[int]:
    uk = (unit_key or "").strip()
    out: set[int] = set()
    if not uk:
        return out
    rows = (
        db.query(JudgeTraineeAssignment.judge_user_id)
        .filter(
            JudgeTraineeAssignment.exercise_id == int(exercise_id),
            JudgeTraineeAssignment.unit_level_key == uk,
        )
        .all()
    )
    for (uid,) in rows:
        if uid is not None:
            out.add(int(uid))
    for (uid,) in db.query(User.id).filter(User.role_key == RoleKey.SYSTEM_ADMIN.value).all():
        out.add(int(uid))
    return out


def notify_chat_new_message(
    db: Session,
    *,
    room: ChatRoom,
    message: ChatMessage,
    sender_id: int,
) -> None:
    member_ids = {
        int(r[0])
        for r in db.query(ChatRoomMember.user_id)
        .filter(ChatRoomMember.room_id == int(room.id))
        .all()
    }
    member_ids.discard(int(sender_id))
    if not member_ids:
        return
    room_title = (room.title or "").strip() or "غرفة محادثة"
    action_url = f"/chat-rooms/{int(room.id)}"
    if (message.message_type or "") == "file":
        mime = (message.mime_type or "").lower()
        fn = (message.original_filename or "").lower()
        is_audio = mime.startswith("audio/") or any(
            fn.endswith(ext) for ext in (".mp3", ".m4a", ".ogg", ".wav", ".webm", ".opus")
        )
        if is_audio:
            title = "لديك رسالة صوتية جديدة"
            body = f"رسالة صوتية في «{room_title}»."
        else:
            title = "ملف جديد في غرفة المحادثة"
            body = f"تمت مشاركة ملف في «{room_title}»."
    else:
        title = "رسالة جديدة في غرفة المحادثة"
        body = f"لديك رسالة جديدة في «{room_title}»."
    ex_id = int(room.exercise_id)
    for uid in member_ids:
        create_notification(
            db,
            exercise_id=ex_id,
            user_id=uid,
            type_=NotificationType.MESSAGE,
            title=title,
            message=body,
            related_room_id=int(room.id),
            action_url=action_url,
            priority=NotificationPriority.NORMAL,
        )


def notify_dilemma_files_added(
    db: Session,
    *,
    exercise_id: int,
    unit_key: str,
    unit_label: str,
    n_files: int,
) -> None:
    if n_files <= 0:
        return
    recipients = _recipient_ids_for_unit(db, exercise_id, unit_key)
    if not recipients:
        return
    ul = (unit_label or unit_key or "").strip()
    title = "تم رفع قائمة معاضل جديدة"
    body = f"تمت إضافة {n_files} ملفاً PDF لمعاضل مستوى الوحدة: {ul}."
    action = f"/judge/dilemmas/{unit_key}"
    for uid in recipients:
        create_notification(
            db,
            exercise_id=int(exercise_id),
            user_id=uid,
            type_=NotificationType.DOCUMENT,
            title=title,
            message=body,
            action_url=action,
            priority=NotificationPriority.IMPORTANT,
        )


def notify_evaluation_lists_added(
    db: Session,
    *,
    exercise_id: int,
    unit_key: str,
    unit_label: str,
    n_files: int,
) -> None:
    if n_files <= 0:
        return
    recipients = _recipient_ids_for_unit(db, exercise_id, unit_key)
    if not recipients:
        return
    ul = (unit_label or unit_key or "").strip()
    title = "تم رفع قائمة تقييم جديدة"
    body = f"تمت إضافة {n_files} ملفاً Excel لقوائم التقييم — {ul}."
    action = f"/judge/evaluation-lists/{unit_key}"
    for uid in recipients:
        create_notification(
            db,
            exercise_id=int(exercise_id),
            user_id=uid,
            type_=NotificationType.DOCUMENT,
            title=title,
            message=body,
            action_url=action,
            priority=NotificationPriority.IMPORTANT,
        )


def notify_evaluation_reopened_by_chief_judge(
    db: Session,
    *,
    exercise_id: int,
    unit_key: str,
    unit_label: str,
    item_title: str,
    item_id: int,
    saved_by_user_id: int | None = None,
    exclude_user_id: int | None = None,
) -> None:
    """تنبيه المحكم عند إعادة كبير المحكمين قائمة التقييم للتعديل."""
    recipients: set[int] = set(_judge_user_ids_for_unit(db, exercise_id, unit_key))
    if saved_by_user_id is not None:
        recipients.add(int(saved_by_user_id))
    if exclude_user_id is not None:
        recipients.discard(int(exclude_user_id))
    if not recipients:
        return
    ul = (unit_label or unit_key or "").strip()
    title_s = (item_title or "قائمة التقييم").strip()
    title = "إعادة التقييم مطلوبة"
    body = (
        f"أعاد كبير المحكمين قائمة «{title_s}» للتعديل — {ul}. "
        "يرجى مراجعة القائمة وحفظ التعديلات ثم إرسالها للاعتماد."
    )
    action = f"/judge/evaluation-lists/{unit_key}/view/{int(item_id)}"
    for uid in recipients:
        create_notification(
            db,
            exercise_id=int(exercise_id),
            user_id=int(uid),
            type_=NotificationType.TASK,
            title=title,
            message=body,
            action_url=action,
            priority=NotificationPriority.URGENT,
        )


def notify_visual_document_added(
    db: Session,
    *,
    exercise_id: int,
    unit_key: str,
    unit_label: str,
    file_type: str,
    action_url: str = "/visual-documentation",
) -> None:
    recipients = _recipient_ids_for_unit(db, exercise_id, unit_key)
    if not recipients:
        return
    ul = (unit_label or unit_key or "").strip()
    ft = (file_type or "").strip().lower()
    if ft == "video":
        title = "تم رفع مقطع فيديو جديد"
    elif ft == "audio":
        title = "تم رفع تسجيل صوتي جديد"
    else:
        title = "تم رفع صورة جديدة"
    body = f"تم رفع مادة توثيق مرئي لوحدة: {ul}."
    for uid in recipients:
        create_notification(
            db,
            exercise_id=int(exercise_id),
            user_id=uid,
            type_=NotificationType.DOCUMENT,
            title=title,
            message=body,
            action_url=action_url,
            priority=NotificationPriority.IMPORTANT,
        )
