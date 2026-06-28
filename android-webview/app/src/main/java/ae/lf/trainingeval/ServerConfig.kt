package ae.lf.trainingeval

import android.content.Context
import android.net.Uri
import java.util.Properties

object ServerConfig {
    private const val PREFS = "lf_server_prefs"
    private const val KEY_HOST = "server_host"
    private const val KEY_PORT = "server_port"
    private const val KEY_INITIALIZED = "defaults_loaded"

    const val DEFAULT_HOST = "192.168.1.100"
    const val DEFAULT_PORT = "8005"

    fun ensureDefaults(context: Context) {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        if (prefs.getBoolean(KEY_INITIALIZED, false)) return

        val props = Properties()
        runCatching {
            context.assets.open("default_server.properties").use { stream ->
                props.load(stream)
            }
        }

        val host = props.getProperty("server.host", DEFAULT_HOST).trim().ifEmpty { DEFAULT_HOST }
        val port = props.getProperty("server.port", DEFAULT_PORT).trim().ifEmpty { DEFAULT_PORT }

        prefs.edit()
            .putString(KEY_HOST, host)
            .putString(KEY_PORT, port)
            .putBoolean(KEY_INITIALIZED, true)
            .apply()
    }

    fun getHost(context: Context): String {
        ensureDefaults(context)
        return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getString(KEY_HOST, DEFAULT_HOST)
            ?.trim()
            ?.ifEmpty { DEFAULT_HOST }
            ?: DEFAULT_HOST
    }

    fun getPort(context: Context): String {
        ensureDefaults(context)
        return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getString(KEY_PORT, DEFAULT_PORT)
            ?.trim()
            ?.ifEmpty { DEFAULT_PORT }
            ?: DEFAULT_PORT
    }

    fun save(context: Context, host: String, port: String) {
        val cleanHost = host.trim()
        val cleanPort = port.trim()
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY_HOST, cleanHost.ifEmpty { DEFAULT_HOST })
            .putString(KEY_PORT, cleanPort.ifEmpty { DEFAULT_PORT })
            .putBoolean(KEY_INITIALIZED, true)
            .apply()
    }

    fun serverUrl(context: Context): String {
        return "http://${getHost(context)}:${getPort(context)}/"
    }

    fun belongsToServer(context: Context, url: String): Boolean {
        return try {
            val uri = Uri.parse(url)
            val scheme = uri.scheme?.lowercase() ?: return false
            if (scheme != "http" && scheme != "https") return false
            val host = uri.host ?: return false
            val port = when {
                uri.port > 0 -> uri.port
                scheme == "https" -> 443
                else -> 80
            }
            val expectedPort = getPort(context).toIntOrNull() ?: 8005
            host.equals(getHost(context), ignoreCase = true) && port == expectedPort
        } catch (_: Exception) {
            false
        }
    }
}
