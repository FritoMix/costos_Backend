import json
import os
from pathlib import Path

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.modules.produccion.models import OrdenProduccion
from app.modules.produccion.schemas import OrdenSalida
from app.modules.produccion.servicios import formula, ordenes
from app.modules.produccion.servicios.lectura import opciones_listado


def test_listados_cargan_solo_relaciones_necesarias(db, datos_base, orden_guardar, guardar_formula, tmp_path):
    ids = []
    for _ in range(30):
        orden = ordenes.crear_orden(db, orden_guardar(), datos_base.supervisor)
        guardar_formula(orden)
        ids.append(orden.id)
    conexion = db.connection()
    consulta = select(OrdenProduccion).where(OrdenProduccion.id.in_(ids)).order_by(OrdenProduccion.id)

    def medir(optimizada):
        sentencias = []
        def contar(conn, cursor, sentencia, parametros, contexto, muchos):
            if sentencia.lstrip().upper().startswith('SELECT'):
                sentencias.append(sentencia)
        event.listen(conexion, 'before_cursor_execute', contar)
        try:
            with Session(bind=conexion, join_transaction_mode='create_savepoint') as lectura:
                filas = lectura.scalars(consulta.options(*opciones_listado()) if optimizada else consulta)
                objetos_orden = filas.unique().all()
                salida = [OrdenSalida.model_validate(fila).model_dump(mode='json')
                          for fila in objetos_orden]
                objetos = len(lectura.identity_map)
            return salida, len(sentencias), objetos
        finally:
            event.remove(conexion, 'before_cursor_execute', contar)

    antes, consultas_antes, objetos_antes = medir(False)
    despues, consultas_despues, objetos_despues = medir(True)
    assert antes == despues
    assert consultas_despues <= 2
    assert consultas_despues < consultas_antes
    assert objetos_despues < objetos_antes
    with Session(bind=conexion, join_transaction_mode='create_savepoint') as lectura:
        bandeja = formula.listar_ordenes_bodega(lectura)
        assert len(bandeja) == 30
        assert all(orden.total_bultos_planificados > 0 for orden in bandeja)
        assert all(orden.total_bultos_producidos == 0 for orden in bandeja)
    destino = Path(os.getenv('PERF_RESULT_DIR', str(tmp_path)))
    destino.mkdir(parents=True, exist_ok=True)
    (destino / 'consultas-listados.json').write_text(json.dumps({
        'ordenes_ficticias': 30,
        'consultas_antes': consultas_antes,
        'consultas_despues': consultas_despues,
        'objetos_antes': objetos_antes,
        'objetos_despues': objetos_despues,
        'respuestas_equivalentes': True,
        'limite': 'Base ficticia; no mide latencia ni capacidad de producción.',
    }, indent=2))
