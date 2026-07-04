# Auditoría de estabilidad y guía para producción

> **Contexto:** este repo es un **prototipo de testeo**. La versión de producción
> se hará **desde cero** tomando estas lecciones. Este documento registra: qué se
> auditó, qué se ajustó en el prototipo, y **qué hacer distinto en producción**.

---

## 1. Proyección de uso

| Momento | Usuarios totales | Concurrentes (~5%) |
|---|---|---|
| Inicio | 10 | ~1 |
| Meses | 30 | ~2 |
| 1 año | 200 | ~10 |
| 2 años | 300 | **~15** |

**Conclusión:** el pico realista es **~15 logins simultáneos**. La web ya queda
holgada (24 concurrentes configurados). El límite real a vigilar no es la web
sino **Nextcloud + la Pi** (ver §4).

---

## 2. Auditoría — hallazgos y estado

### 🔴 Críticos (resueltos en el prototipo, v21–v22)

| # | Hallazgo | Arreglo |
|---|---|---|
| 1 | Rate-limit **global** por IP: detrás del proxy toda la flota compartía 1 IP → 429 a todos. | `ProxyFix` (IP real) + `/auth` limitado **por UID de tarjeta** (20/min), no global. |
| 2 | gunicorn 2 workers **síncronos** → solo 2 logins a la vez. | `3 workers × 8 threads` (gthread) = ~24 concurrentes. I/O-bound: los threads esperan a Nextcloud en paralelo. |
| 3 | Contador del rate-limit en memoria por worker (aprox. con varios workers). | Aceptable: es una red de seguridad, no exactitud fiscal. En producción → storage compartido (Redis). |
| 6 | `ADMIN_PASSWORD` inline en `docker-compose.yml`. | Movido a `.env` (no versionado) + `.env.example`. |

### 🟠 Importantes (roadmap)

| # | Hallazgo | Plan |
|---|---|---|
| 4 | **Pi = punto único de falla** de toda la flota. | Ver §4 (capacidad) y §5 (producción). Monitoreo + backups. |
| 5 | **App-tokens en texto plano** en `users.json`. | Cheap ahora: `chmod 600`. Producción: cifrar en reposo + secretos gestionados (ver §5). |
| 7 | Hardware NFC hardcodeado (bus 6/4, addr 0xA6). | **No aplica**: la flota es un solo modelo de panel. |

### 🟡 Operacional

| # | Tema | Plan |
|---|---|---|
| 8 | Actualizar APK panel por panel. | Se usará el **DMS/MDM** para desplegar el APK (ver §6). |
| 9 | Kiosko no bloqueado / sin auto-reinicio. | ✅ **Auto-reinicio ante crash** implementado (v9). Lock Task = *hook* opt-in; bloqueo real vía MDM (ver §6). |
| 10 | Sin monitoreo central de paneles. | ✅ **Heartbeat** implementado: el APK pinguea `/panel-ping` c/5 min; estado en `/admin/panels`. |
| 11 | `users.json` como “BD”. | Pocos al inicio, OK. Producción → SQLite/Postgres. |

---

## 3. Respuestas técnicas

### Workers vs threads (pregunta #2)
- **Worker** = un proceso separado de Python. Cuesta RAM (~40 MB c/u) y da
  paralelismo de CPU + resiliencia (si uno se cuelga, quedan los otros).
- **Thread** = una línea de ejecución **dentro** de un worker. Es barata.
- Nuestro trabajo es **I/O-bound**: cada `/auth` se queda **esperando** la
  respuesta de Nextcloud (1–3 s). Durante esa espera el thread libera la CPU y
  **otro thread atiende otro login**. Por eso **pocos workers + muchos threads**
  es lo eficiente. `3×8 = 24` concurrentes con poca RAM. Con 4 workers también
  sirve, solo gasta más RAM sin necesidad (tu pico es ~15).

