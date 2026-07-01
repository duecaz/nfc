package com.riotouch.setting.user.utils

import android.provider.Settings
import android.util.Log
import com.blankj.utilcode.util.LogUtils
import com.blankj.utilcode.util.Utils
import com.droidlogic.app.tv.TvControlManager
import com.riotouch.setting.user.data.findUserIdByNfcId
import com.riotouch.setting.user.data.getAllNfcInfo
import com.riotouch.setting.utils.VersionKit
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch


object NfcKit {
    private var cs = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var autoJob: Job? = null
    private var callBack: IDataCallback? = null
    var cardId: String = ""

    val REGADDR_CARD: Int = 0x20
    val REGADDR_CARD_READ: Int = 0x21
    val CARD_ID_ADD: Int = 0x58
    val CARD_ID_DELETE: Int = 0x59
    val CARD_POWER_ON_ID: Int = 0x60
    val CARD_ID_ALL_DELETE: Int = 0x61
    val CARD_ID_RECEIVE: Int = 0x62
    var card_id = IntArray(6)
    var i2c_addr = 0xA2
    const val TAG = "NfcKit"

    init {
        val dazzle_nfc_i2c_addr = Settings.Global.getInt(Utils.getApp().contentResolver, "dazzle_nfc_i2c_addr", 6)
        LogUtils.a("I2cCardInteractive", String.format("dazzle_nfc_i2c_addr: %x", dazzle_nfc_i2c_addr))
        if (dazzle_nfc_i2c_addr == 6) {
            i2c_addr = 0xA6
        } else if (dazzle_nfc_i2c_addr == 8) {
            i2c_addr = 0xA8
        }
        if (VersionKit.is3576V2) {
            TvControlManager.getInstance().i2c_init(7);
        } else {
            TvControlManager.getInstance().i2c_init(6);
        }
    }

    fun register(cb: IDataCallback) {
        log { Log.i(TAG, "注册") }
        callBack = cb
    }

    fun unregister(cb: IDataCallback) {
        log { Log.i(TAG, "反注册") }
        callBack = null

    }


    fun startReadJob() {
        if (autoJob?.isActive == true) {
            return
        }
        autoJob = cs.launch {
            log { Log.i(TAG, "autoJob-start") }
            var nextTime = 0L
            while (isActive) {
                //检查时间
                if (System.currentTimeMillis() > nextTime) {
                    nextTime = System.currentTimeMillis() + 1_000
                    cardId = readCardId()
                    log { Log.i(TAG, "读取卡号-$cardId") }
                    if (callBack != null) {
                        callBack?.callback(cardId)
                    } else {
                        if (cardId != "0000") {
                            //切换用户
                            getAllNfcInfo().forEach { nfcInfo ->
                                if (nfcInfo.id == cardId) {
                                    val userId = findUserIdByNfcId(nfcInfo.id)
                                    if (userId != UserUtils.curUserId) {
                                        UserUtils.switchUser(userId)
                                    } else {
                                        //权限
                                        PermissionKit.handlePermissions(PermissionType.NFC, cardId)
                                    }
                                }
                            }

                        }
                    }
                }
            }
            log { Log.i(TAG, "autoJob-stop") }
        }

    }

    fun stopReadJob() {
        LogUtils.a("读取nfc", "关")
        autoJob?.cancel(null)
    }


    private fun readCardId(): String {
        //63dde350
        var result = ""
        val temp = IntArray(6)
        var ret = -1
        if (VersionKit.is3576V2) {
            ret = TvControlManager.getInstance().i2c_read(7, i2c_addr, REGADDR_CARD_READ, 5, temp)
        } else {
            ret = TvControlManager.getInstance().i2c_read(4, i2c_addr, REGADDR_CARD_READ, 5, temp)
        }

        if (ret == 0) {
            for (i in 0..3) {
                //取value的一个低位byte并将高位清零,转成int
                val curr = (0 shl 8) or (temp[i] and 0xFF)
                temp[i] = 0 or (temp[i] and 0xff)
            }
            result = temp.take(4).joinToString("") { it.toString(16) }
            return result
        } else {
            return result
        }
    }


    fun cardCommandControl(id: String, com: String) {
        val dataid = id.toInt(16).toLong()
        val data = ArrayList<Byte>()
        for (i in 0..3) {
            card_id[4 - i] = (dataid shr (8 * i) and 0xFFL).toInt()
            //Log.d("I2cCardInteractive", String.format("card_id: %x", card_id[i]))
        }
        //Log.d("I2cCardInteractive", String.format("i2c_addr: %x", i2c_addr))
        when (com) {
            "read" -> {}
            "add" -> card_id[0] = CARD_ID_ADD
            "del" -> card_id[0] = CARD_ID_DELETE
            "alldel" -> card_id[0] = CARD_ID_ALL_DELETE
            "getid" -> card_id[0] = CARD_ID_RECEIVE
            else -> {}
        }

        card_id.toList().forEach { data.add(it.toByte()) }
        //第一参数：第4路总线，第二参数：设备地址，第三参数：设备寄存器的地址，第四个数据长度，第五个参数，卡号数据+动作
        if (VersionKit.is3576V2) {
            TvControlManager.getInstance().i2c_write(7, i2c_addr, REGADDR_CARD, 5, data)
        } else {
            TvControlManager.getInstance().i2c_write(4, i2c_addr, REGADDR_CARD, 5, data)
        }
    }

    fun log(f: () -> Unit) {
        if (FingerprintKit.switchLog) {
            f.invoke()
        }
    }


}