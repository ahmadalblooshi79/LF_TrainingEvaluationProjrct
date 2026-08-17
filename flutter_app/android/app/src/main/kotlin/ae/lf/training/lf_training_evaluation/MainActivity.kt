package ae.lf.training.lf_training_evaluation

import android.os.StatFs
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    private val channelName = "lf.training/storage"

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, channelName)
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    "getFreeSpace" -> {
                        try {
                            val path = filesDir.absolutePath
                            val stat = StatFs(path)
                            result.success(stat.availableBytes)
                        } catch (e: Exception) {
                            result.error("storage", e.message, null)
                        }
                    }
                    else -> result.notImplemented()
                }
            }
    }
}
