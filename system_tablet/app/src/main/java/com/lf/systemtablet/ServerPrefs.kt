package com.lf.systemtablet

import android.content.Context
import android.content.SharedPreferences

class ServerPrefs(context: Context) {
    private val prefs: SharedPreferences =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    var host: String
        get() = prefs.getString(KEY_HOST, BuildConfig.DEFAULT_HOST) ?: BuildConfig.DEFAULT_HOST
        set(value) = prefs.edit().putString(KEY_HOST, value.trim()).apply()

    var port: Int
        get() = prefs.getInt(KEY_PORT, BuildConfig.DEFAULT_PORT)
        set(value) = prefs.edit().putInt(KEY_PORT, value).apply()

    var displayId: String
        get() = prefs.getString(KEY_DISPLAY, "default") ?: "default"
        set(value) = prefs.edit().putString(KEY_DISPLAY, value.trim().ifEmpty { "default" }).apply()

    var deviceId: String
        get() {
            val existing = prefs.getString(KEY_DEVICE, null)
            if (!existing.isNullOrBlank()) return existing
            val id = java.util.UUID.randomUUID().toString()
            prefs.edit().putString(KEY_DEVICE, id).apply()
            return id
        }
        private set(_) {}

    var configured: Boolean
        get() = prefs.getBoolean(KEY_CONFIGURED, false)
        set(value) = prefs.edit().putBoolean(KEY_CONFIGURED, value).apply()

    fun baseUrl(): String {
        val h = host.trim().trimEnd('/')
        return "http://$h:$port"
    }

    companion object {
        private const val PREFS = "lf_system_tablet"
        private const val KEY_HOST = "host"
        private const val KEY_PORT = "port"
        private const val KEY_DISPLAY = "display_id"
        private const val KEY_DEVICE = "device_id"
        private const val KEY_CONFIGURED = "configured"
    }
}
