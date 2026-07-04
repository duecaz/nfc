# CLAUDE.md — La Nube (contexto para IA)

Plataforma **Nextcloud** para docentes con login por **tarjeta NFC** en pantallas
interactivas. Sirve a **varios colegios** y a los **docentes desde sus casas**.

## 📖 Chat nuevo: leer PRIMERO, en este orden

1. **[docs/vision.md](docs/vision.md)** — qué es el proyecto, decisiones D1–D18, bitácora.
2. **[docs/infraestructura-pi.md](docs/infraestructura-pi.md)** — la Pi: red, puertos, credenciales, qué hay instalado.
3. **[docs/auditoria.md](docs/auditoria.md)** — hallazgos F1–F9 y guía para rehacer producción desde 0.
4. Este archivo (estado + reglas) y [docs/deploy-pi.md](docs/deploy-pi.md) / [docs/nfc-droidlogic.md](docs/nfc-droidlogic.md) según la tarea.

**Hosting:** todo self-hosted en **una Raspberry Pi 5** (Docker: Nextcloud + Flask
kiosko + nginx + cloudflared; archivos en **SSD**). La "nube" es **solo Cloudflare**
para el **dominio + túnel + TLS** — no se hostea ni se guarda nada afuera.

> ⚠️ **Prototipo de testeo.** La versión de producción se rehará desde cero con las
> lecciones de [`docs/auditoria.md`](docs/auditoria.md). **Mantener ESTE archivo al
> día con cada cambio** (estructura + estado + decisiones).

---

## Estado actual (mantener actualizado)

| Componente | Versión | Dónde vive el dato |
|---|---|---|
| Web (Flask) | **v25** | **SQLite** `web/data/kiosk.db` (tarjetas, paneles, config) |
| APK (.NET) | **v11** (`ApkVersion`) | — |
| Rama | `main` (default) | — |

- **El kiosko ya NO usa `users.json`** — migró a **SQLite** en v25 (users.json solo
  se usó una vez como fuente de la migración automática).
- **Secretos** (`ADMIN_PASSWORD`, `PANEL_SECRET`) → en `~/docker/kiosk/.env` (NO
  versionado). El compose ya no los trae inline.
- **Nextcloud**: su base de datos es **SQLite** (no hay contenedor `*_db` en la Pi).
  *(confirmar con `docker ps`; si algún día se pasa a MariaDB, actualizar aquí y el
  backup).* Archivos de NC en la SSD.

---

## RESTRICCIÓN CRÍTICA DE HARDWARE

Las pantallas **NO tienen teclado físico, ni ratón, ni F12/DevTools**. Toda solución
debe correr escribiendo una URL en la barra o desde botones visibles en la página.
Nunca diseñar un fix que requiera consola del navegador.

---

## Arquitectura

```
Paneles (colegios) + docentes (casas)
        │  todo por internet (no comparten LAN)
        ▼
Cloudflare (dominio lanube.uno + túnel "raspberry" + TLS)
        ▼
Raspberry Pi 5 · Docker
  nginx (NPM) → /app/ → Nextcloud (:8181, SQLite, archivos en SSD)
              → /     → Flask kiosko (:8200, SQLite kiosk.db)
```

`cloudflared` **solo** autentica el túnel; las reglas se configuran online
(`one.dash.cloudflare.com` → Zero Trust → Tunnels → "raspberry"). No hay `config.yml`.
nginx: `~/docker/nginx/data/nginx/custom/http.conf`.

### Servicios (contenedores)

| Contenedor | Puerto | Config |
|---|---|---|
| `nfc_kiosk` (Flask) | 8200 | `~/docker/kiosk/` (`.env`, `data/kiosk.db`) |
| `nextcloud_server` | 8181 | `~/docker/nextcloud/` (SQLite embebido) |
| `nginx_proxy` (NPM) | 80/443 | `~/docker/nginx/` |
| `cloudflared` | — | `~/docker/cloudflared/` |

`alias occ='docker exec -u www-data nextcloud_server php occ'`

---

## Estructura del repo

```
web/    Flask (lo que va a la Pi): app.py, templates/, Dockerfile, compose, .env.example
apk/    kiosko Android .NET (uno.lanube.kiosk) — lee NFC droidlogic
test/   app de diagnóstico NFC (.NET + Kotlin de referencia)
docs/   arquitectura.md, deploy-pi.md, nfc-droidlogic.md, auditoria.md, referencia-fabricante/
tools/  scripts PS1 del menú (nfc-*.ps1) + backup-pi.sh
```

---

## Deploy (la Pi NO es repo git — se curlea desde `main/web/`)

**Rutina** (código): curl `app.py` + `templates/*` + rebuild.
**Infra** (Dockerfile/compose/requirements/.env): curlear también esos archivos.
Los templates van dentro de la imagen → `docker compose restart` NO alcanza, hay
que `down && build --no-cache && up -d`. Guía completa: [`docs/deploy-pi.md`](docs/deploy-pi.md).

