package ae.lf.trainingeval.network

import ae.lf.trainingeval.ServerConfig
import android.content.Context
import java.net.HttpURLConnection
import java.net.InetSocketAddress
import java.net.Socket
import java.net.URL

object ServerReachability {
    private const val CACHE_TTL_MS = 2500L

    @Volatile
    private var lastCheckAt = 0L

    @Volatile
    private var lastReachable = false

    fun isReachable(context: Context, force: Boolean = false): Boolean {
        val now = System.currentTimeMillis()
        if (!force && now - lastCheckAt < CACHE_TTL_MS) {
            return lastReachable
        }
        val host = ServerConfig.getHost(context)
        val port = ServerConfig.getPort(context).toIntOrNull() ?: 8005
        val tcpOk = try {
            Socket().use { socket ->
                socket.connect(InetSocketAddress(host, port), 2000)
            }
            true
        } catch (_: Exception) {
            false
        }
        if (!tcpOk) {
            lastReachable = false
            lastCheckAt = now
            return false
        }
        val httpOk = try {
            val url = URL("http://$host:$port/")
            val conn = (url.openConnection() as HttpURLConnection).apply {
                connectTimeout = 2500
                readTimeout = 2500
                requestMethod = "HEAD"
                instanceFollowRedirects = true
            }
            val code = conn.responseCode
            conn.disconnect()
            code in 200..499
        } catch (_: Exception) {
            true
        }
        lastReachable = httpOk
        lastCheckAt = now
        return lastReachable
    }

    fun markUnreachable() {
        lastReachable = false
        lastCheckAt = System.currentTimeMillis()
    }

    fun markReachable() {
        lastReachable = true
        lastCheckAt = System.currentTimeMillis()
    }
}
