package ae.lf.training.judge.ui

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import ae.lf.training.judge.data.AppContainer
import ae.lf.training.judge.data.api.EvalListRowDto
import ae.lf.training.judge.data.api.HubItemDto
import ae.lf.training.judge.data.api.IncompleteRowDto
import ae.lf.training.judge.data.api.NotificationRowDto
import ae.lf.training.judge.data.api.PhaseTabDto
import ae.lf.training.judge.data.api.UserDto
import ae.lf.training.judge.ui.screens.DashboardScreen
import ae.lf.training.judge.ui.screens.EvalDetailScreen
import ae.lf.training.judge.ui.screens.EvalListsHomeScreen
import ae.lf.training.judge.ui.screens.EvalRowUi
import ae.lf.training.judge.ui.screens.EvalUnitListsScreen
import ae.lf.training.judge.ui.screens.IncompleteTasksScreen
import ae.lf.training.judge.ui.screens.LoginScreen
import ae.lf.training.judge.ui.screens.NotificationsScreen
import ae.lf.training.judge.ui.screens.PlaceholderScreen
import ae.lf.training.judge.ui.screens.SettingsScreen
import com.google.gson.Gson
import kotlinx.coroutines.launch

private object Routes {
    const val LOGIN = "login"
    const val DASH = "dash"
    const val EVAL_HOME = "eval_home"
    const val EVAL_UNIT = "eval_unit/{unitKey}/{phase}"
    const val EVAL_DETAIL = "eval_detail/{unitKey}/{itemId}"
    const val INCOMPLETE = "incomplete"
    const val NOTIFICATIONS = "notifications"
    const val SETTINGS = "settings"
    const val PLACEHOLDER = "placeholder/{title}"
}

