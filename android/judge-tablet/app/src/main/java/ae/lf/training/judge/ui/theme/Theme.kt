package ae.lf.training.judge.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

val Brown500 = Color(0xFF6B5A48)
val Brown400 = Color(0xFF8B7355)
val Brown300 = Color(0xFFA88F78)
val BeigeBg = Color(0xFFF5F0E8)
val SurfaceWhite = Color(0xFFFFFFFF)
val AccentBlue = Color(0xFF2E6DA4)
val SuccessGreen = Color(0xFF2E7D4F)
val UrgentRed = Color(0xFFB54A4A)

private val LightColors = lightColorScheme(
    primary = Brown500,
    onPrimary = Color.White,
    primaryContainer = Brown300,
    secondary = Brown400,
    background = BeigeBg,
    surface = SurfaceWhite,
    onBackground = Color(0xFF2E2823),
    onSurface = Color(0xFF2E2823),
    tertiary = AccentBlue,
)

@Composable
fun LFJudgeTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = LightColors,
        content = content,
    )
}
