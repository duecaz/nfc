# Lectura NFC en el panel Amlogic/Rockchip via `droidlogic.jar`

> Documentación de cómo se lee la tarjeta NFC del panel desde **.NET (Visual
> Studio)** y desde **Android Studio (Kotlin)**, por qué funciona, y qué más
> ofrece `droidlogic.jar` (incluida la opción de **bloqueo de hardware**).

---

## 1. Resumen en una frase

El lector NFC del panel **no es NFC estándar de Android**: es un chip conectado
por **bus I2C** que se controla con la clase `com.droidlogic.app.tv.TvControlManager`
del firmware del panel (`/system/framework/droidlogic.jar`). Se lee llamando
`i2c_read(...)` y formateando los primeros 4 bytes como hex.

---

## 2. La pieza clave: el JAR real vs. el stub

| | `classes.jar` (del programador) | `/system/framework/droidlogic.jar` (en el panel) |
|---|---|---|
| Qué es | **Stub de compilación** (cáscara vacía) | **Driver real** con código nativo conectado al I2C |
| Sus métodos | No hacen nada: devuelven 0, dejan el buffer en ceros | Leen el hardware de verdad |
| Uso | Solo **guía**: nos dio las firmas de los métodos | El que **realmente lee la tarjeta** |
| ¿Va en el APK? | **NO** (si se bundlea, la app ejecuta la cáscara y nunca lee) | No se incluye: ya está en el dispositivo |

> ⚠️ **El error que nos costó días:** meter `classes.jar` dentro del APK
> (`AndroidJavaLibrary` en .NET / `implementation files(...)` en Gradle).
> La app ejecutaba el stub vacío → `i2c_read` devolvía `ret=0` pero el buffer
> siempre en ceros. *Parecía* que todo iba bien pero el UID nunca aparecía.
> **No era un bug de `JNIEnv.CopyArray`** como creíamos: era el stub.

**Solución (igual en Kotlin y en .NET):** cargar el JAR **real** del dispositivo
en tiempo de ejecución con `DexClassLoader` y llamar por **reflexión**. Así no se
necesita el stub ni para compilar.

---

## 3. Parámetros del hardware (confirmados, no cambiar sin motivo)

| Parámetro | Valor | Notas |
|---|---|---|
| Clase | `com.droidlogic.app.tv.TvControlManager` | singleton vía `getInstance()` |
| `i2c_init(bus)` | `6` (chipset normal) / `7` (RK3576 v2) | inicializa el bus |
| `i2c_read(bus,...)` | `bus=4` (normal) / `bus=7` (v2) | bus de **lectura** ≠ bus de init |
| Dirección I2C (`addr`) | `0xA6` | viene del setting `dazzle_nfc_i2c_addr=6` (6→0xA6, 8→0xA8) |
| Registro (`reg`) | `0x21` | `REGADDR_CARD_READ` |
| `count` | `5` | bytes a leer |
| UID | primeros **4 bytes** → hex | minúsculas, p.ej. `d779cd0a`. `"00000000"` = sin tarjeta |

> En Android S+ `Settings.Global.getInt("dazzle_nfc_i2c_addr")` lanza
> `SecurityException` (la clave no es `@Readable`). Por eso se hardcodea
> `0xA6` como default — que es el valor correcto en este panel.

Firmas exactas (de `javap` sobre el JAR):
```
public static TvControlManager getInstance()
public void i2c_init(int bus)
public int  i2c_read(int bus, int addr, int reg, int count, int[] buf)
```

---

## 4. Implementación que funciona

### 4.1 Android Studio (Kotlin) — referencia original
`test/app/src/main/kotlin/.../NfcKit.kt (o docs/referencia-fabricante/NfcKit.kt)`. Usa `DexClassLoader`
probando varias rutas y llama por reflexión. El comentario del `build.gradle.kts`
lo resume: *"classes.jar ya no necesario: TvControlManager se carga desde
/system/framework/ via DexClassLoader"*.

### 4.2 .NET (Visual Studio) — bridge Java + JNI
Como .NET Android no expone `DexClassLoader` cómodamente, usamos un **bridge
Java** (`Jni/NfcBridge.java`, compilado con `<AndroidJavaSource>`) que hace el
`DexClassLoader` + reflexión, y C# lo llama por JNI. El bridge usa reflexión, así
que **no necesita `classes.jar` para compilar**.

- `test/Jni/NfcBridge.java`  (paquete `uno.lanube.nfctest`)
- `apk/Jni/NfcBridge.java` (paquete `uno.lanube.kiosk`)
- C#: `NfcKit.cs` llama `load(Context, initBus)`, `readUid(bus, addr, reg)`, `getStatus()`.

**Rutas de JAR que prueba el bridge (en orden):**
```
/system/framework/droidlogic.jar
/system/framework/droidlogic-tv.jar
/system/framework/droidlogic.software.core.jar
/system/framework/droidlogic.tv.software.core.jar
```

