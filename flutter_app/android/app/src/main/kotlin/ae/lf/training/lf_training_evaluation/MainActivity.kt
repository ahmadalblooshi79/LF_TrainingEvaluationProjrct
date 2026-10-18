package ae.lf.training.lf_training_evaluation

import android.app.Activity
import android.content.ContentValues
import android.content.Intent
import android.media.MediaScannerConnection
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.os.StatFs
import android.provider.DocumentsContract
import android.provider.MediaStore
import android.provider.OpenableColumns
import android.util.Log
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream

class MainActivity : FlutterActivity() {
    private val storageChannelName = "lf.training/storage"
    private val recoveryChannelName = "lf.training/recovery_export"
    private val requestCreateZip = 0x4C46
    private val requestExportFolder = 0x4C47
    private val requestImportFolder = 0x4C48
    private val copyBufferSize = 1024 * 1024

    private var pendingSaveResult: MethodChannel.Result? = null
    private var pendingSourcePath: String? = null
    private var pendingSuggestedName: String? = null
    private var pendingMode: String = ""

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
                        pendingMode = "zip"
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
                    "exportBackupFolder" -> {
                        val sourceDir = call.argument<String>("sourceDir") ?: ""
                        val suggestedName = call.argument<String>("suggestedName") ?: "LF_SCOPED_BACKUP"
                        if (sourceDir.isEmpty() || !File(sourceDir).isDirectory) {
                            result.error("missing_source", "private backup folder not found", null)
                            return@setMethodCallHandler
                        }
                        if (pendingSaveResult != null) {
                            result.error("busy", "a save is already in progress", null)
                            return@setMethodCallHandler
                        }
                        pendingSaveResult = result
                        pendingSourcePath = sourceDir
                        pendingSuggestedName = suggestedName
                        pendingMode = "export_tree"
                        val intent = Intent(Intent.ACTION_OPEN_DOCUMENT_TREE).apply {
                            addFlags(
                                Intent.FLAG_GRANT_READ_URI_PERMISSION or
                                    Intent.FLAG_GRANT_WRITE_URI_PERMISSION or
                                    Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION or
                                    Intent.FLAG_GRANT_PREFIX_URI_PERMISSION,
                            )
                        }
                        startActivityForResult(intent, requestExportFolder)
                    }
                    "importBackupFolder" -> {
                        if (pendingSaveResult != null) {
                            result.error("busy", "a save is already in progress", null)
                            return@setMethodCallHandler
                        }
                        pendingSaveResult = result
                        pendingSourcePath = null
                        pendingSuggestedName = null
                        pendingMode = "import_tree"
                        val intent = Intent(Intent.ACTION_OPEN_DOCUMENT_TREE).apply {
                            addFlags(
                                Intent.FLAG_GRANT_READ_URI_PERMISSION or
                                    Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION or
                                    Intent.FLAG_GRANT_PREFIX_URI_PERMISSION,
                            )
                            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                                putExtra(
                                    DocumentsContract.EXTRA_INITIAL_URI,
                                    downloadsDocumentUri(),
                                )
                            }
                        }
                        startActivityForResult(intent, requestImportFolder)
                    }
                    "copyBackupToPublicDownloads" -> {
                        val sourceDir = call.argument<String>("sourceDir") ?: ""
                        val relativeDir = call.argument<String>("relativeDir") ?: ""
                        if (sourceDir.isEmpty() || !File(sourceDir).isDirectory) {
                            result.error("missing_source", "private backup folder not found", null)
                            return@setMethodCallHandler
                        }
                        if (!isSafePublicRelativeDir(relativeDir)) {
                            result.error("unsafe_path", "invalid public backup path", null)
                            return@setMethodCallHandler
                        }
                        Thread {
                            try {
                                val map = copyBackupToPublicDownloads(File(sourceDir), relativeDir)
                                runOnUiThread { result.success(map) }
                            } catch (e: Exception) {
                                runOnUiThread {
                                    result.error("copy_failed", e.message, null)
                                }
                            }
                        }.start()
                    }
                    "copyExportToPublicDownloads" -> {
                        val sourceDir = call.argument<String>("sourceDir") ?: ""
                        val relativeDir = call.argument<String>("relativeDir") ?: ""
                        if (sourceDir.isEmpty() || !File(sourceDir).isDirectory) {
                            result.error("missing_source", "private export folder not found", null)
                            return@setMethodCallHandler
                        }
                        if (!isSafePublicExportRelativeDir(relativeDir)) {
                            result.error("unsafe_path", "invalid public export path", null)
                            return@setMethodCallHandler
                        }
                        Thread {
                            try {
                                val map = copyExportToPublicDownloads(File(sourceDir), relativeDir)
                                runOnUiThread { result.success(map) }
                            } catch (e: Exception) {
                                runOnUiThread {
                                    result.error("copy_failed", e.message, null)
                                }
                            }
                        }.start()
                    }
                    "openPublicBackupFolder" -> {
                        val relativeDir = call.argument<String>("relativeDir") ?: ""
                        if (!isSafePublicRelativeDir(relativeDir)) {
                            result.error("unsafe_path", "invalid public backup path", null)
                            return@setMethodCallHandler
                        }
                        result.success(openPublicBackupFolder(relativeDir))
                    }
                    else -> result.notImplemented()
                }
            }
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        if (requestCode != requestCreateZip &&
            requestCode != requestExportFolder &&
            requestCode != requestImportFolder
        ) {
            super.onActivityResult(requestCode, resultCode, data)
            return
        }
        val reply = pendingSaveResult
        val sourcePath = pendingSourcePath
        val suggestedName = pendingSuggestedName
        val mode = pendingMode
        pendingSaveResult = null
        pendingSourcePath = null
        pendingSuggestedName = null
        pendingMode = ""
        if (reply == null) return
        if (resultCode != Activity.RESULT_OK || data?.data == null) {
            reply.success(null)
            return
        }
        val uri = data.data!!
        try {
            when (requestCode) {
                requestCreateZip -> {
                    if (sourcePath.isNullOrEmpty()) {
                        reply.success(null)
                        return
                    }
                    contentResolver.openOutputStream(uri, "w")?.use { output ->
                        FileInputStream(File(sourcePath)).use { input ->
                            copyStream(input, output)
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
                }
                requestExportFolder -> {
                    if (sourcePath.isNullOrEmpty()) {
                        reply.success(null)
                        return
                    }
                    takeTreePermission(uri, write = true)
                    val folderName = suggestedName ?: File(sourcePath).name
                    val destFolder = DocumentsContract.createDocument(
                        contentResolver,
                        DocumentsContract.buildDocumentUriUsingTree(
                            uri,
                            DocumentsContract.getTreeDocumentId(uri),
                        ),
                        DocumentsContract.Document.MIME_TYPE_DIR,
                        folderName,
                    ) ?: run {
                        reply.error("write_failed", "could not create backup folder", null)
                        return
                    }
                    copyDirectoryToTree(File(sourcePath), destFolder)
                    reply.success(
                        hashMapOf(
                            "uri" to destFolder.toString(),
                            "name" to folderName,
                        ),
                    )
                }
                requestImportFolder -> {
                    takeTreePermission(uri, write = false)
                    val dest = File(cacheDir, "scoped_backup_import/${System.currentTimeMillis()}")
                    dest.mkdirs()
                    val treeDoc = DocumentsContract.buildDocumentUriUsingTree(
                        uri,
                        DocumentsContract.getTreeDocumentId(uri),
                    )
                    copyTreeToDirectory(treeDoc, dest)
                    reply.success(
                        hashMapOf(
                            "path" to dest.absolutePath,
                            "uri" to uri.toString(),
                        ),
                    )
                }
            }
        } catch (e: Exception) {
            reply.error("copy_failed", e.message, null)
        }
    }

    private fun takeTreePermission(uri: Uri, write: Boolean) {
        val flags = Intent.FLAG_GRANT_READ_URI_PERMISSION or
            if (write) Intent.FLAG_GRANT_WRITE_URI_PERMISSION else 0
        try {
            contentResolver.takePersistableUriPermission(uri, flags)
        } catch (_: Exception) {
        }
    }

    private fun copyDirectoryToTree(source: File, destFolder: Uri) {
        val children = source.listFiles() ?: return
        for (child in children) {
            if (!isSafeName(child.name)) continue
            if (child.isDirectory) {
                val nested = DocumentsContract.createDocument(
                    contentResolver,
                    destFolder,
                    DocumentsContract.Document.MIME_TYPE_DIR,
                    child.name,
                ) ?: continue
                copyDirectoryToTree(child, nested)
            } else if (child.isFile) {
                val mime = mimeFor(child.name)
                val fileUri = DocumentsContract.createDocument(
                    contentResolver,
                    destFolder,
                    mime,
                    child.name,
                ) ?: continue
                contentResolver.openOutputStream(fileUri, "w")?.use { output ->
                    FileInputStream(child).use { input -> copyStream(input, output) }
                    output.flush()
                }
            }
        }
    }

    private fun copyTreeToDirectory(folderUri: Uri, dest: File) {
        dest.mkdirs()
        val childrenUri = DocumentsContract.buildChildDocumentsUriUsingTree(
            folderUri,
            DocumentsContract.getDocumentId(folderUri),
        )
        contentResolver.query(
            childrenUri,
            arrayOf(
                DocumentsContract.Document.COLUMN_DOCUMENT_ID,
                DocumentsContract.Document.COLUMN_DISPLAY_NAME,
                DocumentsContract.Document.COLUMN_MIME_TYPE,
            ),
            null,
            null,
            null,
        )?.use { cursor ->
            val idIdx = cursor.getColumnIndex(DocumentsContract.Document.COLUMN_DOCUMENT_ID)
            val nameIdx = cursor.getColumnIndex(DocumentsContract.Document.COLUMN_DISPLAY_NAME)
            val mimeIdx = cursor.getColumnIndex(DocumentsContract.Document.COLUMN_MIME_TYPE)
            while (cursor.moveToNext()) {
                val docId = cursor.getString(idIdx) ?: continue
                val name = cursor.getString(nameIdx) ?: continue
                val mime = cursor.getString(mimeIdx) ?: ""
                if (!isSafeName(name)) continue
                val childUri = DocumentsContract.buildDocumentUriUsingTree(folderUri, docId)
                val childDest = File(dest, name)
                if (mime == DocumentsContract.Document.MIME_TYPE_DIR) {
                    copyTreeToDirectory(childUri, childDest)
                } else {
                    contentResolver.openInputStream(childUri)?.use { input ->
                        FileOutputStream(childDest).use { output -> copyStream(input, output) }
                    }
                }
            }
        }
    }

    private fun copyStream(input: java.io.InputStream, output: java.io.OutputStream) {
        val buf = ByteArray(copyBufferSize)
        while (true) {
            val n = input.read(buf)
            if (n <= 0) break
            output.write(buf, 0, n)
        }
    }

    private fun isSafeName(name: String): Boolean {
        if (name.isEmpty() || name == "." || name == "..") return false
        if (name.contains("/") || name.contains("\\") || name.contains("\u0000")) return false
        return true
    }

    private fun mimeFor(name: String): String {
        return when {
            name.endsWith(".json", ignoreCase = true) -> "application/json"
            name.endsWith(".png", ignoreCase = true) -> "image/png"
            name.endsWith(".jpg", ignoreCase = true) ||
                name.endsWith(".jpeg", ignoreCase = true) -> "image/jpeg"
            name.endsWith(".mp4", ignoreCase = true) -> "video/mp4"
            name.endsWith(".xlsx", ignoreCase = true) ->
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            else -> "application/octet-stream"
        }
    }

    private val backupExportLogTag = "LFBackupExport"

    private fun filesCollectionUri(): Uri {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            MediaStore.Files.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
        } else {
            MediaStore.Files.getContentUri("external")
        }
    }

    private fun copyBackupToPublicDownloads(
        sourceDir: File,
        relativeDir: String,
    ): HashMap<String, String> {
        val uniqueDir = uniquePublicRelativeDir(relativeDir)
        val files = collectFiles(sourceDir)
        if (files.isEmpty()) {
            throw IllegalStateException("backup folder is empty")
        }
        val scanPaths = ArrayList<String>()
        val scanMimes = ArrayList<String>()
        var copied = 0
        var totalBytes = 0L
        for (file in files) {
            val rel = posixRelative(file, sourceDir)
            if (rel.isEmpty() || rel.contains("..")) {
                Log.w(backupExportLogTag, "skip unsafe rel=$rel")
                continue
            }
            val parentRel = rel.substringBeforeLast('/', missingDelimiterValue = "")
            val displayName = file.name
            if (!isSafeName(displayName)) {
                Log.w(backupExportLogTag, "skip unsafe name=$displayName")
                continue
            }
            val relativePath = buildString {
                append(Environment.DIRECTORY_DOWNLOADS)
                append('/')
                append(uniqueDir.trim('/'))
                append('/')
                if (parentRel.isNotEmpty()) {
                    append(parentRel.replace('\\', '/').trim('/'))
                    append('/')
                }
            }
            val dest = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                copyFileToMediaStoreDownloads(file, displayName, relativePath)
            } else {
                copyFileToLegacyDownloads(file, displayName, relativePath)
            }
            copied += 1
            totalBytes += file.length()
            Log.i(
                backupExportLogTag,
                "wrote name=$displayName size=${file.length()} rel=$relativePath dest=${dest.absolutePath}",
            )
            scanPaths.add(dest.absolutePath)
            scanMimes.add(mimeFor(displayName))
        }
        if (copied <= 0) {
            throw IllegalStateException("no backup files were copied to Downloads")
        }
        if (scanPaths.isNotEmpty()) {
            MediaScannerConnection.scanFile(
                this,
                scanPaths.toTypedArray(),
                scanMimes.toTypedArray(),
                null,
            )
        }
        Log.i(
            backupExportLogTag,
            "export complete files=$copied bytes=$totalBytes dir=$uniqueDir",
        )
        return hashMapOf(
            "displayPath" to "${Environment.DIRECTORY_DOWNLOADS}/$uniqueDir",
            "relativeDir" to uniqueDir,
            "fileCount" to copied.toString(),
            "totalBytes" to totalBytes.toString(),
        )
    }

    private fun uniquePublicRelativeDir(relativeDir: String): String {
        if (!publicRelativeDirExists(relativeDir)) return relativeDir
        var i = 2
        while (publicRelativeDirExists("${relativeDir}_$i")) {
            i++
        }
        return "${relativeDir}_$i"
    }

    private fun publicRelativeDirExists(relativeDir: String): Boolean {
        val like = "${Environment.DIRECTORY_DOWNLOADS}/$relativeDir/%"
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            contentResolver.query(
                filesCollectionUri(),
                arrayOf(MediaStore.MediaColumns._ID),
                "${MediaStore.MediaColumns.RELATIVE_PATH} LIKE ?",
                arrayOf(like),
                null,
            )?.use { cursor ->
                if (cursor.moveToFirst()) return true
            }
        }
        val dir = File(
            Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS),
            relativeDir,
        )
        return dir.exists()
    }

    @Suppress("DEPRECATION")
    private fun copyFileToMediaStoreDownloads(
        source: File,
        displayName: String,
        relativePath: String,
    ): File {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) {
            return copyFileToLegacyDownloads(source, displayName, relativePath)
        }
        val mime = mimeFor(displayName)
        val nowSec = System.currentTimeMillis() / 1000
        val insert = ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, displayName)
            put(MediaStore.MediaColumns.MIME_TYPE, mime)
            put(MediaStore.MediaColumns.RELATIVE_PATH, relativePath)
            put(MediaStore.MediaColumns.IS_PENDING, 1)
            put(MediaStore.MediaColumns.SIZE, source.length())
            put(MediaStore.MediaColumns.DATE_ADDED, nowSec)
            put(MediaStore.MediaColumns.DATE_MODIFIED, nowSec)
        }
        val uri = contentResolver.insert(filesCollectionUri(), insert)
            ?: throw IllegalStateException("could not create $displayName in Downloads")
        try {
            contentResolver.openOutputStream(uri, "w")?.use { output ->
                FileInputStream(source).use { input -> copyStream(input, output) }
                output.flush()
            } ?: throw IllegalStateException("could not write $displayName")
            val publish = ContentValues().apply {
                put(MediaStore.MediaColumns.IS_PENDING, 0)
                put(MediaStore.MediaColumns.SIZE, source.length())
                put(MediaStore.MediaColumns.DATE_MODIFIED, System.currentTimeMillis() / 1000)
            }
            val updated = contentResolver.update(uri, publish, null, null)
            if (updated <= 0) {
                throw IllegalStateException("could not clear IS_PENDING for $displayName")
            }
            val pending = queryMediaInt(uri, MediaStore.MediaColumns.IS_PENDING)
            if (pending != null && pending != 0) {
                throw IllegalStateException("IS_PENDING remained $pending for $displayName")
            }
            val dest = publicDownloadsFile(relativePath, displayName)
            val dataPath = queryMediaString(uri, MediaStore.MediaColumns.DATA)
            if (!dataPath.isNullOrEmpty()) {
                return File(dataPath)
            }
            return dest
        } catch (e: Exception) {
            Log.e(backupExportLogTag, "copy failed name=$displayName size=${source.length()}", e)
            try {
                contentResolver.delete(uri, null, null)
            } catch (_: Exception) {
            }
            throw e
        }
    }

    private fun publicDownloadsFile(relativePath: String, displayName: String): File {
        val downloads = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
        val under = relativePath
            .removePrefix("${Environment.DIRECTORY_DOWNLOADS}/")
            .replace('\\', '/')
            .trim('/')
        return if (under.isEmpty()) {
            File(downloads, displayName)
        } else {
            File(File(downloads, under), displayName)
        }
    }

    @Suppress("DEPRECATION")
    private fun queryMediaString(uri: Uri, column: String): String? {
        return try {
            contentResolver.query(uri, arrayOf(column), null, null, null)?.use { cursor ->
                if (!cursor.moveToFirst()) return null
                val idx = cursor.getColumnIndex(column)
                if (idx < 0) null else cursor.getString(idx)
            }
        } catch (_: Exception) {
            null
        }
    }

    private fun queryMediaInt(uri: Uri, column: String): Int? {
        return try {
            contentResolver.query(uri, arrayOf(column), null, null, null)?.use { cursor ->
                if (!cursor.moveToFirst()) return null
                val idx = cursor.getColumnIndex(column)
                if (idx < 0) null else cursor.getInt(idx)
            }
        } catch (_: Exception) {
            null
        }
    }

    private fun copyFileToLegacyDownloads(
        source: File,
        displayName: String,
        relativePath: String,
    ): File {
        val dest = publicDownloadsFile(relativePath, displayName)
        val destDir = dest.parentFile
            ?: throw IllegalStateException("could not create Downloads folder")
        if (!destDir.exists() && !destDir.mkdirs() && !destDir.isDirectory) {
            throw IllegalStateException("could not create Downloads folder")
        }
        FileOutputStream(dest).use { output ->
            FileInputStream(source).use { input -> copyStream(input, output) }
            output.flush()
        }
        return dest
    }

    private fun collectFiles(dir: File): List<File> {
        val out = ArrayList<File>()
        val children = dir.listFiles() ?: return out
        for (child in children) {
            if (!isSafeName(child.name)) continue
            if (child.isDirectory) {
                out.addAll(collectFiles(child))
            } else if (child.isFile) {
                out.add(child)
            }
        }
        return out
    }

    private fun posixRelative(file: File, root: File): String {
        val full = file.absolutePath.replace('\\', '/')
        val base = root.absolutePath.replace('\\', '/').trimEnd('/')
        if (!full.startsWith(base)) return ""
        return full.substring(base.length).trimStart('/')
    }

    private fun isSafePublicRelativeDir(relativeDir: String): Boolean {
        if (relativeDir.isEmpty() || relativeDir.startsWith("/") || relativeDir.startsWith("\\")) {
            return false
        }
        if (relativeDir.contains('\u0000') || relativeDir.contains('\\')) return false
        if (!relativeDir.startsWith("SmartArbitration_Backups/")) return false
        val parts = relativeDir.split('/')
        if (parts.size < 4) return false
        for (part in parts) {
            if (!isSafeName(part)) return false
        }
        return true
    }

    private fun isSafePublicExportRelativeDir(relativeDir: String): Boolean {
        if (relativeDir.isEmpty() || relativeDir.startsWith("/") || relativeDir.startsWith("\\")) {
            return false
        }
        if (relativeDir.contains('\u0000') || relativeDir.contains('\\')) return false
        if (relativeDir.startsWith("SmartArbitration_Backups")) return false
        if (!relativeDir.startsWith("SmartArbitration/")) return false
        val parts = relativeDir.split('/')
        if (parts.size < 4) return false
        for (part in parts) {
            if (!isSafeName(part)) return false
        }
        return true
    }

    private fun copyExportToPublicDownloads(
        sourceDir: File,
        relativeDir: String,
    ): HashMap<String, String> {
        val files = collectFiles(sourceDir)
        if (files.isEmpty()) {
            throw IllegalStateException("export folder is empty")
        }
        val scanPaths = ArrayList<String>()
        val scanMimes = ArrayList<String>()
        var copied = 0
        var totalBytes = 0L
        val usedNames = HashMap<String, HashSet<String>>()
        for (file in files) {
            val rel = posixRelative(file, sourceDir)
            if (rel.isEmpty() || rel.contains("..")) {
                Log.w(backupExportLogTag, "skip unsafe export rel=$rel")
                continue
            }
            val parentRel = rel.substringBeforeLast('/', missingDelimiterValue = "")
            var displayName = file.name
            if (!isSafeName(displayName)) {
                Log.w(backupExportLogTag, "skip unsafe export name=$displayName")
                continue
            }
            val relativePath = buildString {
                append(Environment.DIRECTORY_DOWNLOADS)
                append('/')
                append(relativeDir.trim('/'))
                append('/')
                if (parentRel.isNotEmpty()) {
                    append(parentRel.replace('\\', '/').trim('/'))
                    append('/')
                }
            }
            val bucket = usedNames.getOrPut(relativePath) { HashSet() }
            displayName = uniquePublicFileName(relativePath, displayName, bucket)
            bucket.add(displayName)
            val dest = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                copyFileToMediaStoreDownloads(file, displayName, relativePath)
            } else {
                copyFileToLegacyDownloads(file, displayName, relativePath)
            }
            copied += 1
            totalBytes += file.length()
            scanPaths.add(dest.absolutePath)
            scanMimes.add(mimeFor(displayName))
        }
        if (copied <= 0) {
            throw IllegalStateException("no export files were copied to Downloads")
        }
        if (scanPaths.isNotEmpty()) {
            MediaScannerConnection.scanFile(
                this,
                scanPaths.toTypedArray(),
                scanMimes.toTypedArray(),
                null,
            )
        }
        return hashMapOf(
            "displayPath" to "${Environment.DIRECTORY_DOWNLOADS}/$relativeDir",
            "relativeDir" to relativeDir,
            "fileCount" to copied.toString(),
            "totalBytes" to totalBytes.toString(),
        )
    }

    private fun uniquePublicFileName(
        relativePath: String,
        displayName: String,
        used: MutableSet<String>,
    ): String {
        if (!used.contains(displayName) && !publicFileExists(relativePath, displayName)) {
            return displayName
        }
        val dot = displayName.lastIndexOf('.')
        val stem = if (dot > 0) displayName.substring(0, dot) else displayName
        val ext = if (dot > 0) displayName.substring(dot) else ""
        var i = 2
        while (true) {
            val candidate = "${stem}_$i$ext"
            if (!used.contains(candidate) && !publicFileExists(relativePath, candidate)) {
                return candidate
            }
            i++
        }
    }

    private fun publicFileExists(relativePath: String, displayName: String): Boolean {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            contentResolver.query(
                filesCollectionUri(),
                arrayOf(MediaStore.MediaColumns._ID),
                "${MediaStore.MediaColumns.RELATIVE_PATH} = ? AND ${MediaStore.MediaColumns.DISPLAY_NAME} = ?",
                arrayOf(relativePath, displayName),
                null,
            )?.use { cursor ->
                if (cursor.moveToFirst()) return true
            }
        }
        return publicDownloadsFile(relativePath, displayName).exists()
    }

    private fun downloadsDocumentUri(): Uri {
        return Uri.parse("content://com.android.externalstorage.documents/document/primary%3ADownload")
    }

    private fun openPublicBackupFolder(relativeDir: String): Boolean {
        return try {
            val encoded = Uri.encode("primary:Download/$relativeDir")
            val uri = Uri.parse(
                "content://com.android.externalstorage.documents/document/$encoded",
            )
            val intent = Intent(Intent.ACTION_VIEW).apply {
                setDataAndType(uri, DocumentsContract.Document.MIME_TYPE_DIR)
                addFlags(
                    Intent.FLAG_ACTIVITY_NEW_TASK or
                        Intent.FLAG_GRANT_READ_URI_PERMISSION,
                )
            }
            startActivity(intent)
            true
        } catch (_: Exception) {
            false
        }
    }

    private fun queryDisplayName(uri: Uri): String? {
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
