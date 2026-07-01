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

## Estructura del repo

```
web/    proyecto Flask (lo que va a la Pi)   -> web/app.py, web/templates/
apk/    kiosko Android .NET (lee NFC droidlogic)
test/   app de diagnóstico NFC (.NET + Kotlin de referencia)
docs/   documentación (arquitectura, nfc-droidlogic, referencia-fabricante)
tools/  utilidades (adb watch)
```

## Repo y deploy

- Repo: `duecaz/nfc` — rama por defecto: **`main`**
- La Pi **NO es git repo** — los archivos se copian con curl desde `main/web/`.
- Los templates están **dentro de la imagen Docker** (COPY en Dockerfile).
  `docker compose restart` NO actualiza nada — siempre hay que hacer rebuild.

### Deploy completo (copiar archivos + rebuild)

```bash
B=main
cd ~/docker/kiosk && \
for f in app.py templates/index.html templates/login_manual.html templates/cambiar_clave.html templates/admin.html; do \
  curl -o "$f" "https://raw.githubusercontent.com/duecaz/nfc/$B/web/$f"; done && \
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
auth.bruteforce.protection.enabled = true    ← reactivado (v16)
```

---

## Versioning

`VERSION` en `app.py` usa números simples: `"5"`, `"6"`, etc. — nunca fechas.
Se muestra como `v5` en todas las páginas. Incrementar de a 1 con cada deploy.
Verificar con `curl -s http://localhost:8200/health` que la versión coincide.

---

## NFC del panel (Amlogic/Rockchip) — droidlogic.jar

Las pantallas con lector NFC integrado leen por bus I2C usando
`com.droidlogic.app.tv.TvControlManager` del firmware. Ver doc completa en
`docs/nfc-droidlogic.md`. Clave: el `classes.jar` del programador es solo un
stub de compilación; el driver real se carga en runtime con `DexClassLoader`
desde `/system/framework/droidlogic.jar`. El APK kiosko (.NET) inyecta el UID
en el WebView llamando `authenticate('UID')`.

---

## Lecciones aprendidas (no repetir)

- **`docker compose restart` no sirve** para actualizar código — los archivos
  quedan en la imagen vieja. Siempre usar `down && build --no-cache && up -d`.

- **Copiar TODOS los archivos modificados**, no solo `app.py`. Los templates
  son archivos independientes que también hay que curlear.

- **El SW bloquea updates en el navegador normal.** Si se ve la versión vieja
  pero incógnito muestra la nueva → ir a `/reset`. No es un problema de deploy.

- **git**: el push por CLI funciona a través del proxy **si el local está
  sincronizado** (`git fetch && git reset --hard origin/main` antes de trabajar).
  Alternativa: `mcp__github__push_files`. Tras un push por MCP, el local queda
  desincronizado → volver a sincronizar con reset --hard.

---

## UID canónico (v16)

Todos los lectores dan la MISMA tarjeta en formatos distintos; el servidor los
unifica a **hex en mayúsculas** con `canon_uid()` antes de comparar:
- Lectora USB Windows y panel droidlogic → decimal `3886968074`
- Web NFC (celular) → hex `E7AE6D0A`
- Todos → `canon_uid` → `E7AE6D0A`

`find_user()` matchea sin importar el formato (decimal o hex), y `/admin` guarda
las tarjetas nuevas ya en hex canónico. No hace falta re-registrar las viejas.

## Cierre de sesión (v16)

La "Duración de sesión" la impone el **APK** con un timer nativo: la web llama
`AndroidKiosk.startSession(minutos)` al autenticar; al expirar, el APK carga
`/logout` (garantizado, sobrevive a la navegación a Nextcloud). En navegadores
sin APK (PC), el service worker cierra al navegar tras expirar (respaldo blando).

## Pendientes antes de producción

1. ✅ Bruteforce NC reactivado — comando:
   `docker exec -u www-data nextcloud_server php occ config:system:set auth.bruteforce.protection.enabled --value true --type boolean`
2. Alta masiva de 30 tarjetas via CSV en `/admin`.
3. ✅ Gunicorn ya en uso (ver Dockerfile).
4. Cambiar contraseñas de testeo.
5. Eliminar regla `app.lanube.uno` en Cloudflare (ya no existe, verificar).