**El `.csproj` NO debe incluir el stub:** sin `<AndroidJavaLibrary>` ni
`Metadata.xml`. Solo `<AndroidJavaSource Include="Jni\NfcBridge.java" />`.

---

## 5. Cómo se conecta con la web del kiosko

El kiosko .NET (`kiosk-dotnet/MainActivity.cs`) solo **lee** el UID y lo entrega
a la web `https://lanube.uno` con JavaScript:
```csharp
NfcKit.Register(uid => RunOnUiThread(() =>
    webView.EvaluateJavascript($"if(typeof authenticate==='function')authenticate('{uid}')", null)));
NfcKit.StartReadJob();
```

> Por lo tanto, **"cambiar de sesión" y "bloquear equipo" son lógica de la WEB**
> (`app.py` / `index.html`), disparada por la función JS `authenticate(uid)`.
> `droidlogic.jar` **solo** se usa para leer la tarjeta. (ver §7 para mejorar el bloqueo).

---

## 6. ¿Quién más usa `droidlogic.jar`?

Es el HAL de control del panel (Amlogic, y en este equipo el servicio
`rockchip.hardware.dazzle.V1_0.IDazzle` → confirma el chipset **Rockchip / v2**).
Lo usan los componentes del **firmware del fabricante**, típicamente:

- La **app de ajustes del panel** (en nuestro equipo: `com.riotouch.setting` — es
  justamente el paquete de la app Kotlin de prueba que sí leía).
- `TvSettings` / menú de fábrica del OEM.
- El launcher/firmware OEM para fuentes HDMI, backlight, standby, etc.

**Para ver en el dispositivo quién lo declara/usa:**
```bash
# Apps que declaran la librería compartida droidlogic
adb shell dumpsys package | grep -i -B2 droidlogic
# Dónde vive el jar y la definición de librería compartida
adb shell ls -l /system/framework/ | grep -i droidlogic
adb shell cat /system/etc/permissions/*droidlogic* 2>/dev/null
# Procesos del HAL dazzle/tvserver
adb shell ps -A | grep -iE "dazzle|tvserver|droidlogic"
```

---

## 7. Mejorar "bloquear equipo" (lo que no funciona bien)

El JAR expone **637 miembros**. Para un bloqueo más sólido que un overlay web,
hay métodos de **hardware** (firmas reales de `javap`):

| Método | Para qué sirve |
|---|---|
| `SetBacklight_Switch(int)` / `GetBacklight_Switch()` | Enciende/apaga el **backlight** de la pantalla |
| `setBlackoutEnable(int, int)` / `getBlackoutEnable()` | **Pantalla en negro** (blackout) por hardware |
| `FactorySet_backlight_onoff(int)` | Backlight on/off (vía fábrica) |
| `SetAudioMuteForTv(int)` | Silenciar audio |
| `SSMSaveStandbyMode(int)` / MCU `MCU_POWER_MODE_STANDBY` | Modo standby del MCU |

### Opciones recomendadas para el bloqueo (de más simple a más robusta)

1. **Overlay nativo en el kiosko (.NET)** — una `Activity`/vista a pantalla
   completa por encima del WebView, que **solo se quita pasando una tarjeta
   válida**. Es lo más controlable y no depende del navegador. *(recomendado)*
2. **Screen pinning / Lock Task Mode** (`startLockTask()`) — modo kiosko de
   Android: impide salir de la app. Ideal para colegio.
3. **Blackout por hardware** con `setBlackoutEnable(1, …)` o
   `SetBacklight_Switch(0)` vía el mismo `NfcBridge` (apaga físicamente la
   imagen). Crudo pero efectivo como complemento del overlay.
4. **DevicePolicyManager.lockNow()** — bloquea a la pantalla de bloqueo de
   Android (requiere registrar la app como *device admin*).

> Sugerencia: combinar **1 + 2** (overlay + lock task) para que sea inviolable
> por el usuario, y opcionalmente **3** si se quiere apagar la pantalla al
> bloquear. La acción se dispara con el mismo UID NFC que ya leemos.

---

## 8. Checklist de build (.NET nfc-test)
```powershell
git pull origin claude/clever-fermat-6852kl
Remove-Item android\nfc-test\obj -Recurse -Force -ErrorAction SilentlyContinue
dotnet build android\nfc-test\NfcTest.csproj -c Release
adb -s 192.168.1.57:5555 install -r "android\nfc-test\bin\Release\net10.0-android\uno.lanube.nfctest-Signed.apk"
adb -s 192.168.1.57:5555 shell monkey -p uno.lanube.nfctest 1
```
En el debug debe verse `[5] OK desde /system/framework/droidlogic.jar` y, al
acercar la tarjeta, el UID en verde. Ya **no** se necesita `classes.jar`.
