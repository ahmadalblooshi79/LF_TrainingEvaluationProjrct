package ae.lf.training.judge.data.api

import com.google.gson.JsonElement
import com.google.gson.annotations.SerializedName

data class ApiResponse<T>(
    val ok: Boolean,
    val error: String? = null,
    val user: UserDto? = null,
    @SerializedName("judge_items") val judgeItems: List<HubItemDto>? = null,
    @SerializedName("chief_items") val chiefItems: List<HubItemDto>? = null,
    @SerializedName("phase_tabs") val phaseTabs: List<PhaseTabDto>? = null,
    @SerializedName("active_phase_key") val activePhaseKey: String? = null,
    @SerializedName("has_exercise") val hasExercise: Boolean? = null,
    val rows: JsonElement? = null,
    @SerializedName("unit_key") val unitKey: String? = null,
    @SerializedName("unit_label") val unitLabel: String? = null,
    @SerializedName("item_id") val itemId: Int? = null,
    @SerializedName("item_title") val itemTitle: String? = null,
    val workflow: WorkflowDto? = null,
    @SerializedName("eval_rows") val evalRows: List<Map<String, Any?>>? = null,
    @SerializedName("saved_payload") val savedPayload: Map<String, Any?>? = null,
    @SerializedName("acquired_options") val acquiredOptions: List<Any>? = null,
    @SerializedName("eval_can_edit") val evalCanEdit: Boolean? = null,
    @SerializedName("show_eval_approve") val showEvalApprove: Boolean? = null,
    @SerializedName("show_chief_approve") val showChiefApprove: Boolean? = null,
    @SerializedName("show_chief_reopen") val showChiefReopen: Boolean? = null,
    @SerializedName("unread_count") val unreadCount: Int? = null,
    val count: Int? = null,
    val results: List<SyncResultDto>? = null,
)

data class UserDto(
    val id: Int,
    val username: String,
    @SerializedName("full_name") val fullName: String,
    @SerializedName("role_key") val roleKey: String,
    @SerializedName("role_tier") val roleTier: String,
    @SerializedName("assigned_unit_key") val assignedUnitKey: String?,
    @SerializedName("can_chief_hub") val canChiefHub: Boolean,
    @SerializedName("can_judge_hub") val canJudgeHub: Boolean,
    val exercise: ExerciseDto?,
)

data class ExerciseDto(
    val id: Int,
    val name: String,
    val code: String,
    @SerializedName("trained_unit") val trainedUnit: String,
    @SerializedName("exercise_type") val exerciseType: String,
)

data class HubItemDto(
    val slug: String,
    val title: String,
    val icon: String,
)

data class PhaseTabDto(
    @SerializedName("phase_key") val phaseKey: String,
    @SerializedName("phase_label") val phaseLabel: String,
    val totals: TotalsDto,
    @SerializedName("unit_rows") val unitRows: List<UnitRowDto>,
)

data class TotalsDto(val total: Int, @SerializedName("not_done") val notDone: Int)

data class UnitRowDto(
    val key: String,
    val label: String,
    @SerializedName("total_count") val totalCount: Int,
    @SerializedName("not_done_count") val notDoneCount: Int,
)

data class EvalListRowDto(
    @SerializedName("item_id") val itemId: Int,
    val title: String,
    @SerializedName("updated_at") val updatedAt: String,
    @SerializedName("status_label") val statusLabel: String,
    @SerializedName("status_done") val statusDone: Boolean,
    @SerializedName("grade_label") val gradeLabel: String,
    @SerializedName("dispatch_label") val dispatchLabel: String,
    @SerializedName("workflow_label") val workflowLabel: String,
)

data class IncompleteRowDto(
    val kind: String,
    val title: String,
    @SerializedName("unit_label") val unitLabel: String,
    @SerializedName("unit_key") val unitKey: String,
    @SerializedName("item_id") val itemId: Int?,
    @SerializedName("phase_label") val phaseLabel: String,
    @SerializedName("started_at") val startedAt: String,
    @SerializedName("status_label") val statusLabel: String,
)

data class NotificationRowDto(
    val id: Int,
    val type: String,
    val title: String,
    val body: String,
    val priority: String,
    @SerializedName("is_read") val isRead: Boolean,
    @SerializedName("created_at") val createdAt: String,
)

data class WorkflowDto(
    val label: String,
    @SerializedName("eval_can_edit") val evalCanEdit: Boolean? = null,
    @SerializedName("show_eval_approve") val showEvalApprove: Boolean? = null,
    @SerializedName("show_chief_approve") val showChiefApprove: Boolean? = null,
    @SerializedName("show_chief_reopen") val showChiefReopen: Boolean? = null,
)

data class LoginRequest(val username: String, val password: String)

data class SaveEvalRequest(
    @SerializedName("payload_json") val payloadJson: String? = null,
    val payload: Map<String, Any?>? = null,
)

data class SyncPushRequest(val operations: List<SyncOperationDto>)

data class SyncOperationDto(
    @SerializedName("client_id") val clientId: String,
    val type: String,
    @SerializedName("unit_key") val unitKey: String,
    @SerializedName("item_id") val itemId: Int,
    @SerializedName("payload_json") val payloadJson: String? = null,
)

data class EvalDetailResponse(
    val ok: Boolean = false,
    val error: String? = null,
    @SerializedName("unit_key") val unitKey: String? = null,
    @SerializedName("unit_label") val unitLabel: String? = null,
    @SerializedName("item_id") val itemId: Int? = null,
    @SerializedName("item_title") val itemTitle: String? = null,
    @SerializedName("eval_rows") val evalRows: List<Map<String, Any?>>? = null,
    @SerializedName("saved_payload") val savedPayload: Map<String, Any?>? = null,
    @SerializedName("acquired_options") val acquiredOptions: List<List<String>>? = null,
    val workflow: WorkflowDto? = null,
)

data class SyncResultDto(
    @SerializedName("client_id") val clientId: String,
    val ok: Boolean,
    val error: String?,
)
