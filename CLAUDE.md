# CLAUDE.md — La Nube (contexto principal)

**Qué es:** los docentes acercan su **tarjeta NFC** a cualquier pantalla interactiva
de la marca (en cualquier colegio) y entran a **sus archivos** en Nextcloud. El token
de acceso vive asociado a la tarjeta. Desde casa entran por navegador. Todo es
**self-hosted en una Raspberry Pi**; Cloudflare es **solo** el dominio + túnel + TLS.

> ⚠️ **Prototipo de testeo.** La producción se rehará **desde cero** siguiendo el plano
> **[`docs/produccion-desde-cero.md`](docs/produccion-desde-cero.md)** — el MD más
> importante del repo. **Regla:** mantener los MD al día con **cada** cambio.

---

## Estado actual (jul 2026)

| | Valor |
|---|---|
| Web (Flask) | **v25** · datos en **SQLite** `web/data/kiosk.db` (ya NO usa users.json) |
| APK (.NET) | **v11** · `uno.lanube.kiosk` · lee NFC por droidlogic |
| Repo | `duecaz/nfc` (privado), **rama única `main`** |
| Servidor | Pi 5 en `192.168.1.50` · Nextcloud (SQLite) + Flask + nginx + cloudflared, en Docker |
| Panel de pruebas | `192.168.1.57:5555` (adb) |
| Backup (F3) | ✅ `tools/backup-pi.sh` + cron 3am andando |

**Flujo (1 línea):** tarjeta → APK lee UID (droidlogic) → inyecta `authenticate(UID)`
→ Flask `canon_uid`→SQLite→app-token → Basic Auth a Nextcloud → cookies → Archivos.
El APK impone un timer nativo de sesión.

---

## 📚 A qué MD ir (abrir SOLO el que necesites — no cargar todo)

| Necesito… | Abrir |
|---|---|
| 🏗️ **Construir el proyecto v2 desde 0** (el plano, lo más importante) | **`docs/produccion-desde-cero.md`** |
| Qué decidimos y por qué (D1–D18), bitácora | `docs/vision.md` |
| Datos de la Pi: IPs, puertos, **credenciales**, rutas, discos, comandos | `docs/infraestructura-pi.md` |
| Hallazgos/auditoría F1–F9 (detalle técnico) | `docs/auditoria.md` |
| Cómo desplegar web o APK | `docs/deploy-pi.md` |
| Cómo se lee el NFC del panel (DexClassLoader) | `docs/nfc-droidlogic.md` |

Estructura del repo: `web/` (Flask) · `apk/` (Android .NET) · `test/` (diagnóstico) ·
`docs/` · `tools/` (scripts PS1 del menú + `backup-pi.sh`).

---

## Reglas críticas (para no romper nada)

- **Pantallas sin teclado/ratón/DevTools**: toda solución por URL o botones visibles.
- **Deploy web**: `docker compose down && build --no-cache && up -d` (restart NO
  actualiza; los templates van dentro de la imagen). Detalle en `deploy-pi.md`.
- **Versionado**: subir `VERSION` (web) y `ApkVersion` (apk) con cada deploy; se ven
  en `/health`, `/admin/panels` y la etiqueta `apk vN`.
- **git**: push CLI funciona si el local está sincronizado (`git fetch && git reset
  --hard origin/main`). Alternativa: `mcp__github__push_files`.
- **SQLite**, no JSON. **Secretos en `.env`** (no en el repo). **Un solo dominio**
  `lanube.uno` (cookies compartidas Flask↔NC).

## Pendiente inmediato (siguiente chat)

1. Copia **offsite** del backup (hoy todo está en la misma microSD — riesgo real).
2. Completar credenciales que faltan en `infraestructura-pi.md` (NPM, Cloudflare, SSH).
3. Producción desde 0: hosting definitivo, cifrar app-tokens, MDM, evaluar PocketBase
   (ver `docs/vision.md` §6 y `docs/auditoria.md`).
