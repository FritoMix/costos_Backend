"""
Exportacion de datos a CSV y Excel.

Genera una fila por orden de produccion, con el numero de orden como
identificador (para poder cruzarla con otros analisis) y los mismos
totales que muestra la pantalla de Analisis, respetando sus filtros.

Las funciones de generacion devuelven generadores para que los archivos
grandes se transmitan por chunks (StreamingResponse) en lugar de cargarse
completamente en memoria.
"""

import csv
import io
from collections.abc import Generator
from datetime import date, datetime, time, timedelta

from openpyxl import Workbook
from sqlalchemy import func, select, union
from sqlalchemy.orm import Session

from app.core.tiempo import ZONA_HORARIA_LOCAL, ahora_local
from app.modules.analitica.schemas import FiltrosAnalisis
from app.modules.analitica.service import consulta_ordenes_filtradas
from app.modules.produccion.models import (
    Desperdicio,
    OrdenProduccion,
    RegistroHorno,
    RegistroSaborizado,
)

ENCABEZADOS = [
    "numero_orden",
    "fecha",
    "destino",
    "estado",
    "supervisor",
    "turno",
    "horno",
    "categoria",
    "producto",
    "cantidad_programada_kg",
    "kg_crudos",
    "cantidad_bultos",
    "kg_papa_frita",
    "kg_sabor_usado",
    "kg_desperdicio",
    "kg_aceite_consumido",
]


def obtener_filas(db: Session, filtros: FiltrosAnalisis) -> list[list]:
    return _filas_por_orden(db, consulta_ordenes_filtradas(filtros))


def obtener_filas_diarias(db: Session, fecha: date) -> list[list]:
    """Agrupa los registros creados durante el día de planta, por orden."""
    inicio = datetime.combine(fecha, time.min, tzinfo=ZONA_HORARIA_LOCAL)
    fin = inicio + timedelta(days=1)
    ventana_horno = (RegistroHorno.fecha_creacion >= inicio, RegistroHorno.fecha_creacion < fin)
    ventana_saborizado = (
        RegistroSaborizado.fecha_creacion >= inicio,
        RegistroSaborizado.fecha_creacion < fin,
    )
    actividad = union(
        select(RegistroHorno.orden_id).where(RegistroHorno.eliminado.is_(False), *ventana_horno),
        select(RegistroSaborizado.orden_id).where(
            RegistroSaborizado.eliminado.is_(False), *ventana_saborizado
        ),
    )
    ordenes = consulta_ordenes_filtradas(FiltrosAnalisis()).where(OrdenProduccion.id.in_(actividad))
    filas = _filas_por_orden(
        db, ordenes, ventana_horno=ventana_horno, ventana_saborizado=ventana_saborizado
    )
    encabezados = [*filas[0], "fecha_informe"]
    encabezados[1] = "fecha_orden"
    return [encabezados, *([*fila, fecha.isoformat()] for fila in filas[1:])]