### “memory://” del rate-limit (pregunta #3)
No es memoria por sesión. Es **dónde guarda flask-limiter los contadores**
(“cuántos intentos lleva esta tarjeta este minuto”). Vive en la RAM de cada
worker. Con varios workers cada uno tiene su contador, así que el límite es
**aproximado** (una tarjeta podría llegar a `workers × 20` antes de frenarse).
Para nosotros da igual (es una red de seguridad, no un control fiscal). En
producción, si se quiere exactitud → Redis compartido.

### Capacidad de la Pi 5 8 GB + M.2 SSD (pregunta #4)
Buen setup — el **SSD M.2 es clave** (una microSD sería el cuello de botella).

| Recurso | Límite práctico (bien tuneado) | Tu horizonte |
|---|---|---|
| **Concurrentes activos** (Nextcloud) | ~40–60 cómodos | ~15 a 2 años ✅ |
| **Usuarios registrados** | miles (solo filas/archivos) | 300 ✅ |
| **Almacenamiento** | lo que dé el SSD | según archivos |
| **Flask/logins** | ~24 concurrentes | ~15 ✅ |

**Veredicto:** la Pi 5 8 GB + SSD **aguanta todo tu horizonte de 2 años (300
usuarios, ~15 concurrentes) con margen**, siempre que Nextcloud esté tuneado:

- Base de datos **MariaDB** (no SQLite).
- **Redis** para locking transaccional y caché.
- **APCu** para caché local.
- **PHP-FPM** con `pm=dynamic` y suficientes children.
- **Previews** limitadas (no generar de todo) — es lo que más CPU consume.
- **Cron** real (no AJAX) para tareas de fondo.

Picos a vigilar: generación de miniaturas, subidas grandes simultáneas y ancho
de banda del túnel. Monitorear CPU/IO/RAM (ver §6).

---

## 4. Seguridad del token (#5)

Hoy los **app-tokens de Nextcloud** se guardan en texto plano en `users.json`.
Si comprometen la Pi, se filtran todos. Mitigaciones:

**Ahora (prototipo):**
- `chmod 600 ~/docker/kiosk/users.json` (solo el dueño lo lee).
- No versionar `users.json` (ya está en `.gitignore` como `.example`).
- Los tokens son **revocables** desde Nextcloud (Ajustes → Seguridad).

**Producción (desde cero):**
- Cifrar el token **en reposo** (p. ej. Fernet con clave fuera del host / KMS).
- Contenedor **no-root**, filesystem de solo-lectura salvo el volumen de datos.
- Secretos en un gestor (Docker secrets / Vault), no en `.env` plano.
- Evaluar **no almacenar** tokens de larga vida: usar el flujo OAuth device-code
  de Nextcloud y refrescar, o sesiones cortas.

---

## 5. Punto único de falla (#4 infra)

Toda la flota depende de una Pi. Para producción:
- **Backups** automáticos de `users.json`, DB y config (a otro disco/nube).
- **Monitoreo con alerta** (si la Pi/tunnel cae, avisa).
- Considerar **redundancia** (segunda Pi en espera / restauración rápida).
- El túnel Cloudflare es otro SPOF: tener plan B (acceso LAN directo de
  respaldo `http://192.168.1.50:8200`).

---

## 6. Operación de la flota (#8, #9, #10)

### Despliegue del APK vía DMS/MDM (#8)
En vez de `adb install` panel por panel, subir el APK firmado al MDM y empujarlo
a todos. El MDM también fija versión y evita drift.

### Kiosko inviolable + auto-reinicio (#9) — implementado (v9)
- **Auto-reinicio ante crash** ✅: `MainActivity` engancha las excepciones no
  controladas y **relanza el kiosko en ~1.5 s** vía `AlarmManager` (método
  `ScheduleRestart`). Una caída ya no deja el panel muerto.
