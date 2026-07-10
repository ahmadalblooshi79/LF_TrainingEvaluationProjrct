package ae.lf.training.judge

import android.app.Application
import ae.lf.training.judge.data.AppContainer

class JudgeApp : Application() {
    lateinit var container: AppContainer
        private set

    override fun onCreate() {
        super.onCreate()
        container = AppContainer(this)
    }
}
