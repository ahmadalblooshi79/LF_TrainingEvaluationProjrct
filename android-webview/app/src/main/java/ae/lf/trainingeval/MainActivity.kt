package ae.lf.trainingeval



import android.annotation.SuppressLint

import android.app.DownloadManager

import android.content.ActivityNotFoundException

import android.content.Intent

import android.graphics.Bitmap

import android.net.Uri

import android.content.Context

import android.net.ConnectivityManager

import android.net.Network

import android.net.NetworkCapabilities

import android.net.NetworkRequest

import android.os.Bundle

import android.os.Environment

import android.view.KeyEvent

import android.view.Menu

import android.view.MenuItem

import android.view.View

import android.webkit.CookieManager

import android.webkit.URLUtil

import android.webkit.WebSettings

import android.webkit.WebView

import android.widget.ProgressBar

import android.widget.TextView

import android.widget.Toast

import androidx.activity.result.contract.ActivityResultContracts

import androidx.appcompat.app.AppCompatActivity

import androidx.lifecycle.lifecycleScope

import androidx.swiperefreshlayout.widget.SwipeRefreshLayout

import ae.lf.trainingeval.cache.LfOfflineWebViewClient

import ae.lf.trainingeval.cache.OfflinePageCache

import ae.lf.trainingeval.network.ServerReachability

import com.google.android.material.appbar.MaterialToolbar