def _filas_por_orden(db: Session, ids_ordenes, *, ventana_horno=(), ventana_saborizado=()) -> list[list]:
    ordenes = list(
        db.scalars(
            select(OrdenProduccion)
            .where(OrdenProduccion.id.in_(ids_ordenes))
            .order_by(OrdenProduccion.fecha, OrdenProduccion.numero_orden)
        ).unique().all()
    )

    if not ordenes:
        return [ENCABEZADOS]

    orden_ids = [orden.id for orden in ordenes]

    # Agregaciones en bloque: O(1) consultas en lugar de O(N)
    horno_totales = {
        fila[0]: (fila[1], fila[2], fila[3])
        for fila in db.execute(
            select(
                RegistroHorno.orden_id,
                func.coalesce(func.sum(RegistroHorno.kg_crudos_calculados), 0),
                func.coalesce(func.sum(RegistroHorno.cantidad_bultos), 0),
                func.coalesce(func.sum(RegistroHorno.kg_aceite_consumido), 0),
            )
            .where(RegistroHorno.orden_id.in_(orden_ids), RegistroHorno.eliminado == False, *ventana_horno)
            .group_by(RegistroHorno.orden_id)
        ).all()
    }

    desperdicio_totales = dict(
        db.execute(
            select(
                RegistroHorno.orden_id,
                func.coalesce(func.sum(Desperdicio.cantidad_kg), 0),
            )
            .join(RegistroHorno, Desperdicio.registro_horno_id == RegistroHorno.id)
            .where(RegistroHorno.orden_id.in_(orden_ids), RegistroHorno.eliminado == False, *ventana_horno)
            .group_by(RegistroHorno.orden_id)
        ).all()
    )

    saborizado_totales = {
        fila[0]: (fila[1], fila[2])
        for fila in db.execute(
            select(
                RegistroSaborizado.orden_id,
                func.coalesce(func.sum(RegistroSaborizado.kg_recibidos), 0),
                func.coalesce(func.sum(RegistroSaborizado.cantidad_sabor_kg), 0),
            )
            .where(
                RegistroSaborizado.orden_id.in_(orden_ids),
                RegistroSaborizado.eliminado == False,
                *ventana_saborizado,
            )
            .group_by(RegistroSaborizado.orden_id)
        ).all()
    }

    filas: list[list] = [ENCABEZADOS]
    for orden in ordenes:
        kg_crudos, bultos, kg_aceite = horno_totales.get(orden.id, (0, 0, 0))
        kg_desperdicio = desperdicio_totales.get(orden.id, 0)
        kg_papa_frita, kg_sabor = saborizado_totales.get(orden.id, (0, 0))

        filas.append(
            [
                orden.numero_orden,
                orden.fecha.isoformat(),
                orden.destino_etiqueta,
                orden.estado_etiqueta,
                orden.supervisor.nombre_completo,
                orden.turno.nombre,
                orden.horno.nombre,
                orden.categoria.nombre,
                orden.producto.nombre_comercial,
                float(orden.cantidad_programada),
                float(kg_crudos),
                float(bultos),
                float(kg_papa_frita),
                float(kg_sabor),
                float(kg_desperdicio),
                float(kg_aceite),
            ]
        )
    return filas


def _csv_chunked(filas: list[list]) -> Generator[bytes, None, None]:
    """
    Genera el CSV en chunks de ~64KB para no cargar todo en memoria.
    Ideal para exportaciones con miles de ordenes.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerows(filas)
    contenido = buffer.getvalue().encode("utf-8-sig")

    chunk_size = 65536
    for i in range(0, len(contenido), chunk_size):
        yield contenido[i : i + chunk_size]


def generar_csv(filas: list[list]) -> Generator[bytes, None, None]:
    """Devuelve un generador de chunks CSV para StreamingResponse."""
    return _csv_chunked(filas)


def generar_excel(filas: list[list]) -> Generator[bytes, None, None]:
    """
    Genera el Excel y lo devuelve en chunks via BytesIO.
    openpyxl necesita un buffer completo para save(), pero luego
    lo transmitimos por partes.
    """
    libro = Workbook()
    hoja = libro.active
    hoja.title = "Producción"
    for fila in filas:
        hoja.append(fila)

    # Ancho de columna aproximado al contenido, para que se lea sin ajustar.
    if filas:
        for indice, encabezado in enumerate(filas[0], start=1):
            largo = max((len(str(fila[indice - 1])) for fila in filas), default=len(encabezado))
            hoja.column_dimensions[hoja.cell(row=1, column=indice).column_letter].width = min(
                max(12, largo + 2), 40
            )

    buffer = io.BytesIO()
    libro.save(buffer)
    contenido = buffer.getvalue()

    chunk_size = 65536
    for i in range(0, len(contenido), chunk_size):
        yield contenido[i : i + chunk_size]


def nombre_archivo(extension: str, momento: datetime | None = None) -> str:
    momento = momento or ahora_local()
    return f"datacontrol_{momento:%Y%m%d_%H%M}.{extension}"
