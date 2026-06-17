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

### Enrutamiento actual (dominio único — ACTIVO)
```
lanube.uno → http://192.168.1.50:80 (NPM)
  /app/  → Nextcloud  :8181
  /      → Flask kiosko :8200
```

### IMPORTANTE — cómo funciona el túnel
El contenedor `cloudflared` (`~/docker/cloudflared/`) **solo autentica** el
túnel. Las **reglas de enrutamiento** están en el **panel web de Cloudflare**:

```
https://one.dash.cloudflare.com → Zero Trust → Networks → Tunnels → "raspberry"
```

**No hay `config.yml` local con reglas de ingress — todo está online.**

Reglas actuales del tunnel:
| # | Hostname | Destino |
|---|---|---|
| 1 | fotos.lanube.uno | http://192.168.1.50:2283 |
| 2 | n.lanube.uno | http://192.168.1.50:8096 |
| 3 | panel.lanube.uno | http://192.168.1.50:8888 |
| 4 | pb.lanube.uno | http://192.168.1.50:8090 |
| 5 | **lanube.uno** | **http://192.168.1.50:80** (NPM) |
| 6 | app.lanube.uno | http://192.168.1.50:8181 (pendiente eliminar) |

### nginx config de NPM (routing por path)
Archivo: `~/docker/nginx/data/nginx/custom/http.conf`
```nginx
server {
    listen 80;
    server_name lanube.uno;
    location /app/ {
        proxy_pass http://192.168.1.50:8181/;
        # ... headers ...
    }
    location / {
        proxy_pass http://192.168.1.50:8200/;
        # ... headers ...
    }
}
```
(ver archivo completo en la Pi)

## Credenciales (TESTEO — cambiar en producción)
- Nextcloud admin: usuario `nextcloud` · contraseña `Colegio2026!`
- Docente de prueba: `jperez` · grupo `profesores` · cuota 5GB
- Kiosko: `~/docker/kiosk/users.json` mapea `UID_tarjeta → {user, token}`

---

## Cómo funciona el kiosko NFC (Flask, puerto 8200)

### Flujo actual (v2026-06-17.1) — Basic Auth + dominio único
1. El lector NFC USB "teclea" el UID + Enter en un campo oculto siempre enfocado.
2. JS del kiosko hace POST a `/auth` con el UID.
3. Flask busca el UID en `users.json` → obtiene `{user, app_token}`.
4. Flask hace `GET http://192.168.1.50:8181/apps/files` con Basic Auth (app_token).
5. NC devuelve HTTP 200 + cookies de sesión.
6. Flask copia cookies al response del navegador (dominio `lanube.uno`).
7. Flask redirige a `https://lanube.uno/app/apps/files`.
8. Navegador envía cookies (mismo dominio) → NC sirve archivos. ✅

> **Por qué Basic Auth:** NC 33 rechaza formulario web desde proxy (CSRF). Basic
> Auth en `/apps/files` genera sesión completa sin CSRF.
>
> **Por qué dominio único:** Flask y NC en `lanube.uno` → cookies válidas para
> ambos sin `COOKIE_DOMAIN` ni workarounds con `__Host-` cookies.

### Variables del contenedor kiosko
```yaml
NEXTCLOUD_URL=http://192.168.1.50:8181
NEXTCLOUD_PUBLIC_URL=https://lanube.uno/app
ADMIN_PASSWORD=Colegio2026!
```

### Formato de users.json
```json
{
  "UID_DE_TARJETA": { "user": "jperez", "name": "jperez", "token": "xxxx..." }
}
```

### Deploy del kiosko (~/docker/kiosk/ NO es git repo)
```bash
curl -o ~/docker/kiosk/app.py \
  "https://raw.githubusercontent.com/duecaz/nfc/claude/clever-fermat-6852kl/app.py"
cd ~/docker/kiosk && docker compose down && docker compose build --no-cache && docker compose up -d
sleep 5 && curl -s http://localhost:8200/health | python3 -m json.tool
```

