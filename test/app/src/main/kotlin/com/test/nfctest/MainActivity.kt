package com.test.hola

import android.app.Activity
import android.os.Bundle
import android.widget.Button
import android.widget.TextView

class MainActivity : Activity() {

    private lateinit var tvUid: TextView
    private lateinit var tvStatus: TextView
    private lateinit var tvLog: TextView
    private lateinit var btnBus: Button

    private val logLines = ArrayDeque<String>()

    private val nfcCallback = object : IDataCallback {
        override fun callback(cardId: String) {
            runOnUiThread {
                when {
                    cardId == "ERR" -> {
                        tvStatus.text = "ERROR I2C - cambiar bus"
                        addLog("Error TvControlManager bus=${NfcKit.i2cBus}")
                    }
                    cardId.isNotEmpty() && cardId != "00000000" -> {
                        tvUid.text = cardId.uppercase()
                        tvStatus.text = "Tarjeta detectada!"
                        addLog("UID: ${cardId.uppercase()}")
                    }
                    else -> {
                        tvStatus.text = "Esperando tarjeta...  bus=${NfcKit.i2cBus}  addr=0x${NfcKit.i2cAddr.toString(16)}"
                    }
                }
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        tvUid    = findViewById(R.id.tv_uid)
        tvStatus = findViewById(R.id.tv_status)
        tvLog    = findViewById(R.id.tv_log)
        btnBus   = findViewById(R.id.btn_bus)

        NfcKit.init(this)
        addLog("Init: addr=0x${NfcKit.i2cAddr.toString(16)}  bus=${NfcKit.i2cBus}")

        btnBus.text = "Bus: ${NfcKit.i2cBus}"
        btnBus.setOnClickListener {
            NfcKit.stopReadJob()
            NfcKit.i2cBus = when (NfcKit.i2cBus) { 4 -> 6; 6 -> 7; else -> 4 }
            btnBus.text = "Bus: ${NfcKit.i2cBus}"
            NfcKit.init(this)
            addLog("Bus cambiado a ${NfcKit.i2cBus}")
            NfcKit.startReadJob()
        }
    }

    override fun onResume() {
        super.onResume()                  // segun NFCKit-Usage.md
        NfcKit.register(nfcCallback)
        NfcKit.startReadJob()
    }

    override fun onPause() {
        super.onPause()                   // segun NFCKit-Usage.md
        NfcKit.stopReadJob()
        NfcKit.unregister(nfcCallback)
    }

    private fun addLog(msg: String) {
        logLines.addLast(msg)
        if (logLines.size > 12) logLines.removeFirst()
        tvLog.text = logLines.joinToString("\n")
    }
}
