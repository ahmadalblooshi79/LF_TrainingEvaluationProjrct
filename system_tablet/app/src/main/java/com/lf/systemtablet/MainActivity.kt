package com.lf.systemtablet

import android.annotation.SuppressLint
import android.content.Intent
import android.graphics.Bitmap
import android.os.Bundle
import android.view.View
import android.webkit.CookieManager
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.lf.systemtablet.databinding.ActivityMainBinding
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private lateinit var prefs: ServerPrefs

    private var remoteEnabled = false
    private var sessionToken: String? = null
    private var sessionLocked = false

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = ServerPrefs(this)
        if (!prefs.configured) {
            startActivity(Intent(this, SettingsActivity::class.java))
            finish()
            return
        }

        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        setupWebView()
        setupToolbar()
        loadSystem()
    }

    private fun setupToolbar() {
        binding.btnSettings.setOnClickListener {
            promptSettingsPin()
        }
        binding.btnResetZoom.setOnClickListener {
            binding.webView.resetZoom()
        }
        binding.btnRemoteToggle.setOnClickListener {
            if (remoteEnabled) stopRemote() else startRemote()
        }
        binding.btnRemoteMore.setOnClickListener { showRemoteMenu() }
        updateModeUi()
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun setupWebView() {
        val wv = binding.webView
        CookieManager.getInstance().setAcceptCookie(true)
        CookieManager.getInstance().setAcceptThirdPartyCookies(wv, true)

        wv.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            databaseEnabled = true
            allowFileAccess = false
            mixedContentMode = WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE
            cacheMode = WebSettings.LOAD_DEFAULT
            userAgentString = "$userAgentString LFSystemTablet/1.0"
            mediaPlaybackRequiresUserGesture = false
            setSupportMultipleWindows(false)
        }

        wv.addJavascriptInterface(JsBridge(), "LFSystemTabletBridge")

        wv.webChromeClient = object : WebChromeClient() {
            override fun onProgressChanged(view: WebView?, newProgress: Int) {
                binding.progress.visibility = if (newProgress in 1..99) View.VISIBLE else View.GONE
                binding.progress.progress = newProgress
            }
        }

        wv.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                val url = request?.url?.toString().orEmpty()
                // ابقَ داخل التطبيق — لا تفتح متصفحاً خارجياً
                return if (url.startsWith(prefs.baseUrl()) || url.startsWith("/")) {
                    false
                } else {
                    true
                }
            }

            override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
                binding.progress.visibility = View.VISIBLE
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                binding.progress.visibility = View.GONE
                injectBridge(url.orEmpty())
            }
        }

        // لا مزامنة تكبير إلى شاشة العرض — كانت تسبب وميض scale عشوائي
    }

    private fun injectBridge(url: String) {
        val enableRc = if (remoteEnabled && sessionToken != null) {
            "window.LFRemoteControl && window.LFRemoteControl.enable(${JSONObject.quote(sessionToken)}, ${JSONObject.quote(prefs.displayId)});"
        } else ""
        val js = """
            (function(){
              document.documentElement.classList.add('lf-system-tablet');
              $enableRc
            })();
        """.trimIndent()
        binding.webView.evaluateJavascript(js, null)
        if (remoteEnabled) {
            val path = url.removePrefix(prefs.baseUrl()).ifEmpty { "/" }
            postCommand("navigate", path, emptyMap())
        }
    }

    private fun loadSystem() {
        binding.webView.loadUrl(prefs.baseUrl() + "/")
    }

    private fun promptSettingsPin() {
        val input = android.widget.EditText(this).apply {
            inputType = android.text.InputType.TYPE_CLASS_NUMBER or
                android.text.InputType.TYPE_NUMBER_VARIATION_PASSWORD
            hint = "PIN"
        }
        AlertDialog.Builder(this)
            .setTitle("إعدادات محمية")
            .setMessage("أدخل رمز الحماية لتغيير عنوان السيرفر")
            .setView(input)
            .setPositiveButton("دخول") { _, _ ->
                if (input.text.toString() == BuildConfig.SETTINGS_PIN) {
                    startActivity(Intent(this, SettingsActivity::class.java))
                } else {
                    Toast.makeText(this, "رمز غير صحيح", Toast.LENGTH_SHORT).show()
                }
            }
            .setNegativeButton("إلغاء", null)
            .show()
    }

    private fun showRemoteMenu() {
        val items = arrayOf(
            getString(R.string.choose_display),
            if (sessionLocked) getString(R.string.remote_unlock) else getString(R.string.remote_lock),
            getString(R.string.remote_end),
            "فتح شاشة العرض على الكمبيوتر (تعليمات)",
        )
        AlertDialog.Builder(this)
            .setTitle(getString(R.string.mode_remote))
            .setItems(items) { _, which ->
                when (which) {
                    0 -> chooseDisplay()
                    1 -> toggleLock()
                    2 -> endSession()
                    3 -> AlertDialog.Builder(this)
                        .setTitle("شاشة العرض")
                        .setMessage(
                            "على جهاز الكمبيوتر/البروجيكتور افتح:\n\n" +
                                "${prefs.baseUrl()}/presentation/live?display_id=${prefs.displayId}\n\n" +
                                "ثم ابدأ التحكم المباشر من هذا التابلت.",
                        )
                        .setPositiveButton("حسناً", null)
                        .show()
                }
            }
            .show()
    }

    private fun chooseDisplay() {
        val input = android.widget.EditText(this).apply {
            setText(prefs.displayId)
            hint = "default"
        }
        AlertDialog.Builder(this)
            .setTitle(getString(R.string.choose_display))
            .setView(input)
            .setPositiveButton("حفظ") { _, _ ->
                prefs.displayId = input.text.toString().ifBlank { "default" }
                Toast.makeText(this, "شاشة العرض: ${prefs.displayId}", Toast.LENGTH_SHORT).show()
            }
            .setNegativeButton("إلغاء", null)
            .show()
    }

    private fun startRemote() {
        lifecycleScope.launch {
            val result = withContext(Dispatchers.IO) {
                apiPost(
                    "/api/remote-control/session/start",
                    JSONObject()
                        .put("display_id", prefs.displayId)
                        .put("device_id", prefs.deviceId)
                        .put("device_label", "System Tablet ${android.os.Build.MODEL}"),
                )
            }
            if (result == null) {
                Toast.makeText(this@MainActivity, "تعذر الاتصال بالسيرفر", Toast.LENGTH_LONG).show()
                return@launch
            }
            if (!result.optBoolean("ok")) {
                val msg = result.optString("message").ifBlank {
                    when (result.optString("error")) {
                        "forbidden" -> "غير مخوّل بتفعيل التحكم المباشر"
                        "login_required" -> "سجّل الدخول في النظام أولاً"
                        "display_busy" -> "الشاشة مشغولة بجهاز آخر"
                        "display_locked" -> "الشاشة مقفلة"
                        else -> "فشل بدء التحكم"
                    }
                }
                Toast.makeText(this@MainActivity, msg, Toast.LENGTH_LONG).show()
                return@launch
            }
            sessionToken = result.optString("session_token")
            remoteEnabled = true
            sessionLocked = false
            updateModeUi()
            injectBridge(binding.webView.url.orEmpty())
            Toast.makeText(this@MainActivity, "تم تفعيل التحكم المباشر", Toast.LENGTH_SHORT).show()
        }
    }

    private fun stopRemote() {
        lifecycleScope.launch {
            withContext(Dispatchers.IO) {
                apiPost(
                    "/api/remote-control/session/stop",
                    JSONObject().put("session_token", sessionToken ?: ""),
                )
            }
            remoteEnabled = false
            sessionToken = null
            sessionLocked = false
            binding.webView.evaluateJavascript(
                "window.LFRemoteControl && window.LFRemoteControl.disable();",
                null,
            )
            updateModeUi()
            Toast.makeText(this@MainActivity, "تم إيقاف التحكم المباشر", Toast.LENGTH_SHORT).show()
        }
    }

    private fun toggleLock() {
        if (!remoteEnabled || sessionToken == null) {
            Toast.makeText(this, "ابدأ التحكم أولاً", Toast.LENGTH_SHORT).show()
            return
        }
        val lock = !sessionLocked
        lifecycleScope.launch {
            val result = withContext(Dispatchers.IO) {
                apiPost(
                    "/api/remote-control/session/lock",
                    JSONObject().put("session_token", sessionToken).put("locked", lock),
                )
            }
            if (result?.optBoolean("ok") == true) {
                sessionLocked = lock
                Toast.makeText(
                    this@MainActivity,
                    if (lock) "تم قفل الجلسة" else "تم فتح القفل",
                    Toast.LENGTH_SHORT,
                ).show()
            }
        }
    }

    private fun endSession() {
        stopRemote()
    }

    private fun updateModeUi() {
        if (remoteEnabled) {
            binding.modeLabel.text = getString(R.string.mode_remote)
            binding.btnRemoteToggle.text = getString(R.string.remote_stop)
        } else {
            binding.modeLabel.text = getString(R.string.mode_normal)
            binding.btnRemoteToggle.text = getString(R.string.remote_start)
        }
    }

    private fun postCommand(type: String, path: String, payload: Map<String, Any>) {
        val token = sessionToken ?: return
        lifecycleScope.launch(Dispatchers.IO) {
            val body = JSONObject()
                .put("session_token", token)
                .put("type", type)
                .put("path", path)
                .put("payload", JSONObject(payload))
            apiPost("/api/remote-control/command", body)
        }
    }

    private fun apiPost(path: String, body: JSONObject): JSONObject? {
        return try {
            val url = URL(prefs.baseUrl() + path)
            val conn = (url.openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = 8000
                readTimeout = 8000
                doOutput = true
                setRequestProperty("Content-Type", "application/json; charset=utf-8")
                // أرسل كوكيز الجلسة من WebView إن وُجدت
                val cookies = CookieManager.getInstance().getCookie(prefs.baseUrl())
                if (!cookies.isNullOrBlank()) {
                    setRequestProperty("Cookie", cookies)
                }
            }
            OutputStreamWriter(conn.outputStream, Charsets.UTF_8).use { it.write(body.toString()) }
            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            val text = stream?.bufferedReader()?.readText().orEmpty()
            if (text.isBlank()) JSONObject().put("ok", code in 200..299) else JSONObject(text)
        } catch (_: Exception) {
            null
        }
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (binding.webView.canGoBack()) {
            binding.webView.goBack()
        } else {
            @Suppress("DEPRECATION")
            super.onBackPressed()
        }
    }

    inner class JsBridge {
        @JavascriptInterface
        fun onNavigate(path: String) {
            if (remoteEnabled) postCommand("navigate", path, emptyMap())
        }

        @JavascriptInterface
        fun onPageReady(path: String) {
            // no-op — الحقن يتم من onPageFinished
        }

        @JavascriptInterface
        fun onRemoteCommand(json: String) {
            // الأوامر تُرسل أصلاً من JS عبر fetch بنفس الكوكيز
        }
    }
}
