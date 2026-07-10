package ae.lf.training.judge.data.local

import androidx.room.Database
import androidx.room.RoomDatabase

@Database(
    entities = [PendingOperationEntity::class, CachedEvalDetailEntity::class],
    version = 1,
    exportSchema = false,
)
abstract class JudgeDatabase : RoomDatabase() {
    abstract fun pendingOperationDao(): PendingOperationDao
    abstract fun cachedEvalDao(): CachedEvalDao
}
