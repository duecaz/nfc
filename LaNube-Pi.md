# La Nube — Infraestructura Raspberry Pi 5 (resumen para retomar)

Plataforma tipo Google Drive para docentes (**Nextcloud**) con **login por
tarjeta NFC** desde pantallas interactivas (un kiosko web en Flask). Expuesto a
internet por **Cloudflare** (túnel "raspberry").

---

## RESTRICCIÓN CRÍTICA DE HARDWARE

> **Las pantallas interactivas del colegio NO tienen teclado físico, NO tienen
> ratón y NO tienen acceso a F12 / DevTools / menús de desarrollador.**
> Toda solución de soporte o diagnóstico DEBE poder ejecutarse:
> - Escribiendo una URL en la barra de direcciones del navegador
>   (las pantallas sí tienen teclado virtual al tocar la barra).
> - O desde botones visibles en la propia página.
>
> Nunca diseñar un fix que requiera la consola del navegador o DevTools.

---

## Conexión a la Pi
```
ssh duecaz@192.168.1.50
```
- Usuario: **duecaz** · hostname: **pio** · IP estática: **192.168.1.50** · Gateway: 192.168.1.1
- DNS: 192.168.1.50 (Pi-hole) + 1.1.1.1
- Si SSH cae/tarda: entrar una vez por **piconnect** despierta la interfaz
  (pendiente: ahorro de energía WiFi → `iwconfig wlan0 | grep Power`).
- Alias creado en `~/.bashrc`:
  `alias occ='docker exec -u www-data nextcloud_server php occ'`
- **Empezar siempre los comandos con `cd ~`** para evitar errores de ruta.

## Hardware
RPi 5 · 8GB RAM · 4 cores ARM · SD 29GB · Disco externo Seagate 1TB USB3:
700GB NTFS (Windows) + **231GB ext4 en `/mnt/datos`** (datos de los servicios).

---

## Servicios Docker, rutas y PUERTOS
| Servicio | Contenedor(es) | Puerto | Ruta config | Datos |
|---|---|---|---|---|
| Pi-hole (DNS+web) | `pihole` | 53, **8080** | — | — |
| Nginx Proxy Manager | `nginx_proxy` | 80, **81**(admin), 443 | `~/docker/nginx/` | — |
| Cloudflared (túnel "raspberry") | `cloudflared` | — | `~/docker/cloudflared/` | — |
| Immich (fotos) | `immich_server/postgres/redis/ml` | **2283** | `~/docker/immich/` | `/mnt/datos/immich` |
| Jellyfin (media) | `jellyfin` | **8096** | `~/docker/jellyfin/` | `/mnt/datos/jellyfin` |
| Pocketbase | `pocketbase` | **8090** | — | — |
| Portal | `portal` | **8888** | `~/docker/portal/` | — |
| **Nextcloud** | `nextcloud_server` / `nextcloud_db` / `nextcloud_redis` | **8181**→80 | `~/docker/nextcloud/` | `/mnt/datos/nextcloud/{html,data,db}` |
| **Kiosko NFC** | `nfc_kiosk` | **8200**→5000 | `~/docker/kiosk/` | `~/docker/kiosk/users.json` |

> Puertos ocupados a evitar: 8080, 8090, 8096, 8888, 2283. El kiosko usa **8200**.

---

## Dominios y túnel Cloudflare

### Enrutamiento actual (dos subdominios)
- `https://lanube.uno` → **kiosko NFC Flask** (192.168.1.50:**8200**)
- `https://app.lanube.uno` → **Nextcloud** (192.168.1.50:**8181**)

### IMPORTANTE — cómo funciona el túnel
El contenedor `cloudflared` (`~/docker/cloudflared/`) **solo autentica** el
túnel. Las **reglas de enrutamiento** (qué hostname va a qué IP:puerto) están
en el **panel web de Cloudflare**:

```
https://one.dash.cloudflare.com → Zero Trust → Networks → Tunnels → "raspberry"
```

**No hay `config.yml` local con reglas de ingress — todo está online.**
Nginx Proxy Manager (`~/docker/nginx/`) está instalado pero **no está en el
camino del tráfico**: cloudflared enruta directamente a los puertos 8200 y 8181.

### Migración pendiente: dominio único
El plan es mover NC a `lanube.uno/app/` para eliminar el problema de cookies
cross-subdomain (ver DEUDAS). Cuando se haga, las reglas en el panel de
Cloudflare también deberán actualizarse.

## Credenciales (TESTEO — cambiar en producción)
- Nextcloud admin: usuario `nextcloud` · contraseña `Colegio2026!`
- Docente de prueba: `jperez` · grupo `profesores` · cuota 5GB
- Kiosko: `~/docker/kiosk/users.json` mapea `UID_tarjeta → {user, token}`

---

## Cómo funciona el kiosko NFC (Flask, puerto 8200)

