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

## Dominios (Cloudflare túnel "raspberry")
- `https://lanube.uno` → **kiosko NFC** (192.168.1.50:**8200**)
- `https://app.lanube.uno` → **Nextcloud** (192.168.1.50:**8181**)
- Cookies de sesión compartidas vía dominio padre `.lanube.uno`.

## Credenciales (TESTEO — cambiar en producción)
- Nextcloud admin: usuario `nextcloud` · contraseña `Colegio2026!`
- Docente de prueba: `jperez` · grupo `profesores` · cuota 5GB
- Kiosko: `~/docker/kiosk/users.json` mapea `UID_tarjeta → {user, token}`

---

## Cómo funciona el kiosko NFC (Flask, puerto 8200)
1. El lector NFC USB "teclea" el UID + Enter en un campo oculto siempre enfocado.
2. El kiosko busca el UID en `users.json` → usuario + token (app password).
3. Hace login server-side contra `https://app.lanube.uno` (como un navegador real).
4. Reenvía las cookies de sesión (dominio `.lanube.uno`) al navegador.
5. Redirige al docente a `https://app.lanube.uno/apps/files` ya logueado.

### Variables del contenedor kiosko (producción)
```
NEXTCLOUD_URL=https://app.lanube.uno
NEXTCLOUD_PUBLIC_URL=https://app.lanube.uno
COOKIE_DOMAIN=.lanube.uno
```

### Formato de users.json (tokens — formato actual)
```json
{
  "UID_DE_TARJETA": { "user": "jperez", "token": "xxxx-yyyy-zzzz-aaaa" }
}
```
> El campo `token` es un **app password de Nextcloud** (revocable desde
> Configuración → Seguridad). Si el docente cambia su contraseña real,
> el token sigue funcionando. Si se pierde o filtra, se revoca sin afectar
> a los demás. El campo `password` (clave real) sigue soportado como
> fallback pero NO debe usarse en producción.

### Generar un app password para un docente
```bash
# Desde la Pi — autenticar con la clave real para obtener un token revocable
docker exec nextcloud_server curl -s \
  -u "jperez:CLAVE_REAL" \
  -H "OCS-APIRequest: true" \
  "http://localhost/ocs/v2.php/core/getapppassword"

# La respuesta XML contiene <apppassword>TOKEN</apppassword>
# Copiar ese valor y ponerlo en users.json como "token": "TOKEN"
```

### Hallazgos clave (que costó descubrir)
- El login programático contra Nextcloud **exige el header `Origin`**; sin él
  redirige a `/login?direct=1` sin validar la contraseña (CSRF).
- Hablar con Nextcloud por su **URL pública** (no por la IP interna) evita los
  conflictos de proxy/HTTPS.
- La cookie de sesión `oc...` NO lleva prefijo `__Host-` (sí se comparte entre
  subdominios); las `__Host-nc_sameSiteCookie*` se saltan (Nextcloud las regenera).
- Diagnóstico de oro: si `curl -u user:token .../remote.php/dav/files/user/` da
  **200**, la credencial es correcta → el problema es CSRF/Origin/cookies, no la clave.
- Los **app passwords** funcionan igual que contraseñas reales en el formulario
  de login de Nextcloud (campo `password` del POST a `/login`).

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

# Reiniciar / reconstruir el kiosko
cd ~/docker/kiosk && docker compose up -d --build --force-recreate
cd ~/docker/kiosk && docker compose logs --tail=15 kiosk

# occ (admin Nextcloud) — usa el alias
occ user:list
occ config:system:get <clave>

# Crear docente + cuota
docker exec -e OC_PASS='ClaveProfe!' -u www-data nextcloud_server php occ \
  user:add --password-from-env --group="profesores" --display-name="Nombre" usuario
occ user:setting usuario files quota "5 GB"

# Verificar credencial por WebDAV (200 = correcta, funciona con token o password)
docker exec nextcloud_server curl -s -o /dev/null -w "%{http_code}\n" \
  -u "USER:TOKEN_O_PASS" http://localhost/remote.php/dav/files/USER/

# Generar app password (token revocable) para un docente
docker exec nextcloud_server curl -s \
  -u "USER:CLAVE_REAL" \
  -H "OCS-APIRequest: true" \
  http://localhost/ocs/v2.php/core/getapppassword
