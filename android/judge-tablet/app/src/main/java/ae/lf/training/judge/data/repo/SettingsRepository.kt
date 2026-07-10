package ae.lf.training.judge.data.repo

import ae.lf.training.judge.data.SettingsKeys
import ae.lf.training.judge.data.api.LoginRequest
import ae.lf.training.judge.data.api.MobileApiService
import ae.lf.training.judge.data.api.UserDto
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import com.google.gson.Gson
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import java.io.IOException
import java.net.ConnectException
import java.net.SocketTimeoutException
import java.net.UnknownHostException

class SettingsRepository(private val store: DataStore<Preferences>) {
    val serverHost: Flow<String> = store.data.map { it[SettingsKeys.SERVER_HOST] ?: "192.168.1.100" }
    val serverPort: Flow<String> = store.data.map { it[SettingsKeys.SERVER_PORT] ?: "8005" }
    val savedUsername: Flow<String> = store.data.map { it[SettingsKeys.USERNAME] ?: "" }

    val serverBaseUrl: Flow<String> = store.data.map { prefs ->
        val host = prefs[SettingsKeys.SERVER_HOST] ?: "192.168.1.100"
        val port = prefs[SettingsKeys.SERVER_PORT] ?: "8005"
        "http://$host:$port/"
    }

    suspend fun saveServer(host: String, port: String) {
        store.edit {
            it[SettingsKeys.SERVER_HOST] = host.trim()
            it[SettingsKeys.SERVER_PORT] = port.trim()
        }
    }

    suspend fun saveUsername(username: String) {
        store.edit { it[SettingsKeys.USERNAME] = username.trim() }
    }
}

class AuthRepository(
    private val api: MobileApiService,
    private val settings: SettingsRepository,
) {
    var currentUser: UserDto? = null
        private set

    suspend fun login(username: String, password: String): Result<UserDto> {
        val trimmedUser = username.trim()
        if (trimmedUser.isEmpty() || password.isEmpty()) {
            return Result.failure(Exception("أدخل اسم المستخدم وكلمة المرور"))
        }
        return try {
            val resp = api.login(LoginRequest(trimmedUser, password))
            if (!resp.isSuccessful) {
                val raw = resp.errorBody()?.string()
                return Result.failure(Exception(parseLoginApiError(raw, resp.code())))
            }
            val body = resp.body() ?: return Result.failure(Exception("استجابة فارغة من السيرفر"))
            if (!body.ok || body.user == null) {
                return Result.failure(Exception(parseLoginApiError(body.error, resp.code())))
            }
            currentUser = body.user
            settings.saveUsername(trimmedUser)
            Result.success(body.user)
        } catch (e: IOException) {
            Result.failure(Exception(networkErrorMessage(e)))
        }
    }

    private fun parseLoginApiError(raw: String?, httpCode: Int): String {
        if (!raw.isNullOrBlank()) {
            runCatching {
                val map = Gson().fromJson(raw, Map::class.java)
                val code = map["error"]?.toString().orEmpty()
                if (code.isNotBlank()) return apiErrorToArabic(code)
            }
            if (raw.length < 120 && !raw.trimStart().startsWith("{")) return raw.trim()
        }
        return when (httpCode) {
            401 -> "بيانات الدخول غير صحيحة"
            403 -> "لا تملك صلاحية دخول مساحة المحكمين"
            in 500..599 -> "خطأ في السيرفر — حاول لاحقاً"
            else -> "فشل الدخول"
        }
    }

    private fun apiErrorToArabic(code: String): String = when (code) {
        "invalid_credentials" -> "بيانات الدخول غير صحيحة"
        "judge_role_required" -> "هذا الحساب ليس من صلاحية المحكمين"
        "missing_credentials" -> "أدخل اسم المستخدم وكلمة المرور"
        else -> code
    }

    private fun networkErrorMessage(e: IOException): String = when (e) {
        is UnknownHostException -> "تعذّر الوصول للسيرفر — تحقق من عنوان IP"
        is ConnectException -> "تعذّر الاتصال — تأكد أن السيرفر يعمل والمنفذ صحيح"
        is SocketTimeoutException -> "انتهت مهلة الاتصال — تحقق من الشبكة والسيرفر"
        else -> "فشل الاتصال بالسيرفر — جرّب «اختبار الاتصال» من الإعدادات"
    }

    suspend fun refreshSession(): Result<UserDto> = runCatching {
        val resp = api.session()
        if (!resp.isSuccessful) error("session_expired")
        val body = resp.body() ?: error("empty")
        if (!body.ok || body.user == null) error(body.error ?: "session_expired")
        currentUser = body.user
        body.user
    }

    suspend fun logout() {
        runCatching { api.logout() }
        currentUser = null
    }
}
