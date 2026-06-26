package com.test.hola

import android.content.Context
import android.provider.Settings
import android.util.Log
import dalvik.system.DexClassLoader
import kotlinx.coroutines.*
import java.lang.reflect.Method

interface IDataCallback {
    fun callback(cardId: String)
}

object NfcKit {
    private const val TAG = "NfcKit"
    private const val REGADDR_CARD_READ = 0x21
    private const val POLL_MS = 200L

    private val cs = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var autoJob: Job? = null
    private var callBack: IDataCallback? = null

    var cardId: String = ""
    var i2cAddr = 0xA6
    var i2cBus = 4

    private var tvManager: Any? = null
    private var i2cInitMethod: Method? = null
    private var i2cReadMethod: Method? = null

    fun init(ctx: Context) {
        val setting = try {
            Settings.Global.getInt(ctx.contentResolver, "dazzle_nfc_i2c_addr", 6)
        } catch (e: SecurityException) {
            Log.w(TAG, "dazzle_nfc_i2c_addr no accesible, usando default=6")
            6
        }
        i2cAddr = when (setting) { 6 -> 0xA6; 8 -> 0xA8; else -> 0xA2 }
        Log.i(TAG, "addr=0x${i2cAddr.toString(16)} bus=$i2cBus")

        loadTvControlManager(ctx)

        if (tvManager != null) {
            try {
                val initBus = if (i2cBus == 7) 7 else 6
                i2cInitMethod?.invoke(tvManager, initBus)
                Log.i(TAG, "i2c_init($initBus) OK")
            } catch (e: Throwable) {
                Log.e(TAG, "i2c_init error: ${e.cause?.message ?: e.message}")
            }
        }
    }

    private fun loadTvControlManager(ctx: Context) {
        val jars = listOf(
            "/system/framework/droidlogic.jar",
            "/system/framework/droidlogic-tv.jar",
            "/system/framework/droidlogic.software.core.jar",
            "/system/framework/droidlogic.tv.software.core.jar"
        )
        val cache = ctx.cacheDir.absolutePath
        for (path in jars) {
            if (!java.io.File(path).exists()) continue
            try {
                val loader = DexClassLoader(path, cache, null, ClassLoader.getSystemClassLoader())
                val cls = loader.loadClass("com.droidlogic.app.tv.TvControlManager")
                val getInstance = cls.getMethod("getInstance")
                tvManager = getInstance.invoke(null)
                i2cInitMethod = cls.getMethod("i2c_init", Int::class.java)
                i2cReadMethod = cls.getMethod("i2c_read",
                    Int::class.java, Int::class.java, Int::class.java,
                    Int::class.java, IntArray::class.java)
                Log.i(TAG, "TvControlManager cargado desde $path")
                return
            } catch (e: Throwable) {
                Log.w(TAG, "Fallo $path: ${e.javaClass.simpleName}: ${e.message}")
            }
        }
        Log.e(TAG, "TvControlManager NO encontrado en /system/framework/")
    }

    fun register(cb: IDataCallback) { callBack = cb }
    fun unregister(cb: IDataCallback) { callBack = null }

    fun startReadJob() {
        if (autoJob?.isActive == true) return
        autoJob = cs.launch {
            Log.i(TAG, "startReadJob bus=$i2cBus poll=${POLL_MS}ms manager=${tvManager != null}")
            var n = 0
            while (isActive) {
                val uid = readCardId()
                if (++n % 25 == 0) Log.d(TAG, "heartbeat #$n bus=$i2cBus")
                if (uid.isNotEmpty()) {
                    cardId = uid
                    callBack?.callback(uid)
                }
                delay(POLL_MS)
            }
        }
    }

    fun stopReadJob() { autoJob?.cancel(null) }

    private fun readCardId(): String {
        val method = i2cReadMethod ?: return ""
        val manager = tvManager ?: return ""
        return try {
            val temp = IntArray(6)
            val ret = method.invoke(manager, i2cBus, i2cAddr, REGADDR_CARD_READ, 5, temp) as Int
            if (ret == 0) {
                val uid = temp.take(4).joinToString("") { it.toString(16).padStart(2, '0') }
                if (uid != "00000000") uid else ""
            } else ""
        } catch (e: Throwable) {
            Log.e(TAG, "readCardId: ${e.cause?.message ?: e.message}")
            ""
        }
    }
}
