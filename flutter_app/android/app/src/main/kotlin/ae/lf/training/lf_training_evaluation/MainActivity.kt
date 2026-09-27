package ae.lf.training.lf_training_evaluation

import android.app.Activity
import android.content.Intent
import android.os.Build
import android.os.StatFs
import android.provider.DocumentsContract
import android.provider.MediaStore
import android.provider.OpenableColumns
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.io.File
import java.io.FileInputStream

class MainActivity : FlutterActivity() {
    private val storageChannelName = "lf.training/storage"
    private val recoveryChannelName = "lf.training/recovery_export"
    private val requestCreateZip = 0x4C46

    private var pendingSaveResult: MethodChannel.Result? = null
    private var pendingSourcePath: String? = null
    private var pendingSuggestedName: String? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, storageChannelName)
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    "getFreeSpace" -> {
                        try {
                            val path = filesDir.absolutePath
                            val stat = StatFs(path)
                            result.success(stat.availableBytes)
                        } catch (e: Exception) {
                            result.error("storage", e.message, null)
                        }
                    }
                    else -> result.notImplemented()
                }
            }
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, recoveryChannelName)
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    "saveZipCopy" -> {
                        val sourcePath = call.argument<String>("sourcePath") ?: ""
                        val suggestedName = call.argument<String>("suggestedName") ?: "recovery.zip"
                        if (sourcePath.isEmpty() || !File(sourcePath).isFile) {
                            result.error("missing_source", "private zip not found", null)
                            return@setMethodCallHandler
                        }
                        if (pendingSaveResult != null) {
                            result.error("busy", "a save is already in progress", null)
                            return@setMethodCallHandler
                        }
                        pendingSaveResult = result
                        pendingSourcePath = sourcePath
                        pendingSuggestedName = suggestedName
                        val intent = Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
                            addCategory(Intent.CATEGORY_OPENABLE)
                            type = "application/zip"
                            putExtra(Intent.EXTRA_TITLE, suggestedName)
                            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                                putExtra(
                                    DocumentsContract.EXTRA_INITIAL_URI,
                                    MediaStore.Downloads.EXTERNAL_CONTENT_URI,
                                )
                            }
                        }
                        startActivityForResult(intent, requestCreateZip)
                    }
                    else -> result.notImplemented()
                }
            }
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        if (requestCode != requestCreateZip) {
            super.onActivityResult(requestCode, resultCode, data)
            return
        }
        val reply = pendingSaveResult
        val sourcePath = pendingSourcePath
        val suggestedName = pendingSuggestedName
        pendingSaveResult = null
        pendingSourcePath = null
        pendingSuggestedName = null
        if (reply == null) return
        if (resultCode != Activity.RESULT_OK || data?.data == null || sourcePath.isNullOrEmpty()) {
            reply.success(null)
            return
        }
        val uri = data.data!!
        try {
            contentResolver.openOutputStream(uri, "w")?.use { output ->
                FileInputStream(File(sourcePath)).use { input ->
                    input.copyTo(output)
                }
                output.flush()
            } ?: run {
                reply.error("write_failed", "could not open destination", null)
                return
            }
            val displayName = queryDisplayName(uri) ?: suggestedName ?: File(sourcePath).name
            reply.success(
                hashMapOf(
                    "uri" to uri.toString(),
                    "name" to displayName,
                ),
            )
        } catch (e: Exception) {
            reply.error("copy_failed", e.message, null)
        }
    }

    private fun queryDisplayName(uri: android.net.Uri): String? {
        return try {
            contentResolver.query(
                uri,
                arrayOf(OpenableColumns.DISPLAY_NAME),
                null,
                null,
                null,
            )?.use { cursor ->
                if (cursor.moveToFirst()) {
                    val idx = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                    if (idx >= 0) cursor.getString(idx) else null
                } else {
                    null
                }
            }
        } catch (_: Exception) {
            null
        }
    }
}
