package ae.lf.trainingeval.data

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "offline_operations")
data class OfflineOperationEntity(
    @PrimaryKey val clientOperationId: String,
    val type: String,
    val url: String,
    val payloadJson: String? = null,
    val fileBase64: String? = null,
    val evaluationListItemId: String? = null,
    val itemId: String? = null,
    val rowIndex: String? = null,
    val mediaKind: String? = null,
    val bundleActionEvalId: String? = null,
    val exerciseId: String? = null,
    val unitLevelKey: String? = null,
    val mimeType: String? = null,
    val createdAt: Long = System.currentTimeMillis(),
    val status: String = STATUS_PENDING,
) {
    companion object {
        const val STATUS_PENDING = "pending"
        const val STATUS_SYNCING = "syncing"
        const val STATUS_SYNCED = "synced"
        const val STATUS_FAILED = "failed"
    }
}
