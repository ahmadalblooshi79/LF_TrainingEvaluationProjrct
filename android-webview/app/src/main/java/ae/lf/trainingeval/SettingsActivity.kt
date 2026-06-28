package ae.lf.trainingeval

import android.content.Intent
import android.os.Bundle
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import ae.lf.trainingeval.databinding.ActivitySettingsBinding
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors

class SettingsActivity : AppCompatActivity() {
    private lateinit var binding: ActivitySettingsBinding
    private val executor = Executors.newSingleThreadExecutor()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivitySettingsBinding.inflate(layoutInflater)
        setContentView(binding.root)

        supportActionBar?.setDisplayHomeAsUpEnabled(true)
        title = getString(R.string.settings_title)

        binding.inputHost.setText(ServerConfig.getHost(this))
        binding.inputPort.setText(ServerConfig.getPort(this))
        binding.currentUrl.text = ServerConfig.serverUrl(this)

        binding.btnSave.setOnClickListener { saveAndReturn() }
        binding.btnTest.setOnClickListener { testConnection() }
        binding.btnReset.setOnClickListener {
            binding.inputHost.setText(ServerConfig.DEFAULT_HOST)
            binding.inputPort.setText(ServerConfig.DEFAULT_PORT)
        }
    }

    private fun saveAndReturn() {
        val host = binding.inputHost.text?.toString()?.trim().orEmpty()
        val port = binding.inputPort.text?.toString()?.trim().orEmpty()

        if (host.isEmpty() || port.isEmpty()) {
            Toast.makeText(this, R.string.settings_invalid, Toast.LENGTH_SHORT).show()
            return
        }

        ServerConfig.save(this, host, port)
        Toast.makeText(this, R.string.settings_saved, Toast.LENGTH_SHORT).show()

        val intent = Intent(this, MainActivity::class.java).apply {
            addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP)
            putExtra(EXTRA_RELOAD, true)
        }
        startActivity(intent)
        finish()
    }

    private fun testConnection() {
        val host = binding.inputHost.text?.toString()?.trim().orEmpty()
        val port = binding.inputPort.text?.toString()?.trim().orEmpty()
        if (host.isEmpty() || port.isEmpty()) {
            Toast.makeText(this, R.string.settings_invalid, Toast.LENGTH_SHORT).show()
            return
        }

        val url = "http://$host:$port/"
        binding.btnTest.isEnabled = false
        executor.execute {
            val ok = runCatching {
                val connection = URL(url).openConnection() as HttpURLConnection
                connection.connectTimeout = 5000
                connection.readTimeout = 5000
                connection.requestMethod = "GET"
                connection.instanceFollowRedirects = true
                val code = connection.responseCode
                connection.disconnect()
                code in 200..399
            }.getOrDefault(false)

            runOnUiThread {
                binding.btnTest.isEnabled = true
                Toast.makeText(
                    this,
                    if (ok) R.string.test_ok else R.string.test_failed,
                    Toast.LENGTH_LONG,
                ).show()
            }
        }
    }

    override fun onSupportNavigateUp(): Boolean {
        finish()
        return true
    }

    override fun onDestroy() {
        executor.shutdownNow()
        super.onDestroy()
    }

    companion object {
        const val EXTRA_RELOAD = "extra_reload"
    }
}
