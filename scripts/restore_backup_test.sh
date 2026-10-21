#!/usr/bin/env bash
#
# Verifica que un backup de PostgreSQL se pueda restaurar, sin tocar la base
# de produccion. Crea una base temporal, restaura el dump, comprueba tablas
# clave y la elimina al terminar.
#
# Uso:
#   ./scripts/restore_backup_test.sh [archivo.dump]
#
# Sin argumento toma el backup mas reciente de BACKUP_DIR (./backups).
# Variables: DB_CONTAINER, POSTGRES_USER, POSTGRES_DB, BACKUP_DIR.

set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [ -f "$RAIZ/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    . "$RAIZ/.env"
    set +a
fi

CONTENEDOR="${DB_CONTAINER:-datacontrol-db}"
USUARIO="${POSTGRES_USER:-datacontrol}"
DESTINO="${BACKUP_DIR:-$RAIZ/backups}"
BASE_TEMPORAL="${TEST_DB:-datacontrol_restore_test_$(date +%Y%m%d_%H%M%S)}"

if [ "$#" -ge 1 ]; then
    ARCHIVO="$1"
else
    ARCHIVO="$(find "$DESTINO" -maxdepth 1 -type f -name '*.dump' -printf '%T@ %p\n' \
        | sort -nr | head -1 | cut -d' ' -f2-)"
fi

if [ -z "${ARCHIVO:-}" ] || [ ! -f "$ARCHIVO" ]; then
    echo "ERROR: no se encontro el backup. Uso: $0 [archivo.dump]" >&2
    exit 1
fi

limpiar() {
    docker exec "$CONTENEDOR" dropdb -U "$USUARIO" --if-exists --force "$BASE_TEMPORAL" \
        >/dev/null 2>&1 || true
}
trap limpiar EXIT

echo "Backup: $ARCHIVO"
echo "Base temporal: $BASE_TEMPORAL (contenedor: $CONTENEDOR)"

# El dump debe ser legible antes de crear la base temporal.
docker exec -i "$CONTENEDOR" pg_restore --list < "$ARCHIVO" > /dev/null
docker exec "$CONTENEDOR" createdb -U "$USUARIO" "$BASE_TEMPORAL"

INICIO="$(date +%s)"
docker exec -i "$CONTENEDOR" pg_restore -U "$USUARIO" -d "$BASE_TEMPORAL" \
    --no-owner --no-privileges --exit-on-error < "$ARCHIVO"
FIN="$(date +%s)"

TABLAS="$(docker exec "$CONTENEDOR" psql -At -U "$USUARIO" -d "$BASE_TEMPORAL" -c \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE';")"
MIGRACIONES="$(docker exec "$CONTENEDOR" psql -At -U "$USUARIO" -d "$BASE_TEMPORAL" -c \
    "SELECT count(*) FROM esquema_migraciones;")"
USUARIOS="$(docker exec "$CONTENEDOR" psql -At -U "$USUARIO" -d "$BASE_TEMPORAL" -c \
    "SELECT count(*) FROM usuarios;")"
ORDENES="$(docker exec "$CONTENEDOR" psql -At -U "$USUARIO" -d "$BASE_TEMPORAL" -c \
    "SELECT count(*) FROM ordenes_produccion;")"

if [ "$TABLAS" -lt 10 ] || [ "$MIGRACIONES" -lt 1 ] || [ "$USUARIOS" -lt 1 ]; then
    echo "ERROR: el restore quedo incompleto (tablas=$TABLAS, migraciones=$MIGRACIONES, usuarios=$USUARIOS)." >&2
    exit 1
fi

echo "OK: restore verificado en $((FIN - INICIO)) s"
echo "    tablas=$TABLAS migraciones=$MIGRACIONES usuarios=$USUARIOS ordenes=$ORDENES"
echo "    La base temporal se elimina al salir."