```bash
cd ~/docker/kiosk
for f in app.py templates/index.html templates/login_manual.html templates/cambiar_clave.html templates/admin.html; do
  curl -fsSL -o "$f" "https://raw.githubusercontent.com/duecaz/nfc/main/web/$f"; done
docker compose down && docker compose build --no-cache && docker compose up -d
sleep 5 && curl -s http://localhost:8200/health     # debe decir "version":"25"
```

Si el panel muestra versión vieja: el service worker cachea el HTML → `lanube.uno/reset`.

---

## Flujo de auth NFC (real, panel de producción)

1. El **APK** lee la tarjeta por I2C (droidlogic) → UID decimal, y lo inyecta en el
   WebView: `authenticate('UID')`. *(en PC: lector USB teclea; en celular: Web NFC)*
2. La web hace `POST /auth` con el UID.
3. Flask normaliza con `canon_uid()` y busca en **SQLite** (`find_user`) → `{user, app_token}`.
4. Flask hace `GET .../apps/files` con Basic Auth (app-token) y copia las cookies de NC.
5. La web redirige a Archivos. El **APK** arma el timer de sesión.

**Basic Auth** porque NC rechaza POST de formulario desde proxy externo (CSRF).
**Dominio único** (`lanube.uno` para Flask y NC) → cookies compartidas entre `/` y `/app/`.

---

## Almacenamiento — SQLite (v25)

`web/data/kiosk.db` (WAL, transacciones seguras entre los 3 workers gunicorn). Tablas:
- `cards(uid, user, name, token)` — tarjetas. `token` = app-password de Nextcloud.
- `panels(id, apk, nfc, ip, seen, ram)` — inventario del heartbeat.
- `config(k, v)` — flags (ej. monitoreo intensivo).

Migración automática desde `users.json` al primer arranque (log: `[DB] migradas N`).

---

## UID canónico (v16)

Cualquier formato (decimal de lectora, hex de Web NFC, con `:`) → `canon_uid()` a hex
mayúsculas. `find_user()` matchea sin importar el formato; `/admin` guarda ya canónico.

## Cierre de sesión (v16)

La "Duración de sesión" la impone el **APK** con un timer nativo
(`AndroidKiosk.startSession(minutos)`); al expirar carga `/logout`. `0` = sin límite.
El stepper `− / +` (5 min) es el único control (los chips se quitaron en v24).

## Monitoreo de la flota (v24–v25)

- Cada panel hace `POST /panel-ping` (id = **MAC de eth0**, versión APK, NFC ok/fail,
  RAM del panel, `secret` = `PANEL_SECRET`). Bajo demanda: 10 min normal / 1 min con
  "monitoreo intensivo" ON.
- `/admin/panels` (link en el admin): salud de la **Pi** (carga/RAM/disco/temp) + tabla
  de paneles (online/offline, versión, NFC, RAM). Toggle de monitoreo intensivo.

## Robustez del APK (v9–v11)

Auto-reinicio ante crash (~1.5 s vía AlarmManager). Lock Task = hook opt-in
(`KioskLock=false`; bloqueo real vía MDM device-owner, ver auditoria §6).

## Respaldo (F3)

`tools/backup-pi.sh` (correr en la Pi, cron 3am): `kiosk.db` + base/archivos de NC en
modo mantenimiento, retención 7 días, `rsync` offsite opcional a PC/NAS.

---

## Versioning

`VERSION` en `web/app.py` (números simples, nunca fechas) y `ApkVersion` en
`apk/MainActivity.cs`. Se ven en `/health`, en `/admin/panels` y en la etiqueta
`apk vN` del kiosko. Subir de a 1 con cada deploy.

---

## NFC del panel — droidlogic

Lectura por I2C con `com.droidlogic.app.tv.TvControlManager`, cargado en runtime con
`DexClassLoader` desde `/system/framework/droidlogic-tv.jar`. El `classes.jar` del
programador es solo stub de compilación. Doc completa: [`docs/nfc-droidlogic.md`](docs/nfc-droidlogic.md).

---

## Lecciones aprendidas (no repetir)

- **`docker compose restart` no actualiza código** → `down && build --no-cache && up -d`.
- **Curlear TODOS los archivos** modificados (templates aparte; y `requirements.txt`
  cuando cambian deps, o gunicorn "not found").
- **El SW sirve HTML viejo** → `/reset` (incógnito muestra la versión real).
- **git**: push por CLI funciona si el local está sincronizado (`git fetch && git reset
  --hard origin/main`). Alternativa: `mcp__github__push_files`.
- **Mantener este CLAUDE.md al día** con cada cambio — es la fuente de verdad.

---

## Pendientes / decisiones (ver `docs/auditoria.md` para el detalle F1–F9)

1. **Respaldo automático** (F3): instalar `tools/backup-pi.sh` + cron + copia offsite.
2. **Cifrar app-tokens** en reposo (server público) — F5/seguridad.
3. Tuning Nextcloud si crece (previews, cache) — F4.
4. Producción desde 0: hosting (¿mejor equipo?), DB (SQLite vs **PocketBase**),
   cifrado, MDM (Lock Task + despliegue APK).
5. Cambiar contraseñas de testeo antes de producción.
