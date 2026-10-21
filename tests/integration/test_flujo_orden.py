"""
Pruebas de integracion del flujo de una orden contra PostgreSQL real.

Aqui si se ejercitan las restricciones de la base (indice unico parcial,
llaves foraneas, borrado suave) que las pruebas unitarias no pueden ver.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import time, timedelta
from decimal import Decimal
from threading import Barrier

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errores import ErrorDeValidacion
from app.core.tiempo import hoy_local
from app.modules.bodega import service as servicio_bodega
from app.modules.produccion.models import (
    DestinoOrden,
    EstadoOrden,
    OrdenProduccion,
    SecuenciaOrden,
    UnidadSolicitada,
)
from app.modules.produccion.schemas import RecepcionGuardar, RegistroHornoGuardar
from app.modules.produccion.servicios import horno as servicio_horno
from app.modules.produccion.servicios import ordenes as servicio_ordenes
from app.modules.produccion.servicios import saborizado as servicio_saborizado
from app.modules.produccion.servicios.totales import calcular_totales


def _orden_en_bd(db, datos_base, numero: str, estado: str) -> OrdenProduccion:
    """Inserta una orden directa, sin pasar por las validaciones del servicio."""
    orden = OrdenProduccion(
        numero_orden=numero,
        fecha=hoy_local(),
        supervisor_id=datos_base.supervisor.id,
        turno_id=datos_base.turno.id,
        horno_id=datos_base.horno.id,
        producto_id=datos_base.producto.id,
        categoria_id=datos_base.categoria.id,
        cantidad_programada=Decimal("100.00"),
        unidad_solicitada=UnidadSolicitada.KG,
        horas_produccion=2,
        destino=DestinoOrden.NACIONAL,
        estado=estado,
    )
    db.add(orden)
    return orden


def _registro_horno(**cambios) -> RegistroHornoGuardar:
    base = dict(
        hora_inicio=time(6, 0),
        hora_fin=time(7, 0),
        referencia_papa_id=1,
        cantidad_bultos=Decimal("10"),
        operarios_seleccion=2,
        operarios_horno=1,
        nivel_aceite_inicial_cm=Decimal("20"),
        nivel_aceite_final_cm=Decimal("18"),
        temperatura_aceite_c=Decimal("175"),
    )
    base.update(cambios)
    return RegistroHornoGuardar(**base)


def _recepcion(datos_base, **cambios) -> RecepcionGuardar:
    base = dict(
        hora_inicio=time(7, 0),
        hora_fin=time(8, 0),
        sabor_id=datos_base.sabor.id,
        cantidad_sabor_kg=Decimal("1.00"),
        pesos_canastillas=[Decimal("6.00"), Decimal("5.50")],
    )
    base.update(cambios)
    return RecepcionGuardar(**base)


def test_crear_iniciar_y_finalizar_una_orden(db, datos_base, orden_guardar):
    orden = servicio_ordenes.crear_orden(
        db, orden_guardar(), datos_base.supervisor
    )

    assert orden.estado == EstadoOrden.PENDIENTE
    assert orden.numero_orden == f"OP-{orden.fecha:%Y%m%d}-0001"
    assert orden.cantidad_programada == Decimal("100.00")

    servicio_ordenes.iniciar_orden(db, orden)
    assert orden.estado == EstadoOrden.EN_PRODUCCION
    assert orden.hora_inicio is not None

    # Mientras una orden ocupa el horno, otra no puede entrar en produccion.
    segunda = servicio_ordenes.crear_orden(db, orden_guardar(), datos_base.supervisor)
    with pytest.raises(ErrorDeValidacion, match="ya tiene la orden"):
        servicio_ordenes.iniciar_orden(db, segunda)

    servicio_ordenes.finalizar_orden(db, orden)
    assert orden.estado == EstadoOrden.FINALIZADA
    assert orden.hora_fin is not None

    # Al liberar el horno, la segunda orden si puede iniciar.
    servicio_ordenes.iniciar_orden(db, segunda)
    assert segunda.estado == EstadoOrden.EN_PRODUCCION


def test_exportacion_exige_horno_apto(db, datos_base, orden_guardar):
    datos_base.horno.apto_exportacion = False
    db.flush()

    with pytest.raises(ErrorDeValidacion, match="exportación"):
        servicio_ordenes.crear_orden(
            db,
            orden_guardar(destino=DestinoOrden.EXPORTACION),
            datos_base.supervisor,
        )

    datos_base.horno.apto_exportacion = True
    db.flush()

    orden = servicio_ordenes.crear_orden(
        db,
        orden_guardar(destino=DestinoOrden.EXPORTACION),
        datos_base.supervisor,
    )
    assert orden.destino == DestinoOrden.EXPORTACION


def test_la_base_impide_dos_ordenes_en_produccion_en_el_mismo_horno(db, datos_base):
    _orden_en_bd(db, datos_base, "OP-TEST-0001", EstadoOrden.EN_PRODUCCION)
    db.flush()

    _orden_en_bd(db, datos_base, "OP-TEST-0002", EstadoOrden.EN_PRODUCCION)
    with pytest.raises(IntegrityError):
        db.flush()

    # La sesion queda inutilizable despues del error; se limpia el savepoint.
    db.rollback()


def test_borrado_suave_arrastra_registros_y_sale_de_los_totales(
    db, datos_base, orden_guardar
):
    orden = servicio_ordenes.crear_orden(
        db, orden_guardar(), datos_base.supervisor
    )
    servicio_ordenes.iniciar_orden(db, orden)

    registro = servicio_horno.crear_registro(
        db,
        orden,
        _registro_horno(referencia_papa_id=datos_base.referencia_papa.id),
        datos_base.operario_horno,
    )
    recepcion = servicio_saborizado.crear_recepcion(
        db, orden, _recepcion(datos_base), datos_base.operario_saborizado
    )

    totales = calcular_totales(db, orden)
    assert totales.kg_crudos == Decimal("500.00")
    assert totales.cantidad_bultos == Decimal("10.00")
    assert totales.kg_fritos_estimados == Decimal("125.00")
    assert totales.kg_papa_frita == Decimal("11.50")

    arrastrados = servicio_ordenes.eliminar_orden(db, orden, datos_base.admin)

    assert arrastrados == 2
    db.refresh(orden)
    db.refresh(registro)
    db.refresh(recepcion)
    assert orden.eliminado is True
    assert registro.eliminado is True
    assert recepcion.eliminado is True

    totales = calcular_totales(db, orden)
    assert totales.kg_crudos == 0
    assert totales.kg_papa_frita == 0


def test_cancelar_orden_libera_el_horno(db, datos_base, orden_guardar):
    primera = servicio_ordenes.crear_orden(
        db, orden_guardar(), datos_base.supervisor
    )
    servicio_ordenes.iniciar_orden(db, primera)

    servicio_ordenes.cancelar_orden(db, primera)
    assert primera.estado == EstadoOrden.CANCELADA

    segunda = servicio_ordenes.crear_orden(
        db, orden_guardar(), datos_base.supervisor
    )
    servicio_ordenes.iniciar_orden(db, segunda)
    assert segunda.estado == EstadoOrden.EN_PRODUCCION


def test_borrado_suave_de_una_orden_en_produccion_libera_el_horno(
    db, datos_base, orden_guardar
):
    primera = servicio_ordenes.crear_orden(
        db, orden_guardar(), datos_base.supervisor
    )
    servicio_ordenes.iniciar_orden(db, primera)

    servicio_ordenes.eliminar_orden(db, primera, datos_base.admin)

    assert primera.eliminado is True
    assert primera.estado == EstadoOrden.CANCELADA

    segunda = servicio_ordenes.crear_orden(
        db, orden_guardar(), datos_base.supervisor
    )
    servicio_ordenes.iniciar_orden(db, segunda)
    assert segunda.estado == EstadoOrden.EN_PRODUCCION


def test_no_se_puede_editar_una_orden_finalizada(db, datos_base, orden_guardar):
    orden = servicio_ordenes.crear_orden(
        db, orden_guardar(), datos_base.supervisor
    )
    servicio_ordenes.iniciar_orden(db, orden)
    servicio_ordenes.finalizar_orden(db, orden)

    with pytest.raises(ErrorDeValidacion, match="ya no se puede editar"):
        servicio_ordenes.editar_orden(
            db, orden, orden_guardar(cantidad_kg=Decimal("150.00"))
        )


def test_la_tanda_usa_y_congela_los_parametros_de_la_referencia(
    db, datos_base, orden_guardar
):
    orden = servicio_ordenes.crear_orden(
        db, orden_guardar(), datos_base.supervisor
    )
    servicio_ordenes.iniciar_orden(db, orden)

    referencia = datos_base.referencia_papa
    referencia.peso_promedio_bulto_kg = Decimal("48.00")
    db.flush()

    registro = servicio_horno.crear_registro(
        db, orden, _registro_horno(referencia_papa_id=referencia.id),
        datos_base.operario_horno,
    )

    assert registro.referencia_papa_id == referencia.id
    assert registro.peso_estandar_bulto_kg == Decimal("48.00")
    assert registro.rendimiento_fritura_pct == Decimal("25.00")
    assert registro.porcentaje_produccion_pct == Decimal("100.00")
    assert registro.kg_crudos_calculados == Decimal("480.00")
    assert registro.kg_fritos_estimados == Decimal("120.00")

    # Un cambio posterior en bodega no reescribe la tanda ya guardada.
    referencia.peso_promedio_bulto_kg = Decimal("45.00")
    referencia.rendimiento_fritura_pct = Decimal("30.00")
    db.flush()
    db.refresh(registro)

    assert registro.peso_estandar_bulto_kg == Decimal("48.00")
    assert registro.rendimiento_fritura_pct == Decimal("25.00")
    assert registro.kg_crudos_calculados == Decimal("480.00")
    assert registro.kg_fritos_estimados == Decimal("120.00")


def test_una_referencia_historica_sin_parametros_no_se_usa_en_tandas_nuevas(
    db, datos_base, orden_guardar
):
    orden = servicio_ordenes.crear_orden(db, orden_guardar(), datos_base.supervisor)
    servicio_ordenes.iniciar_orden(db, orden)

    referencia = datos_base.referencia_papa
    referencia.rendimiento_fritura_pct = None
    referencia.porcentaje_produccion_pct = None
    db.flush()

    with pytest.raises(ErrorDeValidacion, match="todavía no tiene configurados"):
        servicio_horno.crear_registro(
            db,
            orden,
            _registro_horno(referencia_papa_id=referencia.id),
            datos_base.operario_horno,
        )


def test_una_tanda_historica_sin_rendimiento_se_puede_corregir(
    db, datos_base, orden_guardar
):
    orden = servicio_ordenes.crear_orden(db, orden_guardar(), datos_base.supervisor)
    servicio_ordenes.iniciar_orden(db, orden)
    referencia = datos_base.referencia_papa
    registro = servicio_horno.crear_registro(
        db,
        orden,
        _registro_horno(referencia_papa_id=referencia.id),
        datos_base.operario_horno,
    )

    # Simula un registro anterior a V9: la referencia nunca tuvo rendimiento
    # ni participacion y la tanda no guardo esos snapshots.
    referencia.rendimiento_fritura_pct = None
    referencia.porcentaje_produccion_pct = None
    registro.rendimiento_fritura_pct = None
    registro.porcentaje_produccion_pct = None
    registro.kg_fritos_estimados = None
    db.flush()

    corregido = servicio_horno.editar_registro(
        db,
        registro,
        _registro_horno(
            referencia_papa_id=referencia.id,
            cantidad_bultos=Decimal("12.00"),
        ),
        datos_base.operario_horno,
    )

    assert corregido.kg_crudos_calculados == Decimal("600.00")
    assert corregido.rendimiento_fritura_pct is None
    assert corregido.porcentaje_produccion_pct is None
    assert corregido.kg_fritos_estimados is None


def test_no_se_elimina_una_referencia_que_ya_tiene_tandas(
    db, datos_base, orden_guardar
):
    orden = servicio_ordenes.crear_orden(
        db, orden_guardar(), datos_base.supervisor
    )
    servicio_ordenes.iniciar_orden(db, orden)
    servicio_horno.crear_registro(
        db,
        orden,
        _registro_horno(referencia_papa_id=datos_base.referencia_papa.id),
        datos_base.operario_horno,
    )

    with pytest.raises(ErrorDeValidacion, match="desactivarla"):
        servicio_bodega.eliminar(db, datos_base.referencia_papa.id)


def test_una_referencia_inactiva_no_se_puede_usar_en_una_tanda_nueva(
    db, datos_base, orden_guardar
):
    orden = servicio_ordenes.crear_orden(
        db, orden_guardar(), datos_base.supervisor
    )
    servicio_ordenes.iniciar_orden(db, orden)

    datos_base.referencia_papa.activo = False
    db.flush()

    with pytest.raises(ErrorDeValidacion, match="inactiva"):
        servicio_horno.crear_registro(
            db,
            orden,
            _registro_horno(referencia_papa_id=datos_base.referencia_papa.id),
            datos_base.operario_horno,
        )


def test_el_desperdicio_se_refleja_en_los_totales(db, datos_base, orden_guardar):
    orden = servicio_ordenes.crear_orden(
        db, orden_guardar(), datos_base.supervisor
    )
    servicio_ordenes.iniciar_orden(db, orden)

    registro = servicio_horno.crear_registro(
        db,
        orden,
        _registro_horno(
            referencia_papa_id=datos_base.referencia_papa.id,
            tipo_desperdicio_id=datos_base.tipo_desperdicio.id,
            cantidad_desperdicio_kg=Decimal("2.50"),
        ),
        datos_base.operario_horno,
    )

    assert len(registro.desperdicios) == 1
    totales = calcular_totales(db, orden)
    assert totales.kg_desperdicio == Decimal("2.50")


def test_recepcion_guarda_los_pesos_reales_de_cada_canastilla(
    db, datos_base, orden_guardar
):
    orden = servicio_ordenes.crear_orden(
        db, orden_guardar(), datos_base.supervisor
    )
    servicio_ordenes.iniciar_orden(db, orden)

    recepcion = servicio_saborizado.crear_recepcion(
        db,
        orden,
        _recepcion(
            datos_base,
            pesos_canastillas=[
                Decimal("6.00"),
                Decimal("5.50"),
                Decimal("4.25"),
            ],
        ),
        datos_base.operario_saborizado,
    )

    assert recepcion.kg_recibidos == Decimal("15.75")
    assert [canastilla.peso_kg for canastilla in recepcion.canastillas] == [
        Decimal("6.00"),
        Decimal("5.50"),
        Decimal("4.25"),
    ]


def test_numeracion_diaria_es_incremental(db):
    fecha = hoy_local()

    primera = servicio_ordenes.generar_numero_orden(db, fecha)
    segunda = servicio_ordenes.generar_numero_orden(db, fecha)

    assert primera.endswith("-0001")
    assert segunda.endswith("-0002")


def test_numeracion_concurrente_no_repite(engine_integracion):
    """
    Diez sesiones piden numero a la vez. El upsert atomico de PostgreSQL
    debe entregar diez consecutivos distintos, no numeros repetidos.
    """
    fecha = hoy_local() + timedelta(days=365)
    barrera = Barrier(10)

    def generar(_: int) -> str:
        with Session(engine_integracion) as sesion:
            # timeout: si un hilo no llega, el test falla en vez de colgarse.
            barrera.wait(timeout=15)
            numero = servicio_ordenes.generar_numero_orden(sesion, fecha)
            sesion.commit()
            return numero

    try:
        with ThreadPoolExecutor(max_workers=10) as ejecutor:
            numeros = list(ejecutor.map(generar, range(10)))

        esperados = [f"OP-{fecha:%Y%m%d}-{n:04d}" for n in range(1, 11)]
        assert sorted(numeros) == esperados

        with Session(engine_integracion) as sesion:
            secuencia = sesion.get(SecuenciaOrden, fecha)
            assert secuencia is not None
            assert secuencia.ultimo_numero == 10
    finally:
        with Session(engine_integracion) as sesion:
            sesion.execute(delete(SecuenciaOrden).where(SecuenciaOrden.fecha == fecha))
            sesion.commit()
