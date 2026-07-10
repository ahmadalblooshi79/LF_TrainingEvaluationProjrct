package ae.lf.training.judge.data.local

import androidx.room.Dao
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.PrimaryKey
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

@Entity(tableName = "pending_operations")
data class PendingOperationEntity(
    @PrimaryKey val clientId: String,
    val type: String,
    val unitKey: String,
    val itemId: Int,
    val payloadJson: String?,
    val createdAt: Long,
)

@Dao
interface PendingOperationDao {
    @Query("SELECT * FROM pending_operations ORDER BY createdAt ASC")
    fun observeAll(): Flow<List<PendingOperationEntity>>

    @Query("SELECT * FROM pending_operations ORDER BY createdAt ASC")
    suspend fun getAll(): List<PendingOperationEntity>

    @Query("SELECT COUNT(*) FROM pending_operations")
    fun observeCount(): Flow<Int>

    @Insert
    suspend fun insert(entity: PendingOperationEntity)

    @Query("DELETE FROM pending_operations WHERE clientId = :clientId")
    suspend fun delete(clientId: String)

    @Query("DELETE FROM pending_operations")
    suspend fun clearAll()
}

@Entity(tableName = "cached_eval_detail")
data class CachedEvalDetailEntity(
    @PrimaryKey val cacheKey: String,
    val json: String,
    val updatedAt: Long,
)

@Dao
interface CachedEvalDao {
    @Query("SELECT * FROM cached_eval_detail WHERE cacheKey = :key LIMIT 1")
    suspend fun get(key: String): CachedEvalDetailEntity?

    @Insert
    suspend fun upsert(entity: CachedEvalDetailEntity)
}
