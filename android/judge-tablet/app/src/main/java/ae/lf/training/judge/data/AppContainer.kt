package ae.lf.training.judge.data

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import androidx.room.Room
import ae.lf.training.judge.data.api.MobileApiService
import ae.lf.training.judge.data.local.JudgeDatabase
import ae.lf.training.judge.data.repo.AuthRepository
import ae.lf.training.judge.data.repo.EvalRepository
import ae.lf.training.judge.data.repo.SettingsRepository
import ae.lf.training.judge.data.repo.SyncRepository
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import okhttp3.Cookie
import okhttp3.CookieJar
import okhttp3.HttpUrl
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit

private val Context.dataStore by preferencesDataStore("judge_settings")

class AppContainer(context: Context) {
    private val appContext = context.applicationContext

    val settings = SettingsRepository(appContext.dataStore)
    val db: JudgeDatabase = Room.databaseBuilder(appContext, JudgeDatabase::class.java, "judge_local.db")
        .fallbackToDestructiveMigration()
        .build()

    private val cookieStore = ConcurrentHashMap<String, ConcurrentHashMap<String, Cookie>>()

    private val cookieJar = object : CookieJar {
        override fun saveFromResponse(url: HttpUrl, cookies: List<Cookie>) {
            val key = url.host
            val map = cookieStore.getOrPut(key) { ConcurrentHashMap() }
            cookies.forEach { map[it.name] = it }
        }

        override fun loadForRequest(url: HttpUrl): List<Cookie> {
            return cookieStore[url.host]?.values?.filter { it.matches(url) }?.toList().orEmpty()
        }
    }

    private fun buildApi(): MobileApiService {
        val baseUrl = runBlocking { settings.serverBaseUrl.first() }
        val logging = HttpLoggingInterceptor().apply {
            level = HttpLoggingInterceptor.Level.BASIC
        }
        val client = OkHttpClient.Builder()
            .cookieJar(cookieJar)
            .addInterceptor(logging)
            .build()
        return Retrofit.Builder()
            .baseUrl(baseUrl)
            .client(client)
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(MobileApiService::class.java)
    }

    @Volatile
    private var api: MobileApiService = buildApi()

    fun refreshApiClient() {
        api = buildApi()
        auth = AuthRepository(api, settings)
        evalRepo = EvalRepository(api, db)
        syncRepo = SyncRepository(api, db.pendingOperationDao())
    }

    var auth: AuthRepository = AuthRepository(api, settings)
        private set

    var evalRepo: EvalRepository = EvalRepository(api, db)
        private set

    var syncRepo: SyncRepository = SyncRepository(api, db.pendingOperationDao())
        private set

    val pendingCount = db.pendingOperationDao().observeCount()

    init {
        refreshApiClient()
    }

    /** يختبر الاتصال بالقيم المدخلة (دون اشتراط الحفظ مسبقاً). */
    suspend fun testConnection(host: String, port: String): Result<String> = withContext(Dispatchers.IO) {
        runCatching {
            val h = host.trim()
            val p = port.trim()
            require(h.isNotEmpty()) { "أدخل عنوان IP للسيرفر" }
            require(p.isNotEmpty()) { "أدخل المنفذ (Port)" }
            val baseUrl = "http://$h:$p/"
            val client = OkHttpClient.Builder()
                .connectTimeout(10, TimeUnit.SECONDS)
                .readTimeout(10, TimeUnit.SECONDS)
                .build()
            val ping = Request.Builder()
                .url("${baseUrl}api/mobile/v1/ping")
                .get()
                .build()
            client.newCall(ping).execute().use { resp ->
                if (!resp.isSuccessful) {
                    error(
                        when (resp.code) {
                            404 -> "واجهة التطبيق غير موجودة على هذا السيرفر — أعد تثبيت LF_TrainingEvaluation_Setup.exe من مجلد dist ثم أعد تشغيل السيرفر"
                            else -> "فشل الاتصال — رمز الاستجابة ${resp.code}"
                        },
                    )
                }
                val body = resp.body?.string().orEmpty()
                if (!body.contains("\"ok\"") && !body.contains("ok")) {
                    error("استجابة غير متوقعة من السيرفر")
                }
            }
            "نجح الاتصال بالسيرفر ($h:$p)"
        }
    }
}

object SettingsKeys {
    val SERVER_HOST = stringPreferencesKey("server_host")
    val SERVER_PORT = stringPreferencesKey("server_port")
    val USERNAME = stringPreferencesKey("saved_username")
}
