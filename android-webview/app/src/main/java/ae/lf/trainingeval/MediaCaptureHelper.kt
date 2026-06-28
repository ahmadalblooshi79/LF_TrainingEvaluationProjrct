package ae.lf.trainingeval

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.provider.MediaStore
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import androidx.activity.result.ActivityResultLauncher
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import java.io.File

class MediaCaptureHelper(
    private val activity: AppCompatActivity,
    private val permissionLauncher: ActivityResultLauncher<Array<String>>,
    private val onLaunchIntent: (Intent) -> Unit,
) {
    private var callback: ValueCallback<Array<Uri>>? = null
    private var photoOutputUri: Uri? = null
    private var mode: Int = MODE_FILE
    private var fileChooserParams: WebChromeClient.FileChooserParams? = null

    fun start(params: WebChromeClient.FileChooserParams?, cb: ValueCallback<Array<Uri>>) {
        callback?.onReceiveValue(null)
        callback = cb
        photoOutputUri = null
        fileChooserParams = params

        val acceptTypes = params?.acceptTypes
            ?.map { it.lowercase().trim() }
            ?.filter { it.isNotBlank() }
            ?: emptyList()
        val capture = params?.isCaptureEnabled == true
        val wantsVideo = acceptTypes.any { it.startsWith("video/") }
        val wantsImage = acceptTypes.isEmpty() || acceptTypes.any { it.startsWith("image/") }

        mode = when {
            wantsVideo && !wantsImage -> MODE_VIDEO
            wantsImage && !wantsVideo -> MODE_PHOTO
            capture && wantsVideo -> MODE_VIDEO
            capture -> MODE_PHOTO
            else -> MODE_FILE
        }

        val perms = requiredPermissions()
        if (perms.isEmpty() || perms.all { granted(it) }) {
            launchIntent()
            return
        }
        permissionLauncher.launch(perms)
    }

    fun onPermissionsResult(grants: Map<String, Boolean>) {
        if (grants.values.all { it }) {
            launchIntent()
        } else {
            finish(null)
        }
    }

    fun onActivityResult(resultCode: Int, data: Intent?) {
        val uris = when {
            resultCode != Activity.RESULT_OK -> null
            mode == MODE_PHOTO && photoOutputUri != null -> arrayOf(photoOutputUri!!)
            mode == MODE_VIDEO -> {
                val uri = data?.data
                if (uri != null) arrayOf(uri) else FileChooserResultParser.parse(resultCode, data)
            }
            else -> FileChooserResultParser.parse(resultCode, data)
        }
        finish(uris)
    }

    fun cancel() {
        finish(null)
    }

    private fun launchIntent() {
        val intent = buildIntent() ?: run {
            finish(null)
            return
        }
        if (intent.resolveActivity(activity.packageManager) == null) {
            finish(null)
            return
        }
        onLaunchIntent(intent)
    }

    private fun buildIntent(): Intent? = when (mode) {
        MODE_PHOTO -> {
            val uri = createPhotoUri()
            photoOutputUri = uri
            Intent(MediaStore.ACTION_IMAGE_CAPTURE).apply {
                putExtra(MediaStore.EXTRA_OUTPUT, uri)
                addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION or Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
        }
        MODE_VIDEO -> Intent(MediaStore.ACTION_VIDEO_CAPTURE).apply {
            putExtra(MediaStore.EXTRA_VIDEO_QUALITY, 1)
        }
        else -> {
            val fromWebView = fileChooserParams?.createIntent()
            fromWebView ?: Intent(Intent.ACTION_GET_CONTENT).apply {
                addCategory(Intent.CATEGORY_OPENABLE)
                type = "*/*"
            }
        }
    }

    private fun createPhotoUri(): Uri {
        val dir = File(activity.cacheDir, "camera").apply { mkdirs() }
        val file = File(dir, "capture_${System.currentTimeMillis()}.jpg")
        return FileProvider.getUriForFile(
            activity,
            "${activity.packageName}.fileprovider",
            file,
        )
    }

    private fun requiredPermissions(): Array<String> = when (mode) {
        MODE_PHOTO -> arrayOf(Manifest.permission.CAMERA)
        MODE_VIDEO -> arrayOf(Manifest.permission.CAMERA, Manifest.permission.RECORD_AUDIO)
        else -> emptyArray()
    }

    private fun granted(permission: String): Boolean {
        return ContextCompat.checkSelfPermission(activity, permission) == PackageManager.PERMISSION_GRANTED
    }

    private fun finish(uris: Array<Uri>?) {
        callback?.onReceiveValue(uris)
        callback = null
        photoOutputUri = null
        fileChooserParams = null
        mode = MODE_FILE
    }

    companion object {
        const val MODE_FILE = 0
        const val MODE_PHOTO = 1
        const val MODE_VIDEO = 2
    }
}