### Flujo actual (v2026-06-17.1+) — Basic Auth
1. El lector NFC USB "teclea" el UID + Enter en un campo oculto siempre enfocado.
2. JS del kiosko hace POST a `/auth` con el UID.
3. Flask busca el UID en `users.json` → obtiene `{user, app_token}`.
4. Flask hace `GET http://192.168.1.50:8181/apps/files` con
   `Authorization: Basic base64(user:app_token)`.
   NC devuelve HTTP 200 + cookies de sesión.
5. Flask copia esas cookies al response del navegador.
6. Flask responde `{ok:true, redirect:"https://app.lanube.uno/apps/files"}`.
7. JS del kiosko redirige al navegador a `app.lanube.uno/apps/files`.

> **Por qué Basic Auth y no formulario web:**
> NC 33 hace validación estricta de `Origin` contra `overwrite.cli.url`.
> El POST de formulario desde Flask **siempre falla con CSRF rejection** — no
> tiene solución sin modificar NC. El endpoint `/apps/files` con Basic Auth
> sí funciona y genera sesión completa (confirmado con curl: HTTP 200 + Set-Cookie).

> **Limitación pendiente:** Flask está en `lanube.uno` pero las cookies de sesión
> de NC se setean en `lanube.uno`. Al redirigir a `app.lanube.uno` el navegador
> no envía esas cookies. Las `__Host-` cookies de NC no admiten `Domain=`, así
> que no se pueden compartir aunque se use `COOKIE_DOMAIN=.lanube.uno`.
> **Solución definitiva: migración a dominio único** (ver DEUDAS).

### Variables del contenedor kiosko (docker-compose en Pi)
```yaml
NEXTCLOUD_URL=http://192.168.1.50:8181        # URL interna — para llamadas server-side
NEXTCLOUD_PUBLIC_URL=https://app.lanube.uno   # URL pública — para redirects al browser
COOKIE_DOMAIN=.lanube.uno                     # intento de compartir cookies (insuficiente)
ADMIN_PASSWORD=Colegio2026!
```

### Formato de users.json (tokens — formato actual)
```json
{
  "UID_DE_TARJETA": { "user": "jperez", "name": "jperez", "token": "xxxx..." }
}
```
> El campo `token` es un **app password de Nextcloud** (revocable desde
> Configuración → Seguridad). Si el docente cambia su contraseña real,
> el token sigue funcionando. Si se pierde o filtra, se revoca sin afectar
> a los demás.

### Generar un app password para un docente
```bash
docker exec nextcloud_server curl -s \
  -u "jperez:CLAVE_REAL" \
  -H "OCS-APIRequest: true" \
  "http://localhost/ocs/v2.php/core/getapppassword"
# Respuesta: <apppassword>TOKEN</apppassword>
# O usar el panel admin del kiosko: lanube.uno/admin
```

### Hallazgos clave (que costó descubrir)
- **NC 33 rechaza el formulario web desde proxy externo.** La CSRF validation
  compara el `Origin` con `overwrite.cli.url`. Aunque se envíe el `Origin`
  correcto, NC 33 añade validaciones adicionales de cookie que fallan desde Flask.
  Solución: usar Basic Auth en `/apps/files`, no el formulario.
- **Basic Auth en `/apps/files` genera sesión completa.** NC devuelve 200 +
  `Set-Cookie` con las cookies de sesión. Confirmado con curl.
- **Las `__Host-` cookies no admiten Domain.** NC setea
  `__Host-nc_sameSiteCookielax` y `__Host-nc_sameSiteCookiestrict` sin dominio.
  Flask las omite al copiar cookies al browser.
- Diagnóstico de oro: si `curl -u user:token .../remote.php/dav/files/user/` da
  **200**, la credencial es correcta.

---

## Config Nextcloud clave (reverse proxy)
```
overwriteprotocol = https
overwritehost     = app.lanube.uno
overwrite.cli.url = https://app.lanube.uno
trusted_proxies   = 172.16.0.0/12, 192.168.1.0/24
trusted_domains   = 192.168.1.50, 192.168.1.50:8181, lanube.uno, app.lanube.uno
auth.bruteforce.protection.enabled = false   (DESACTIVADO temporal — reactivar)
skeletondirectory = /var/www/html/data/skeleton   (carpeta limpia para usuarios nuevos)
```

---

