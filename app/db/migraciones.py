"""
Aplicador de migraciones para entornos SIN Flyway (por ejemplo, Render).

Por que existe
--------------
En local, Flyway corre en su propio contenedor y aplica los .sql antes de
que arranque la API. Pero cuando el backend se despliega solo (Render,
Railway, un VPS...) no hay contenedor de Flyway: alguien tiene que aplicar
el esquema o la base queda vacia y la app falla en la primera consulta.

Este modulo lee los mismos archivos `migraciones/V<n>__<descripcion>.sql`
y aplica los que falten, en orden dentro de una transacción protegida frente a arranques concurrentes.

Convive con Flyway
------------------
Antes de aplicar nada, mira que versiones ya estan puestas:
  * en `flyway_schema_history`, si Flyway ya trabajo sobre esa base, y
  * en `esquema_migraciones`, su propia tabla de control.
Asi, una base migrada con Flyway no se vuelve a migrar aqui, y una base
migrada aqui no se rompe si algun dia se le pasa Flyway por encima.
"""

import logging
import re
from pathlib import Path

from sqlalchemy import Engine, text

logger = logging.getLogger("datacontrol")

# V1__descripcion.sql  ->  version 1, descripcion "descripcion"
PATRON_ARCHIVO = re.compile(r"^V(\d+)__(.+)\.sql$", re.IGNORECASE)

TABLA_CONTROL = "esquema_migraciones"


def _carpeta_por_defecto() -> Path:
    """`backend/migraciones`, tomando como referencia este mismo archivo."""
    return Path(__file__).resolve().parent.parent.parent / "migraciones"


def _archivos_de_migracion(carpeta: Path) -> list[tuple[int, str, Path]]:
    """Devuelve (version, descripcion, ruta) ordenado por version."""
    encontrados: list[tuple[int, str, Path]] = []
    for archivo in carpeta.glob("*.sql"):
        coincidencia = PATRON_ARCHIVO.match(archivo.name)
        if coincidencia is None:
            logger.warning("Archivo ignorado (no sigue V<n>__nombre.sql): %s", archivo.name)
            continue
        version = int(coincidencia.group(1))
        descripcion = coincidencia.group(2).replace("_", " ")
        encontrados.append((version, descripcion, archivo))
    return sorted(encontrados, key=lambda fila: fila[0])


def _versiones_aplicadas(conexion) -> set[int]:
    """Versiones ya instaladas, mirando la tabla propia y la de Flyway."""
    aplicadas: set[int] = set()

    conexion.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS {TABLA_CONTROL} (
                version     INTEGER      NOT NULL PRIMARY KEY,
                descripcion VARCHAR(200) NOT NULL,
                aplicada_en TIMESTAMPTZ  NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    aplicadas.update(conexion.scalars(text(f"SELECT version FROM {TABLA_CONTROL}")).all())

    # Si Flyway ya trabajo sobre esta base, respetamos su historial.
    existe_flyway = conexion.scalar(text("SELECT to_regclass('public.flyway_schema_history')"))
    if existe_flyway:
        filas = conexion.scalars(
            text(
                "SELECT version FROM flyway_schema_history "
                "WHERE success = true AND version IS NOT NULL"
            )
        ).all()
        for valor in filas:
            try:
                # Flyway guarda la version como texto ("1", "2"...).
                aplicadas.add(int(str(valor).split(".")[0]))
            except ValueError:
                continue

    return aplicadas


def aplicar_migraciones_pendientes(engine: Engine, carpeta: Path | None = None) -> int:
    """
    Aplica las migraciones que falten. Devuelve cuantas se aplicaron.

    Todas las pendientes se confirman juntas. Si una falla, se revierte el lote
    y se detiene el arranque. El bloqueo transaccional serializa los workers.
    """
    carpeta = carpeta or _carpeta_por_defecto()
    if not carpeta.is_dir():
        logger.warning("No hay carpeta de migraciones en %s: no se aplica nada.", carpeta)
        return 0

    archivos = _archivos_de_migracion(carpeta)
    if not archivos:
        logger.warning("La carpeta %s no tiene migraciones.", carpeta)
        return 0

    # Una única transacción y bloqueo compartido por todos los workers.
    # El segundo arranque vuelve a leer el historial después de obtener el lock.
    with engine.begin() as conexion:
        conexion.execute(text("SELECT pg_advisory_xact_lock(741902631)"))
        aplicadas = _versiones_aplicadas(conexion)
        pendientes = [fila for fila in archivos if fila[0] not in aplicadas]
        for version, descripcion, ruta in pendientes:
            logger.info("Aplicando migración V%d - %s", version, descripcion)
            conexion.execute(text(ruta.read_text(encoding="utf-8")))
            conexion.execute(
                text(
                    f"INSERT INTO {TABLA_CONTROL} (version, descripcion) "
                    "VALUES (:version, :descripcion)"
                ),
                {"version": version, "descripcion": descripcion[:200]},
            )

    logger.info("Migraciones aplicadas: %d", len(pendientes))
    return len(pendientes)
