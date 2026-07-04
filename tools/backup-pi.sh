#!/usr/bin/env bash
# ============================================================
#  backup-pi.sh — respaldo nocturno de La Nube (correr EN la Pi)
#  Respalda: base del kiosko (SQLite) + base de Nextcloud + archivos NC + config.
#  Guarda las ultimas N copias locales y (opcional) las deja en una PC/NAS.
#
#  Instalar en la Pi:
#    curl -fsSL -o ~/backup-pi.sh https://raw.githubusercontent.com/duecaz/nfc/main/tools/backup-pi.sh
#    chmod +x ~/backup-pi.sh
#    # probar a mano:
#    ~/backup-pi.sh
#    # programar 3am:  crontab -e   ->   0 3 * * * /home/duecaz/backup-pi.sh >> /home/duecaz/backup.log 2>&1
# ============================================================
set -euo pipefail

# ============ CONFIG — ajustá estos valores ============
KIOSK_DIR="$HOME/docker/kiosk"                 # donde vive data/kiosk.db y .env
NC_DIR="$HOME/docker/nextcloud"                # compose de Nextcloud
NC_CONTAINER="nextcloud_server"                # nombre del contenedor NC
NC_DATA="$HOME/docker/nextcloud/data"          # <-- RUTA REAL de los archivos en la SSD (verificá!)

# Base de datos de Nextcloud (dejá DB_CONTAINER vacío si NC usa SQLite):
DB_CONTAINER="nextcloud_db"                     # contenedor MariaDB/MySQL de NC (o "")
DB_NAME="nextcloud"
DB_USER="nextcloud"
DB_PASS="CAMBIAR_PASSWORD_DB_NC"               # el de config.php (dbpassword)

BACKUP_DIR="/mnt/backup"                        # destino local (idealmente OTRO disco, no la SSD principal)
KEEP=7                                          # cuantas copias diarias conservar

# Copia OFFSITE opcional (a una PC/NAS por SSH). Dejá RSYNC_TARGET vacío para desactivar.
RSYNC_TARGET=""                                 # ej: "usuario@192.168.1.100:/backups/lanube"
# ======================================================

STAMP=$(date +%Y-%m-%d_%H%M)
DEST="$BACKUP_DIR/$STAMP"
mkdir -p "$DEST"
echo "=== Backup La Nube $STAMP -> $DEST ==="

fail() { echo "!!! ERROR: $1" >&2; exit 1; }
size() { du -h "$1" 2>/dev/null | cut -f1; }

# 1) Kiosko (SQLite: .backup respeta WAL y da copia consistente) --------------
if [ -f "$KIOSK_DIR/data/kiosk.db" ]; then
  sqlite3 "$KIOSK_DIR/data/kiosk.db" ".backup '$DEST/kiosk.db'" \
    || cp "$KIOSK_DIR/data/kiosk.db" "$DEST/kiosk.db"
  cp "$KIOSK_DIR/.env" "$DEST/kiosk.env" 2>/dev/null || true
  [ -s "$DEST/kiosk.db" ] || fail "kiosk.db salio vacio"
  echo "  [ok] kiosk.db  ($(size "$DEST/kiosk.db"))"
else
  echo "  [!] no encontre kiosk.db en $KIOSK_DIR/data (revisá KIOSK_DIR)"
fi

# 2) Nextcloud en modo mantenimiento (copia consistente) ----------------------
occ() { docker exec -u www-data "$NC_CONTAINER" php occ "$@"; }
MAINT=0
if docker ps --format '{{.Names}}' | grep -qx "$NC_CONTAINER"; then
  occ maintenance:mode --on && MAINT=1 && echo "  [ok] Nextcloud en mantenimiento"
fi

# 3) Base de datos de Nextcloud ----------------------------------------------
if [ -n "$DB_CONTAINER" ] && docker ps --format '{{.Names}}' | grep -qx "$DB_CONTAINER"; then
  docker exec "$DB_CONTAINER" sh -c "exec mysqldump --single-transaction -u'$DB_USER' -p'$DB_PASS' '$DB_NAME'" \
    | gzip > "$DEST/nextcloud-db.sql.gz" || fail "mysqldump fallo (revisá DB_PASS/DB_USER)"
  [ -s "$DEST/nextcloud-db.sql.gz" ] || fail "el dump de la DB salio vacio"
  echo "  [ok] nextcloud-db.sql.gz  ($(size "$DEST/nextcloud-db.sql.gz"))"
else
  echo "  [i] sin DB_CONTAINER: asumo que NC usa SQLite (se respalda con los archivos)"
fi

# 4) Archivos + config de Nextcloud (lo grande) ------------------------------
if [ -d "$NC_DATA" ]; then
  tar czf "$DEST/nextcloud-data.tgz" -C "$(dirname "$NC_DATA")" "$(basename "$NC_DATA")" \
    || fail "tar de los archivos NC fallo"
  echo "  [ok] nextcloud-data.tgz  ($(size "$DEST/nextcloud-data.tgz"))"
else
  echo "  [!] no encontre $NC_DATA — ¡ajustá NC_DATA a la ruta real de la SSD!"
fi
[ -d "$NC_DIR" ] && tar czf "$DEST/nextcloud-config.tgz" -C "$(dirname "$NC_DIR")" "$(basename "$NC_DIR")" \
  --exclude='*/data' 2>/dev/null && echo "  [ok] nextcloud-config.tgz  ($(size "$DEST/nextcloud-config.tgz"))"

# 5) salir de mantenimiento ---------------------------------------------------
[ "$MAINT" = 1 ] && occ maintenance:mode --off && echo "  [ok] Nextcloud operativo de nuevo"

# 6) retencion: borrar copias mas viejas que KEEP ----------------------------
ls -1dt "$BACKUP_DIR"/*/ 2>/dev/null | tail -n +$((KEEP+1)) | xargs -r rm -rf
echo "  [ok] retencion: conservando ultimas $KEEP copias"

# 7) copia offsite opcional (a PC/NAS) ---------------------------------------
if [ -n "$RSYNC_TARGET" ]; then
  rsync -a --delete "$BACKUP_DIR/" "$RSYNC_TARGET/" && echo "  [ok] copia offsite -> $RSYNC_TARGET" \
    || echo "  [!] rsync offsite fallo (¿PC apagada? ¿llave SSH?)"
fi

echo "=== Backup terminado: $DEST ($(size "$DEST")) ==="
