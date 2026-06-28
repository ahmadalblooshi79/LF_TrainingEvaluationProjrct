package ae.lf.trainingeval.cache

import ae.lf.trainingeval.ServerConfig
import ae.lf.trainingeval.data.CachedPageEntity
import ae.lf.trainingeval.data.LfOfflineDatabase
import android.content.Context
import android.webkit.CookieManager
import android.webkit.MimeTypeMap
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import kotlinx.coroutines.runBlocking
import java.io.ByteArrayInputStream
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import java.util.Locale
import java.util.zip.GZIPInputStream

class OfflinePageCache(private val context: Context) {
    private val dao = LfOfflineDatabase.get(context).cachedPageDao()
    private val cacheDir = File(context.cacheDir, "lf_offline_pages").apply { mkdirs() }

    companion object {
        private const val MAX_ENTRIES = 800
        private val SKIP_REQUEST_HEADERS = setOf(
            "if-none-match",
            "if-modified-since",
            "host",
            "connection",
            "content-length",
        )
    }

    fun urlKey(url: String): String {
        val digest = MessageDigest.getInstance("SHA-256")
        val hash = digest.digest(url.trim().toByteArray(Charsets.UTF_8))
        return hash.joinToString("") { "%02x".format(it) }
    }

    fun getBlocking(url: String): CachedPageEntity? = runBlocking {
        dao.getByUrl(url) ?: dao.getByKey(urlKey(url))
    }

    fun getWebResourceResponse(url: String): WebResourceResponse? {
        val entity = getBlocking(url) ?: return null
        val file = File(cacheDir, entity.bodyFile)
        if (!file.isFile) return null
        val stream = ByteArrayInputStream(file.readBytes())
        return WebResourceResponse(
            entity.mimeType,
            entity.encoding,
            entity.statusCode,
            "OK",
            emptyMap(),
            stream,
        )
    }

    fun getHtmlForLoad(url: String): Pair<String, String>? {
        val entity = getBlocking(url) ?: return null
        val file = File(cacheDir, entity.bodyFile)
        if (!file.isFile) return null
        val mime = entity.mimeType.lowercase(Locale.US)
        if (!mime.contains("html") && !mime.contains("text")) return null
        return entity.mimeType to file.readText(Charsets.UTF_8)
    }

    fun putFromNetwork(url: String, request: WebResourceRequest? = null): WebResourceResponse? {
        if (!ServerConfig.belongsToServer(context, url)) return null
        return try {
            val fetched = fetch(url, request?.requestHeaders ?: emptyMap())
            store(url, fetched.mimeType, fetched.encoding, fetched.statusCode, fetched.body)
            WebResourceResponse(
                fetched.mimeType,
                fetched.encoding,
                fetched.statusCode,
                "OK",
                fetched.headers,
                ByteArrayInputStream(fetched.body),
            )
        } catch (_: Exception) {
            getWebResourceResponse(url)
        }
    }

    private fun store(url: String, mimeType: String, encoding: String, statusCode: Int, body: ByteArray) {
        val key = urlKey(url)
        val fileName = "$key.bin"
        val file = File(cacheDir, fileName)
        file.writeBytes(body)
        runBlocking {
            dao.upsert(
                CachedPageEntity(
                    urlKey = key,
                    url = url,
                    mimeType = mimeType,
                    encoding = encoding,
                    statusCode = statusCode,
                    bodyFile = fileName,
                    bodySize = body.size.toLong(),
                ),
            )
            trimIfNeeded()
        }
    }

    private suspend fun trimIfNeeded() {
        val count = dao.count()
        if (count <= MAX_ENTRIES) return
        val removeCount = count - MAX_ENTRIES + 50
        val oldest = dao.oldest(removeCount)
        for (item in oldest) {
            File(cacheDir, item.bodyFile).delete()
            dao.deleteByKey(item.urlKey)
        }
    }

    private data class Fetched(
        val mimeType: String,
        val encoding: String,
        val statusCode: Int,
        val body: ByteArray,
        val headers: Map<String, String>,
    )

    private fun fetch(url: String, extraHeaders: Map<String, String>): Fetched {
        val conn = (URL(url).openConnection() as HttpURLConnection).apply {
            connectTimeout = 12_000
            readTimeout = 45_000
            instanceFollowRedirects = true
            setRequestProperty("Accept", "*/*")
            setRequestProperty("Accept-Language", "ar,en;q=0.9")
            val cookie = CookieManager.getInstance().getCookie(url)
            if (!cookie.isNullOrBlank()) {
                setRequestProperty("Cookie", cookie)
            }
            extraHeaders.forEach { (k, v) ->
                val lower = k.lowercase(Locale.US)
                if (lower in SKIP_REQUEST_HEADERS) return@forEach
                setRequestProperty(k, v)
            }
        }
        try {
            conn.connect()
            val status = conn.responseCode
            val stream = if (status in 200..299) conn.inputStream else conn.errorStream
            val encoding = conn.contentEncoding?.lowercase(Locale.US).orEmpty()
            val raw = stream?.readBytes() ?: ByteArray(0)
            val body = if (encoding == "gzip") {
                java.io.ByteArrayInputStream(raw).use { input ->
                    GZIPInputStream(input).use { it.readBytes() }
                }
            } else {
                raw
            }
            val mime = conn.contentType?.substringBefore(";")?.trim()
                ?: guessMime(url)
            val charset = conn.contentType?.substringAfter("charset=", "")?.trim()
                ?.ifBlank { null } ?: "UTF-8"
            return Fetched(
                mimeType = mime,
                encoding = charset,
                statusCode = status,
                body = body,
                headers = emptyMap(),
            )
        } finally {
            conn.disconnect()
        }
    }

    private fun guessMime(url: String): String {
        val ext = url.substringAfterLast('.', "").lowercase(Locale.US)
        if (ext.isBlank() || ext.contains("/") || ext.contains("?")) {
            return "text/html"
        }
        return MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext) ?: "application/octet-stream"
    }

    fun shouldCacheUrl(url: String): Boolean {
        if (!ServerConfig.belongsToServer(context, url)) return false
        val lower = url.lowercase(Locale.US)
        if (lower.startsWith("ws:") || lower.startsWith("wss:")) return false
        return true
    }
}
