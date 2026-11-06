#!/usr/bin/env bash
# Backup do banco e dos prontuários digitalizados. Mantém os últimos 14 dias.
# Agendar todo dia às 3h:   (crontab -l 2>/dev/null; echo "0 3 * * * /root/central-odonto/scripts/backup.sh") | crontab -
set -euo pipefail
cd "$(dirname "$0")/.."
DESTINO="${BACKUP_DIR:-/root/backups-central-odonto}"
DATA="$(date +%F_%H%M)"
mkdir -p "$DESTINO"
docker compose exec -T postgres pg_dump -U postgres odonto | gzip > "$DESTINO/banco_$DATA.sql.gz"
docker compose exec -T bot tar czf - -C /app arquivos > "$DESTINO/prontuarios_$DATA.tar.gz"
find "$DESTINO" -name '*.gz' -mtime +14 -delete
echo "Backup salvo em $DESTINO ($DATA)"
# IMPORTANTE: copie esta pasta para FORA do servidor (ex.: Google Drive com rclone) — se o servidor
# quebrar, um backup que só existe nele se perde junto.
