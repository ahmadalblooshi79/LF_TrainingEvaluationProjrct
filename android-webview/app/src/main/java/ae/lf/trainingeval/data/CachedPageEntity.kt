package ae.lf.trainingeval.data

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "cached_pages")
data class CachedPageEntity(
    @PrimaryKey val urlKey: String,
    val url: String,
    val mimeType: String,
    val encoding: String,
    val statusCode: Int,
    val bodyFile: String,
    val bodySize: Long,
    val cachedAt: Long = System.currentTimeMillis(),
)
