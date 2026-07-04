#!/usr/bin/env bash
# ============================================================
#  backup-pi.sh — respaldo nocturno de La Nube (correr EN la Pi)
#  Config ajustada a la Pi actual: Debian 13, NC con SQLite en /mnt/datos.
#  Respalda: kiosk.db (SQLite) + archivos y base de Nextcloud + config + .env.
#  Se auto-eleva a root (los archivos de NC son de www-data).
#
#  Instalar:
#    sudo apt update && sudo apt install -y sqlite3
#    curl -fsSL -o ~/backup-pi.sh https://raw.githubusercontent.com/duecaz/nfc/main/tools/backup-pi.sh
#    chmod +x ~/backup-pi.sh
#    ~/backup-pi.sh                 # probar (pedirá la clave de sudo una vez)
#    sudo crontab -e   ->   0 3 * * * /home/duecaz/backup-pi.sh >> /var/log/lanube-backup.log 2>&1
# ============================================================
set -euo pipefail

# se necesita root para leer /mnt/datos/nextcloud (www-data). Auto-elevar:
[ "$(id -u)" -ne 0 ] && exec sudo "$0" "$@"

# ============ CONFIG (rutas absolutas: funcionan como root y en cron) ============
PI_HOME="/home/duecaz"
KIOSK_DIR="$PI_HOME/docker/kiosk"                     # kiosk.db + .env
NC_CONTAINER="nextcloud_server"                       # contenedor NC (modo mantenimiento)
NC_FILES="/mnt/datos/nextcloud/data"                  # archivos docentes + base SQLite de NC
NC_CONFIG="/mnt/datos/nextcloud/html/config"          # config.php de Nextcloud
DB_CONTAINER=""                                        # vacío: NC usa SQLite (va dentro de NC_FILES)

BACKUP_DIR="$PI_HOME/backups"                          # destino. IDEAL: un disco USB aparte (ej. /mnt/usb/backups)
KEEP=7                                                 # copias diarias a conservar
RSYNC_TARGET=""                                        # offsite opcional, ej: "duecaz@192.168.1.92:/backups/lanube"
# =================================================================================

STAMP=$(date +%Y-%m-%d_%H%M)
DEST="$BACKUP_DIR/$STAMP"
mkdir -p "$DEST"
echo "=== Backup La Nube $STAMP -> $DEST ==="
fail() { echo "!!! ERROR: $1" >&2; exit 1; }
sz()   { du -h "$1" 2>/dev/null | cut -f1; }
occ()  { docker exec -u www-data "$NC_CONTAINER" php occ "$@"; }

# 1) Kiosko (SQLite .backup = copia consistente con WAL) ----------------------
if [ -f "$KIOSK_DIR/data/kiosk.db" ]; then
  sqlite3 "$KIOSK_DIR/data/kiosk.db" ".backup '$DEST/kiosk.db'" \
    || cp "$KIOSK_DIR/data/kiosk.db" "$DEST/kiosk.db"
  cp "$KIOSK_DIR/.env" "$DEST/kiosk.env" 2>/dev/null || true
  [ -s "$DEST/kiosk.db" ] || fail "kiosk.db salió vacío"
  echo "  [ok] kiosk.db  ($(sz "$DEST/kiosk.db"))"
else
  echo "  [!] no encontré $KIOSK_DIR/data/kiosk.db"
fi

# 2) Nextcloud en modo mantenimiento (SIEMPRE se sale, aunque el backup falle) -
MAINT=0
if docker ps --format '{{.Names}}' | grep -qx "$NC_CONTAINER"; then
  occ maintenance:mode --on >/dev/null && MAINT=1 && echo "  [ok] Nextcloud en mantenimiento"
  trap '[ "$MAINT" = 1 ] && occ maintenance:mode --off >/dev/null 2>&1 && echo "  [ok] Nextcloud operativo"; true' EXIT
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

# 5) retención + permisos para leer los backups como duecaz -------------------
ls -1dt "$BACKUP_DIR"/*/ 2>/dev/null | tail -n +$((KEEP+1)) | xargs -r rm -rf
chown -R duecaz:duecaz "$BACKUP_DIR" 2>/dev/null || true
echo "  [ok] retención: conservando últimas $KEEP copias"

# 6) copia offsite opcional ---------------------------------------------------
if [ -n "$RSYNC_TARGET" ]; then
  rsync -a --delete "$BACKUP_DIR/" "$RSYNC_TARGET/" \
    && echo "  [ok] offsite -> $RSYNC_TARGET" || echo "  [!] rsync offsite falló"
fi

echo "=== Backup terminado: $DEST ($(sz "$DEST")) ==="
