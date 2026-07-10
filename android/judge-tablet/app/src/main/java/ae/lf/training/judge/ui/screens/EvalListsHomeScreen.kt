package ae.lf.training.judge.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ScrollableTabRow
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import ae.lf.training.judge.data.api.PhaseTabDto
import ae.lf.training.judge.ui.components.AppTopBar

@Composable
fun EvalListsHomeScreen(
    tabs: List<PhaseTabDto>,
    selectedIndex: Int,
    loading: Boolean,
    error: String?,
    onTabSelect: (Int) -> Unit,
    onUnitClick: (String, String) -> Unit,
    onBack: () -> Unit,
) {
    Column(modifier = Modifier.fillMaxSize()) {
        AppTopBar(title = "قوائم التقييم", subtitle = "اختر مستوى الوحدة")
        TextButton(onClick = onBack, modifier = Modifier.padding(horizontal = 12.dp)) { Text("رجوع") }
        if (tabs.isNotEmpty()) {
            ScrollableTabRow(selectedTabIndex = selectedIndex) {
                tabs.forEachIndexed { i, tab ->
                    Tab(
                        selected = i == selectedIndex,
                        onClick = { onTabSelect(i) },
                        text = {
                            Text("${tab.phaseLabel} (${tab.totals.total})")
                        },
                    )
                }
            }
        }
        if (!error.isNullOrBlank()) {
            Text(error, color = MaterialTheme.colorScheme.error, modifier = Modifier.padding(16.dp))
        }
        val tab = tabs.getOrNull(selectedIndex)
        LazyColumn(
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
            modifier = Modifier.fillMaxSize(),
        ) {
            items(tab?.unitRows.orEmpty()) { unit ->
                Card(
                    onClick = { onUnitClick(unit.key, tab?.phaseKey.orEmpty()) },
                    modifier = Modifier.fillMaxWidth(),
                    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
                    elevation = CardDefaults.cardElevation(3.dp),
                ) {
                    Column(Modifier.padding(20.dp)) {
                        Text(unit.label, fontWeight = FontWeight.Bold, style = MaterialTheme.typography.titleMedium)
                        Text(
                            "قوائم: ${unit.totalCount} | غير منجزة: ${unit.notDoneCount}",
                            style = MaterialTheme.typography.bodyMedium,
                            modifier = Modifier.padding(top = 8.dp),
                        )
                    }
                }
            }
        }
    }
}
