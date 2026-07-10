package ae.lf.training.judge

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import ae.lf.training.judge.ui.JudgeRoot
import ae.lf.training.judge.ui.theme.LFJudgeTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val container = (application as JudgeApp).container
        setContent {
            LFJudgeTheme {
                JudgeRoot(container)
            }
        }
    }
}
