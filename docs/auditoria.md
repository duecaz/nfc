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
| 9 | Kiosko no bloqueado / sin auto-reinicio. | **Lock Task Mode** + auto-restart vía MDM (ver §6). |
| 10 | Sin monitoreo central de paneles. | Heartbeat + panel de estado, o el dashboard del MDM (ver §6). |
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

### Kiosko inviolable + auto-reinicio (#9)
- **Lock Task Mode** (screen pinning / modo kiosco): bloquea el panel a **nuestra
  app**; el usuario no puede salir a Ajustes, otras apps ni al home. Requiere que
  la app sea **device owner** — se logra con el **MDM** (o `dpm set-device-owner`
  en aprovisionamiento). Con el MDM esto viene “de fábrica”.
- **Auto-reinicio:** si la app crashea, que vuelva sola. El modo kiosco del MDM lo
  hace; alternativa: registrar la app como **HOME/launcher** para que Android la
  relance.

### Monitoreo central (#10)
Con muchos paneles no podés ir a cada uno. Opciones:
- **Dashboard del MDM**: la mayoría muestra online/offline + versión de app
  instalada. Si el MDM lo da, quizás no haga falta nada más.
- **Heartbeat propio**: cada panel hace `POST /panel-ping` cada X min con su id +
  versión + hora; el server guarda “última vez visto” y una página admin lista
  paneles (online/offline, versión). Barato y da inventario propio.

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
