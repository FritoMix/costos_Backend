"""Compara el servicio con caché fría. PYTHONPATH elige la revisión de app."""
import hashlib
import json
import math
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from threading import local
from time import perf_counter

from sqlalchemy import event, select
from sqlalchemy.engine import make_url

from app.db.session import SessionLocal, engine
from app.modules.analitica.schemas import FiltrosAnalisis
from app.modules.analitica.service import calcular_indicadores
from app.modules.identidad.models import Usuario


muestra = local()


@event.listens_for(engine, "before_cursor_execute")
def _inicio_sql(*_):
    muestra.inicio_sql = perf_counter()


@event.listens_for(engine, "after_cursor_execute")
def _fin_sql(*_):
    muestra.sql_ms += (perf_counter() - muestra.inicio_sql) * 1000
    muestra.consultas += 1


def lectura(i):
    # Claves diferentes; la ventana selecciona las mismas 240 órdenes del fixture.
    filtros = FiltrosAnalisis(fecha_desde=date(2035, 1, 1) + timedelta(days=i), fecha_hasta=date(2036, 1, 1))
    muestra.sql_ms = 0
    muestra.consultas = 0
    inicio = perf_counter()
    with SessionLocal() as db:
        db.scalar(select(Usuario.id).where(Usuario.nombre_usuario == "benchmark_kpi"))
        indicadores = calcular_indicadores(db, filtros)
    ms = (perf_counter() - inicio) * 1000
    assert indicadores.numero_ordenes == 240 and len(indicadores.por_producto) == 10
    return ms, muestra.sql_ms, muestra.consultas, indicadores.model_dump_json()


if __name__ == "__main__":
    destino = make_url(os.environ["DATABASE_URL"])
    if destino.host not in {"localhost", "127.0.0.1"} or destino.database != "datacontrol_kpi_test":
        raise SystemExit("Usa la base local desechable datacontrol_kpi_test.")
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lectura, range(12)))
        muestras = list(pool.map(lectura, range(12, 132)))
    tiempos = sorted(m[0] for m in muestras)
    tiempos_sql = sorted(m[1] for m in muestras)
    consultas = {m[2] for m in muestras}
    assert len(consultas) == 1
    respuestas = {m[3] for m in muestras}
    assert len(respuestas) == 1
    huella = hashlib.sha256(respuestas.pop().encode()).hexdigest()
    indice = math.ceil(.95 * len(tiempos)) - 1
    resultado = {
        "muestras": len(tiempos), "concurrencia": 4, "p95_ms": round(tiempos[indice], 2),
        "p95_sql_ms": round(tiempos_sql[indice], 2), "consultas_con_lectura_previa": consultas.pop(),
        "sha256_indicadores": huella,
    }
    Path(sys.argv[1]).write_text(json.dumps(resultado))
    print(json.dumps(resultado))