- **Lock Task Mode**: hay un *hook* (`KioskLock`, **apagado por defecto**). El
  lock-task estricto **bloquea abrir/subir archivos** (Nextcloud usa apps
  externas), así que el bloqueo real se hace con el **MDM** (device-owner +
  `setLockTaskPackages` incluyendo las apps de archivos). Con MDM se activa
  `KioskLock=true` sin romper nada.

### Monitoreo central (#10) — implementado (v24, bajo demanda)
- **Heartbeat propio** ✅: cada panel hace `POST /panel-ping` con su **id**
  (ANDROID_ID), **versión de APK** y **estado NFC** (ok/fail). El server guarda
  “última vez visto” + IP en `panels.json` (efímero).
- **Bajo demanda (carga mínima):** por defecto los paneles pinguean **cada 10 min**
  (≈3 req/min con 30 paneles). Desde `/admin/panels` se activa **"Monitoreo
  intensivo"** → el server responde a cada ping con un intervalo corto y los
  paneles pasan a **cada 1 min** (para soporte en vivo). Se apaga y vuelven a 10 min.
  El panel se auto-ajusta con la respuesta del ping (sin polling extra).
- **Vista**: `/admin/panels` (link en el admin): tabla de la flota (online/offline,
  versión, NFC) + el toggle ON/OFF. Se refresca sola cada 30 s.
- Complementario al **dashboard del MDM** (online/offline + versión).

---

## 7. Recomendaciones para PRODUCCIÓN (desde cero)

Resumen de lo que conviene cambiar respecto al prototipo:

1. **Datos**: `users.json` → **SQLite/Postgres** (o Supabase, ya evaluado).
2. **Secretos**: gestor de secretos + tokens cifrados en reposo.
3. **Rate-limit**: storage **Redis** (exacto y compartido).
4. **Infra**: backups + monitoreo con alertas + plan de redundancia/SPOF.
5. **APK**: device-owner por MDM (Lock Task + auto-restart + OTA).
6. **Observabilidad**: heartbeat de paneles + métricas de Nextcloud/Pi.
7. **NFC**: mantener el patrón `DexClassLoader` (probado); parametrizar bus/addr
   por si cambia el modelo de panel.
8. **Versionado**: mantener el número `VERSION`/`ApkVersion` visible (ya sirve
   para detectar drift).

Lo que **funcionó bien** y hay que conservar:
- Lectura NFC por `droidlogic.jar` real (`DexClassLoader`) — estable, ~1.7 ms.
- UID canónico en el server (`canon_uid`) — matchea venga de donde venga.
- Cierre de sesión con **timer nativo del APK** (no depende del navegador).
- Deploy web reproducible desde `main/web/` + `.env`.

---

## 8. Revisión para 50 pantallas (2ª auditoría, flujo completo)

> Veredicto: **APTO CON 2 CORRECCIONES PREVIAS** (F1 y F2). El camino NFC→login
> es sólido; la web aguanta la concurrencia (pico estimado ~25 logins/min vs
> 24 slots). Diagrama completo publicado como artifact de la sesión.

### Hallazgos nuevos (F#) — orden de riesgo