# Respuesta: <apppassword>TOKEN</apppassword> -> copiar en users.json

# Health check del kiosko (muestra cuántos usuarios tienen token vs password)
curl http://localhost:8200/health
```

---

## Service worker fantasma — diagnóstico y solución

### Síntoma
Una pantalla entra a `lanube.uno` y redirige sola a `lanube.uno/index.php/login`
(la página de login de Nextcloud) en vez de mostrar el kiosko.

### Causa raíz
Cuando `lanube.uno` servía Nextcloud, el browser instaló el **service worker
(SW) de Nextcloud** en el scope `/` del dominio. Ahora que `lanube.uno` sirve
el kiosko Flask, ese SW viejo sigue registrado y **intercepta TODAS las
requests**, sirviendo contenido cacheado de Nextcloud.

### Por qué `Clear-Site-Data` no alcanza
El header `Clear-Site-Data: "cache", "cookies", "storage"` borra la caché
HTTP y el localStorage, **pero NO desregistra service workers** — esa opción
no existe en la spec del navegador (2024). El SW sobrevive.

### Solución implementada (en app.py)
**Ruta `/reset`** — acceder desde la barra de URLs de la pantalla táctil:
1. JS llama `navigator.serviceWorker.getRegistrations()` y desregistra todos.
2. Limpia Cache API, localStorage y sessionStorage.
3. Registra `/sw.js` como **segunda capa**: un SW "auto-destructor" que
   toma el control inmediatamente (`skipWaiting`), borra caches y se
   desregistra solo, **sin navegar clientes** (si navegara de vuelta a
   `/reset` causaría un bucle infinito).
4. Muestra un botón verde **"Abrir kiosko NFC →"** y auto-redirige a `/`
   después de 2 s extra para que el SW termine.

### Cómo aplicarlo en la pantalla atascada
```
lanube.uno/reset
```
Escribir esa URL en la barra de direcciones (teclado virtual de la pantalla
táctil). En ~3 segundos la pantalla muestra el botón verde y se limpia sola.
No requiere F12 ni DevTools.

### Lección para futuros desarrollos
> Si en algún momento se instala un service worker en `lanube.uno` o en
> cualquier dominio del colegio, el proceso de desinstalación DEBE poder
> ejecutarse desde la barra de URLs del navegador, sin herramientas de
> desarrollador. Diseñar siempre una ruta `/reset` (o similar) con esta
> lógica de dos capas (JS directo + SW destructor).

---

## DEUDAS / PENDIENTES
1. ~~**Service worker fantasma:** `lanube.uno` redirigía a `/index.php/login`~~
   → **RESUELTO**: `/reset` con JS de desregistro + SW auto-destructor.
   Ver sección "Service worker fantasma" para el diagnóstico completo.
2. **App passwords:** ~~`users.json` guarda contraseña real; si el docente
   cambia su clave, el NFC se rompe.~~
   → **MIGRADO**: `app.py` ahora prefiere el campo `token` (app password
   revocable). Pendiente: migrar los `users.json` existentes en producción
   generando un token por docente con el comando de arriba.
3. Reactivar protección anti-fuerza-bruta antes de producción.
4. Servidor WSGI real para el kiosko (hoy usa el server de desarrollo de Flask).
5. Alta masiva de las 30 tarjetas (script CSV → usuarios + tokens).
6. Google Drive: cada docente con su Drive personal → OAuth en modo Testing
   exige agregar cada correo (pesado para 30 cuentas personales). Decisión pendiente.

---

## Prompt para retomar en otra conversación
> Estoy montando "La Nube": Nextcloud (app.lanube.uno) + un kiosko NFC en Flask
> (lanube.uno) en mi Raspberry Pi 5, expuesto por Cloudflare. El docente pasa su
> tarjeta NFC y entra a sus archivos sin teclear. Te adjunto el MD con todo el
> inventario (puertos, rutas, comandos, config y deudas). No puedes acceder a mi
> Pi: yo ejecuto los comandos por SSH y te pego resultados; empieza siempre con
> `cd ~`. RESTRICCIÓN CRÍTICA: las pantallas interactivas no tienen F12 ni
> DevTools — toda solución debe funcionar desde la barra de URLs o botones
> visibles en pantalla.
