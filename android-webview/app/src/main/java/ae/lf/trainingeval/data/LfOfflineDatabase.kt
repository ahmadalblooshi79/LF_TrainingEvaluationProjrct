package ae.lf.trainingeval.data

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase

@Database(
    entities = [OfflineOperationEntity::class, CachedPageEntity::class],
    version = 2,
    exportSchema = false,
)
abstract class LfOfflineDatabase : RoomDatabase() {
    abstract fun offlineOperationDao(): OfflineOperationDao
    abstract fun cachedPageDao(): CachedPageDao

    companion object {
        @Volatile
        private var instance: LfOfflineDatabase? = null

        fun get(context: Context): LfOfflineDatabase {
            return instance ?: synchronized(this) {
                instance ?: Room.databaseBuilder(
                    context.applicationContext,
                    LfOfflineDatabase::class.java,
                    "lf_offline_sync.db",
                )
                    .fallbackToDestructiveMigration()
                    .build()
                    .also { instance = it }
            }
        }
    }
}