| # | Sev. | Falla | Corrección |
|---|---|---|---|
| **F1** | 🔴 | El APK apunta a `https://lanube.uno`: TODO el tráfico panel↔Pi sale a internet y vuelve por Cloudflare. **Corte de internet = 50 paneles sin login** aunque la LAN funcione; además duplica el consumo del ISP. | **DNS local**: resolver `lanube.uno` → `192.168.1.50` en el router/Pi-hole (split-horizon). Cloudflare queda solo para acceso externo. Sin tocar el APK. ~2 h |
| **F2** | 🔴 | Los locks de `users.json`/`panels.json` son `threading.Lock` (por proceso). Con 3 workers gunicorn, 2 procesos pueden hacer read-modify-write a la vez → registro perdido o **JSON corrupto** (sin users.json nadie entra). Con monitoreo ON y 50 paneles (50 writes/min) la colisión es cuestión de días. | Escritura **atómica** (tmp + `os.replace`) + **file-lock** (`fcntl`). ~2 h |
| **F3** | 🔴 | Pi = SPOF (ya conocido, #4). | Backup diario users.json+DB, SD clonada de repuesto, alerta si `/health` no responde. |
| **F4** | 🟠 | Ráfaga del cambio de hora: 20-30 aperturas de Archivos simultáneas encolan PHP en la Pi (lentitud, no caída). | Tuning NC (§3) + F1 quita el RTT de internet. |
| **F5** | 🟠 | `/panel-ping` es público: ids inventables gratis → panels.json crece sin tope. | Secreto compartido en el POST + tope 200 entradas. ~1 h |
| **F6** | 🟠 | Tarjeta durante sesión abierta **se ignora** (las páginas NC no tienen `authenticate()`); no hay cambio de usuario/bloqueo hasta expirar el timer. | Mover la detección al APK (sesión activa + tarjeta → logout o preguntar). **Diseñar en producción.** |
| **F7** | 🟡 | Id de panel = `ANDROID_ID`; en 50 paneles clonados de fábrica puede repetirse → 2 paneles = 1 fila del inventario. | Concatenar con serial (`Build.SERIAL`/getprop). |
| **F8** | 🟡 | WebView semanas encendido: memoria sin medir a largo plazo. | Soak test 7 días en piloto + reinicio nocturno 3 am. |
| **F9** | 🟡 | Rate-limit `memory://` aproximado entre workers. | Aceptado en prototipo; producción → Redis. |

### Números a 50 paneles

- Heartbeat en reposo: 50/10 min = **5 req/min** (nada). Monitoreo ON: 50/min.
- Pico de login (cambio de hora): **~25/min**, capacidad actual 24 concurrentes ✅.
- Lectura NFC local por panel: sin límite de escala (1.7 ms, no toca el server).

### Orden de ejecución antes del despliegue

1. DNS local (F1) → 2. escritura atómica (F2) → 3. backups+alerta (F3) →
4. secreto panel-ping (F5) → 5. soak test (F8) → 6. despliegue por MDM +
Lock Task device-owner → (producción) F6, Redis, SQLite, tokens cifrados.

---

## 9. Decisiones del cliente sobre F1–F9 (y estado de implementación)

| # | Decisión / aclaración | Estado |
|---|---|---|
| **F1** | ⚠️ **Aclaración de topología**: en producción los paneles del colegio **NO están en la misma red que la Pi** (192.168.1.x es la red local de la Pi, no existe en el colegio). El atajo por DNS local **solo es posible si el servidor se instala físicamente en el colegio**. El dominio `lanube.uno` NUNCA cambia (Nextcloud valida por `trusted_domains`, que ya incluye el dominio — la regla DNS solo cambia *a qué IP* apunta ese dominio dentro del edificio, no el nombre). **Decisión pendiente**: dónde vivirá el servidor de producción. Recomendación: **en el colegio** (ver F3). | 📋 Decisión de despliegue |
| **F2** | **SQLite aprobado e implementado (v25)**: `web/data/kiosk.db` reemplaza `users.json` y `panels.json`. Tablas `cards`, `panels`, `config` (flag de monitoreo). WAL + busy_timeout → transacciones seguras entre los 3 workers. **Migración automática**: al primer arranque importa `users.json` si la tabla está vacía. Probado con 3 procesos escribiendo a la vez sin corrupción. | ✅ v25 |
| **F3** | Respaldo: propuesta = **producción en mini-PC x86 (Intel N100, 16 GB, NVMe, ~150-250 USD)** instalado EN el colegio (resuelve F1 y da 2-3× el rendimiento de la Pi para Nextcloud), y **la Pi 5 actual pasa a ser el standby/espejo** (restauración en minutos) + backup diario automatizado a otro medio. Alternativa más barata: segunda Pi 5 como standby. | 📋 Para producción |
| **F4** | Aclaración MariaDB vs SQLite — **son para cosas distintas y coexisten**: SQLite = la tablita del kiosko (tarjetas/paneles, nuestra app). MariaDB = la base **interna de Nextcloud** (NC desaconseja SQLite para multiusuario). Ambas recomendaciones siguen vigentes. | 📋 Tuning NC pendiente |
| **F5** | Secreto compartido implementado: el APK manda `secret` en cada `/panel-ping`; el server lo exige si `PANEL_SECRET` está definido en `.env` (vacío = compatibilidad). Tope de inventario: 200 paneles (se expulsa el más viejo). | ✅ v25/apk11 |
| **F6** | **Aceptado como diseño**: el flujo normal es que el docente use "Cerrar sesión" de Nextcloud (que ya intercepta `/logout` y vuelve al kiosko) o expire el timer. No se cambia en el prototipo. | ✅ Aceptado |
| **F7** | Id de panel = **MAC de la red cableada** (`/sys/class/net/eth0/address`), con ANDROID_ID como fallback. | ✅ apk11 |
| **F8** | Supervisión de paneles: el heartbeat ahora manda **RAM usada/total del panel**; se muestra por panel en `/admin/panels`. | ✅ v25/apk11 |
| **F9** | Supervisión de la Pi: `/admin/panels` muestra tiles de **carga CPU (load), RAM, disco y temperatura** de la Pi con umbral rojo (load>3, RAM>85%, disco>85%, temp>75°C). Docker no aísla `/proc`, así que las cifras son del host real. | ✅ v25 |

### Migración de infra para v25 (una vez, en la Pi)

```bash
cd ~/docker/kiosk
curl -o docker-compose.yml "https://raw.githubusercontent.com/duecaz/nfc/main/web/docker-compose.yml"
mkdir -p data
echo "PANEL_SECRET=lanube-panel-2026" >> .env    # mismo valor que PanelSecret del APK
# luego el deploy normal (curl app.py+templates + rebuild). Al arrancar veras en logs:
# [DB] migradas N tarjetas desde users.json
```

---

## 10. Arquitectura real y respaldo (aclaración del cliente)

**Topología confirmada:** un solo servidor = **la Raspberry Pi 5** (Docker: Nextcloud
+ Flask + nginx + cloudflared, archivos en SSD). La "nube" es **solo Cloudflare para
el dominio/túnel** — no se hostea ni se guarda nada afuera. Sirve a los paneles de
**varios colegios** y a los **docentes desde sus casas**, todo vía `lanube.uno`.

- **F1 se descarta**: con multi-colegio + acceso desde casas, el tráfico por internet
  es inherente y correcto. No hay atajo DNS posible (no comparten LAN).
- **El SPOF real es la Pi**: su SSD, corriente e internet son el punto único de falla
  de toda la operación. Mitigación = respaldo + Pi de repuesto (no mover a la nube).

**Base de datos (1 sola Pi):** SQLite es la elección correcta (ya implementada, sin
servidor extra, no compite por RAM con Nextcloud). MariaDB solo tendría sentido si
NC ya la usa y se quiere una sola base. **PocketBase** (SQLite + admin + API +
respaldos automáticos, un binario) es el candidato para la producción si se quiere
menos código propio. Se descartan JSON (F2) y un DB server dedicado en la Pi.

**Respaldo (F3) — implementado:** `tools/backup-pi.sh` (correr en la Pi):
1. `kiosk.db` con `sqlite3 .backup` (consistente con WAL).
2. Nextcloud en **modo mantenimiento** → dump de su base (`mysqldump`) + `tar` de los
   archivos de la SSD + config. Sale de mantenimiento.
3. Conserva las últimas 7 copias; opcional `rsync` a una PC/NAS (regla 3-2-1).
Programar con cron a las 3am. **Ideal: `BACKUP_DIR` en OTRO disco**, no en la SSD
principal (si muere la SSD, el backup no debe morir con ella). Copia offsite
recomendada: PC/NAS encendido o un bucket B2/Wasabi.