class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView

    private lateinit var swipeRefresh: SwipeRefreshLayout

    private lateinit var progressBar: ProgressBar

    private lateinit var errorPanel: View

    private lateinit var errorMessage: TextView



    private var fileChooserCallback: android.webkit.ValueCallback<Array<Uri>>? = null

    private lateinit var mediaCapture: MediaCaptureHelper

    private lateinit var appBridge: LfAppBridge

    private lateinit var pageCache: OfflinePageCache

    private var pageZoomPercent = 100

    private var networkCallback: ConnectivityManager.NetworkCallback? = null

    private var lastLoadedUrl: String? = null



    private val prefs by lazy { getSharedPreferences("lf_webview_prefs", Context.MODE_PRIVATE) }



    private val permissionLauncher = registerForActivityResult(

        ActivityResultContracts.RequestMultiplePermissions(),

    ) { grants ->

        mediaCapture.onPermissionsResult(grants)

    }



    private val fileChooserLauncher = registerForActivityResult(

        ActivityResultContracts.StartActivityForResult(),

    ) { result ->

        mediaCapture.onActivityResult(result.resultCode, result.data)

        fileChooserCallback = null

    }



    @SuppressLint("SetJavaScriptEnabled")

    override fun onCreate(savedInstanceState: Bundle?) {

        super.onCreate(savedInstanceState)

        ServerConfig.ensureDefaults(this)

        setContentView(R.layout.activity_main)



        val toolbar = findViewById<MaterialToolbar>(R.id.toolbar)

        setSupportActionBar(toolbar)



        webView = findViewById(R.id.webView)

        swipeRefresh = findViewById(R.id.swipeRefresh)

        progressBar = findViewById(R.id.progressBar)

        errorPanel = findViewById(R.id.errorPanel)

        errorMessage = findViewById(R.id.errorMessage)

        pageCache = OfflinePageCache(this)



        findViewById<View>(R.id.btnRetry).setOnClickListener { retryConnection() }

        findViewById<View>(R.id.btnOpenSettings).setOnClickListener { openSettings() }



        mediaCapture = MediaCaptureHelper(

            activity = this,

            permissionLauncher = permissionLauncher,

            onLaunchIntent = { intent -> fileChooserLauncher.launch(intent) },

        )



        appBridge = LfAppBridge(this, lifecycleScope) { result ->

            if (result.synced > 0) {

                runOnUiThread {

                    if (ServerReachability.isReachable(this, force = true)) {

                        webView.reload()

                    }

                }

            }

        }

        pageZoomPercent = prefs.getInt("page_zoom_percent", 100)

        registerNetworkMonitor()



        configureWebView()

        swipeRefresh.setOnRefreshListener {

            if (ServerReachability.isReachable(this)) {

                webView.reload()

            } else {

                reloadFromCache()

                swipeRefresh.isRefreshing = false

                Toast.makeText(this, R.string.offline_cached_page, Toast.LENGTH_SHORT).show()

            }

        }



        if (savedInstanceState != null) {

            webView.restoreState(savedInstanceState)

        } else {

            loadHome()

        }

    }



    private fun configureWebView() {

        CookieManager.getInstance().setAcceptCookie(true)

        CookieManager.getInstance().setAcceptThirdPartyCookies(webView, true)



        webView.addJavascriptInterface(appBridge, "LfAndroidBridge")



        webView.settings.apply {

            javaScriptEnabled = true

            domStorageEnabled = true

            databaseEnabled = true

            loadsImagesAutomatically = true

            useWideViewPort = true

            loadWithOverviewMode = true

            builtInZoomControls = false

            displayZoomControls = false

            setSupportZoom(true)

            textZoom = 100

            mixedContentMode = WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE

            cacheMode = WebSettings.LOAD_DEFAULT

            allowFileAccess = true

            allowContentAccess = true

            mediaPlaybackRequiresUserGesture = false

            javaScriptCanOpenWindowsAutomatically = true

            layoutAlgorithm = WebSettings.LayoutAlgorithm.TEXT_AUTOSIZING

        }



        webView.isVerticalScrollBarEnabled = true

        webView.isHorizontalScrollBarEnabled = true

        webView.overScrollMode = View.OVER_SCROLL_IF_CONTENT_SCROLLS

        webView.setDownloadListener { url, userAgent, contentDisposition, mimeType, _ ->

            downloadFile(url, userAgent, contentDisposition, mimeType)

        }



        webView.webChromeClient = LfWebChromeClient(

            onProgress = { progress ->

                if (progress in 1..99) {

                    progressBar.visibility = View.VISIBLE

                    progressBar.progress = progress

                } else {

                    progressBar.visibility = View.GONE

                }

            },

            onFileChooser = { callback, params ->

                fileChooserCallback = callback

                mediaCapture.start(params, callback)

            },

        )



        webView.webViewClient = LfOfflineWebViewClient(

            context = this,

            pageCache = pageCache,

            onPageReady = { view, url ->

                errorPanel.visibility = View.GONE

                swipeRefresh.isRefreshing = false

                progressBar.visibility = View.GONE

                lastLoadedUrl = url

                CookieManager.getInstance().flush()

                LfAppBridge.install(webView, appBridge)

                applyPageZoom(pageZoomPercent)

                injectOfflineState()

            },

            onOfflineMode = {

                runOnUiThread { injectOfflineState() }

            },

            onServerBack = {

                runOnUiThread {

                    injectServerOnline()

                }

            },

            onMainFrameCacheMiss = { url ->

                runOnUiThread {

                    showOfflineNoCache(url)

                }

            },

            onExternalUrl = { uri ->

                runCatching {

                    startActivity(Intent(Intent.ACTION_VIEW, uri))

                }.onFailure {

                    Toast.makeText(this, R.string.link_open_failed, Toast.LENGTH_SHORT).show()

                }

                true

            },

        )

    }



    private fun loadHome() {

        errorPanel.visibility = View.GONE

        val url = ServerConfig.serverUrl(this)

        lastLoadedUrl = url

        webView.loadUrl(url)

    }



    private fun retryConnection() {

        errorPanel.visibility = View.GONE

        if (ServerReachability.isReachable(this, force = true)) {

            loadHome()

            return

        }

        reloadFromCache()

    }



    private fun reloadFromCache() {

        val url = lastLoadedUrl ?: webView.url ?: ServerConfig.serverUrl(this)

        val cached = pageCache.getHtmlForLoad(url)

        if (cached != null) {

            errorPanel.visibility = View.GONE

            webView.loadDataWithBaseURL(url, cached.second, cached.first, "UTF-8", url)

            injectOfflineState()

            return

        }

        showOfflineNoCache(url)

    }



    private fun showOfflineNoCache(url: String) {

        errorMessage.text = getString(R.string.offline_no_cache, url)

        errorPanel.visibility = View.VISIBLE

    }



    private fun showConnectionError() {

        errorMessage.text = getString(R.string.connection_error, ServerConfig.serverUrl(this))

        errorPanel.visibility = View.VISIBLE

    }



    private fun downloadFile(

        url: String,

        userAgent: String,

        contentDisposition: String,

        mimeType: String,

    ) {

        val fileName = URLUtil.guessFileName(url, contentDisposition, mimeType)

        val request = DownloadManager.Request(Uri.parse(url)).apply {

            setMimeType(mimeType)

            addRequestHeader("User-Agent", userAgent)

            val cookie = CookieManager.getInstance().getCookie(url)

            if (!cookie.isNullOrBlank()) {

                addRequestHeader("Cookie", cookie)

            }

            setDescription(getString(R.string.download_started))

            setTitle(fileName)

            setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)

            setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, fileName)

            setAllowedOverMetered(true)

            setAllowedOverRoaming(true)

        }



        val manager = getSystemService(DOWNLOAD_SERVICE) as DownloadManager

        runCatching { manager.enqueue(request) }

            .onSuccess {

                Toast.makeText(this, R.string.download_started, Toast.LENGTH_SHORT).show()

            }

            .onFailure {

                Toast.makeText(this, R.string.download_failed, Toast.LENGTH_SHORT).show()

            }

    }



    private fun openSettings() {

        startActivity(Intent(this, SettingsActivity::class.java))

    }



    override fun onResume() {

        super.onResume()

        webView.onResume()

        CookieManager.getInstance().flush()

        if (ServerReachability.isReachable(this, force = true)) {

            injectServerOnline()

        } else {

            injectOfflineState()

        }

    }



    override fun onNewIntent(intent: Intent) {

        super.onNewIntent(intent)

        if (intent.getBooleanExtra(SettingsActivity.EXTRA_RELOAD, false)) {

            loadHome()

        }

    }



    override fun onPause() {

        webView.onPause()

        CookieManager.getInstance().flush()

        super.onPause()

    }



    override fun onDestroy() {

        val cm = getSystemService(CONNECTIVITY_SERVICE) as ConnectivityManager

        networkCallback?.let { runCatching { cm.unregisterNetworkCallback(it) } }

        networkCallback = null

        super.onDestroy()

    }



    override fun onSaveInstanceState(outState: Bundle) {

        super.onSaveInstanceState(outState)

        webView.saveState(outState)

    }



    override fun onCreateOptionsMenu(menu: Menu): Boolean {

        menuInflater.inflate(R.menu.main_menu, menu)

        return true

    }



    override fun onOptionsItemSelected(item: MenuItem): Boolean {

        return when (item.itemId) {

            R.id.action_reload -> {

                if (ServerReachability.isReachable(this)) {

                    webView.reload()

                } else {

                    reloadFromCache()

                }

                true

            }

            R.id.action_settings -> {

                openSettings()

                true

            }

            R.id.action_zoom_in -> {

                applyPageZoom(pageZoomPercent + 10)

                true

            }

            R.id.action_zoom_out -> {

                applyPageZoom(pageZoomPercent - 10)

                true

            }

            R.id.action_zoom_reset -> {

                applyPageZoom(100)

                true

            }

            else -> super.onOptionsItemSelected(item)

        }

    }



    override fun onKeyDown(keyCode: Int, event: KeyEvent?): Boolean {

        if (keyCode == KeyEvent.KEYCODE_BACK && webView.canGoBack()) {

            webView.goBack()

            return true

        }

        return super.onKeyDown(keyCode, event)

    }



    private fun isNetworkAvailable(): Boolean {

        val cm = getSystemService(CONNECTIVITY_SERVICE) as ConnectivityManager

        val network = cm.activeNetwork ?: return false

        val caps = cm.getNetworkCapabilities(network) ?: return false

        return caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)

    }



    private fun applyPageZoom(percent: Int) {

        pageZoomPercent = percent.coerceIn(70, 200)

        prefs.edit().putInt("page_zoom_percent", pageZoomPercent).apply()

        val scale = pageZoomPercent / 100.0

        webView.evaluateJavascript(

            "document.documentElement.style.zoom='$scale';",

            null,

        )

    }



    private fun triggerOfflineSync() {

        if (!ServerReachability.isReachable(this)) return

        webView.evaluateJavascript(

            "(window.LFOfflineSync&&window.LFOfflineSync.flush&&window.LFOfflineSync.flush());",

            null,

        )

        OfflineSyncWorker.syncNow(this)

    }



    private fun injectOfflineState() {

        webView.evaluateJavascript(

            """

            (function(){

              window.dispatchEvent(new Event('lf-server-offline'));

              if (window.LFOfflineSync && window.LFOfflineSync.showOfflineBanner) {

                window.LFOfflineSync.showOfflineBanner();

              }

            })();

            """.trimIndent(),

            null,

        )

    }



    private fun injectServerOnline() {

        webView.evaluateJavascript(

            """

            (function(){

              window.dispatchEvent(new Event('lf-server-online'));

              if (window.LFOfflineSync && window.LFOfflineSync.hideOfflineBanner) {

                window.LFOfflineSync.hideOfflineBanner();

              }

            })();

            """.trimIndent(),

            null,

        )

    }



    private fun registerNetworkMonitor() {

        val cm = getSystemService(CONNECTIVITY_SERVICE) as ConnectivityManager

        val request = NetworkRequest.Builder()

            .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)

            .build()

        val callback = object : ConnectivityManager.NetworkCallback() {

            override fun onAvailable(network: Network) {

                runOnUiThread {

                    if (ServerReachability.isReachable(this@MainActivity, force = true)) {

                        ServerReachability.markReachable()

                        injectServerOnline()

                    }

                }

            }



            override fun onLost(network: Network) {

                runOnUiThread {

                    if (!isNetworkAvailable()) {

                        ServerReachability.markUnreachable()

                        injectOfflineState()

                    }

                }

            }

        }

        networkCallback = callback

        cm.registerNetworkCallback(request, callback)

    }

}


