# NfcKit 使用文档

基于 I2C 总线读取 NFC 卡片 UID 的工具类（Kotlin 单例）。

## 依赖

- `com.blankj:utilcodex:1.31.1` — 提供 `LogUtils`、`Utils` 工具

## API 概览

| 方法 | 说明 |
|------|------|
| `register(cb)` | 注册回调监听，读取到卡号后通过回调返回 |
| `unregister(cb)` | 取消回调监听 |
| `startReadJob()` | 开启自动读取任务（每秒轮询一次） |
| `stopReadJob()` | 停止自动读取任务 |
| `cardId` | 公开属性，当前读取到的最新卡号（16进制字符串） |

## 回调接口

```kotlin
interface IDataCallback {
    fun callback(cardId: String)
}
```

## 核心流程

### 1. 读取卡片 UID

初始化后可通过两种方式获取卡号：

- **自动读取**：调用 `startReadJob()`，利用协程每秒自动轮询，读到的卡号存入 `NfcKit.cardId`。
- **注册回调监听**：调用 `register(callback)` 后，每次轮询读到卡号时会回调 `callback(cardId)`。

> 若未注册回调，读到非 `"0000"` 卡号时会自动进入用户切换 / 权限处理逻辑。

### 2. 自动读取任务

```kotlin
// 启动（已在运行时不会重复启动）
NfcKit.startReadJob()

// 停止
NfcKit.stopReadJob()
```

- 内部使用 `CoroutineScope(SupervisorJob() + Dispatchers.IO)` 在 IO 线程执行
- 每 **1 秒** 通过 I2C 总线读取一次卡号
- 任务可取消（`Job.cancel()`）

### 3. 注册 / 取消监听

```kotlin
val callback = object : IDataCallback {
    override fun callback(cardId: String) {
        // 处理读到的卡号
    }
}

NfcKit.register(callback)   // 注册
NfcKit.unregister(callback) // 取消注册
```

- 注册后，自动读取任务每次读到卡号都会调用 `callback(cardId)`
- 若已注册回调，则 **不会** 自动执行用户切换逻辑

## 使用示例

```kotlin
class MainActivity : AppCompatActivity() {

    private val nfcCallback = object : IDataCallback {
        override fun callback(cardId: String) {
            // 收到刷卡事件，cardId 为 16 进制 UID 字符串
            runOnUiThread {
                tvCardId.text = "卡片 UID: $cardId"
            }
        }
    }

    override fun onResume() {
        super.onResume()
        NfcKit.register(nfcCallback)
        NfcKit.startReadJob()
    }

    override fun onPause() {
        super.onPause()
        NfcKit.stopReadJob()
        NfcKit.unregister(nfcCallback)
    }
}
```

## 架构说明

```
I2C 总线 (bus 4/7) ──→ TvControlManager.i2c_read()
                              │
                              ▼
                     NfcKit.readCardId()
                     (读取 4 字节，拼为 16 进制字符串)
                              │
            ┌─────────────────┼──────────────────┐
            ▼                 ▼                  ▼
     已注册回调           未注册回调           cardId 属性
   callback(cardId)    自动用户切换逻辑      最新卡号
```

- 硬件通过 I2C 连接，寄存器地址 `0x21` 用于读卡
- 卡号由 4 字节组成，拼接为 16 进制字符串（如 `"63dde350"`）
- 返回值 `"0000"` 表示无卡或读卡失败
