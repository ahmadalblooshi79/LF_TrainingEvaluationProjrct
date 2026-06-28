package ae.lf.trainingeval.sync

import ae.lf.trainingeval.ServerConfig
import ae.lf.trainingeval.data.OfflineOperationEntity
import android.content.Context
import android.os.Build
import android.provider.Settings
import android.webkit.CookieManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.atomic.AtomicBoolean

class NativeSyncManager(private val context: Context) {
    private val repo = OfflineSyncRepository(context)
    private val mutex = Mutex()
    private val running = AtomicBoolean(false)

    suspend fun syncNow(): SyncResult = mutex.withLock {
        if (running.getAndSet(true)) {
            return SyncResult(skipped = true, reason = "already_running")
        }
        try {
            withContext(Dispatchers.IO) {
                doSync()
            }
        } finally {
            running.set(false)
        }
    }

    private suspend fun doSync(): SyncResult {
        val pending = repo.getPending()
        if (pending.isEmpty()) {
            return SyncResult(ok = true, synced = 0)
        }

        val baseUrl = ServerConfig.serverUrl(context).trimEnd('/')
        val syncUrl = "$baseUrl/api/sync/batch"
        val cookie = CookieManager.getInstance().getCookie(baseUrl) ?: ""
        if (cookie.isBlank()) {
            return SyncResult(ok = false, reason = "no_session")
        }

        val deviceId = Settings.Secure.getString(context.contentResolver, Settings.Secure.ANDROID_ID) ?: ""
        val deviceName = listOf(Build.MANUFACTURER, Build.MODEL).filter { it.isNotBlank() }.joinToString(" ")

        val operations = JSONArray()
        pending.forEach { op ->
            repo.markStatus(op.clientOperationId, OfflineOperationEntity.STATUS_SYNCING)
            operations.put(repo.entityToJson(op))
        }

        val body = JSONObject().apply {
            put("device_id", deviceId)
            put("device_name", deviceName)
            put("operations", operations)
        }

        val conn = (URL(syncUrl).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 30_000
            readTimeout = 120_000
            doOutput = true
            setRequestProperty("Content-Type", "application/json; charset=utf-8")
            setRequestProperty("Accept", "application/json")
            setRequestProperty("Cookie", cookie)
            setRequestProperty("X-LF-Device-Id", deviceId)
            setRequestProperty("X-LF-Device-Name", deviceName)
            setRequestProperty("User-Agent", "LF-Android-OfflineSync/1.0")
        }

        return try {
            OutputStreamWriter(conn.outputStream, Charsets.UTF_8).use { it.write(body.toString()) }
            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            val responseText = BufferedReader(InputStreamReader(stream, Charsets.UTF_8)).use { it.readText() }
            if (code !in 200..299) {
                pending.forEach { repo.markStatus(it.clientOperationId, OfflineOperationEntity.STATUS_FAILED) }
                return SyncResult(ok = false, reason = "http_$code", detail = responseText.take(200))
            }

            val json = JSONObject(responseText)
            if (!json.optBoolean("ok", false)) {
                pending.forEach { repo.markStatus(it.clientOperationId, OfflineOperationEntity.STATUS_FAILED) }
                return SyncResult(ok = false, reason = "server_rejected")
            }

            var synced = 0
            val results = json.optJSONArray("results") ?: JSONArray()
            for (i in 0 until results.length()) {
                val res = results.optJSONObject(i) ?: continue
                val opId = res.optString("client_operation_id")
                if (res.optBoolean("ok", false) && opId.isNotBlank()) {
                    repo.deleteById(opId)
                    synced++
                } else if (opId.isNotBlank()) {
                    repo.markStatus(opId, OfflineOperationEntity.STATUS_FAILED)
                }
            }

            SyncResult(ok = true, synced = synced, failed = json.optInt("failed", 0))
        } catch (ex: Exception) {
            pending.forEach { repo.markStatus(it.clientOperationId, OfflineOperationEntity.STATUS_PENDING) }
            SyncResult(ok = false, reason = ex.javaClass.simpleName, detail = ex.message)
        } finally {
            conn.disconnect()
        }
    }

    data class SyncResult(
        val ok: Boolean = false,
        val synced: Int = 0,
        val failed: Int = 0,
        val skipped: Boolean = false,
        val reason: String? = null,
        val detail: String? = null,
    )
}
