package ae.lf.trainingeval

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebView

object FileChooserResultParser {
    fun parse(resultCode: Int, data: Intent?): Array<Uri>? {
        if (resultCode != Activity.RESULT_OK) return null
        val uri = data?.data
        if (uri != null) return arrayOf(uri)
        val clip = data?.clipData ?: return null
        return Array(clip.itemCount) { index -> clip.getItemAt(index).uri }
    }
}

class LfWebChromeClient(
    private val onProgress: (Int) -> Unit,
    private val onFileChooser: (ValueCallback<Array<Uri>>, FileChooserParams?) -> Unit,
) : WebChromeClient() {

    override fun onProgressChanged(view: WebView?, newProgress: Int) {
        onProgress(newProgress)
    }

    override fun onShowFileChooser(
        webView: WebView?,
        filePathCallback: ValueCallback<Array<Uri>>?,
        fileChooserParams: FileChooserParams?,
    ): Boolean {
        if (filePathCallback == null) return false
        onFileChooser(filePathCallback, fileChooserParams)
        return true
    }
}
