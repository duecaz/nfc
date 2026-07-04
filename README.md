# La Nube — Kiosko NFC → Nextcloud

Plataforma de acceso para docentes por **tarjeta NFC** en pantallas interactivas
(Amlogic/Rockchip). Una tarjeta abre la sesión de Nextcloud del docente; el
kiosko corre en un APK Android que lee el NFC del panel y en un backend Flask
en una Raspberry Pi.

> ⚠️ **Este repo es un prototipo de testeo.** La versión de producción se hará
> desde cero con las lecciones de [docs/auditoria.md](docs/auditoria.md).

## Estructura

| Carpeta | Qué es |
|---|---|
| **`web/`** | Backend Flask (Docker) que corre en la Pi → Nextcloud. Lo que ve el usuario. |
| **`apk/`** | Kiosko Android **.NET** (`uno.lanube.kiosk`): WebView + lectura NFC por I2C (droidlogic). |
| **`test/`** | App de diagnóstico NFC (.NET) + la app Kotlin de Android Studio de referencia. |
| **`docs/`** | Documentación (abajo). |
| **`tools/`** | Utilidades (`nfc-login-watch.ps1`). |

## Documentación

- **[docs/produccion-desde-cero.md](docs/produccion-desde-cero.md)** — 🏗️ **el plano para construir el v2 desde 0** (el MD más importante). Qué conservar, qué mejorar, errores a no repetir.
- **[docs/vision.md](docs/vision.md)** — 🎯 qué es el proyecto, decisiones tomadas (D1–D18), bitácora de versiones.
- **[docs/infraestructura-pi.md](docs/infraestructura-pi.md)** — 🔐 la Pi al detalle: red, puertos, credenciales, contenedores, comandos (repo privado).
- **[docs/auditoria.md](docs/auditoria.md)** — auditorías de estabilidad (F1–F9) + guía para la versión de producción.
- **[docs/deploy-pi.md](docs/deploy-pi.md)** — cómo desplegar la web y compilar/instalar el APK.
- **[docs/nfc-droidlogic.md](docs/nfc-droidlogic.md)** — cómo se lee el NFC del panel (DexClassLoader).
- **[docs/arquitectura.md](docs/arquitectura.md)** — histórico (ver infraestructura-pi.md para el estado actual).
- **[docs/referencia-fabricante/](docs/referencia-fabricante/)** — material del programador: `NFCKit-Usage.md`, `NfcKit.kt`, `classes.jar` (stub de firmas, **no** se usa en runtime).
- **[CLAUDE.md](CLAUDE.md)** — contexto para asistentes de IA (estado actual + reglas).

## Resumen técnico

- **NFC del panel**: se lee vía `com.droidlogic.app.tv.TvControlManager` cargado en
  runtime con `DexClassLoader` desde `/system/framework/droidlogic-tv.jar`. El UID
  se entrega a la web con `authenticate('UID')`.
- **UID canónico**: cualquier formato (decimal de lectora, hex de Web NFC) se
  normaliza a hex en el servidor (`canon_uid`), así la misma tarjeta matchea venga
  de donde venga.
- **Sesión**: la duración elegida la impone el APK con un timer nativo
  (`AndroidKiosk.startSession(minutos)`); "Desactivado" = sin auto-logout.
