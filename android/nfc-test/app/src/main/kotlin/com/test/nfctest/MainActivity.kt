package com.test.hola

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

    private val REGADDR = 0x21
    private var i2cAddr = 0xA2
    private var i2cBus = 4

    private lateinit var tvUid: TextView
    private lateinit var tvStatus: TextView
    private lateinit var tvLog: TextView
    private lateinit var btnBus: Button

    private val log = ArrayDeque<String>()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        tvUid    = findViewById(R.id.tv_uid)
        tvStatus = findViewById(R.id.tv_status)
        tvLog    = findViewById(R.id.tv_log)
        btnBus   = findViewById(R.id.btn_bus)

        val setting = Settings.Global.getInt(contentResolver, "dazzle_nfc_i2c_addr", 6)
        i2cAddr = when (setting) { 6 -> 0xA6; 8 -> 0xA8; else -> 0xA2 }
        addLog("i2c_addr setting=$setting → 0x${i2cAddr.toString(16)}")

        btnBus.setOnClickListener {
            i2cBus = if (i2cBus == 4) 7 else 4
            btnBus.text = "Bus: $i2cBus"
            addLog("Cambiando a bus $i2cBus")
            initI2c()
            startReading()
        }

        initI2c()
    }

    private fun initI2c() {
        try {
            TvControlManager.getInstance().i2c_init(i2cBus)
            addLog("i2c_init(bus=$i2cBus) OK")
            runOnUiThread { tvStatus.text = "I2C OK  bus=$i2cBus  addr=0x${i2cAddr.toString(16)}" }
        } catch (e: Throwable) {
            addLog("ERROR init: ${e.javaClass.simpleName}: ${e.message}")
            runOnUiThread { tvStatus.text = "ERROR: ${e.message}" }
        }
    }

    override fun onResume() {
        super.onResume()
        startReading()
    }

    override fun onPause() {
        super.onPause()
        readJob?.cancel()
    }

    override fun onDestroy() {
        super.onDestroy()
        scope.cancel()
    }

    private fun startReading() {
        readJob?.cancel()
        readJob = scope.launch {
            while (isActive) {
                try {
                    val temp = IntArray(6)
                    val ret = TvControlManager.getInstance()
                        .i2c_read(i2cBus, i2cAddr, REGADDR, 5, temp)
                    val uid = if (ret == 0)
                        temp.take(4).joinToString("") { it.toString(16).padStart(2, '0') }
                    else ""

                    withContext(Dispatchers.Main) {
                        when {
                            uid.isNotEmpty() && uid != "00000000" -> {
                                tvUid.text = uid.uppercase()
                                tvStatus.text = "Tarjeta detectada"
                                addLog("UID: ${uid.uppercase()}")
                                Log.d("NFCTest", "UID=$uid")
                            }
                            else -> tvStatus.text = "Esperando tarjeta...  bus=$i2cBus"
                        }
                    }
                } catch (e: Throwable) {
                    addLog("ERROR lectura: ${e.javaClass.simpleName}")
                    Log.e("NFCTest", "i2c_read error", e)
                }
                delay(1_000)
            }
        }
    }

    private fun addLog(msg: String) {
        runOnUiThread {
            log.addLast(msg)
            if (log.size > 12) log.removeFirst()
            tvLog.text = log.joinToString("\n")
        }
    }
}
