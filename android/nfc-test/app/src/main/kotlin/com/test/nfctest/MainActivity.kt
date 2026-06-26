package com.test.nfctest

import android.app.Activity
import android.os.Bundle
import android.provider.Settings
import android.util.Log
import android.widget.Button
import android.widget.TextView
import com.droidlogic.app.tv.TvControlManager
import kotlinx.coroutines.*

class MainActivity : Activity() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var readJob: Job? = null

    // Registros I2C del lector NFC del panel
    private val REGADDR_CARD_READ = 0x21
    private var i2cAddr = 0xA2
    private var i2cBus = 4   // 4 = normal, 7 = rk3576v2

    private lateinit var tvUid: TextView
    private lateinit var tvRaw: TextView
    private lateinit var tvStatus: TextView
    private lateinit var tvLog: TextView
    private lateinit var btnBus: Button

    private val logLines = ArrayDeque<String>()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        tvUid    = findViewById(R.id.tv_uid)
        tvRaw    = findViewById(R.id.tv_raw)
        tvStatus = findViewById(R.id.tv_status)
        tvLog    = findViewById(R.id.tv_log)
        btnBus   = findViewById(R.id.btn_bus)

        // Leer configuración de dirección I2C igual que NfcKit
        val setting = Settings.Global.getInt(contentResolver, "dazzle_nfc_i2c_addr", 6)
        i2cAddr = when (setting) {
            6 -> 0xA6
            8 -> 0xA8
            else -> 0xA2
        }
        addLog("dazzle_nfc_i2c_addr=$setting → addr=0x${i2cAddr.toString(16)}")

        btnBus.text = "Bus actual: $i2cBus"
        btnBus.setOnClickListener {
            // Alternar entre bus 4 y 7 para probar
            i2cBus = if (i2cBus == 4) 7 else 4
            btnBus.text = "Bus actual: $i2cBus"
            addLog("Cambiando a bus $i2cBus")
            initI2c()
            restartReading()
        }

        initI2c()
    }

    private fun initI2c() {
        try {
            TvControlManager.getInstance().i2c_init(i2cBus)
            addLog("i2c_init(bus=$i2cBus) OK")
            tvStatus.text = "I2C OK — bus=$i2cBus addr=0x${i2cAddr.toString(16)}"
        } catch (e: Throwable) {
            addLog("i2c_init ERROR: ${e.javaClass.simpleName}: ${e.message}")
            tvStatus.text = "ERROR init: ${e.message}"
        }
    }

    override fun onResume() {
        super.onResume()
        restartReading()
    }

    override fun onPause() {
        super.onPause()
        readJob?.cancel()
    }

    override fun onDestroy() {
        super.onDestroy()
        scope.cancel()
    }

    private fun restartReading() {
        readJob?.cancel()
        readJob = scope.launch {
            addLog("Leyendo cada 1s...")
            while (isActive) {
                val (uid, raw, ret) = readCardId()
                withContext(Dispatchers.Main) {
                    tvRaw.text = "ret=$ret  ${raw.take(5).joinToString(" ") { "0x${it.toString(16).padStart(2,'0')}" }}"
                    when {
                        uid.startsWith("ERR") -> {
                            tvStatus.text = uid
                        }
                        uid.isEmpty() || uid == "0000" -> {
                            tvStatus.text = "Sin tarjeta  bus=$i2cBus  ret=$ret"
                        }
                        else -> {
                            tvUid.text = uid.uppercase()
                            tvStatus.text = "Tarjeta detectada!"
                            addLog("UID: ${uid.uppercase()}")
                            Log.d("NFCTest", "UID=${uid.uppercase()} raw=${raw.take(5)}")
                        }
                    }
                }
                delay(1_000)
            }
        }
    }

    private fun readCardId(): Triple<String, IntArray, Int> {
        return try {
            val temp = IntArray(6)
            val ret = TvControlManager.getInstance()
                .i2c_read(i2cBus, i2cAddr, REGADDR_CARD_READ, 5, temp)
            val uid = if (ret == 0) {
                temp.take(4).joinToString("") { it.toString(16).padStart(2, '0') }
            } else ""
            Triple(uid, temp, ret)
        } catch (e: Throwable) {
            Log.e("NFCTest", "i2c_read: ${e.message}")
            Triple("ERR:${e.javaClass.simpleName}", IntArray(6), -99)
        }
    }

    private fun addLog(msg: String) {
        runOnUiThread {
            logLines.addLast(msg)
            if (logLines.size > 14) logLines.removeFirst()
            tvLog.text = logLines.joinToString("\n")
        }
    }
}
