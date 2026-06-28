package ae.lf.trainingeval.data

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query

@Dao
interface OfflineOperationDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(entity: OfflineOperationEntity)

    @Query("SELECT * FROM offline_operations WHERE status IN ('pending', 'failed') ORDER BY createdAt ASC")
    suspend fun getPending(): List<OfflineOperationEntity>

    @Query("SELECT COUNT(*) FROM offline_operations WHERE status IN ('pending', 'failed')")
    suspend fun countPending(): Int

    @Query("DELETE FROM offline_operations WHERE clientOperationId = :id")
    suspend fun deleteById(id: String)

    @Query("UPDATE offline_operations SET status = :status WHERE clientOperationId = :id")
    suspend fun updateStatus(id: String, status: String)
}
