package ae.lf.training.judge.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.foundation.layout.size
import androidx.compose.ui.unit.dp
import ae.lf.training.judge.data.api.IncompleteRowDto
import ae.lf.training.judge.data.api.NotificationRowDto
import ae.lf.training.judge.ui.components.AppTopBar
import ae.lf.training.judge.ui.theme.SuccessGreen
import ae.lf.training.judge.ui.theme.UrgentRed

@Composable
fun IncompleteTasksScreen(
    rows: List<IncompleteRowDto>,
    onOpen: (String, Int?) -> Unit,
    onBack: () -> Unit,
) {
    Column(Modifier.fillMaxSize()) {
        AppTopBar(title = "مهام غير مكتملة", subtitle = "العدد: ${rows.size}")
        TextButton(onClick = onBack, modifier = Modifier.padding(horizontal = 12.dp)) { Text("رجوع") }
        LazyColumn(contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            items(rows) { row ->
                Card(modifier = Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp)) {
                        Text(row.title, fontWeight = FontWeight.SemiBold)
                        Text("${row.unitLabel} — ${row.phaseLabel}")
                        if (row.itemId != null && row.unitKey.isNotBlank()) {
                            TextButton(onClick = { onOpen(row.unitKey, row.itemId) }) { Text("فتح") }
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun NotificationsScreen(
    rows: List<NotificationRowDto>,
    onBack: () -> Unit,
) {
    Column(Modifier.fillMaxSize()) {
        AppTopBar(title = "سجل الإشعارات")
        TextButton(onClick = onBack, modifier = Modifier.padding(horizontal = 12.dp)) { Text("رجوع") }
        LazyColumn(contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            items(rows) { n ->
                Card(modifier = Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp)) {
                        Text(n.title, fontWeight = FontWeight.Bold)
                        if (n.priority == "urgent") {
                            Text("عاجل", color = UrgentRed, modifier = Modifier.padding(top = 4.dp))
                        }
                        Text(n.body, modifier = Modifier.padding(top = 8.dp))
                        Text(n.createdAt, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 6.dp))
                    }
                }
            }
        }
    }
}

@Composable
fun SettingsScreen(
    host: String,
    port: String,
    message: String?,
    messageSuccess: Boolean,
    testingConnection: Boolean,
    onHostChange: (String) -> Unit,
    onPortChange: (String) -> Unit,
    onTestConnection: () -> Unit,
    onSave: () -> Unit,
    onBack: () -> Unit,
) {
    Column(Modifier.fillMaxSize()) {
        AppTopBar(title = "إعدادات الاتصال", subtitle = "عنوان السيرفر و المنفذ")
        TextButton(onClick = onBack, modifier = Modifier.padding(horizontal = 12.dp)) { Text("رجوع") }
        Column(Modifier.padding(24.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
            androidx.compose.material3.OutlinedTextField(
                value = host,
                onValueChange = onHostChange,
                label = { Text("IP السيرفر") },
                modifier = Modifier.fillMaxWidth(0.7f),
                singleLine = true,
            )
            androidx.compose.material3.OutlinedTextField(
                value = port,
                onValueChange = onPortChange,
                label = { Text("المنفذ (Port)") },
                modifier = Modifier.fillMaxWidth(0.7f),
                singleLine = true,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                androidx.compose.material3.OutlinedButton(
                    onClick = onTestConnection,
                    enabled = !testingConnection,
                ) {
                    if (testingConnection) {
                        androidx.compose.material3.CircularProgressIndicator(
                            modifier = Modifier.size(18.dp),
                            strokeWidth = 2.dp,
                        )
                    } else {
                        Text("اختبار الاتصال")
                    }
                }
                androidx.compose.material3.Button(onClick = onSave) { Text("حفظ وإعادة الاتصال") }
            }
            if (!message.isNullOrBlank()) {
                Text(
                    message,
                    color = if (messageSuccess) SuccessGreen else MaterialTheme.colorScheme.error,
                )
            }
            Text(
                "اختبر الاتصال أولاً ثم احفظ الإعدادات قبل تسجيل الدخول.\nمثال: 192.168.1.50 — المنفذ 8005",
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

@Composable
fun PlaceholderScreen(title: String, note: String, onBack: () -> Unit) {
    Column(Modifier.fillMaxSize()) {
        AppTopBar(title = title)
        TextButton(onClick = onBack, modifier = Modifier.padding(horizontal = 12.dp)) { Text("رجوع") }
        Text(note, modifier = Modifier.padding(24.dp))
    }
}
