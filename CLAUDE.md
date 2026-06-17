# CLAUDE.md — La Nube (contexto para IA)

Plataforma Nextcloud para docentes con login por tarjeta NFC en pantallas
interactivas. Raspberry Pi 5, expuesto a internet por Cloudflare Tunnel.

> Leer también `LaNube-Pi.md` para inventario completo de servicios, puertos
> y comandos frecuentes.

---

## RESTRICCION CRITICA DE HARDWARE

Las pantallas interactivas **NO tienen teclado físico, NO tienen ratón y NO
tienen F12 / DevTools**. Toda solución de soporte o diagnóstico DEBE poder
ejecutarse:
- Escribiendo una URL en la barra de direcciones (las pantallas sí tienen
  teclado virtual al tocar la barra).
- O desde botones visibles en la propia página.

Nunca diseñar un fix que requiera la consola del navegador o DevTools.

---

## Arquitectura (dominio único — ACTIVA)

```
Internet
  └── Cloudflare Tunnel "raspberry"
        └── lanube.uno → nginx:80 (NPM, 192.168.1.50)
                          ├── /app/  → Nextcloud  (192.168.1.50:8181)
                          └── /      → Flask kiosko (192.168.1.50:8200)
```

### IMPORTANTE: cómo funciona el túnel Cloudflare

El contenedor `cloudflared` en `~/docker/cloudflared/` **solo autentica** el
túnel con Cloudflare. Las **reglas de enrutamiento** se configuran desde el
**panel web de Cloudflare**:
`https://one.dash.cloudflare.com` → Zero Trust → Networks → Tunnels → "raspberry".

**No hay `config.yml` local con reglas de ingress — todo está online.**

Regla activa: `lanube.uno → http://192.168.1.50:80` (NPM)
NPM enruta internamente según path (ver nginx config abajo).

### nginx config (NPM custom)
Archivo: `~/docker/nginx/data/nginx/custom/http.conf`
```nginx
server {
    listen 80;
    server_name lanube.uno;

    location /app/ {
        proxy_pass         http://192.168.1.50:8181/;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_set_header   Upgrade           $http_upgrade;
        proxy_set_header   Connection        "upgrade";
        client_max_body_size 0;
        proxy_buffering    off;
    }

    location / {
        proxy_pass         http://192.168.1.50:8200/;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }
}
```

---

## Repos y rama de desarrollo

- Repo kiosko Flask: `duecaz/nfc`
- Rama activa: `claude/clever-fermat-6852kl`
- Deploy en Pi: `~/docker/kiosk/` (NO es git repo — copiar archivos manualmente o con curl)

```bash
# Actualizar app.py desde GitHub
curl -o ~/docker/kiosk/app.py \
  "https://raw.githubusercontent.com/duecaz/nfc/claude/clever-fermat-6852kl/app.py"
cd ~/docker/kiosk && docker compose down && docker compose build --no-cache && docker compose up -d
```

---

## Servicios clave

| Contenedor | Puerto externo | Ruta config |
|---|---|---|
| `nfc_kiosk` (Flask) | 8200 | `~/docker/kiosk/` |
| `nextcloud_server` | 8181 | `~/docker/nextcloud/` |
| `nginx_proxy` (NPM) | 80/81/443 | `~/docker/nginx/` |
| `cloudflared` | — | `~/docker/cloudflared/` (solo autentica) |

Alias útil en la Pi: `alias occ='docker exec -u www-data nextcloud_server php occ'`

---

## Flujo de auth NFC (cómo funciona HOY)

1. Lector NFC USB "teclea" el UID de la tarjeta en campo oculto siempre enfocado.
2. JS del kiosko hace POST a `/auth` con el UID.
3. Flask busca el UID en `users.json` → obtiene `{user, app_token}`.
4. Flask hace `GET http://192.168.1.50:8181/apps/files` con
   `Authorization: Basic base64(user:app_token)`.
   NC devuelve HTTP 200 + cookies de sesión.
5. Flask copia esas cookies al response del navegador (dominio `lanube.uno`).
6. Flask responde JSON `{ok: true, redirect: "https://lanube.uno/app/apps/files"}`.
7. JS redirige a `lanube.uno/app/apps/files` — las cookies están en el mismo dominio.
8. NC sirve los archivos. ✅

**POR QUE Basic Auth y no formulario web:**
NC 33 rechaza el POST del formulario desde proxy externo (CSRF). El endpoint
`/apps/files` con Basic Auth genera sesión completa sin CSRF.

**POR QUE dominio único resuelve las cookies:**
Flask y NC están en `lanube.uno`. Las cookies seteadas por Flask se envían
automáticamente a `lanube.uno/app/`. Sin `COOKIE_DOMAIN` ni `__Host-` workarounds.

---

## Login manual (docentes sin tarjeta)

Ruta: `lanube.uno/login-manual`
Flujo: usuario/contraseña → OCS API genera app-token → Basic Auth a `/apps/files`
→ cookies en `lanube.uno` → redirect a `lanube.uno/app/apps/files`. ✅

---

## Variables de entorno del kiosko

```yaml
NEXTCLOUD_URL=http://192.168.1.50:8181        # URL interna de NC (server-side)
NEXTCLOUD_PUBLIC_URL=https://lanube.uno/app   # URL pública de NC (redirects)
ADMIN_PASSWORD=Colegio2026!
# COOKIE_DOMAIN: NO necesario (dominio único)
```

---

## Config Nextcloud clave (config.php)

```
overwriteprotocol = https
overwritehost     = lanube.uno
overwrite.cli.url = https://lanube.uno/app
overwrite.webroot = /app
trusted_proxies   = 172.16.0.0/12, 192.168.1.0/24
trusted_domains   = 192.168.1.50, lanube.uno, app.lanube.uno
auth.bruteforce.protection.enabled = false   (TEMPORAL — reactivar en producción)
```

---

## Deploy rápido

```bash
curl -o ~/docker/kiosk/app.py \
  "https://raw.githubusercontent.com/duecaz/nfc/claude/clever-fermat-6852kl/app.py"
cd ~/docker/kiosk && docker compose down && docker compose build --no-cache && docker compose up -d
sleep 5 && curl -s http://localhost:8200/health | python3 -m json.tool
```

---

## Pendientes antes de producción

1. **Reactivar brute-force protection** en Nextcloud.
2. **Alta masiva de 30 tarjetas** via CSV en el panel admin (`lanube.uno/admin`).
3. **Servidor WSGI** (Gunicorn) en vez del server dev de Flask.
4. **Cambiar contraseñas** de testeo.
5. Eliminar regla `app.lanube.uno` de Cloudflare (ya no necesaria).
