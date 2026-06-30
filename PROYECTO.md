# NFC Kiosk – La Nube (lanube.uno)

## Arquitectura

```
[Tarjeta NFC]
     │
     ▼
[Panel Android]  ─── WebView ───►  [Flask Kiosk Pi]  ───►  [Nextcloud]
  kiosk-dotnet                      lanube.uno:8200           lanube.uno
  I2C via NfcKit.cs                 /auth + /admin            App tokens
  O NfcAdapter fallback             Gunicorn 2 workers        por usuario
     │
     └─► authenticate(uid) JS
         → POST /auth {uid}
         → sesión Nextcloud
         → redirect /apps/files
```

---

## 1. Flask Kiosk (Raspberry Pi)

**Repo:** `duecaz/nfc` rama `claude/clever-fermat-6852kl`  
**Path en Pi:** `~/docker/kiosk/`  
**URL pública:** `https://lanube.uno` (Docker port 8200→5000)

### Deploy en Pi
```bash
ssh duecaz@192.168.1.50
cd ~/docker/kiosk
git pull origin claude/clever-fermat-6852kl
docker compose up -d --build
curl -s http://localhost:8200/health   # esperar {"version":"14"}
docker logs nfc_kiosk --tail 30
```

### Características
- Python Flask + Gunicorn 2 workers (dos profesores pueden autenticar a la vez)
- `users.json` mapeando UID NFC → usuario/token Nextcloud (cache mtime en memoria)
- Flask-Limiter: `/auth` 30/min, `/auth-form` 10/5min
- Service Worker expiración de sesión automática
- Admin en `https://lanube.uno/admin` (password en `ADMIN_PASSWORD` del Docker)
- Chips de duración en pantalla principal (40min a 4h) – el profe elige ANTES de escanear

### Archivos clave
| Archivo | Función |
|---|---|
| `app.py` | Servidor Flask (VERSION="14") |
| `templates/index.html` | Pantalla kiosk con chips de duración |
| `templates/admin.html` | Panel de administración |
| `Dockerfile` | Imagen con Gunicorn |
| `docker-compose.yml` | Puerto 8200→5000, volumen users.json |

### Gestión de usuarios
**Archivo:** `~/docker/kiosk/users.json`
```json
{
  "53A3A343300001": {
    "user": "jperez",
    "name": "Juan Pérez",
    "token": "APP-TOKEN-NEXTCLOUD"
  }
}
```
Agregar usuarios vía admin web o editando el JSON directamente.
**Token NC:** Nextcloud → Configuración personal → Seguridad → Nueva contraseña de aplicación.

---

## 2. Android Kiosk APK (`kiosk-dotnet`)

**Path:** `android/kiosk-dotnet/` (C# .NET 10 Android)  
**Package:** `uno.lanube.kiosk`  
**IP del panel:** `192.168.1.57` (ADB por TCP puerto 5555)

### Build y deploy (desde Windows con .NET 10 + ADB instalados)
```powershell
cd D:\claude\nfc
git pull origin claude/clever-fermat-6852kl
Remove-Item -Recurse -Force android\kiosk-dotnet\bin -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force android\kiosk-dotnet\obj -ErrorAction SilentlyContinue
dotnet publish android/kiosk-dotnet/KioskNfc.csproj -c Release -f net10.0-android
adb connect 192.168.1.57:5555
adb install -r "D:\claude\nfc\android\kiosk-dotnet\bin\Release\net10.0-android\uno.lanube.kiosk-Signed.apk"
adb shell monkey -p uno.lanube.kiosk -c android.intent.category.LAUNCHER 1
```

### Ver logs del panel en tiempo real
```powershell
adb connect 192.168.1.57:5555
adb logcat -s LaNubeKiosk NfcKit
```

### Características
- WebView fullscreen apuntando a `https://lanube.uno`
- Kiosk mode: sin barra de navegación, sin botón atrás funcional, pantalla siempre encendida
- **NFC I2C** via `NfcKit.cs`: carga `TvControlManager` de `/system/framework/droidlogic.jar`
  a través de DexClassLoader/JNI para leer el NFC integrado del panel Amlogic
- **NFC estándar** via `NfcAdapter` como fallback (tablets/teléfonos Android normales)
- Descarga de archivos con cookies de sesión (DownloadManager + auto-apertura)
- Si la sesión NC expira, redirige automáticamente al kiosk
- El número de versión APK aparece en esquina inferior izquierda de la pantalla kiosk

### Versiones APK
| v | Cambios principales |
|---|---|
| 4 | Descarga de archivos + FileProvider + auto-apertura |
| **5** | **NFC I2C via NfcKit.cs (TvControlManager droidlogic.jar)** |

---

## 3. Android NFC Test App (`nfc-test`)

**Path:** `android/nfc-test/` (Kotlin)  
**Package:** `com.test.hola` (versionCode 5)  
**Para qué sirve:** diagnóstico — confirmar que el NFC I2C del panel funciona antes de instalar el kiosk.

### Uso
1. Compilar desde Android Studio o `./gradlew assembleDebug`
2. Instalar en el panel con `adb install`
3. Si aparece error I2C, tocar **Bus:** para cambiar entre bus 4, 6 y 7
4. UID confirmado funcionando: `D779CD0A`
5. Una vez confirmado el bus correcto, usar ese mismo bus en `NfcKit.cs` de kiosk-dotnet

---

## Raspberry Pi

| Dato | Valor |
|---|---|
| IP local | `192.168.1.50` |
| SSH | `ssh duecaz@192.168.1.50` |
| Kiosk dir | `~/docker/kiosk/` |
| Puerto kiosk | 8200 (externo) → 5000 (Flask) |
| Health check | `curl http://localhost:8200/health` |
| Logs | `docker logs nfc_kiosk --tail 50` |
| Rebuild | `docker compose up -d --build` |

---

## Panel Android

| Dato | Valor |
|---|---|
| IP local | `192.168.1.57` |
| ADB TCP | `adb connect 192.168.1.57:5555` |
| Package kiosk | `uno.lanube.kiosk` |
| Package test | `com.test.hola` |
| NFC chip | I2C, bus 4 (o 6/7), addr 0xA6, reg 0x21 |
| droidlogic.jar | `/system/framework/droidlogic.jar` |

---

## Seguridad – pendiente antes de producción

- [ ] Reactivar bruteforce protection en Nextcloud:  
  `'auth.bruteforce.protection.enabled' => true` en `config/config.php`
- [ ] Cambiar `ADMIN_PASSWORD` del kiosk Flask en docker-compose.yml
- [ ] Revisar que `KIOSK_URL` en kiosk-dotnet apunte a `https://lanube.uno` (no HTTP)

---

## Repo y ramas

- **GitHub:** `duecaz/nfc` (público)
- **Rama activa:** `claude/clever-fermat-6852kl`
- **Merge a main** cuando todo esté estable en producción
