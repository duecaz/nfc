# NfcKit Usage

A Kotlin singleton utility for reading NFC card UIDs via the I2C bus.

## Dependencies

- `com.blankj:utilcodex:1.31.1` — provides `LogUtils`, `Utils`

## API Overview

| Method | Description |
|--------|-------------|
| `register(cb)` | Register a callback listener; card ID is returned via the callback |
| `unregister(cb)` | Unregister the callback listener |
| `startReadJob()` | Start the auto-read task (polls every 1 second) |
| `stopReadJob()` | Stop the auto-read task |
| `cardId` | Public property, the latest card ID read (hex string) |

## Callback Interface

```kotlin
interface IDataCallback {
    fun callback(cardId: String)
}
```

## Core Workflow

### 1. Reading Card UID

Two ways to obtain the card ID after initialization:

- **Auto-read**: Call `startReadJob()`. A coroutine polls every second and stores results in `NfcKit.cardId`.
- **Register a callback**: Call `register(callback)`. The callback receives `cardId` on every poll cycle.

> Without a registered callback, reading a non-`"0000"` card ID triggers built-in user switching / permission handling logic.

### 2. Auto-Read Task

```kotlin
// Start (no-op if already running)
NfcKit.startReadJob()

// Stop
NfcKit.stopReadJob()
```

- Runs on `CoroutineScope(SupervisorJob() + Dispatchers.IO)` (IO thread)
- Polls the I2C bus **every 1 second**
- Task is cancelable via `Job.cancel()`

### 3. Register / Unregister Callback

```kotlin
val callback = object : IDataCallback {
    override fun callback(cardId: String) {
        // Handle the card ID
    }
}

NfcKit.register(callback)   // Register
NfcKit.unregister(callback) // Unregister
```

- Once registered, `callback(cardId)` is invoked on each successful read
- When a callback is registered, the built-in user switching logic is **not** executed

## Usage Example

```kotlin
class MainActivity : AppCompatActivity() {

    private val nfcCallback = object : IDataCallback {
        override fun callback(cardId: String) {
            // Card ID is a hex UID string
            runOnUiThread {
                tvCardId.text = "Card UID: $cardId"
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

## Architecture

```
I2C Bus (4/7) ──→ TvControlManager.i2c_read()
                           │
                           ▼
                  NfcKit.readCardId()
          (reads 4 bytes, joins as hex string)
                           │
         ┌─────────────────┼──────────────────┐
         ▼                 ▼                  ▼
   Callback Registered   No Callback       cardId Property
   callback(cardId)      Auto user-switch   Latest card ID
```

- Hardware connects via I2C, register address `0x21` for reading
- Card ID consists of 4 bytes joined into a hex string (e.g. `"63dde350"`)
- Returns `"0000"` when no card is present or reading fails
