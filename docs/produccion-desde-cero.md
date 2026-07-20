# 🏗️ Producción desde cero — el plano de La Nube v2

> **EL DOCUMENTO MÁS IMPORTANTE DEL REPO.** Este proyecto (repo `duecaz/nfc`) es un
> **prototipo de testeo**. La versión de **producción se construye desde cero** usando
> este plano — que destila TODO lo aprendido. Objetivo: un sistema **sin los fallos**
> que descubrimos en el prototipo.
>
> Léelo junto con: `vision.md` (decisiones D1–D18 con su porqué) y `auditoria.md`
> (hallazgos F1–F9 con el detalle técnico).

---

## 1. Qué construimos (alcance del v2)

Sistema **self-hosted** donde un docente acerca su **tarjeta NFC** a cualquier
pantalla interactiva de la marca — **en cualquier colegio** — y entra a **sus
archivos** (Nextcloud) en segundos. Desde su casa entra por navegador. El token de
acceso vive asociado a la tarjeta. Multi-colegio, un servidor central, flota de
paneles Android administrados por MDM.

Tres pilares: **sin fricción** (un toque = sesión) · **multi-colegio** (misma tarjeta
en cualquier pantalla) · **soberanía** (todo en hardware propio; la nube externa es
solo dominio/túnel).

---

## 2. CONSERVAR — lo que funcionó (probado en el prototipo)

