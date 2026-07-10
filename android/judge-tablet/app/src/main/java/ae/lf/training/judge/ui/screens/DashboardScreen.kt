package ae.lf.training.judge.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CloudOff
import androidx.compose.material.icons.filled.CloudQueue
import androidx.compose.material.icons.filled.Logout
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import ae.lf.training.judge.data.api.HubItemDto
import ae.lf.training.judge.data.api.UserDto
import ae.lf.training.judge.ui.components.AppTopBar
import ae.lf.training.judge.ui.components.HubTile

@Composable
fun DashboardScreen(
    user: UserDto,
    judgeItems: List<HubItemDto>,
    chiefItems: List<HubItemDto>,
    online: Boolean,
    pendingSync: Int,
    unreadNotifications: Int,
    onHubClick: (String, Boolean) -> Unit,
    onNotifications: () -> Unit,
    onSettings: () -> Unit,
    onSync: () -> Unit,
    onLogout: () -> Unit,
) {
    Column(modifier = Modifier.fillMaxSize()) {
        AppTopBar(
            title = "مساحة المحكمين",
            subtitle = buildString {
                append(user.fullName.ifBlank { user.username })
                user.exercise?.name?.let { append(" — $it") }
            },
            trailing = {
                Row {
                    IconButton(onClick = onSync) {
                        BadgedBox(badge = { if (pendingSync > 0) Badge { Text("$pendingSync") } }) {
                            Icon(Icons.Default.Sync, contentDescription = "مزامنة", tint = MaterialTheme.colorScheme.onPrimary)
                        }
                    }
                    IconButton(onClick = onNotifications) {
                        BadgedBox(badge = { if (unreadNotifications > 0) Badge { Text("$unreadNotifications") } }) {
                            Icon(Icons.Default.Notifications, contentDescription = "إشعارات", tint = MaterialTheme.colorScheme.onPrimary)
                        }
                    }
                    IconButton(onClick = onSettings) {
                        Icon(Icons.Default.Settings, contentDescription = "إعدادات", tint = MaterialTheme.colorScheme.onPrimary)
                    }
                    IconButton(onClick = onLogout) {
                        Icon(Icons.Default.Logout, contentDescription = "خروج", tint = MaterialTheme.colorScheme.onPrimary)
                    }
                    Icon(
                        if (online) Icons.Default.CloudQueue else Icons.Default.CloudOff,
                        contentDescription = if (online) "متصل" else "غير متصل",
                        tint = MaterialTheme.colorScheme.onPrimary,
                        modifier = Modifier.padding(start = 8.dp),
                    )
                }
            },
        )
        if (chiefItems.isNotEmpty()) {
            Text(
                "أوامر كبير المحكمين",
                modifier = Modifier.padding(20.dp, 16.dp, 20.dp, 8.dp),
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.primary,
            )
            LazyVerticalGrid(
                columns = GridCells.Adaptive(220.dp),
                contentPadding = PaddingValues(horizontal = 20.dp, vertical = 8.dp),
                horizontalArrangement = Arrangement.spacedBy(16.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
                modifier = Modifier.fillMaxWidth(),
            ) {
                items(chiefItems) { item ->
                    HubTile(title = item.title, modifier = Modifier.fillMaxWidth()) {
                        onHubClick(item.slug, true)
                    }
                }
            }
        }
        Text(
            "أوامر المحكمين",
            modifier = Modifier.padding(20.dp, 16.dp, 20.dp, 8.dp),
            style = MaterialTheme.typography.titleMedium,
            color = MaterialTheme.colorScheme.primary,
        )
        LazyVerticalGrid(
            columns = GridCells.Adaptive(220.dp),
            contentPadding = PaddingValues(20.dp),
            horizontalArrangement = Arrangement.spacedBy(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
            modifier = Modifier.fillMaxSize(),
        ) {
            items(judgeItems) { item ->
                HubTile(title = item.title, modifier = Modifier.fillMaxWidth()) {
                    onHubClick(item.slug, false)
                }
            }
        }
    }
}
