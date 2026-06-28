package ae.lf.trainingeval.data

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query

@Dao
interface CachedPageDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(entity: CachedPageEntity)

    @Query("SELECT * FROM cached_pages WHERE urlKey = :key LIMIT 1")
    suspend fun getByKey(key: String): CachedPageEntity?

    @Query("SELECT * FROM cached_pages WHERE url = :url ORDER BY cachedAt DESC LIMIT 1")
    suspend fun getByUrl(url: String): CachedPageEntity?

    @Query("SELECT COUNT(*) FROM cached_pages")
    suspend fun count(): Int

    @Query(
        """
        SELECT * FROM cached_pages
        ORDER BY cachedAt ASC
        LIMIT :limit
        """,
    )
    suspend fun oldest(limit: Int): List<CachedPageEntity>

    @Query("DELETE FROM cached_pages WHERE urlKey = :key")
    suspend fun deleteByKey(key: String)
}
