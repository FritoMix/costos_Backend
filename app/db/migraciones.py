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

import hashlib
import json
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
    versiones: set[int] = set()
    for archivo in carpeta.glob("*.sql"):
        coincidencia = PATRON_ARCHIVO.match(archivo.name)
        if coincidencia is None:
            raise RuntimeError(f"Nombre de migración SQL inválido: {archivo.name}")
        version = int(coincidencia.group(1))
        if version in versiones:
            raise RuntimeError(f"Versión de migración duplicada: V{version}")
        versiones.add(version)
        descripcion = coincidencia.group(2).replace("_", " ")
        encontrados.append((version, descripcion, archivo))
    if versiones and versiones != set(range(1, max(versiones) + 1)):
        raise RuntimeError("Faltan versiones intermedias en las migraciones.")
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
                aplicada_en TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                checksum_sha256 VARCHAR(64)
            )
            """
        )
    )
    conexion.execute(
        text(f"ALTER TABLE {TABLA_CONTROL} ADD COLUMN IF NOT EXISTS checksum_sha256 VARCHAR(64)")
    )
    aplicadas.update(conexion.scalars(text(f"SELECT version FROM {TABLA_CONTROL}")).all())

    # Si Flyway ya trabajo sobre esta base, respetamos su historial.
    existe_flyway = conexion.scalar(text("SELECT to_regclass('public.flyway_schema_history')"))
    if existe_flyway:
        filas = conexion.scalars(
            text("SELECT version FROM flyway_schema_history WHERE success = true AND version IS NOT NULL")
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
        raise RuntimeError(f"No existe la carpeta de migraciones: {carpeta}")
    archivos = _archivos_de_migracion(carpeta)
    if not archivos:
        raise RuntimeError("No hay migraciones SQL para verificar el esquema.")
    manifiesto = json.loads((carpeta / "checksums.json").read_text(encoding="utf-8"))
    contenido = {ruta.name: ruta.read_bytes() for _, _, ruta in archivos}
    if set(manifiesto) != set(contenido):
        raise RuntimeError("El manifiesto de migraciones no coincide con los archivos SQL.")
    hashes = {nombre: hashlib.sha256(datos).hexdigest() for nombre, datos in contenido.items()}
    if hashes != manifiesto:
        raise RuntimeError("Integridad de migraciones inválida: un archivo SQL fue modificado.")

    # Una única transacción y bloqueo compartido por todos los workers.
    # El segundo arranque vuelve a leer el historial después de obtener el lock.
    with engine.begin() as conexion:
        conexion.execute(text("SELECT pg_advisory_xact_lock(741902631)"))
        aplicadas = _versiones_aplicadas(conexion)
        por_version = {version: (descripcion, ruta) for version, descripcion, ruta in archivos}
        if aplicadas - por_version.keys():
            raise RuntimeError("El esquema tiene versiones que faltan en este despliegue.")
        registradas = dict(
            conexion.execute(text(f"SELECT version, checksum_sha256 FROM {TABLA_CONTROL}")).all()
        )
        for version in aplicadas:
            descripcion, ruta = por_version[version]
            guardado = registradas.get(version)
            if guardado is not None and guardado != hashes[ruta.name]:
                raise RuntimeError(f"La migración histórica V{version} cambió después de aplicarse.")
            if guardado is None:
                # Adopción explícita del manifiesto publicado para instalaciones antiguas.
                # Esto NO demuestra qué bytes se ejecutaron antes de incorporar SHA-256.
                logger.warning("Registrando línea base SHA-256 para la migración histórica V%d", version)
                conexion.execute(
                    text(
                        f"INSERT INTO {TABLA_CONTROL} (version, descripcion, checksum_sha256) "
                        "VALUES (:v, :d, :h) ON CONFLICT (version) DO UPDATE "
                        "SET checksum_sha256 = EXCLUDED.checksum_sha256"
                    ),
                    {"v": version, "d": descripcion[:200], "h": hashes[ruta.name]},
                )
        pendientes = [fila for fila in archivos if fila[0] not in aplicadas]
        for version, descripcion, ruta in pendientes:
            logger.info("Aplicando migración V%d - %s", version, descripcion)
            conexion.execute(text(contenido[ruta.name].decode("utf-8")))
            conexion.execute(
                text(
                    f"INSERT INTO {TABLA_CONTROL} (version, descripcion, checksum_sha256) "
                    "VALUES (:version, :descripcion, :checksum)"
                ),
                {"version": version, "descripcion": descripcion[:200], "checksum": hashes[ruta.name]},
            )

    logger.info("Migraciones aplicadas: %d", len(pendientes))
    return len(pendientes)
