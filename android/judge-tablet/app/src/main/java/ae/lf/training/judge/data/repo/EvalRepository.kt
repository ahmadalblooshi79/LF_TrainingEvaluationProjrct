package ae.lf.training.judge.data.repo

import ae.lf.training.judge.data.api.EvalDetailResponse
import ae.lf.training.judge.data.api.EvalListRowDto
import ae.lf.training.judge.data.api.HubItemDto
import ae.lf.training.judge.data.api.IncompleteRowDto
import ae.lf.training.judge.data.api.MobileApiService
import ae.lf.training.judge.data.api.NotificationRowDto
import ae.lf.training.judge.data.api.PhaseTabDto
import ae.lf.training.judge.data.api.SaveEvalRequest
import ae.lf.training.judge.data.local.CachedEvalDetailEntity
import ae.lf.training.judge.data.local.JudgeDatabase
import ae.lf.training.judge.data.local.PendingOperationEntity
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken

class EvalRepository(
    private val api: MobileApiService,
    private val db: JudgeDatabase,
) {
    private val gson = Gson()

    suspend fun fetchHub(): Pair<List<HubItemDto>, List<HubItemDto>> {
        val resp = api.judgeHub()
        val body = resp.body() ?: error("empty")
        if (!resp.isSuccessful || !body.ok) error(body.error ?: "hub_failed")
        return body.judgeItems.orEmpty() to body.chiefItems.orEmpty()
    }

    suspend fun fetchEvalHome(): List<PhaseTabDto> {
        val resp = api.evalListsHome()
        val body = resp.body() ?: error("empty")
        if (!resp.isSuccessful || !body.ok) error(body.error ?: "lists_failed")
        return body.phaseTabs.orEmpty()
    }

    suspend fun fetchUnitLists(unitKey: String, phase: String?): List<EvalListRowDto> {
        val resp = api.evalListsUnit(unitKey, phase)
        val body = resp.body() ?: error("empty")
        if (!resp.isSuccessful || !body.ok) error(body.error ?: "unit_failed")
        val type = object : TypeToken<List<EvalListRowDto>>() {}.type
        return gson.fromJson(body.rows, type) ?: emptyList()
    }

    suspend fun fetchEvalDetail(unitKey: String, itemId: Int, allowCache: Boolean = true): EvalDetailResponse {
        return try {
            val resp = api.evalDetail(unitKey, itemId)
            val body = resp.body() ?: error("empty")
            if (!resp.isSuccessful || !body.ok) error(body.error ?: "detail_failed")
            db.cachedEvalDao().upsert(
                CachedEvalDetailEntity(
                    cacheKey = "$unitKey:$itemId",
                    json = gson.toJson(body),
                    updatedAt = System.currentTimeMillis(),
                )
            )
            body
        } catch (e: Exception) {
            if (!allowCache) throw e
            val cached = db.cachedEvalDao().get("$unitKey:$itemId")
                ?: throw e
            gson.fromJson(cached.json, EvalDetailResponse::class.java)
        }
    }

    suspend fun saveEval(unitKey: String, itemId: Int, payloadJson: String, online: Boolean): Result<Unit> {
        if (online) {
            return runCatching {
                val resp = api.saveEval(unitKey, itemId, SaveEvalRequest(payloadJson = payloadJson))
                val body = resp.body() ?: error("empty")
                if (!resp.isSuccessful || !body.ok) error(body.error ?: "save_failed")
            }
        }
        db.pendingOperationDao().insert(
            PendingOperationEntity(
                clientId = "${System.currentTimeMillis()}-$itemId",
                type = "eval_save",
                unitKey = unitKey,
                itemId = itemId,
                payloadJson = payloadJson,
                createdAt = System.currentTimeMillis(),
            )
        )
        return Result.success(Unit)
    }

    suspend fun approveEval(unitKey: String, itemId: Int, online: Boolean): Result<Unit> {
        if (online) {
            return runCatching {
                val resp = api.approveEval(unitKey, itemId)
                val body = resp.body() ?: error("empty")
                if (!resp.isSuccessful || !body.ok) error(body.error ?: "approve_failed")
            }
        }
        db.pendingOperationDao().insert(
            PendingOperationEntity(
                clientId = "${System.currentTimeMillis()}-approve-$itemId",
                type = "eval_approve",
                unitKey = unitKey,
                itemId = itemId,
                payloadJson = null,
                createdAt = System.currentTimeMillis(),
            )
        )
        return Result.success(Unit)
    }

    suspend fun chiefApprove(unitKey: String, itemId: Int): Result<Unit> = runCatching {
        val resp = api.chiefApprove(unitKey, itemId)
        val body = resp.body() ?: error("empty")
        if (!resp.isSuccessful || !body.ok) error(body.error ?: "chief_approve_failed")
    }

    suspend fun chiefReopen(unitKey: String, itemId: Int): Result<Unit> = runCatching {
        val resp = api.chiefReopen(unitKey, itemId)
        val body = resp.body() ?: error("empty")
        if (!resp.isSuccessful || !body.ok) error(body.error ?: "reopen_failed")
    }

    suspend fun fetchIncomplete(): List<IncompleteRowDto> {
        val resp = api.incompleteTasks()
        val body = resp.body() ?: error("empty")
        if (!resp.isSuccessful || !body.ok) error(body.error ?: "incomplete_failed")
        val type = object : TypeToken<List<IncompleteRowDto>>() {}.type
        return gson.fromJson(body.rows, type) ?: emptyList()
    }

    suspend fun fetchNotifications(): Pair<Int, List<NotificationRowDto>> {
        val resp = api.notifications()
        val body = resp.body() ?: error("empty")
        if (!resp.isSuccessful || !body.ok) error(body.error ?: "notifications_failed")
        val type = object : TypeToken<List<NotificationRowDto>>() {}.type
        val rows: List<NotificationRowDto> = gson.fromJson(body.rows, type) ?: emptyList()
        return (body.unreadCount ?: 0) to rows
    }

    suspend fun isOnline(): Boolean = runCatching {
        api.ping().isSuccessful
    }.getOrDefault(false)
}