Estas decisiones son correctas; replicarlas. Detalle y porqué en `vision.md` (D#).

- **D1 · NFC**: leer con el `droidlogic-tv.jar` REAL del panel vía `DexClassLoader` +
  reflexión. **Nunca** bundlear el `classes.jar` (es stub vacío → lee ceros). ~1.7 ms.
- **D2 · UID canónico** en el servidor (decimal/hex/`:` → hex mayúsculas). Matchea
  venga del lector que venga; sin re-registrar tarjetas.
- **D3 · Cierre de sesión desde el APK** (timer nativo), no desde la web (un
  `setTimeout` muere al navegar). `0` = sin límite.
- **D5 · Un solo dominio** (Flask + Nextcloud bajo `lanube.uno`) → cookies
  compartidas. Login por **Basic Auth con app-token** (NC rechaza POST de login por CSRF).
- **D7/D8 · Escala**: `ProxyFix` + rate-limit **por UID de tarjeta** (no global) +
  gunicorn con **threads** (I/O-bound: cada login espera a NC).
- **D9/D10 · Flota**: heartbeat bajo demanda (el server dicta el intervalo) · id de
  panel = **MAC** · secreto compartido en el ping.
- **D12/D13 · APK robusto**: debounce (1 toque = 1 evento), auto-reinicio ante crash,
  poll 100 ms.
- **D18 · Operación**: menú de scripts (build/deploy/log/captura/versiones) con `main`
  forzado y `adb connect`/`ssh` siempre primero.

---

## 3. HACER DISTINTO en v2 (mejoras sobre el prototipo)

| Área | Prototipo (hoy) | Producción (v2) | Por qué |
|---|---|---|---|
| **Hosting** | Pi 5 + microSD (todo un disco) | Servidor decidido (Pi 5 con **M.2**, o mini-PC x86 si crece), OS + datos + **backup en medios separados** | La microSD es SPOF total; separar discos = no perder datos |
| **Datos del kiosko** | SQLite (`kiosk.db`) | **SQLite** sigue bien; o **PocketBase** (SQLite + admin + API + auth + backups en 1 binario) si se quiere menos código propio | Escala chica, lecturas dominantes |
| **Base de Nextcloud** | SQLite embebida | **MariaDB** (NC desaconseja SQLite para multiusuario/300 docentes) | Concurrencia real de NC |
| **App-tokens** | texto plano en la DB | **cifrados en reposo** (Fernet con clave fuera del repo / KMS) | Servidor público; robo de DB = robo de accesos |
| **Rate-limit** | `memory://` (aprox. entre workers) | **Redis** compartido (exacto) | Correcto entre procesos |
| **Cache NC** | — | **Redis + APCu**, PHP-FPM tuneado, previews limitadas, cron real | Ráfaga del cambio de hora (F4) |
| **Respaldo** | script + cron (1 disco) | Backup a **medio separado** + **offsite** (PC/NAS/cloud B2) + restauración probada | Regla 3-2-1 (F3) |
| **Flota APK** | adb panel por panel | **MDM/DMS**: despliegue centralizado + **Lock Task** (device-owner) + auto-reinicio | 50 paneles sin drift ni escapes |
| **Secretos** | `.env` plano | gestor de secretos (Docker secrets / Vault) | Servidor público |
| **Sesión abierta + tarjeta** (F6) | se ignora | decidir: ¿misma tarjeta = logout / cambio de usuario? diseñarlo en el APK | UX de aula |
| **Contenedor** | root | **no-root**, FS de solo-lectura salvo datos | Endurecimiento |

---

## 4. Arquitectura de producción propuesta

```
Paneles (colegios) + docentes (casas)  ──todo por internet──►
   Cloudflare (dominio + túnel + TLS)
      ▼
   Servidor central (self-hosted, con internet y energía estables)
     nginx → /app → Nextcloud (MariaDB + Redis + APCu, archivos en disco de datos)
           → /    → App kiosko (SQLite/PocketBase, tokens cifrados)
     backup nocturno → disco aparte + offsite
   Flota Android administrada por MDM (Lock Task, OTA del APK, dashboard)
```

**Nota crítica (F1):** como los paneles y los docentes entran por internet, el
servidor **debe estar donde tenga internet y energía confiables**. No hay atajo de red
(no comparten LAN). Un corte en el sitio del servidor deja a TODOS sin login → prever
UPS + internet redundante o un plan de contingencia.

---

## 5. Stack recomendado (v2)

- **APK**: Android .NET (igual que hoy) — el patrón droidlogic ya está probado.
  Parametrizar bus/addr NFC por si cambia el modelo de panel.
- **Backend kiosko**: Flask + SQLite (lo actual, funciona) **o** PocketBase (evaluar).
- **Nextcloud**: Docker + **MariaDB** + **Redis** + APCu + cron real.
- **Proxy/TLS**: nginx (NPM) + Cloudflare túnel.
- **Secretos**: Docker secrets o `.env` cifrado + tokens cifrados en la DB.
- **Flota**: MDM con device-owner (Lock Task + despliegue del APK + monitoreo).
- **Respaldo**: `backup` a disco separado + offsite; monitoreo con **alerta** si cae.

---

## 6. Plan de construcción por fases

1. **Infra base**: servidor definitivo (discos separados: OS / datos / backup) + OS +
   Docker + dominio + túnel + TLS válido.
2. **Nextcloud** con MariaDB + Redis + APCu + cron + previews limitadas + bruteforce ON.
3. **Backend kiosko** (SQLite/PocketBase) con: `canon_uid`, `/auth`, `/logout`,
   heartbeat, `/admin` (tarjetas + salud + paneles), **tokens cifrados**, rate-limit Redis.
4. **APK**: WebView + droidlogic NFC + timer de sesión + heartbeat (MAC + secreto) +
   auto-reinicio. Firmado para el MDM.
5. **Flota**: MDM con device-owner (Lock Task + OTA del APK + dashboard).
6. **Respaldo + monitoreo**: backup 3-2-1 con restauración probada + alertas.
7. **Piloto**: 1 colegio, soak test 7 días (memoria del WebView, F8), medir carga.
8. **Despliegue** progresivo por colegios.

---

## 7. Errores conocidos a NO repetir (del prototipo)

- ❌ Bundlear el `classes.jar` stub (lee ceros). → Cargar el jar real del panel.
- ❌ JSON como base de datos (se corrompe con escrituras concurrentes, F2). → SQLite+.
- ❌ Cerrar sesión con `setTimeout` de la web (muere al navegar). → Timer nativo del APK.
- ❌ Rate-limit global por IP detrás del túnel (bloquea a toda la flota). → Por UID.
- ❌ Backup en el mismo disco que los datos (F3). → Medio separado + offsite.
- ❌ Lock Task estricto sin whitelist (rompe subir/abrir archivos). → Vía MDM device-owner.
- ❌ Poll NFC a 50 ms (pierde la 1ª lectura). → 100 ms.
- ❌ id de panel = ANDROID_ID (clonable de fábrica, F7). → MAC.
- ❌ Tokens en texto plano en servidor público. → Cifrar en reposo.
- ❌ **Repo con secretos Y público** (el prototipo quedó **público** con
  `docs/infraestructura-pi.md` + `PanelSecret` hardcodeado en el APK → fuga real, F10).
  → **Repo privado desde el día 1** y **secretos NUNCA en el repo ni en el código**
  (van a `.env` / gestor de secretos); si alguna vez se filtran, **rotar todo**.
- ❌ **GitHub Pages desde una carpeta con secretos**: Pages publica esa carpeta como
  web **pública aunque el repo sea privado** (repo privado ≠ sitio privado; solo
  Enterprise Cloud restringe el acceso). → Publicar solo una carpeta sin credenciales.
  En plan Free, un repo privado **no puede** servir Pages.
- ❌ **Hook de Lock Task dentro del APK** (parecía anti-desinstalación; se quitó del
  prototipo). → El bloqueo del kiosko va **solo por MDM** (device-owner), no cableado
  en la app; el equipo se puede salir/desinstalar con normalidad.

---

## 8. Requisitos no funcionales (deben cumplirse en v2)

- **Seguridad**: tokens cifrados · secretos gestionados · contenedor no-root ·
  bruteforce NC ON · repo privado · rotar TODAS las claves de testeo.
- **Disponibilidad**: backup 3-2-1 probado · monitoreo con alerta · UPS · plan si
  cae el servidor/internet.
- **Operación**: versionado visible · deploy reproducible · MDM para la flota ·
  monitoreo de salud (Pi + paneles) ya prototipado en `/admin/panels`.
- **Documentación**: mantener estos MD al día con cada cambio (regla del proyecto).
