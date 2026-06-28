package ae.lf.trainingeval.cache

import ae.lf.trainingeval.network.ServerReachability
import android.content.Context
import android.graphics.Bitmap
import android.net.Uri
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient

class LfOfflineWebViewClient(
    private val context: Context,
    private val pageCache: OfflinePageCache,
    private val onPageReady: (WebView, String?) -> Unit,
    private val onOfflineMode: () -> Unit,
    private val onServerBack: () -> Unit,
    private val onMainFrameCacheMiss: (String) -> Unit,
    private val onExternalUrl: (Uri) -> Boolean,
) : WebViewClient() {
    private var wasOffline = false

    override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
        // لا شيء — نتجنب صفحة خطأ Chrome الافتراضية عبر onReceivedError
    }

    override fun onPageFinished(view: WebView, url: String?) {
        val serverUp = ServerReachability.isReachable(context)
        if (!serverUp) {
            onOfflineMode()
            wasOffline = true
        } else if (wasOffline) {
            wasOffline = false
            onServerBack()
        }
        onPageReady(view, url)
    }

    override fun shouldInterceptRequest(
        view: WebView,
        request: WebResourceRequest,
    ): android.webkit.WebResourceResponse? {
        if (request.method != "GET") return null
        val url = request.url?.toString() ?: return null
        if (!pageCache.shouldCacheUrl(url)) return null

        val serverUp = ServerReachability.isReachable(context)
        if (!serverUp) {
            return pageCache.getWebResourceResponse(url)
        }

        return pageCache.putFromNetwork(url, request)
    }

    override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
        val uri = request.url ?: return false
        val scheme = uri.scheme?.lowercase() ?: return false
        if (scheme == "http" || scheme == "https") return false
        return onExternalUrl(uri)
    }

    override fun onReceivedError(
        view: WebView,
        request: WebResourceRequest,
        error: WebResourceError,
    ) {
        if (!request.isForMainFrame) return
        val url = request.url?.toString() ?: return
        ServerReachability.markUnreachable()

        val cached = pageCache.getHtmlForLoad(url)
        if (cached != null) {
            view.stopLoading()
            view.loadDataWithBaseURL(url, cached.second, cached.first, "UTF-8", url)
            onOfflineMode()
            return
        }

        if (pageCache.getWebResourceResponse(url) != null) {
            view.stopLoading()
            onOfflineMode()
            return
        }

        onMainFrameCacheMiss(url)
    }
}
