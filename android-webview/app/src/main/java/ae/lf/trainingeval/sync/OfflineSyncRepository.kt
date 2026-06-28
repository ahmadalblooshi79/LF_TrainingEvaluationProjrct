package ae.lf.trainingeval.sync

import ae.lf.trainingeval.data.LfOfflineDatabase
import ae.lf.trainingeval.data.OfflineOperationEntity
import android.content.Context
import org.json.JSONObject

class OfflineSyncRepository(context: Context) {
    private val dao = LfOfflineDatabase.get(context).offlineOperationDao()

    suspend fun enqueueFromJson(raw: String): String {
        val json = JSONObject(raw)
        val opId = json.optString("client_operation_id").ifBlank {
            "op-${System.currentTimeMillis()}-${(Math.random() * 1e6).toInt()}"
        }
        val entity = OfflineOperationEntity(
            clientOperationId = opId,
            type = json.optString("type", "http_post"),
            url = json.optString("url", ""),
            payloadJson = json.optString("payload_json").ifBlank { null },
            fileBase64 = json.optString("file_base64").ifBlank { null },
            evaluationListItemId = json.optString("evaluation_list_item_id").ifBlank { null },
            itemId = json.optString("item_id").ifBlank { null },
            rowIndex = json.optString("row_index").ifBlank { null },
            mediaKind = json.optString("media_kind").ifBlank { null },
            bundleActionEvalId = json.optString("bundle_action_eval_id").ifBlank { null },
            exerciseId = json.optString("exercise_id").ifBlank { null },
            unitLevelKey = json.optString("unit_level_key").ifBlank { null },
            mimeType = json.optString("mime_type").ifBlank { null },
            createdAt = json.optLong("created_at", System.currentTimeMillis()),
            status = OfflineOperationEntity.STATUS_PENDING,
        )
        dao.upsert(entity)
        return opId
    }

    suspend fun pendingCount(): Int = dao.countPending()

    suspend fun getPending(): List<OfflineOperationEntity> = dao.getPending()

    suspend fun deleteById(id: String) {
        dao.deleteById(id)
    }

    suspend fun markStatus(id: String, status: String) {
        dao.updateStatus(id, status)
    }

    fun entityToJson(entity: OfflineOperationEntity): JSONObject {
        return JSONObject().apply {
            put("client_operation_id", entity.clientOperationId)
            put("type", entity.type)
            put("url", entity.url)
            entity.payloadJson?.let { put("payload_json", it) }
            entity.fileBase64?.let { put("file_base64", it) }
            entity.evaluationListItemId?.let { put("evaluation_list_item_id", it) }
            entity.itemId?.let { put("item_id", it) }
            entity.rowIndex?.let { put("row_index", it) }
            entity.mediaKind?.let { put("media_kind", it) }
            entity.bundleActionEvalId?.let { put("bundle_action_eval_id", it) }
            entity.exerciseId?.let { put("exercise_id", it) }
            entity.unitLevelKey?.let { put("unit_level_key", it) }
            entity.mimeType?.let { put("mime_type", it) }
            put("created_at", entity.createdAt)
        }
    }
}
