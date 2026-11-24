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


def _orden_con_registros(db, datos_base, orden_guardar, guardar_formula, cantidad):
    """Orden en produccion con `cantidad` tandas de horno y recepciones."""
    from datetime import timedelta
    from decimal import Decimal

    from app.modules.produccion.schemas import (
        RecepcionGuardar,
        RegistroHornoGuardar,
        RegistroReferenciaGuardar,
    )
    from app.modules.produccion.servicios import horno, saborizado

    orden = ordenes.crear_orden(db, orden_guardar(horas_produccion=8), datos_base.supervisor)
    guardar_formula(orden)
    orden = ordenes.iniciar_orden(db, orden)
    orden.hora_inicio -= timedelta(hours=9)
    db.flush()
    for numero in range(1, cantidad + 1):
        horno.crear_registro(
            db,
            orden,
            RegistroHornoGuardar(
                numero_tanda=numero,
                referencias=[
                    RegistroReferenciaGuardar(
                        referencia_papa_id=datos_base.referencia_papa.id, cantidad_bultos=Decimal("10")
                    )
                ],
                operarios_seleccion=2,
                operarios_horno=1,
                nivel_aceite_inicial_cm=Decimal("20"),
                nivel_aceite_final_cm=Decimal("18"),
                temperatura_aceite_c=Decimal("175"),
            ),
            datos_base.operario_horno,
        )
        saborizado.crear_recepcion(
            db,
            orden,
            RecepcionGuardar(
                numero_tanda=numero,
                sabor_id=datos_base.sabor.id,
                cantidad_sabor_kg=Decimal("1"),
                pesos_canastillas=[Decimal("6")] * 5,
            ),
            datos_base.operario_saborizado,
        )
    return orden.id


def test_detalle_de_orden_no_crece_con_las_tandas(db, datos_base, orden_guardar, guardar_formula):
    """
    Rendimiento: abrir una orden (horno, saborizado, detalle) cuesta lo mismo con
    1 tanda que con 6. Cada consulta extra son ~0,1 s en produccion (Render y
    Supabase en sitios distintos); antes de este control eran 48 en el detalle.
    """
    from app.modules.produccion.schemas import RecepcionSalida, RegistroHornoSalida
    from app.modules.produccion.servicios import horno, saborizado

    conexion = db.connection()

    def medir(orden_id):
        sentencias = []

        def contar(conn, cursor, sentencia, parametros, contexto, muchos):
            sentencias.append(sentencia)

        event.listen(conexion, "before_cursor_execute", contar)
        try:
            with Session(bind=conexion, join_transaction_mode="create_savepoint") as lectura:
                orden = ordenes.obtener_orden(lectura, orden_id)
                OrdenSalida.model_validate(orden).model_dump(mode="json")
                tandas = [
                    RegistroHornoSalida.model_validate(r).model_dump(mode="json")
                    for r in horno.listar_registros(lectura, orden_id, orden)
                ]
                recepciones = [
                    RecepcionSalida.model_validate(r).model_dump(mode="json")
                    for r in saborizado.listar_recepciones(lectura, orden_id, orden)
                ]
            return len(sentencias), len(tandas), len(recepciones)
        finally:
            event.remove(conexion, "before_cursor_execute", contar)

    primera = _orden_con_registros(db, datos_base, orden_guardar, guardar_formula, 1)
    una = medir(primera)
    ordenes.finalizar_orden(db, db.get(OrdenProduccion, primera))
    seis = medir(_orden_con_registros(db, datos_base, orden_guardar, guardar_formula, 6))
    assert una[1:] == (1, 1) and seis[1:] == (6, 6)
    assert seis[0] == una[0], f"Las consultas crecen con las tandas: {una[0]} con 1, {seis[0]} con 6"
    assert seis[0] <= 16, f"Abrir una orden hace {seis[0]} consultas"
