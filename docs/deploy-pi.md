# Deploy

Rama por defecto: **`main`**. La web se sirve desde `web/`, el APK desde `apk/`.

## Web (Flask) → Raspberry Pi

La Pi **no es un repo git**: se copian los archivos con `curl` desde `main/web/`
y se reconstruye la imagen Docker (los templates van *dentro* de la imagen, por
eso `docker compose restart` NO alcanza — hay que rebuild).

```bash
B=main
cd ~/docker/kiosk && \
for f in app.py templates/index.html templates/login_manual.html templates/cambiar_clave.html templates/admin.html; do \
  curl -o "$f" "https://raw.githubusercontent.com/duecaz/nfc/$B/web/$f"; done && \
docker compose down && docker compose build --no-cache && docker compose up -d && \
sleep 5 && curl -s http://localhost:8200/health
```

- El `health` debe mostrar `"version": "N"` (el número de `VERSION` en `web/app.py`).
- Si el panel muestra la versión vieja: el service worker cachea el HTML →
  abrir `lanube.uno/reset` (en incógnito siempre se ve la real).

- **Rutina** (cambios de código): con el `curl` de arriba (app.py + templates) alcanza.
- **Infra** (Dockerfile / docker-compose / gunicorn): cambian poco; cuando cambian hay
  que curlear tambien esos archivos (ver abajo).

> `web/users.json.example` es solo plantilla. El `users.json` real vive en la Pi
> (`~/docker/kiosk/users.json`, montado como volumen) y **no** se versiona.

### Datos en SQLite (desde v25)

Las tarjetas y paneles viven en **`data/kiosk.db`** (volumen `./data`), ya no en
users.json (queda montado solo como fuente de la migración automática inicial).
Backup = copiar `~/docker/kiosk/data/kiosk.db`.

### Secretos en `.env` (obligatorio desde v21; `PANEL_SECRET` desde v25)

`docker-compose.yml` ya no trae los secretos inline; los lee de `~/docker/kiosk/.env`
(no versionado). Crear una vez en la Pi:

```bash
cd ~/docker/kiosk
cat > .env <<'EOF'
NEXTCLOUD_URL=http://192.168.1.50:8181
NEXTCLOUD_PUBLIC_URL=https://lanube.uno/app
ADMIN_PASSWORD=TU_CLAVE_ADMIN
EOF
chmod 600 .env
```

### Migración de infra (una vez, para aplicar gunicorn+threads y el .env)

```bash
cd ~/docker/kiosk
curl -o Dockerfile          "https://raw.githubusercontent.com/duecaz/nfc/main/web/Dockerfile"
curl -o docker-compose.yml  "https://raw.githubusercontent.com/duecaz/nfc/main/web/docker-compose.yml"
# (crear .env como arriba si no existe)
docker compose down && docker compose build --no-cache && docker compose up -d
sleep 5 && curl -s http://localhost:8200/health
```

## APK (.NET) → panel

Desde el PC Windows (PowerShell), con el panel accesible por adb:

```powershell
$D = "192.168.1.57:5555"
adb connect $D
cd D:\ruta\al\repo
git pull origin main
Remove-Item apk\obj,apk\bin -Recurse -Force -ErrorAction SilentlyContinue
dotnet build apk\KioskNfc.csproj -c Release
adb -s $D uninstall uno.lanube.kiosk        # opcional: build limpio + borra cookies
adb -s $D install "apk\bin\Release\net10.0-android\uno.lanube.kiosk-Signed.apk"
adb -s $D shell monkey -p uno.lanube.kiosk 1
```

- La etiqueta abajo-izquierda del kiosko muestra `apk vN` (constante `ApkVersion`
  en `apk/MainActivity.cs`) — sirve para confirmar que instalaste el build nuevo.
- Ver NFC + sesión en vivo:
  ```powershell
  adb -s $D logcat -v time -s NfcKit:* NfcBridge:* LaNubeKiosk:*
  ```
- Borrar cookies/datos del kiosko: `adb -s $D shell pm clear uno.lanube.kiosk`

## Diagnóstico en el panel (sin DevTools)

En el kiosko, link **"test"** (abajo-derecha) → página `/test`: muestra el UID
crudo + canónico, si está registrada, el puente `AndroidKiosk`, y un botón para
probar el auto-logout en 1 minuto.

## Pendientes de producción

1. ✅ Bruteforce Nextcloud reactivado:
   `docker exec -u www-data nextcloud_server php occ config:system:set auth.bruteforce.protection.enabled --value true --type boolean`
2. Alta masiva de tarjetas por CSV en `/admin`.
3. Sacar `ADMIN_PASSWORD` de `web/docker-compose.yml` a un `.env` en la Pi.
4. Cambiar contraseñas de testeo.
