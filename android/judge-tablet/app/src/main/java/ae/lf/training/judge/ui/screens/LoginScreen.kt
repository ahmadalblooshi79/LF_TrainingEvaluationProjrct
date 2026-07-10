package ae.lf.training.judge.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import ae.lf.training.judge.ui.components.AppTopBar

@Composable
fun LoginScreen(
    username: String,
    password: String,
    loading: Boolean,
    error: String?,
    onUsernameChange: (String) -> Unit,
    onPasswordChange: (String) -> Unit,
    onLogin: () -> Unit,
    onOpenSettings: () -> Unit,
) {
    Column(modifier = Modifier.fillMaxSize()) {
        AppTopBar(title = "نظام إدارة التمارين", subtitle = "دخول المحكمين")
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(32.dp),
            verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            OutlinedTextField(
                value = username,
                onValueChange = onUsernameChange,
                label = { Text("اسم المستخدم") },
                modifier = Modifier.fillMaxWidth(0.6f),
                singleLine = true,
                keyboardOptions = KeyboardOptions.Default,
            )
            Spacer(Modifier.height(16.dp))
            OutlinedTextField(
                value = password,
                onValueChange = onPasswordChange,
                label = { Text("كلمة المرور") },
                modifier = Modifier.fillMaxWidth(0.6f),
                singleLine = true,
                visualTransformation = PasswordVisualTransformation(),
            )
            if (!error.isNullOrBlank()) {
                Spacer(Modifier.height(12.dp))
                Text(error, color = androidx.compose.material3.MaterialTheme.colorScheme.error)
            }
            Spacer(Modifier.height(24.dp))
            if (loading) {
                CircularProgressIndicator()
            } else {
                Button(onClick = onLogin, modifier = Modifier.fillMaxWidth(0.4f)) {
                    Text("دخول")
                }
            }
            TextButton(onClick = onOpenSettings) {
                Text("إعدادات السيرفر")
            }
        }
    }
}
