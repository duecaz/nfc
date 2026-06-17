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

## Arquitectura actual (dos subdominios)

```
Internet
  └── Cloudflare Tunnel "raspberry"
        ├── lanube.uno      → Flask kiosko NFC  (192.168.1.50:8200)
        └── app.lanube.uno  → Nextcloud          (192.168.1.50:8181)
```

### IMPORTANTE: cómo funciona el túnel Cloudflare

El contenedor `cloudflared` en `~/docker/cloudflared/` **solo autentica** el
túnel con Cloudflare. Las **reglas de enrutamiento** (qué hostname va a qué
IP:puerto) se configuran desde el **panel web de Cloudflare**:
`https://one.dash.cloudflare.com` → Zero Trust → Networks → Tunnels.

NO hay un `config.yml` local con reglas de ingress — todo está online.
Nginx Proxy Manager (`~/docker/nginx/`) existe en la Pi pero actualmente
**no está en el camino del tráfico**: cloudflared enruta directo a los servicios.

### Pendiente: migración a dominio único

El problema de dos subdominios: las cookies de sesión de Nextcloud se setean
en `lanube.uno` (donde está Flask); al redirigir a `app.lanube.uno` el
navegador no las envía. Las cookies `__Host-` de NC no admiten el atributo
`Domain`, por lo que no se pueden compartir aunque se use `COOKIE_DOMAIN=.lanube.uno`.

**Plan de migración (aún no ejecutado):**
```
lanube.uno/        → Flask kiosko (igual que hoy)
lanube.uno/app/    → Nextcloud (nuevo — via nginx con proxy_pass + strip prefix)
```
Requiere:
- Panel Cloudflare: regla única `lanube.uno → nginx local`
- nginx: `location /app/ { proxy_pass http://192.168.1.50:8181/; }`
- NC config.php: `overwrite.cli.url=https://lanube.uno/app`, `overwrite.webroot=/app`
- docker-compose kiosko: `NEXTCLOUD_PUBLIC_URL=https://lanube.uno/app`, sin `COOKIE_DOMAIN`

---

## Repos y rama de desarrollo

- Repo kiosko Flask: `duecaz/nfc`
- Rama activa: `claude/clever-fermat-6852kl`
- Deploy en Pi: `~/docker/kiosk/` (git pull + docker compose up)

---

## Servicios clave

| Contenedor | Puerto externo | Ruta config |
|---|---|---|
| `nfc_kiosk` (Flask) | 8200 | `~/docker/kiosk/` |
| `nextcloud_server` | 8181 | `~/docker/nextcloud/` |
| `nginx_proxy` (NPM) | 80/81/443 | `~/docker/nginx/` (sin uso activo en tráfico) |
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
5. Flask copia esas cookies al response del navegador.
6. Flask responde JSON `{ok: true, redirect: "https://app.lanube.uno/apps/files"}`.
7. JS del kiosko redirige al navegador a `app.lanube.uno/apps/files`.

**POR QUE Basic Auth y no formulario web:**
NC 33 hace validación estricta de `Origin` contra `overwrite.cli.url`.
El POST del formulario desde Flask **siempre falla con CSRF rejection** — no
tiene solución desde un proxy externo sin modificar NC. El endpoint `/apps/files`
con Basic Auth sí funciona y genera sesión completa.

**Limitación actual:** las cookies se setean en `lanube.uno` (Flask) pero la
redirección va a `app.lanube.uno`. El navegador no envía esas cookies al dominio
diferente. Solución: migración a dominio único (ver arriba).

---

## Login manual (docentes sin tarjeta)

Ruta: `lanube.uno/login-manual`
Flujo: usuario/contraseña → OCS API genera app-token → Basic Auth a `/apps/files`.
Mismo problema de cookies cross-subdomain que el NFC.

Alternativa temporal: el link "Sin tarjeta →" en el kiosko apunta directamente
a `https://app.lanube.uno/login` (login nativo de NC, funciona perfecto).

---

## Variables de entorno del kiosko (docker-compose en Pi)

```yaml
NEXTCLOUD_URL=http://192.168.1.50:8181        # URL interna de NC
NEXTCLOUD_PUBLIC_URL=https://app.lanube.uno   # URL pública de NC
COOKIE_DOMAIN=.lanube.uno                     # compartir cookies entre subdominios
ADMIN_PASSWORD=Colegio2026!
```

Tras migración a dominio único:
```yaml
NEXTCLOUD_URL=http://192.168.1.50:8181
NEXTCLOUD_PUBLIC_URL=https://lanube.uno/app
# COOKIE_DOMAIN ya no necesario
```

---

## Config Nextcloud clave (config.php actual)

```
overwriteprotocol = https
overwritehost     = app.lanube.uno
overwrite.cli.url = https://app.lanube.uno
trusted_proxies   = 172.16.0.0/12, 192.168.1.0/24
trusted_domains   = 192.168.1.50, lanube.uno, app.lanube.uno
auth.bruteforce.protection.enabled = false   (TEMPORAL — reactivar en producción)
```

---

## Deploy rápido (tras cambios en el repo)

```bash
cd ~/docker/kiosk
git fetch origin claude/clever-fermat-6852kl
git pull origin claude/clever-fermat-6852kl
docker compose down && docker compose build --no-cache && docker compose up -d
sleep 5 && curl -s http://localhost:8200/health | python3 -m json.tool
```

Verificar que `/health` muestre la versión correcta y `cookie_domain` activo.

---

## Pendientes críticos antes de producción

1. **Migración a dominio único** (`lanube.uno/app` para NC) — resuelve el
   problema de cookies y simplifica la arquitectura.
2. **Reactivar brute-force protection** en Nextcloud.
3. **Alta masiva de 30 tarjetas** via CSV en el panel admin.
4. **Servidor WSGI** (Gunicorn/uWSGI) en vez del server dev de Flask.
5. **Cambiar contraseñas** de testeo antes de producción.
