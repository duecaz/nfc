# CLAUDE.md — La Nube (contexto para IA)

Plataforma Nextcloud para docentes con login por tarjeta NFC en pantallas
interactivas. Raspberry Pi 5, expuesto a internet por Cloudflare Tunnel.

---

## RESTRICCION CRITICA DE HARDWARE

Las pantallas interactivas **NO tienen teclado físico, NO tienen ratón y NO
tienen F12 / DevTools**. Toda solución DEBE poder ejecutarse:
- Escribiendo una URL en la barra de direcciones (teclado virtual al tocar la barra).
- O desde botones visibles en la propia página.

Nunca diseñar un fix que requiera consola del navegador o DevTools.

---

## Arquitectura

```
Internet
  └── Cloudflare Tunnel "raspberry"
        └── lanube.uno → nginx:80 (NPM, 192.168.1.50)
                          ├── /app/  → Nextcloud  (192.168.1.50:8181)
                          └── /      → Flask kiosko (192.168.1.50:8200)
```

El contenedor `cloudflared` **solo autentica** el túnel. Las reglas de
enrutamiento se configuran en el panel web:
`one.dash.cloudflare.com` → Zero Trust → Networks → Tunnels → "raspberry".
**No hay `config.yml` local — todo está online.**

nginx config: `~/docker/nginx/data/nginx/custom/http.conf`

---

## Servicios

| Contenedor | Puerto | Config |
|---|---|---|
| `nfc_kiosk` (Flask) | 8200 | `~/docker/kiosk/` |
| `nextcloud_server` | 8181 | `~/docker/nextcloud/` |
| `nginx_proxy` (NPM) | 80/443 | `~/docker/nginx/` |
| `cloudflared` | — | `~/docker/cloudflared/` |

`alias occ='docker exec -u www-data nextcloud_server php occ'`

---

## Pantalla Android — ADB

- IP del dispositivo: `192.168.1.57:5555`
- Conectar: `adb connect 192.168.1.57:5555`
- Siempre usar `-s 192.168.1.57:5555` en cada comando adb

### dazzle_nfc (daemon NFC del panel)

El panel tiene un daemon del fabricante que gestiona el NFC por I2C.
Si el NFC deja de responder (no beep al pasar tarjeta), reiniciar:

```powershell
adb -s 192.168.1.57:5555 shell stop dazzle_nfc
adb -s 192.168.1.57:5555 shell start dazzle_nfc
```

**Importante:** dazzle_nfc compite con apps que leen I2C directamente.
Para que `com.test.hola` lea el UID sin interferencia, detener dazzle_nfc
antes de probar y reiniciarlo al terminar.

### nfc-test APK (com.test.hola)

- Proyecto: `android/nfc-test/`
- Requiere `classes.jar` del fabricante en `app/libs/` (NO en git, copiar manualmente)
- `classes.jar` va como `implementation` (no compileOnly) para que TvControlManager
  sea encontrable en runtime
- Compilar desde Android Studio (Ctrl+F9), luego:

```powershell
adb -s 192.168.1.57:5555 install -r app\build\outputs\apk\debug\app-debug.apk
adb -s 192.168.1.57:5555 shell am start -n com.test.hola/.MainActivity
```

- `dazzle_nfc_i2c_addr` es clave @hide — SecurityException en apps normales,
  usar try/catch con default 6 (→ addr=0xA6)
- Poll cada 200ms para capturar UID antes de que dazzle_nfc lo consuma
- cardId=`00000000` = sin tarjeta; cardId=UID hex = tarjeta detectada
- Sostener la tarjeta 2+ segundos para asegurar captura
- Botón en pantalla cicla entre Bus 4 → 6 → 7

---

## Repo y deploy

- Repo: `duecaz/nfc` — rama activa: `claude/clever-fermat-6852kl`
- La Pi **NO es git repo** — los archivos se copian manualmente con curl.
- Los templates están **dentro de la imagen Docker** (COPY en Dockerfile).
  `docker compose restart` NO actualiza nada — siempre hay que hacer rebuild.

### Deploy completo (copiar archivos + rebuild)

```bash
cd ~/docker/kiosk && \
curl -o app.py "https://raw.githubusercontent.com/duecaz/nfc/claude/clever-fermat-6852kl/app.py" && \
curl -o templates/index.html "https://raw.githubusercontent.com/duecaz/nfc/claude/clever-fermat-6852kl/templates/index.html" && \
curl -o templates/login_manual.html "https://raw.githubusercontent.com/duecaz/nfc/claude/clever-fermat-6852kl/templates/login_manual.html" && \
curl -o templates/cambiar_clave.html "https://raw.githubusercontent.com/duecaz/nfc/claude/clever-fermat-6852kl/templates/cambiar_clave.html" && \
docker compose down && docker compose build --no-cache && docker compose up -d && \
sleep 5 && curl -s http://localhost:8200/health
```

