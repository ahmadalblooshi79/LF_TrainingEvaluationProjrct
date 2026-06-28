package ae.lf.trainingeval

import android.annotation.SuppressLint
import android.content.Context
import android.os.Build
import android.provider.Settings
import android.webkit.JavascriptInterface
import android.webkit.WebView
import ae.lf.trainingeval.network.ServerReachability
import ae.lf.trainingeval.sync.NativeSyncManager
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking

class LfAppBridge(
    private val context: Context,
    private val scope: CoroutineScope,
    private val onSyncComplete: ((NativeSyncManager.SyncResult) -> Unit)? = null,
) {
    private val app get() = context.applicationContext as LfApplication

    @JavascriptInterface
    fun getDeviceId(): String {
        return Settings.Secure.getString(context.contentResolver, Settings.Secure.ANDROID_ID) ?: "android-unknown"
    }

    @JavascriptInterface
    fun getDeviceName(): String {
        val manufacturer = Build.MANUFACTURER?.trim().orEmpty()
        val model = Build.MODEL?.trim().orEmpty()
        return listOf(manufacturer, model).filter { it.isNotEmpty() }.joinToString(" ")
    }

    @JavascriptInterface
    fun hasNativeOfflineStorage(): Boolean = true

    @JavascriptInterface
    fun enqueueOfflineOperation(json: String): String {
        return runBlocking(Dispatchers.IO) {
            app.offlineRepository.enqueueFromJson(json)
        }
    }

    @JavascriptInterface
    fun getPendingSyncCount(): Int {
        return runBlocking(Dispatchers.IO) {
            app.offlineRepository.pendingCount()
        }
    }

    @JavascriptInterface
    fun isServerReachable(): Boolean {
        return ServerReachability.isReachable(context, force = true)
    }

    @JavascriptInterface
    fun triggerNativeSync() {
        scope.launch(Dispatchers.IO) {
            val result = app.nativeSyncManager.syncNow()
            onSyncComplete?.invoke(result)
        }
    }

    companion object {
        @SuppressLint("SetJavaScriptEnabled")
        fun install(webView: WebView, bridge: LfAppBridge) {
            webView.addJavascriptInterface(bridge, "LfAndroidBridge")
            val script = """
                (function(){
                  var b = window.LfAndroidBridge;
                  if (!b) return;
                  window.LFDevice = {
                    id: String(b.getDeviceId()),
                    name: String(b.getDeviceName()),
                    platform: 'android'
                  };
                  if (b.hasNativeOfflineStorage && b.hasNativeOfflineStorage()) {
                    window.LFNativeOffline = {
                      available: true,
                      enqueue: function(json){ return String(b.enqueueOfflineOperation(json)); },
                      pendingCount: function(){ return b.getPendingSyncCount(); },
                      isServerReachable: function(){ return !!b.isServerReachable(); },
                      triggerSync: function(){ b.triggerNativeSync(); }
                    };
                  }
                })();
            """.trimIndent()
            webView.evaluateJavascript(script, null)
        }
    }
}
