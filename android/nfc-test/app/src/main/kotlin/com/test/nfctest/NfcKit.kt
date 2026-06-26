package com.test.hola

import android.content.Context
import android.provider.Settings
import android.util.Log
import com.droidlogic.app.tv.TvControlManager
import kotlinx.coroutines.*

interface IDataCallback {
    fun callback(cardId: String)
}

object NfcKit {
    private const val TAG = "NfcKit"
    private const val REGADDR_CARD_READ = 0x21
    private const val POLL_MS = 200L  // 200ms para ganarle a dazzle_nfc (que lee cada ~1s)

    private val cs = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var autoJob: Job? = null
    private var callBack: IDataCallback? = null

    var cardId: String = ""
    var i2cAddr = 0xA6   // default 0xA6 (setting=6)
    var i2cBus = 4       // 4 = default, 7 = rk3576v2

    fun init(ctx: Context) {
        val setting = try {
            Settings.Global.getInt(ctx.contentResolver, "dazzle_nfc_i2c_addr", 6)
        } catch (e: SecurityException) {
            Log.w(TAG, "dazzle_nfc_i2c_addr no accesible, usando default=6 (0xA6)")
            6
        }
        i2cAddr = when (setting) { 6 -> 0xA6; 8 -> 0xA8; else -> 0xA2 }
        Log.i(TAG, "dazzle_nfc_i2c_addr=$setting addr=0x${i2cAddr.toString(16)} bus=$i2cBus")
        try {
            val initBus = if (i2cBus == 7) 7 else 6
            TvControlManager.getInstance().i2c_init(initBus)
            Log.i(TAG, "i2c_init($initBus) OK")
        } catch (e: Throwable) {
            Log.e(TAG, "i2c_init error: ${e.javaClass.simpleName}: ${e.message}")
        }
    }

    fun register(cb: IDataCallback) { callBack = cb }
    fun unregister(cb: IDataCallback) { callBack = null }

    fun startReadJob() {
        if (autoJob?.isActive == true) return
        autoJob = cs.launch {
            Log.i(TAG, "startReadJob bus=$i2cBus poll=${POLL_MS}ms")
            while (isActive) {
                val uid = readCardId()
                if (uid.isNotEmpty()) {
                    cardId = uid
                    callBack?.callback(uid)
                }
                delay(POLL_MS)
            }
            Log.i(TAG, "stopReadJob")
        }
    }

    fun stopReadJob() { autoJob?.cancel(null) }

    private fun readCardId(): String {
        return try {
            val temp = IntArray(6)
            val ret = TvControlManager.getInstance()
                .i2c_read(i2cBus, i2cAddr, REGADDR_CARD_READ, 5, temp)
            if (ret == 0) {
                val uid = temp.take(4).joinToString("") { it.toString(16).padStart(2, '0') }
                if (uid != "00000000") uid else ""
            } else ""
        } catch (e: Throwable) {
            Log.e(TAG, "readCardId error: ${e.javaClass.simpleName}: ${e.message}")
            ""
        }
    }
}