El health debe devolver `"version": "N"` para confirmar que levantó correctamente.

### Si el navegador no muestra cambios después del deploy

El service worker (SW) sirve el HTML viejo aunque el servidor esté actualizado.
Borrar caché del navegador NO desregistra el SW. Solución: ir a `lanube.uno/reset`.
En incógnito siempre se ve la versión real (sin SW previo).

---

## Flujo de auth NFC

1. Lector NFC USB "teclea" el UID en campo oculto siempre enfocado.
2. JS hace POST a `/auth` con el UID.
3. Flask busca el UID en `users.json` → obtiene `{user, app_token}`.
4. Flask hace `GET http://192.168.1.50:8181/apps/files` con `Authorization: Basic`.
5. Flask copia las cookies de sesión al response del navegador.
6. JS redirige a `lanube.uno/app/apps/files`. ✅

**Por qué Basic Auth:** NC 33 rechaza POST de formulario desde proxy externo (CSRF).
**Por qué dominio único:** Flask y NC están ambos en `lanube.uno`, las cookies se
comparten automáticamente entre `/` y `/app/`. Sin `COOKIE_DOMAIN` ni workarounds.

---

## Rutas del kiosko

| Ruta | Función |
|---|---|
| `/` | Kiosko NFC principal |
| `/login-manual` | Login con usuario/contraseña |
| `/cambiar-clave` | Docente cambia su propia contraseña (re-asocia tarjeta) |
| `/admin` | Panel admin (alta masiva de tarjetas) |
| `/reset` | Limpia SW y caché del navegador, vuelve al kiosko |
| `/health` | Estado del servicio + versión actual |

---

## Variables de entorno del kiosko

```yaml
NEXTCLOUD_URL=http://192.168.1.50:8181        # URL interna (server-side)
NEXTCLOUD_PUBLIC_URL=https://lanube.uno/app   # URL pública (redirects)
ADMIN_PASSWORD=Colegio2026!
# COOKIE_DOMAIN: NO necesario (dominio único)
```

---

## Config Nextcloud (config.php)

```
overwriteprotocol = https
overwritehost     = lanube.uno
overwrite.cli.url = https://lanube.uno/app
overwrite.webroot = /app
trusted_proxies   = 172.16.0.0/12, 192.168.1.0/24
trusted_domains   = 192.168.1.50, lanube.uno
auth.bruteforce.protection.enabled = false   ← REACTIVAR antes de producción
```

---

## Versioning

`VERSION` en `app.py` usa números simples: `"5"`, `"6"`, etc. — nunca fechas.
Se muestra como `v5` en todas las páginas. Incrementar de a 1 con cada deploy.
Verificar con `curl -s http://localhost:8200/health` que la versión coincide.

---

## Lecciones aprendidas (no repetir)

- **`docker compose restart` no sirve** para actualizar código — los archivos
  quedan en la imagen vieja. Siempre usar `down && build --no-cache && up -d`.

- **Copiar TODOS los archivos modificados**, no solo `app.py`. Los templates
  son archivos independientes que también hay que curlear.

- **El SW bloquea updates en el navegador normal.** Si se ve la versión vieja
  pero incógnito muestra la nueva → ir a `/reset`. No es un problema de deploy.

- **`git push` por CLI falla** en este entorno (sin credenciales). Usar
  `mcp__github__push_files` para todos los pushes a GitHub.

- **Después de push por MCP**, el repo local queda desincronizado. Si se
  necesita trabajar con git: `git fetch origin && git reset --hard origin/<rama>`.

- **dazzle_nfc compite con I2C directo** — detenerlo antes de probar NFC
  con `com.test.hola`. Reiniciar con stop/start después.

- **classes.jar debe ser `implementation`** (no `compileOnly`) en el proyecto
  nfc-test para que TvControlManager sea encontrable en runtime.

---

## Pendientes antes de producción

1. Reactivar `auth.bruteforce.protection.enabled` en Nextcloud.
2. Alta masiva de 30 tarjetas via CSV en `/admin`.
3. Reemplazar servidor dev de Flask con Gunicorn.
4. Cambiar contraseñas de testeo.
5. Eliminar regla `app.lanube.uno` en Cloudflare (ya no existe, verificar).
