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
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.foundation.layout.Box
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import ae.lf.training.judge.data.api.EvalListRowDto
import ae.lf.training.judge.ui.components.AppTopBar
import ae.lf.training.judge.ui.components.ZoomableSurface

@Composable
fun EvalUnitListsScreen(
    unitLabel: String,
    rows: List<EvalListRowDto>,
    error: String?,
    onOpenEval: (Int) -> Unit,
    onBack: () -> Unit,
) {
    Column(modifier = Modifier.fillMaxSize()) {
        AppTopBar(title = "قوائم التقييم", subtitle = unitLabel)
        TextButton(onClick = onBack, modifier = Modifier.padding(horizontal = 12.dp)) { Text("رجوع") }
        if (!error.isNullOrBlank()) {
            Text(error, color = MaterialTheme.colorScheme.error, modifier = Modifier.padding(16.dp))
        }
        ZoomableSurface(modifier = Modifier.weight(1f)) {
            LazyColumn(
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                items(rows) { row ->
                    Card(
                        modifier = Modifier.fillMaxWidth(),
                        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
                        elevation = CardDefaults.cardElevation(2.dp),
                    ) {
                        Column(Modifier.padding(16.dp)) {
                            Text(row.title, fontWeight = FontWeight.SemiBold)
                            Text("الحالة: ${row.statusLabel} — ${row.dispatchLabel}", modifier = Modifier.padding(top = 6.dp))
                            Text("التقدير: ${row.gradeLabel.ifBlank { "—" }}", modifier = Modifier.padding(top = 4.dp))
                            TextButton(onClick = { onOpenEval(row.itemId) }) {
                                Text("فتح التقييم")
                            }
                        }
                    }
                }
            }
        }
    }
}

data class EvalRowUi(
    val index: Int,
    val rowKind: String,
    val element: String,
    val maxVal: String,
    var acquired: String,
    var notes: String,
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun AcquiredScoreField(
    value: String,
    options: List<Pair<String, String>>,
    enabled: Boolean,
    onSelect: (String) -> Unit,
) {
    if (options.isEmpty()) {
        OutlinedTextField(
            value = value,
            onValueChange = { if (enabled) onSelect(it) },
            label = { Text("المكتسبة") },
            enabled = enabled,
            modifier = Modifier.fillMaxWidth(),
        )
        return
    }
    var expanded by remember { mutableStateOf(false) }
    val display = options.find { it.first == value }?.second ?: value.ifBlank { "—" }
    ExposedDropdownMenuBox(
        expanded = expanded,
        onExpandedChange = { if (enabled) expanded = !expanded },
        modifier = Modifier.fillMaxWidth(),
    ) {
        OutlinedTextField(
            value = display,
            onValueChange = {},
            readOnly = true,
            label = { Text("المكتسبة") },
            enabled = enabled,
            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = expanded) },
            modifier = Modifier
                .menuAnchor()
                .fillMaxWidth(),
        )
        DropdownMenu(
            expanded = expanded,
            onDismissRequest = { expanded = false },
        ) {
            options.forEach { (optValue, optLabel) ->
                DropdownMenuItem(
                    text = { Text(optLabel) },
                    onClick = {
                        onSelect(optValue)
                        expanded = false
                    },
                )
            }
        }
    }
}

@Composable
fun EvalDetailScreen(
    title: String,
    unitLabel: String,
    workflowLabel: String,
    rows: List<EvalRowUi>,
    acquiredOptions: List<Pair<String, String>>,
    canEdit: Boolean,
    canApprove: Boolean,
    canChiefApprove: Boolean,
    canChiefReopen: Boolean,
    message: String?,
    onRowChange: (Int, String, String) -> Unit,
    onSave: () -> Unit,
    onApprove: () -> Unit,
    onChiefApprove: () -> Unit,
    onChiefReopen: () -> Unit,
    onBack: () -> Unit,
) {
    Column(modifier = Modifier.fillMaxSize()) {
        AppTopBar(title = title, subtitle = "$unitLabel — $workflowLabel")
        TextButton(onClick = onBack, modifier = Modifier.padding(horizontal = 12.dp)) { Text("رجوع") }
        if (!message.isNullOrBlank()) {
            Text(message, modifier = Modifier.padding(horizontal = 16.dp), color = MaterialTheme.colorScheme.primary)
        }
        ZoomableSurface(modifier = Modifier.weight(1f)) {
            LazyColumn(contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                items(rows.size) { i ->
                    val row = rows[i]
                    val isSection = row.rowKind == "section"
                    Card(
                        modifier = Modifier.fillMaxWidth(),
                        colors = CardDefaults.cardColors(
                            containerColor = if (isSection) {
                                MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.35f)
                            } else {
                                MaterialTheme.colorScheme.surface
                            },
                        ),
                    ) {
                        Column(Modifier.padding(12.dp)) {
                            Text(
                                row.element,
                                fontWeight = if (isSection) FontWeight.Bold else FontWeight.Medium,
                            )
                            if (!isSection) {
                                Text("القصوى: ${row.maxVal}", style = MaterialTheme.typography.bodySmall)
                                AcquiredScoreField(
                                    value = row.acquired,
                                    options = acquiredOptions,
                                    enabled = canEdit,
                                    onSelect = { onRowChange(i, it, row.notes) },
                                )
                                OutlinedTextField(
                                    value = row.notes,
                                    onValueChange = { if (canEdit) onRowChange(i, row.acquired, it) },
                                    label = { Text("ملاحظات") },
                                    enabled = canEdit,
                                    modifier = Modifier.fillMaxWidth(),
                                )
                            }
                        }
                    }
                }
            }
        }
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            if (canEdit) Button(onClick = onSave) { Text("حفظ") }
            if (canApprove) Button(onClick = onApprove) { Text("إرسال للاعتماد") }
            if (canChiefApprove) Button(onClick = onChiefApprove) { Text("اعتماد كبير المحكمين") }
            if (canChiefReopen) Button(onClick = onChiefReopen) { Text("إعادة للمحكم") }
        }
    }
}
