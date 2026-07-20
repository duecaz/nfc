# La Nube — Visión del proyecto y bitácora de decisiones

> **Este documento es la memoria del proyecto.** Registra qué estamos construyendo,
> las decisiones que tomamos (y por qué), y los hallazgos — porque este repo es un
> **prototipo de testeo**: la versión de producción se hará **desde cero** usando
> todo lo aprendido aquí.

---

## 1. Qué es La Nube (la visión)

Un sistema **Nextcloud self-hosted** (vive en una Raspberry Pi, con dominio propio
en Cloudflare) al que los **docentes ingresan con su tarjeta NFC**:

> El docente llega a **cualquier pantalla interactiva de nuestra marca — sea cual
> sea el colegio** —, la app kiosko está abierta, **acerca su tarjeta NFC** y en
> segundos está dentro de **sus archivos**. El token de acceso "vive" asociado a su
> tarjeta. Al terminar (o al expirar el tiempo elegido) la sesión se cierra sola y
> la pantalla queda lista para el siguiente docente. Desde **su casa** entra a los
> mismos archivos por el navegador con usuario/contraseña.

**Los tres pilares:**
1. **Sin fricción**: un toque de tarjeta = sesión abierta con TUS archivos.
2. **Multi-colegio**: la misma tarjeta funciona en cualquier pantalla de la marca.
3. **Soberanía**: todo (archivos, credenciales, servidor) vive en NUESTRO hardware;
   la nube externa es solo el dominio/túnel (Cloudflare).

## 2. Cómo funciona (flujo real, v25/apk11)

```
Tarjeta NFC ──1.7ms──► APK kiosko (.NET, lee chip I2C del panel vía droidlogic)
                        │ inyecta authenticate(UID) en el WebView
                        ▼
                 Web kiosko (Flask en la Pi) ──► canon_uid → SQLite → app-token
                        │ Basic Auth contra Nextcloud → cookies de sesión
                        ▼
                 Archivos del docente (Nextcloud) · timer nativo del APK
                        │ al expirar o al cerrar sesión
                        ▼
                 /logout → pantalla de login lista para el siguiente
```

Componentes: `apk/` (kiosko Android .NET), `web/` (Flask + templates), la Pi
(Nextcloud + nginx + cloudflared), `test/` (app de diagnóstico NFC).

---

## 3. Decisiones tomadas (las que funcionaron — conservar en producción)

| # | Decisión | Por qué fue la correcta |
|---|---|---|
| D1 | **Leer el NFC con el `droidlogic-tv.jar` REAL del panel vía `DexClassLoader` + reflexión** — nunca bundlear el `classes.jar` del fabricante (es un stub vacío). | El stub fue la causa de días de "lee pero devuelve ceros". Lectura real: **~1.7 ms**. |
| D2 | **UID canónico en el servidor** (`canon_uid`: decimal, hex, con `:` → hex mayúsculas). | La misma tarjeta da formatos distintos según el lector (Windows decimal, panel decimal, celular hex). Unificar en el server evitó re-registrar tarjetas. |
| D3 | **El cierre de sesión lo impone el APK** con timer nativo (`AndroidKiosk.startSession(min)`), no la web. | Un `setTimeout` web muere al navegar a Nextcloud. El timer nativo es garantizado. `0` = sin límite. |
| D4 | **SQLite** para los datos del kiosko (tarjetas/paneles/config) — no JSON, no servidor de DB dedicado. | JSON se corrompe con escrituras concurrentes (3 workers). Un DB server en la Pi robaría RAM a Nextcloud. SQLite+WAL probado con escrituras simultáneas sin corrupción. |
| D5 | **Un solo dominio** (`lanube.uno`) para Flask y Nextcloud → cookies compartidas sin trucos. Basic Auth con app-token (NC rechaza POST de login vía proxy por CSRF). | Simplificó todo el auth. |
| D6 | **Self-hosted en la Pi; Cloudflare SOLO dominio+túnel+TLS.** | Soberanía de datos y costo cero de nube. |
| D7 | **Rate-limit por UID de tarjeta** (no global por IP) + ProxyFix. | Detrás del túnel toda la flota comparte IP: un límite global bloqueaba a todos los colegios a la vez. |
| D8 | **gunicorn 3 workers × 8 threads** (I/O-bound: cada login espera a NC). | De 2 logins concurrentes a ~24 (pico proyectado ~15 a 2 años). |
| D9 | **Heartbeat bajo demanda**: paneles reportan cada 10 min; "monitoreo intensivo" ON → cada 1 min. El server dicta el intervalo en la respuesta del ping. | Supervisión de la flota casi sin carga; se enciende solo durante soporte. |
| D10 | **Id del panel = MAC de la red cableada** (fallback ANDROID_ID) + `PANEL_SECRET` en cada ping. | ANDROID_ID puede venir clonado de fábrica; sin secreto cualquiera infla el inventario. |
| D11 | **Secretos en `.env`** (no en compose/repo). | Higiene básica; el repo queda compartible. |
| D12 | **Debounce NFC**: 1 toque = 1 evento (re-arma al retirar la tarjeta); poll 100 ms (50 ms fallaba la 1ª lectura). | Sin ráfagas a la web ni dobles disparos. |
| D13 | **Auto-reinicio del APK ante crash** (~1.5 s vía AlarmManager). Lock Task queda para el MDM (device-owner). | Panel 24/7 sin intervención. El lock estricto sin MDM rompería abrir/subir archivos. |
| D14 | **Selector de duración = stepper − / + de 5 min** (0 = sin límite). Los chips fijos se quitaron: redundantes. | UX más simple en pantalla táctil. |
| D15 | **Cerrar sesión = botón de Nextcloud (interceptado por `/logout`) o timer.** Tarjeta durante sesión abierta NO hace nada (decisión consciente, F6). | Flujo natural de los docentes; rediseñar en producción si hace falta "cambio rápido de usuario". |
| D16 | **Despliegue de la flota vía MDM/DMS** (no adb panel por panel). | 50 paneles, misma versión, sin drift. |
| D17 | **Versionado visible**: `VERSION` web y `ApkVersion` en pantalla/health/admin. | Detectar al instante despliegues a medias. |
| D18 | **Menú de scripts PS1** (`D:\claude\scripts` + `tools/`): build/deploy/log/captura/versiones con `git main` forzado y `adb connect`/`ssh` siempre primero. | Operación repetible sin memorizar comandos. |

