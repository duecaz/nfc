# Infraestructura — la Pi y el entorno (datos operativos)

> ⚠️ **Este archivo contiene credenciales.** El repo `duecaz/nfc` debe permanecer
> **PRIVADO**. Antes de producción: rotar todas las claves de testeo.
> Los campos `(COMPLETAR)` son datos que el dueño debe rellenar — no inventar.

---

## 1. Equipos y red

| Equipo | Dirección | Acceso | Notas |
|---|---|---|---|
| **Raspberry Pi 5** (8 GB, SSD M.2) | `192.168.1.50` · hostname `pio` | `ssh duecaz@192.168.1.50` (clave: la del usuario duecaz) | Corre TODO (Docker) |
| **Panel interactivo de pruebas** | `192.168.1.57:5555` | `adb connect 192.168.1.57:5555` (sin clave) | Android; NFC I2C droidlogic |
| **PC de desarrollo (Windows)** | — | repo en `D:\claude\android\nfc`; scripts en `D:\claude\scripts` | compila el APK, corre el menú |

- La red `192.168.1.x` es la **red local de la Pi/pruebas**. Los colegios y casas
  entran SOLO por `https://lanube.uno` (Cloudflare → túnel → Pi).

## 2. Dominio y Cloudflare

| Qué | Valor |
|---|---|
| Dominio | `lanube.uno` (público) · `lanube.uno/app` → Nextcloud · `/` → kiosko Flask |
| Túnel | Cloudflare Tunnel **"raspberry"** (contenedor `cloudflared`, solo autentica) |
| Config del túnel | **Online**: `one.dash.cloudflare.com` → Zero Trust → Networks → Tunnels. NO hay `config.yml` local |
| Cuenta Cloudflare | (COMPLETAR: email de la cuenta) |

## 3. Puertos y contenedores (Docker en la Pi)

| Contenedor | Puerto | Qué es | Config en la Pi |
|---|---|---|---|
| `nginx_proxy` (NPM) | **80/443** (público vía túnel) · **81** admin NPM | Proxy: enruta `/app/`→NC, `/`→Flask | `~/docker/nginx/` · custom: `~/docker/nginx/data/nginx/custom/http.conf` |
| `nextcloud_server` | **8181** | Nextcloud 33 (base de datos **SQLite embebida** — no hay contenedor de DB) | `~/docker/nextcloud/` |
| `nfc_kiosk` (Flask) | **8200** | Web del kiosko (gunicorn 3×8) | `~/docker/kiosk/` |
| `cloudflared` | — | Túnel | `~/docker/cloudflared/` |

**Datos persistentes:**
- Kiosko: `~/docker/kiosk/data/kiosk.db` (SQLite: tarjetas/paneles/config) + `~/docker/kiosk/.env`
- Nextcloud: archivos de los docentes en la **SSD** — ruta exacta: (COMPLETAR: `docker inspect nextcloud_server | grep -i source`)
- `users.json`: **legado**, solo fue la fuente de la migración a SQLite (v25)

## 4. Credenciales (testeo — ROTAR antes de producción)

| Servicio | Usuario | Clave / valor | Dónde vive |
|---|---|---|---|
| Kiosko `/admin` | — (solo clave) | `Colegio2026!` | `ADMIN_PASSWORD` en `~/docker/kiosk/.env` |
| Heartbeat de paneles | — | `lanube-panel-2026` | `PANEL_SECRET` en `.env` **y** `PanelSecret` en `apk/MainActivity.cs` (deben coincidir) |
| SSH Pi | `duecaz` | (COMPLETAR) | — |
| Nextcloud admin | (COMPLETAR) | (COMPLETAR) | se usa en `/admin` del kiosko para crear docentes |
| NPM admin (puerto 81) | (COMPLETAR) | (COMPLETAR) | panel del proxy |
| Cloudflare | (COMPLETAR) | (COMPLETAR) | dashboard del túnel/dominio |
| GitHub | `duecaz` | — | repo privado `duecaz/nfc`, rama única `main` |

**App-tokens de docentes**: viven en la tabla `cards` de `kiosk.db` — **en texto
plano** (pendiente de producción: cifrar en reposo). Revocables desde NC → Ajustes → Seguridad.

## 5. Qué hay instalado

| Dónde | Software |
|---|---|
| **Pi** | Raspberry Pi OS (64-bit) · Docker + docker compose · los 4 contenedores de arriba. ⚠️ Para `tools/backup-pi.sh` hace falta `sqlite3` en el host: `sudo apt install sqlite3` |
| **Panel** | Android (Rockchip; NFC vía `/system/framework/droidlogic-tv.jar`) · APK `uno.lanube.kiosk` v11 |
| **PC dev** | .NET 10 SDK (workload android) · adb · git · menú PS1 (`D:\claude\scripts\menu.ps1`) |

## 6. Variables de entorno del kiosko (`~/docker/kiosk/.env`)

```bash
NEXTCLOUD_URL=http://192.168.1.50:8181        # interna (server-side)
NEXTCLOUD_PUBLIC_URL=https://lanube.uno/app   # pública (redirects)
ADMIN_PASSWORD=Colegio2026!
PANEL_SECRET=lanube-panel-2026
# COOKIE_DOMAIN: no necesario (dominio único)
```

## 7. Config Nextcloud relevante (`config.php`)

```
overwriteprotocol = https
overwritehost     = lanube.uno
overwrite.cli.url = https://lanube.uno/app
overwrite.webroot = /app
trusted_proxies   = 172.16.0.0/12, 192.168.1.0/24
trusted_domains   = 192.168.1.50, lanube.uno
auth.bruteforce.protection.enabled = true
```

## 8. Comandos operativos frecuentes

```bash
# estado general (o desde el menú PS1: "nfc PI status")
ssh duecaz@192.168.1.50
docker ps
curl -s http://localhost:8200/health          # versión web + nº usuarios

# occ de Nextcloud
alias occ='docker exec -u www-data nextcloud_server php occ'

# panel de la flota (salud Pi + paneles): lanube.uno/admin -> Paneles
# diagnóstico NFC en el panel:            lanube.uno/test (link "test" en el kiosko)

# logs NFC en vivo (desde la PC):  adb connect 192.168.1.57:5555
adb -s 192.168.1.57:5555 logcat -v time -s NfcKit:* NfcBridge:* LaNubeKiosk:*
```

Deploy completo: ver [`deploy-pi.md`](deploy-pi.md). Menú PS1 de la PC: opciones
`nfc APK / WEB deploy / LOG / CLEAR / PI status / CAPTURA / VERSIONES`.

## 9. Pendientes de completar en este documento

- [ ] Ruta exacta de los archivos NC en la SSD (`docker inspect nextcloud_server | grep -i source`)
- [ ] Credenciales NC admin, NPM admin, cuenta Cloudflare, clave SSH
- [ ] Versión exacta de Raspberry Pi OS (`cat /etc/os-release`)
- [ ] Instalar `sqlite3` en la Pi y configurar `tools/backup-pi.sh` + cron (F3)
