#!/usr/bin/env bash
# ============================================================
#  backup-pi.sh — respaldo nocturno de La Nube (correr EN la Pi)
#  Config ya ajustada a la Pi actual: Debian 13, NC con SQLite en /mnt/datos.
#  Respalda: kiosk.db (SQLite) + archivos y base de Nextcloud + config + .env.
#
#  Instalar:
#    sudo apt update && sudo apt install -y sqlite3
#    curl -fsSL -o ~/backup-pi.sh https://raw.githubusercontent.com/duecaz/nfc/main/tools/backup-pi.sh
#    chmod +x ~/backup-pi.sh
#    ~/backup-pi.sh                 # probar a mano
#    crontab -e   ->   0 3 * * * /home/duecaz/backup-pi.sh >> /home/duecaz/backup.log 2>&1
# ============================================================
set -euo pipefail

# ============ CONFIG (ya ajustada; revisá BACKUP_DIR) ============
KIOSK_DIR="$HOME/docker/kiosk"                        # kiosk.db + .env
NC_CONTAINER="nextcloud_server"                       # contenedor NC (para modo mantenimiento)
NC_FILES="/mnt/datos/nextcloud/data"                  # archivos docentes + base SQLite de NC
NC_CONFIG="/mnt/datos/nextcloud/html/config"          # config.php de Nextcloud
DB_CONTAINER=""                                        # vacío: NC usa SQLite (va dentro de NC_FILES)

BACKUP_DIR="$HOME/backups"                             # destino. IDEAL: un disco USB aparte (ej. /mnt/usb/backups)
KEEP=7                                                 # copias diarias a conservar

# Copia OFFSITE opcional (a una PC/NAS por SSH). Vacío = desactivada.
RSYNC_TARGET=""                                        # ej: "usuario@192.168.1.92:/backups/lanube"
# ================================================================

STAMP=$(date +%Y-%m-%d_%H%M)
DEST="$BACKUP_DIR/$STAMP"
mkdir -p "$DEST"
echo "=== Backup La Nube $STAMP -> $DEST ==="
fail() { echo "!!! ERROR: $1" >&2; exit 1; }
sz()   { du -h "$1" 2>/dev/null | cut -f1; }

# 1) Kiosko (SQLite .backup = copia consistente con WAL) ----------------------
if [ -f "$KIOSK_DIR/data/kiosk.db" ]; then
  sqlite3 "$KIOSK_DIR/data/kiosk.db" ".backup '$DEST/kiosk.db'" \
    || cp "$KIOSK_DIR/data/kiosk.db" "$DEST/kiosk.db"
  cp "$KIOSK_DIR/.env" "$DEST/kiosk.env" 2>/dev/null || true
  [ -s "$DEST/kiosk.db" ] || fail "kiosk.db salió vacío"
  echo "  [ok] kiosk.db  ($(sz "$DEST/kiosk.db"))"
else
  echo "  [!] no encontré $KIOSK_DIR/data/kiosk.db (revisá KIOSK_DIR)"
fi

# 2) Nextcloud en modo mantenimiento (copia consistente de su SQLite + archivos)
occ() { docker exec -u www-data "$NC_CONTAINER" php occ "$@"; }
MAINT=0
if docker ps --format '{{.Names}}' | grep -qx "$NC_CONTAINER"; then
  occ maintenance:mode --on >/dev/null && MAINT=1 && echo "  [ok] Nextcloud en mantenimiento"
fi

# (si algún día NC pasa a MariaDB, poné DB_CONTAINER y se hace mysqldump acá)
if [ -n "$DB_CONTAINER" ] && docker ps --format '{{.Names}}' | grep -qx "$DB_CONTAINER"; then
  docker exec "$DB_CONTAINER" sh -c "exec mysqldump --single-transaction -u root nextcloud" \
    | gzip > "$DEST/nextcloud-db.sql.gz" && echo "  [ok] nextcloud-db.sql.gz  ($(sz "$DEST/nextcloud-db.sql.gz"))"
fi

# 3) Archivos + base SQLite de NC (lo grande) --------------------------------
if [ -d "$NC_FILES" ]; then
  tar czf "$DEST/nextcloud-data.tgz" -C "$(dirname "$NC_FILES")" "$(basename "$NC_FILES")" \
    || fail "tar de $NC_FILES falló"
  echo "  [ok] nextcloud-data.tgz  ($(sz "$DEST/nextcloud-data.tgz"))"
else
  echo "  [!] no encontré $NC_FILES"
fi

# 4) config.php de Nextcloud --------------------------------------------------
[ -d "$NC_CONFIG" ] && tar czf "$DEST/nextcloud-config.tgz" -C "$(dirname "$NC_CONFIG")" "$(basename "$NC_CONFIG")" \
  && echo "  [ok] nextcloud-config.tgz  ($(sz "$DEST/nextcloud-config.tgz"))"

# 5) salir de mantenimiento ---------------------------------------------------
[ "$MAINT" = 1 ] && occ maintenance:mode --off >/dev/null && echo "  [ok] Nextcloud operativo de nuevo"

# 6) retención ----------------------------------------------------------------
ls -1dt "$BACKUP_DIR"/*/ 2>/dev/null | tail -n +$((KEEP+1)) | xargs -r rm -rf
echo "  [ok] retención: conservando últimas $KEEP copias"

# 7) copia offsite opcional ---------------------------------------------------
if [ -n "$RSYNC_TARGET" ]; then
  rsync -a --delete "$BACKUP_DIR/" "$RSYNC_TARGET/" \
    && echo "  [ok] offsite -> $RSYNC_TARGET" || echo "  [!] rsync offsite falló"
fi

echo "=== Backup terminado: $DEST ($(sz "$DEST")) ==="