### Decisiones descartadas (y por qué — no repetir)
- ❌ Bundlear `classes.jar` en el APK (stub vacío → lee ceros).
- ❌ JSON como base de datos (corrupción con escrituras concurrentes).
- ❌ `setTimeout` web para cerrar sesión (muere al navegar).
- ❌ Atajo DNS local "split-horizon" (F1): **no aplica** — son varios colegios + casas,
  no comparten LAN con la Pi; el tráfico por internet es inherente.
- ❌ Mover el servidor a un VPS: descartado por el dueño; self-hosted en la Pi.
- ❌ Poll NFC a 50 ms (perdía la primera lectura del ciclo RF).

---

## 4. Hallazgos de las auditorías (detalle en `auditoria.md`)

| Hallazgo | Estado |
|---|---|
| F1 tráfico por internet | **Descartado** — inherente a multi-colegio+casas |
| F2 corrupción JSON multi-worker | ✅ Resuelto (SQLite, v25) |
| F3 la Pi es punto único de falla | ⚠️ Script `tools/backup-pi.sh` listo; **falta instalarlo** (cron + ruta SSD) |
| F4 ráfaga NC en cambio de hora | 📋 Tuning NC pendiente (previews, caché) |
| F5 /panel-ping público | ✅ Resuelto (PANEL_SECRET + tope 200) |
| F6 tarjeta durante sesión | ✅ Aceptado como diseño (logout NC manual + timer) |
| F7 id de panel clonable | ✅ Resuelto (MAC eth0) |
| F8 memoria WebView a largo plazo | 📋 Soak test 7 días pendiente |
| F9 supervisión de la Pi | ✅ Resuelto (/admin/panels: carga/RAM/disco/temp) |
| F10 repo público con credenciales | 🔴 **Abierto** — poner privado + rotar claves + revisar Pages (ver `auditoria.md F10`) |

## 4b. Bitácora de la sesión de limpieza (jul 2026)

Cambios y problemas de esta sesión, para el proyecto nuevo:

- **Se quitó el hook de Lock Task del APK** (`KioskLock`/`StartLockTask`) y la sección
  "bloqueo de hardware" del doc (`nfc-droidlogic.md §7`, métodos backlight/blackout/lockNow,
  nunca implementados). Parecían anti-desinstalación / control del equipo y no eran
  esenciales: el bloqueo del kiosko va **solo por MDM** en producción. El APK queda libre
  de salir/desinstalar. Se **conservó** el auto-reinicio ante crash (recuperación de la
  app, no persistencia) y la lectura NFC por `DexClassLoader` (esencial).
- **Hallazgo F10**: el repo estaba **público** con credenciales (`infraestructura-pi.md`
  + `PanelSecret` hardcodeado) → fuga real. Acción: privado + rotar + revisar Pages.
- **Nota de proceso (falso positivo de safeguards)**: el modelo rápido *Fable 5* bloqueó
  el análisis del proyecto porque la mezcla de señales (DexClassLoader del framework,
  bypass SELinux, "bloqueo de hardware", kiosk lock, leer UID, inyectar JS) pattern-matchea
  con malware Android, aunque el uso es legítimo (hardware propio, autorizado). Salida:
  **trabajar con un modelo más capaz (Opus)** y dar contexto de autorización; quitar lo no
  esencial (arriba) reduce esas señales.

## 5. Bitácora de versiones (resumen)

| Versión | Qué entró |
|---|---|
| web v5–v14 | Kiosko base, login manual, cambiar-clave, admin, rediseño UI, duración de sesión |
| v15 | `inputmode=none` (teclado virtual ya no salta en el panel) |
| v16 | **UID canónico** + timer nativo de sesión (apk7) |
| v17–v19 | Página `/test` de diagnóstico, clearAll, fix solapes |
| v20 | Stepper de duración −/+ (chips fuera) |
| v21–v22 | **Escala**: ProxyFix, rate-limit por UID, gunicorn 3×8, `.env`, auditoría |
| v23–v24 | **Heartbeat** + `/admin/panels` + monitoreo bajo demanda (apk9–10) |
| v25 | **SQLite** (migración automática), PANEL_SECRET, MAC id, salud Pi/paneles (apk11) |

## 6. Lo que la PRODUCCIÓN (desde 0) debe tener

1. Conservar D1–D18 (arriba) — son las decisiones probadas.
2. **Cifrar los app-tokens en reposo** (hoy en texto plano en SQLite).
3. Respaldo automático instalado desde el día 1 (F3) + Pi/equipo de repuesto.
4. Tuning Nextcloud (F4) si crece: previews limitadas, APCu/Redis, cron real.
5. MDM: despliegue del APK + Lock Task device-owner + dashboard.
6. Evaluar **PocketBase** como backend (SQLite + panel admin + API + respaldos
   automáticos en un binario) vs Flask+SQLite actual.
7. Soak test de 7 días en panel piloto antes del despliegue masivo.
8. Cambiar TODAS las contraseñas de testeo (ver `infraestructura-pi.md`).