@Composable
fun JudgeRoot(container: AppContainer) {
    val nav = rememberNavController()
    val scope = rememberCoroutineScope()
    val gson = remember { Gson() }

    var username by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var loginLoading by remember { mutableStateOf(false) }
    var loginError by remember { mutableStateOf<String?>(null) }

    var user by remember { mutableStateOf<UserDto?>(null) }
    var online by remember { mutableStateOf(false) }
    var judgeItems by remember { mutableStateOf<List<HubItemDto>>(emptyList()) }
    var chiefItems by remember { mutableStateOf<List<HubItemDto>>(emptyList()) }

    var phaseTabs by remember { mutableStateOf<List<PhaseTabDto>>(emptyList()) }
    var phaseIndex by remember { mutableIntStateOf(0) }
    var unitRows by remember { mutableStateOf<List<EvalListRowDto>>(emptyList()) }
    var unitLabel by remember { mutableStateOf("") }
    var currentUnitKey by remember { mutableStateOf("") }
    var currentPhase by remember { mutableStateOf("") }

    var evalTitle by remember { mutableStateOf("") }
    var evalWorkflow by remember { mutableStateOf("") }
    var evalCanEdit by remember { mutableStateOf(false) }
    var evalCanApprove by remember { mutableStateOf(false) }
    var evalCanChiefApprove by remember { mutableStateOf(false) }
    var evalCanChiefReopen by remember { mutableStateOf(false) }
    var evalMessage by remember { mutableStateOf<String?>(null) }
    val evalRows = remember { mutableStateListOf<EvalRowUi>() }
    var acquiredOptions by remember { mutableStateOf<List<Pair<String, String>>>(emptyList()) }

    var incompleteRows by remember { mutableStateOf<List<IncompleteRowDto>>(emptyList()) }
    var notificationRows by remember { mutableStateOf<List<NotificationRowDto>>(emptyList()) }
    var unreadCount by remember { mutableIntStateOf(0) }

    var settingsHost by remember { mutableStateOf("192.168.1.100") }
    var settingsPort by remember { mutableStateOf("8005") }
    var settingsMsg by remember { mutableStateOf<String?>(null) }
    var settingsMsgSuccess by remember { mutableStateOf(false) }
    var settingsTesting by remember { mutableStateOf(false) }

    val pendingSync by container.pendingCount.collectAsState(initial = 0)

    LaunchedEffect(Unit) {
        container.settings.savedUsername.collect { username = it }
    }
    LaunchedEffect(Unit) {
        container.settings.serverHost.collect { settingsHost = it }
    }
    LaunchedEffect(Unit) {
        container.settings.serverPort.collect { settingsPort = it }
    }

    suspend fun refreshOnline() {
        online = container.evalRepo.isOnline()
        if (online && pendingSync > 0) {
            runCatching { container.syncRepo.pushPending() }
        }
    }

    suspend fun loadDashboard() {
        refreshOnline()
        val hub = container.evalRepo.fetchHub()
        judgeItems = hub.first
        chiefItems = hub.second
        runCatching {
            val (unread, rows) = container.evalRepo.fetchNotifications()
            unreadCount = unread
            notificationRows = rows
        }
    }

    suspend fun tryRestoreSession() {
        runCatching {
            user = container.auth.refreshSession().getOrThrow()
            loadDashboard()
            nav.navigate(Routes.DASH) { popUpTo(Routes.LOGIN) { inclusive = true } }
        }
    }

    LaunchedEffect(Unit) { tryRestoreSession() }

    NavHost(navController = nav, startDestination = Routes.LOGIN) {
        composable(Routes.LOGIN) {
            LoginScreen(
                username = username,
                password = password,
                loading = loginLoading,
                error = loginError,
                onUsernameChange = { username = it },
                onPasswordChange = { password = it },
                onLogin = {
                    scope.launch {
                        loginLoading = true
                        loginError = null
                        val result = container.auth.login(username, password)
                        loginLoading = false
                        result.onSuccess {
                            user = it
                            loadDashboard()
                            nav.navigate(Routes.DASH) { popUpTo(Routes.LOGIN) { inclusive = true } }
                        }.onFailure {
                            loginError = it.message ?: "فشل الدخول"
                        }
                    }
                },
                onOpenSettings = { nav.navigate(Routes.SETTINGS) },
            )
        }
        composable(Routes.DASH) {
            val u = user
            if (u == null) {
                LaunchedEffect(Unit) { nav.navigate(Routes.LOGIN) }
            } else {
                DashboardScreen(
                    user = u,
                    judgeItems = judgeItems,
                    chiefItems = chiefItems,
                    online = online,
                    pendingSync = pendingSync,
                    unreadNotifications = unreadCount,
                    onHubClick = { slug, isChief ->
                        when (slug) {
                            "evaluation-lists", "planner-flow-bundle-overview" -> {
                                scope.launch {
                                    runCatching {
                                        phaseTabs = container.evalRepo.fetchEvalHome()
                                        phaseIndex = 0
                                        nav.navigate(Routes.EVAL_HOME)
                                    }
                                }
                            }
                            "incomplete-tasks" -> {
                                scope.launch {
                                    runCatching {
                                        incompleteRows = container.evalRepo.fetchIncomplete()
                                        nav.navigate(Routes.INCOMPLETE)
                                    }
                                }
                            }
                            else -> nav.navigate("placeholder/$slug")
                        }
                    },
                    onNotifications = {
                        scope.launch {
                            runCatching {
                                val (unread, rows) = container.evalRepo.fetchNotifications()
                                unreadCount = unread
                                notificationRows = rows
                                nav.navigate(Routes.NOTIFICATIONS)
                            }
                        }
                    },
                    onSettings = { nav.navigate(Routes.SETTINGS) },
                    onSync = {
                        scope.launch {
                            refreshOnline()
                            val (ok, fail) = runCatching { container.syncRepo.pushPending() }.getOrElse { 0 to 0 }
                            evalMessage = if (ok + fail == 0) "لا توجد عمليات معلّقة" else "تمت مزامنة $ok — متبقي $fail"
                        }
                    },
                    onLogout = {
                        scope.launch {
                            container.auth.logout()
                            user = null
                            nav.navigate(Routes.LOGIN) { popUpTo(0) }
                        }
                    },
                )
            }
        }
        composable(Routes.EVAL_HOME) {
            EvalListsHomeScreen(
                tabs = phaseTabs,
                selectedIndex = phaseIndex,
                loading = false,
                error = null,
                onTabSelect = { phaseIndex = it },
                onUnitClick = { uk, phase ->
                    currentUnitKey = uk
                    currentPhase = phase
                    scope.launch {
                        runCatching {
                            unitRows = container.evalRepo.fetchUnitLists(uk, phase.ifBlank { null })
                            unitLabel = phaseTabs.getOrNull(phaseIndex)?.unitRows?.find { it.key == uk }?.label ?: uk
                            nav.navigate("eval_unit/$uk/${phase.ifBlank { "_" }}")
                        }
                    }
                },
                onBack = { nav.popBackStack() },
            )
        }
        composable(Routes.EVAL_UNIT) { entry ->
            val uk = entry.arguments?.getString("unitKey").orEmpty()
            EvalUnitListsScreen(
                unitLabel = unitLabel.ifBlank { uk },
                rows = unitRows,
                error = null,
                onOpenEval = { itemId -> nav.navigate("eval_detail/$uk/$itemId") },
                onBack = { nav.popBackStack() },
            )
        }
        composable(Routes.EVAL_DETAIL) { entry ->
            val uk = entry.arguments?.getString("unitKey").orEmpty()
            val itemId = entry.arguments?.getString("itemId")?.toIntOrNull() ?: 0
            LaunchedEffect(uk, itemId) {
                runCatching {
                    refreshOnline()
                    val detail = container.evalRepo.fetchEvalDetail(uk, itemId, allowCache = !online)
                    evalTitle = detail.itemTitle.orEmpty()
                    unitLabel = detail.unitLabel.orEmpty()
                    evalWorkflow = detail.workflow?.label.orEmpty()
                    evalCanEdit = detail.workflow?.evalCanEdit == true
                    evalCanApprove = detail.workflow?.showEvalApprove == true
                    evalCanChiefApprove = detail.workflow?.showChiefApprove == true
                    evalCanChiefReopen = detail.workflow?.showChiefReopen == true
                    acquiredOptions = detail.acquiredOptions.orEmpty().mapNotNull { pair ->
                        if (pair.size >= 2) pair[0] to pair[1] else null
                    }
                    evalRows.clear()
                    val template = detail.evalRows.orEmpty()
                    val savedRows = (detail.savedPayload?.get("rows") as? List<*>) ?: emptyList<Any>()
                    template.forEachIndexed { i, tpl ->
                        val m = tpl as? Map<*, *> ?: emptyMap<String, Any?>()
                        val saved = savedRows.getOrNull(i) as? Map<*, *>
                        evalRows.add(
                            EvalRowUi(
                                index = i,
                                rowKind = (m["row_kind"] ?: "score").toString(),
                                element = (m["element"] ?: m["label"] ?: "—").toString(),
                                maxVal = (m["max_val"] ?: m["max"] ?: m["max_score"] ?: "").toString(),
                                acquired = saved?.get("acquired")?.toString().orEmpty(),
                                notes = saved?.get("notes")?.toString().orEmpty(),
                            ),
                        )
                    }
                }.onFailure {
                    evalMessage = "تعذّر تحميل التقييم"
                }
            }
            EvalDetailScreen(
                title = evalTitle,
                unitLabel = unitLabel,
                workflowLabel = evalWorkflow,
                rows = evalRows,
                acquiredOptions = acquiredOptions,
                canEdit = evalCanEdit,
                canApprove = evalCanApprove,
                canChiefApprove = evalCanChiefApprove,
                canChiefReopen = evalCanChiefReopen,
                message = evalMessage,
                onRowChange = { i, acquired, notes ->
                    if (i in evalRows.indices) {
                        evalRows[i] = evalRows[i].copy(acquired = acquired, notes = notes)
                    }
                },
                onSave = {
                    scope.launch {
                        val payload = mapOf(
                            "rows" to evalRows.map {
                                mapOf(
                                    "row_kind" to it.rowKind,
                                    "element" to it.element,
                                    "max_val" to it.maxVal,
                                    "acquired" to it.acquired,
                                    "notes" to it.notes,
                                )
                            },
                        )
                        val json = gson.toJson(payload)
                        val result = container.evalRepo.saveEval(uk, itemId, json, online)
                        evalMessage = result.fold(
                            onSuccess = { if (online) "تم الحفظ" else "حُفظ محلياً — سيتم المزامنة عند الاتصال" },
                            onFailure = { "فشل الحفظ: ${it.message}" },
                        )
                    }
                },
                onApprove = {
                    scope.launch {
                        val result = container.evalRepo.approveEval(uk, itemId, online)
                        evalMessage = result.fold(
                            onSuccess = { "تم الإرسال للاعتماد" },
                            onFailure = { "فشل: ${it.message}" },
                        )
                    }
                },
                onChiefApprove = {
                    scope.launch {
                        val result = container.evalRepo.chiefApprove(uk, itemId)
                        evalMessage = result.fold(
                            onSuccess = { "تم اعتماد كبير المحكمين" },
                            onFailure = { "فشل: ${it.message}" },
                        )
                    }
                },
                onChiefReopen = {
                    scope.launch {
                        val result = container.evalRepo.chiefReopen(uk, itemId)
                        evalMessage = result.fold(
                            onSuccess = { "أُعيدت القائمة للمحكم" },
                            onFailure = { "فشل: ${it.message}" },
                        )
                    }
                },
                onBack = { nav.popBackStack() },
            )
        }
        composable(Routes.INCOMPLETE) {
            IncompleteTasksScreen(
                rows = incompleteRows,
                onOpen = { uk, id -> if (id != null) nav.navigate("eval_detail/$uk/$id") },
                onBack = { nav.popBackStack() },
            )
        }
        composable(Routes.NOTIFICATIONS) {
            NotificationsScreen(rows = notificationRows, onBack = { nav.popBackStack() })
        }
        composable(Routes.SETTINGS) {
            SettingsScreen(
                host = settingsHost,
                port = settingsPort,
                message = settingsMsg,
                messageSuccess = settingsMsgSuccess,
                testingConnection = settingsTesting,
                onHostChange = { settingsHost = it },
                onPortChange = { settingsPort = it },
                onTestConnection = {
                    scope.launch {
                        settingsTesting = true
                        settingsMsg = null
                        val result = container.testConnection(settingsHost, settingsPort)
                        settingsTesting = false
                        result.onSuccess {
                            settingsMsg = it
                            settingsMsgSuccess = true
                        }.onFailure {
                            settingsMsg = it.message ?: "فشل اختبار الاتصال"
                            settingsMsgSuccess = false
                        }
                    }
                },
                onSave = {
                    scope.launch {
                        container.settings.saveServer(settingsHost, settingsPort)
                        container.refreshApiClient()
                        settingsMsg = "تم الحفظ — ${settingsHost}:${settingsPort}"
                        settingsMsgSuccess = true
                        refreshOnline()
                    }
                },
                onBack = { nav.popBackStack() },
            )
        }
        composable(Routes.PLACEHOLDER) { entry ->
            val title = entry.arguments?.getString("title").orEmpty()
            PlaceholderScreen(
                title = title,
                note = "هذا القسم متاح عبر الويب حالياً — سيتم توسيع التطبيق لاحقاً.",
                onBack = { nav.popBackStack() },
            )
        }
    }
}