## Comandos frecuentes
```bash
# Estado de contenedores
cd ~ && docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# Deploy del kiosko (tras actualizar el repo en GitHub)
cd ~/docker/kiosk
git fetch origin claude/clever-fermat-6852kl
git pull origin claude/clever-fermat-6852kl
docker compose down && docker compose build --no-cache && docker compose up -d
sleep 5 && curl -s http://localhost:8200/health | python3 -m json.tool

# Ver logs en vivo del kiosko
cd ~/docker/kiosk && docker compose logs --tail=30 -f kiosk

# occ (admin Nextcloud) — usa el alias
occ user:list
occ config:system:get <clave>
occ config:system:set <clave> --value='<valor>'

# Crear docente + cuota
docker exec -e OC_PASS='ClaveProfe!' -u www-data nextcloud_server php occ \
  user:add --password-from-env --group="profesores" --display-name="Nombre" usuario
occ user:setting usuario files quota "5 GB"

# Verificar credencial por WebDAV (200 = correcta, funciona con token o password)
docker exec nextcloud_server curl -s -o /dev/null -w "%{http_code}\n" \
  -u "USER:TOKEN_O_PASS" http://localhost/remote.php/dav/files/USER/

# Verificar que Basic Auth a /apps/files funciona (debe dar 200 + Set-Cookie)
docker exec nextcloud_server curl -si -L \
  -u "USER:TOKEN" -H "Accept: text/html" \
  http://localhost/apps/files | head -25

# Generar app password (token revocable) para un docente
docker exec nextcloud_server curl -s \
  -u "USER:CLAVE_REAL" \
  -H "OCS-APIRequest: true" \
  http://localhost/ocs/v2.php/core/getapppassword
# Respuesta: <apppassword>TOKEN</apppassword> → copiar en users.json

# Health check del kiosko
curl -s http://localhost:8200/health | python3 -m json.tool
```

---

## Service worker fantasma — diagnóstico y solución

### Síntoma
Una pantalla entra a `lanube.uno` y redirige sola a `lanube.uno/index.php/login`
(la página de login de Nextcloud) en vez de mostrar el kiosko.

### Causa raíz
Cuando `lanube.uno` servía Nextcloud, el browser instaló el **service worker
(SW) de Nextcloud** en el scope `/`. Ese SW sigue interceptando TODAS las
requests aunque ahora `lanube.uno` sirva el kiosko Flask.

### Solución — desde la barra de URLs
```
lanube.uno/reset
```
En ~3 segundos la pantalla se limpia sola. No requiere F12 ni DevTools.

La ruta `/reset` en `app.py` ejecuta JS que desregistra todos los SW, limpia
Cache API / localStorage / sessionStorage, instala un SW "auto-destructor" que
se elimina solo, y redirige a `/`.

---

## DEUDAS / PENDIENTES

1. **Migración a dominio único** — PENDIENTE (prioridad alta)
   - Problema: Flask en `lanube.uno` no puede setear cookies válidas para
     `app.lanube.uno`. Las `__Host-` cookies bloquean el workaround con
     `COOKIE_DOMAIN=.lanube.uno`.
   - Plan: `lanube.uno/app/` → NC via nginx `proxy_pass` con strip de prefix.
   - Cambios necesarios:
     - **Panel Cloudflare** (one.dash.cloudflare.com): el tunnel "raspberry"
       pasa a tener una sola regla `lanube.uno → nginx local (puerto 80)`.
     - **nginx** (`~/docker/nginx/`): `location /app/` → NC:8181 (strip `/app`).
     - **NC config.php**: `overwrite.cli.url=https://lanube.uno/app`,
       `overwrite.webroot=/app`.
     - **docker-compose kiosko**: `NEXTCLOUD_PUBLIC_URL=https://lanube.uno/app`,
       eliminar `COOKIE_DOMAIN`.
     - **app.py**: sin cambios en lógica, solo cambia el env var.

2. **Reactivar brute-force protection** antes de producción:
   ```bash
   occ config:system:set auth.bruteforce.protection.enabled --value=true --type=bool
   ```

3. **Alta masiva de 30 tarjetas** via CSV en el panel admin (`lanube.uno/admin`).

4. **Servidor WSGI** (Gunicorn) en vez del server dev de Flask.

5. **Cambiar todas las contraseñas** de testeo antes de producción.

6. ~~Service worker fantasma~~ → RESUELTO con `/reset`.

7. ~~App passwords~~ → MIGRADO: `app.py` usa el campo `token` (app password
   revocable). El campo `password` (clave real) sigue soportado como fallback.

---

## Prompt para retomar en otra conversación

> Estoy montando "La Nube": Nextcloud en `app.lanube.uno` (puerto 8181) + un
> kiosko NFC Flask en `lanube.uno` (puerto 8200) en mi Raspberry Pi 5.
> Cloudflare Tunnel "raspberry" enruta el tráfico: las reglas están en el
> **panel web de Cloudflare** (one.dash.cloudflare.com → Zero Trust → Tunnels),
> NO en config local. El docente pasa su tarjeta NFC y entra a sus archivos.
> Te adjunto el MD con inventario completo. No puedes acceder a mi Pi: yo
> ejecuto los comandos por SSH y te pego resultados; empieza siempre con `cd ~`.
> RESTRICCIÓN CRÍTICA: las pantallas no tienen F12 ni DevTools — toda solución
> debe funcionar desde la barra de URLs o botones visibles en pantalla.
> Repo: `duecaz/nfc`, rama activa: `claude/clever-fermat-6852kl`.
