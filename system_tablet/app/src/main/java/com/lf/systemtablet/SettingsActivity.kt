package com.lf.systemtablet

import android.content.Intent
import android.os.Bundle
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.lf.systemtablet.databinding.ActivitySettingsBinding

class SettingsActivity : AppCompatActivity() {

    private lateinit var binding: ActivitySettingsBinding
    private lateinit var prefs: ServerPrefs

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = ServerPrefs(this)
        binding = ActivitySettingsBinding.inflate(layoutInflater)
        setContentView(binding.root)

        binding.inputHost.setText(prefs.host)
        binding.inputPort.setText(prefs.port.toString())

        binding.btnSave.setOnClickListener { save() }
    }

    private fun save() {
        val host = binding.inputHost.text?.toString()?.trim().orEmpty()
        val portText = binding.inputPort.text?.toString()?.trim().orEmpty()
        val pin = binding.inputPin.text?.toString().orEmpty()

        if (host.isBlank()) {
            Toast.makeText(this, "أدخل عنوان IP", Toast.LENGTH_SHORT).show()
            return
        }
        val port = portText.toIntOrNull()
        if (port == null || port !in 1..65535) {
            Toast.makeText(this, "منفذ غير صالح", Toast.LENGTH_SHORT).show()
            return
        }
        // عند أول إعداد لا يُطلب PIN؛ عند التعديل من الشاشة المحمية يكون المستخدم قد مرّ بالـ PIN
        if (prefs.configured && pin.isNotBlank() && pin != BuildConfig.SETTINGS_PIN) {
            Toast.makeText(this, "رمز الحماية غير صحيح", Toast.LENGTH_SHORT).show()
            return
        }

        prefs.host = host
        prefs.port = port
        prefs.configured = true
        Toast.makeText(this, "تم الحفظ", Toast.LENGTH_SHORT).show()
        startActivity(
            Intent(this, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_NEW_TASK),
        )
        finish()
    }
}
