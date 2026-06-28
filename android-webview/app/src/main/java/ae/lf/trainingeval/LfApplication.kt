package ae.lf.trainingeval

import ae.lf.trainingeval.sync.NativeSyncManager
import ae.lf.trainingeval.sync.OfflineSyncRepository
import android.app.Application

class LfApplication : Application() {
    val offlineRepository: OfflineSyncRepository by lazy { OfflineSyncRepository(this) }
    val nativeSyncManager: NativeSyncManager by lazy { NativeSyncManager(this) }
}
