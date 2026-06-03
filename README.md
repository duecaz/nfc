# Login NFC — Demo

Demo de inicio de sesión con tarjeta NFC. Una sola página (`index.html`, sin
frameworks) con **tres formas** de leer la tarjeta, según el equipo:

| Modo | Equipo | Cómo |
|------|--------|------|
| **Web NFC** | Teléfono/tablet con Chrome para **Android** + chip NFC | `NDEFReader`, lee el UID |
| **Lector USB (teclado)** | PC / pantallas interactivas con lector USB HID | el lector "tipea" el UID |
| **Perfil (app dazzle)** | Paneles RK3588 con NFC propietario "dazzle" | la tarjeta cambia el perfil de Android |

> Es una **demo**: la cuenta y la sesión se simulan con `localStorage`. Los
> comentarios `TODO SUPABASE` en `index.html` y `MainActivity.java` marcan
> dónde conectar Supabase.

---

## 1. Web (teléfono o lector USB)

Serví `index.html` por **HTTPS** (Web NFC lo exige) — p.ej. GitHub Pages o un
túnel (`ngrok` / `cloudflared`). Elegí el modo de lectura en la página.

---

## 2. Paneles interactivos RK3588 con NFC "dazzle"

En estos paneles el lector NFC es un **módulo cerrado** (MCU **GD32F103** por
**I2C bus 6, dirección 0x52**) gestionado por el servicio **`com.dazzle.system.service`**.
Al leer la tarjeta **no entrega el UID**: **cambia el perfil de usuario de
Android** (user 0, 10, 11, …). Además SELinux impide que una app normal lea
`/dev/i2c-*`, así que no se puede leer el chip directamente sin root.

**Solución:** usar lo que el hardware sí da — el **perfil activo**. Cada
tarjeta queda asociada a un perfil; la app sabe en qué perfil corre y hace el
login de esa cuenta.

### 2a. Probar al toque, sin instalar nada (`tools/nfc-login-watch.ps1`)

```powershell
adb connect 192.168.1.43:5555
cd tools
.\nfc-login-watch.ps1
```
Acercá las tarjetas: la consola muestra el "login" del perfil que se activa.
Editá el mapa `$users` con tus perfiles (los ves con `adb shell dumpsys user`).

### 2b. App Android (reusa `index.html`)

Proyecto en `android/`. La app carga `index.html` en un `WebView` y, vía el
puente `DazzleBridge`, hace **auto-login según el perfil** activo.

**Mapa de perfiles:** editá `USERS` en
`android/app/src/main/java/com/demo/nfclogin/MainActivity.java`
(`serial -> nombre`; el serial sale de `adb shell dumpsys user`).

**Compilar:**
- Con **Android Studio**: abrí la carpeta `android/`, dejá que sincronice y
  *Run* / *Build > Build APK(s)*.
- Por consola (con Gradle instalado):
  ```bash
  cd android
  gradle wrapper        # genera ./gradlew la primera vez
  ./gradlew assembleDebug
  # APK: android/app/build/outputs/apk/debug/app-debug.apk
  ```

**Instalar (multi-usuario):**
```powershell
adb install -r android/app/build/outputs/apk/debug/app-debug.apk
# habilitarla también en cada perfil:
adb shell pm install-existing --user 10 com.demo.nfclogin
```

**Auto-aparecer al tocar la tarjeta (kiosko):** en *cada perfil*,
Ajustes > Apps > Apps predeterminadas > **App de inicio > "NFC Login"**.
Así, al cambiar de perfil con la tarjeta, aparece directamente el login.

### Limitaciones conocidas en el panel
- No se obtiene el **UID crudo** (módulo cerrado + SELinux). Se usa el perfil.
- Las "otras funciones" de dazzle (bloquear, pantalla on/off al re-tocar la
  misma tarjeta) son internas de dazzle; sólo se pueden **observar** por
  broadcasts (`ACTION_SCREEN_ON/OFF`, `ACTION_USER_PRESENT`), no interceptar.
- Para obtener el UID real haría falta: un **lector USB** (recomendado), root,
  o reversear `dazzle`.
