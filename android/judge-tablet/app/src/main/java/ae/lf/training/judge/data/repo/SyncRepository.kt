package ae.lf.training.judge.data.repo

import ae.lf.training.judge.data.api.SyncOperationDto
import ae.lf.training.judge.data.api.SyncPushRequest
import ae.lf.training.judge.data.local.PendingOperationDao
import ae.lf.training.judge.data.api.MobileApiService

class SyncRepository(
    private val api: MobileApiService,
    private val dao: PendingOperationDao,
) {
    suspend fun pushPending(): Pair<Int, Int> {
        val pending = dao.getAll()
        if (pending.isEmpty()) return 0 to 0
        val ops = pending.map {
            SyncOperationDto(
                clientId = it.clientId,
                type = it.type,
                unitKey = it.unitKey,
                itemId = it.itemId,
                payloadJson = it.payloadJson,
            )
        }
        val resp = api.syncPush(SyncPushRequest(ops))
        val body = resp.body() ?: error("empty")
        if (!resp.isSuccessful || !body.ok) error(body.error ?: "sync_failed")
        var okCount = 0
        body.results.orEmpty().forEach { r ->
            if (r.ok) {
                dao.delete(r.clientId)
                okCount++
            }
        }
        return okCount to (pending.size - okCount)
    }
}