---

## Config Nextcloud clave (reverse proxy)
```
overwriteprotocol = https
overwritehost     = lanube.uno
overwrite.cli.url = https://lanube.uno/app
overwrite.webroot = /app
trusted_proxies   = 172.16.0.0/12, 192.168.1.0/24
trusted_domains   = 192.168.1.50, 192.168.1.50:8181, lanube.uno, app.lanube.uno
auth.bruteforce.protection.enabled = false   (TEMPORAL — reactivar)
```

---

## Comandos frecuentes
```bash
# Estado de contenedores
cd ~ && docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# Ver logs en vivo del kiosko
cd ~/docker/kiosk && docker compose logs --tail=30 -f kiosk

# occ (admin Nextcloud)
occ user:list
occ config:system:get <clave>
occ config:system:set <clave> --value='<valor>'

# Crear docente + cuota
docker exec -e OC_PASS='ClaveProfe!' -u www-data nextcloud_server php occ \
  user:add --password-from-env --group="profesores" --display-name="Nombre" usuario
occ user:setting usuario files quota "5 GB"

# Verificar credencial por WebDAV (200 = correcta)
docker exec nextcloud_server curl -s -o /dev/null -w "%{http_code}\n" \
  -u "USER:TOKEN" http://localhost/remote.php/dav/files/USER/

# Generar app password (token) para un docente
docker exec nextcloud_server curl -s \
  -u "USER:CLAVE_REAL" -H "OCS-APIRequest: true" \
  http://localhost/ocs/v2.php/core/getapppassword

# Health check
curl -s http://localhost:8200/health | python3 -m json.tool
```

---

## Service worker fantasma

Si una pantalla redirige a `/index.php/login`, ir a:
```
lanube.uno/reset
```
En ~3 segundos se limpia sola. No requiere F12 ni DevTools.

---

## DEUDAS / PENDIENTES

1. ~~**Migración a dominio único**~~ → **COMPLETADA** (v2026-06-17.1).
   NC en `lanube.uno/app/`, nginx routing, dominio único operativo.

2. **Eliminar regla `app.lanube.uno`** de Cloudflare (ya no necesaria).

3. **Reactivar brute-force protection**:
   ```bash
   occ config:system:set auth.bruteforce.protection.enabled --value=true --type=bool
   ```

4. **Alta masiva de 30 tarjetas** via CSV en el panel admin (`lanube.uno/admin`).

5. **Servidor WSGI** (Gunicorn) en vez del server dev de Flask.

6. **Cambiar todas las contraseñas** de testeo antes de producción.

7. ~~Service worker fantasma~~ → RESUELTO con `/reset`.

8. ~~App passwords~~ → MIGRADO: usa `token` (app password revocable).

9. ~~Cookies cross-subdomain~~ → RESUELTO con dominio único.

---

## Prompt para retomar en otra conversación

> Estoy montando "La Nube": Nextcloud en `lanube.uno/app/` + kiosko NFC Flask
> en `lanube.uno/` en mi Raspberry Pi 5. Cloudflare Tunnel "raspberry" enruta
> `lanube.uno` a nginx:80 (NPM) que hace routing por path. Las reglas del tunnel
> están en el **panel web de Cloudflare** (one.dash.cloudflare.com → Zero Trust
> → Tunnels), NO en config local. El docente pasa su tarjeta NFC y entra a sus
> archivos. Te adjunto el MD con inventario completo. No puedes acceder a mi Pi:
> yo ejecuto los comandos por SSH y te pego resultados; empieza siempre con
> `cd ~`. RESTRICCIÓN CRÍTICA: las pantallas no tienen F12 ni DevTools — toda
> solución debe funcionar desde la barra de URLs o botones visibles en pantalla.
> Repo: `duecaz/nfc`, rama: `claude/clever-fermat-6852kl`.
