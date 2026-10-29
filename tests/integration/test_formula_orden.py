"""
Pruebas de integración de la fórmula de producción por orden.

Cubren el ciclo Bodega → Horno contra PostgreSQL: guardado, reemplazo,
congelado, bandeja restringida, tandas multi-referencia y límites físicos.
"""

from datetime import time
from decimal import Decimal

import pytest

from app.core.errores import ErrorDeValidacion
from app.modules.bodega.models import ReferenciaPapa
from app.modules.produccion.models import (
    EstadoFormula,
    EstadoOrden,
)
from app.modules.produccion.schemas import (
    FormulaGuardar,
    FormulaProyeccionGuardar,
    FormulaReferenciaGuardar,
    RegistroHornoGuardar,
    RegistroReferenciaGuardar,
)
from app.modules.produccion.servicios import formula as servicio_formula
from app.modules.produccion.servicios import horno as servicio_horno
from app.modules.produccion.servicios import ordenes as servicio_ordenes


def _segunda_referencia(db, datos_base, **cambios) -> ReferenciaPapa:
    base = dict(
        nombre="Papa Pastusa de Prueba",
        tipo="Papa pastusa",
        peso_promedio_bulto_kg=Decimal("40.00"),
        rendimiento_fritura_pct=Decimal("30.00"),
        porcentaje_produccion_pct=Decimal("40.00"),
        activo=True,
    )
    base.update(cambios)
    referencia = ReferenciaPapa(**base)
    db.add(referencia)
    db.flush()
    return referencia


def _formula(*filas: tuple[ReferenciaPapa, int], notas: str | None = None) -> FormulaGuardar:
    return FormulaGuardar(
        referencias=[
            FormulaReferenciaGuardar(
                referencia_papa_id=referencia.id, bultos_por_tanda=bultos
            )
            for referencia, bultos in filas
        ],
        notas=notas,
    )


def _tanda(
    datos_base,
    *,
    inicio: time = time(6, 0),
    fin: time = time(7, 0),
    referencias: list[RegistroReferenciaGuardar] | None = None,
    **cambios,
) -> RegistroHornoGuardar:
    if referencias is None:
        referencias = [
            RegistroReferenciaGuardar(
                referencia_papa_id=datos_base.referencia_papa.id,
                cantidad_bultos=Decimal("10"),
            )
        ]
    base = dict(
        hora_inicio=inicio,
        hora_fin=fin,
        referencias=referencias,
        operarios_seleccion=2,
        operarios_horno=1,
        nivel_aceite_inicial_cm=Decimal("20"),
        nivel_aceite_final_cm=Decimal("18"),
        temperatura_aceite_c=Decimal("175"),
    )
    base.update(cambios)
    return RegistroHornoGuardar(**base)


def test_bodega_guarda_y_consulta_la_formula_con_snapshots(
    db, datos_base, orden_guardar, guardar_formula
):
    orden = servicio_ordenes.crear_orden(db, orden_guardar(), datos_base.supervisor)

    guardar_formula(orden, notas="Mezcla de la semana")

    formula = servicio_formula.obtener(db, orden)
    assert formula.estado == EstadoFormula.LISTA
    assert formula.notas == "Mezcla de la semana"
    assert formula.total_bultos_por_tanda == 10
    assert formula.total_bultos_planificados == 20
    assert formula.tandas_programadas == 2
    assert formula.tandas_registradas == 0
    assert formula.avance_bultos_porcentaje == Decimal("0.00")
    assert formula.actualizada_por.id == datos_base.bodeguero.id
    assert formula.fecha_actualizacion is not None
    fila = formula.referencias[0]
    assert fila.porcentaje_produccion_pct == Decimal("100.0000")
    assert fila.peso_promedio_bulto_kg == Decimal("50.00")
    assert fila.kg_crudos_planificados == Decimal("1000.00")
    assert fila.kg_fritos_estimados == Decimal("250.00")

    # Corregir el catálogo no reescribe la fórmula ya guardada.
    datos_base.referencia_papa.peso_promedio_bulto_kg = Decimal("45.00")
    datos_base.referencia_papa.rendimiento_fritura_pct = Decimal("30.00")
    db.flush()

    formula = servicio_formula.obtener(db, orden)
    assert formula.referencias[0].peso_promedio_bulto_kg == Decimal("50.00")
    assert formula.referencias[0].rendimiento_fritura_pct == Decimal("25.0000")


def test_una_orden_nueva_no_inicia_sin_formula(db, datos_base, orden_guardar):
    orden = servicio_ordenes.crear_orden(db, orden_guardar(), datos_base.supervisor)

    assert orden.formula_estado == EstadoFormula.SIN_FORMULA

    with pytest.raises(ErrorDeValidacion, match="Bodega debe definir la fórmula"):
        servicio_ordenes.iniciar_orden(db, orden)

    assert orden.estado == EstadoOrden.PENDIENTE


def test_una_orden_historica_no_admite_formula(
    db, datos_base, orden_guardar, guardar_formula
):
    orden = servicio_ordenes.crear_orden(db, orden_guardar(), datos_base.supervisor)
    orden.formula_obligatoria = False
    db.flush()

    assert orden.formula_estado == EstadoFormula.NO_APLICA

    with pytest.raises(ErrorDeValidacion, match="histórica"):
        guardar_formula(orden)


def test_la_formula_solo_se_guarda_en_pendiente_y_sin_tandas(
    db, datos_base, orden_guardar, guardar_formula
):
    orden = servicio_ordenes.crear_orden(db, orden_guardar(), datos_base.supervisor)
    guardar_formula(orden)

    # Reemplazarla mientras sigue Pendiente y sin tandas está permitido.
    guardar_formula(orden, bultos_por_tanda=12)
    assert len(orden.referencias) == 1
    assert orden.referencias[0].bultos_por_tanda == 12

    servicio_ordenes.iniciar_orden(db, orden)
    assert orden.formula_estado == EstadoOrden.EN_PRODUCCION

    with pytest.raises(ErrorDeValidacion, match="mientras la orden esté Pendiente"):
        guardar_formula(orden)

    servicio_ordenes.finalizar_orden(db, orden)
    with pytest.raises(ErrorDeValidacion, match="mientras la orden esté Pendiente"):
        guardar_formula(orden)


def test_una_tanda_congela_la_formula(
    db, datos_base, orden_guardar, guardar_formula
):
    orden = servicio_ordenes.crear_orden(db, orden_guardar(), datos_base.supervisor)
    guardar_formula(orden)
    servicio_ordenes.iniciar_orden(db, orden)
    servicio_horno.crear_registro(
        db, orden, _tanda(datos_base), datos_base.operario_horno
    )

    with pytest.raises(ErrorDeValidacion, match="congelada"):
        guardar_formula(orden)


def test_formula_rechaza_referencia_repetida(
    db, datos_base, orden_guardar
):
    orden = servicio_ordenes.crear_orden(db, orden_guardar(), datos_base.supervisor)
    datos = FormulaGuardar(
        referencias=[
            FormulaReferenciaGuardar(
                referencia_papa_id=datos_base.referencia_papa.id,
                bultos_por_tanda=5,
            ),
            FormulaReferenciaGuardar(
                referencia_papa_id=datos_base.referencia_papa.id,
                bultos_por_tanda=5,
            ),
        ]
    )

    with pytest.raises(ErrorDeValidacion, match="repetir"):
        servicio_formula.guardar(db, orden, datos, datos_base.bodeguero)


def test_formula_rechaza_referencia_inactiva(
    db, datos_base, orden_guardar
):
    orden = servicio_ordenes.crear_orden(db, orden_guardar(), datos_base.supervisor)
    datos_base.referencia_papa.activo = False
    db.flush()

    with pytest.raises(ErrorDeValidacion, match="inactiva"):
        servicio_formula.guardar(
            db,
            orden,
            _formula((datos_base.referencia_papa, 10)),
            datos_base.bodeguero,
        )


def test_formula_rechaza_referencia_incompleta(
    db, datos_base, orden_guardar
):
    orden = servicio_ordenes.crear_orden(db, orden_guardar(), datos_base.supervisor)
    datos_base.referencia_papa.tipo = None
    db.flush()

    with pytest.raises(ErrorDeValidacion, match="incompleta"):
        servicio_formula.guardar(
            db,
            orden,
            _formula((datos_base.referencia_papa, 10)),
            datos_base.bodeguero,
        )


def test_formula_rechaza_mezcla_mayor_que_la_capacidad(
    db, datos_base, orden_guardar
):
    orden = servicio_ordenes.crear_orden(db, orden_guardar(), datos_base.supervisor)

    with pytest.raises(ErrorDeValidacion, match="admite máximo 50"):
        servicio_formula.guardar(
            db,
            orden,
            _formula((datos_base.referencia_papa, 51)),
            datos_base.bodeguero,
        )


def test_formula_exige_capacidad_del_horno(
    db, datos_base, orden_guardar
):
    orden = servicio_ordenes.crear_orden(db, orden_guardar(), datos_base.supervisor)
    datos_base.horno.capacidad_bultos_hora = None
    db.flush()

    with pytest.raises(ErrorDeValidacion, match="capacidad de bultos por hora"):
        servicio_formula.guardar(
            db,
            orden,
            _formula((datos_base.referencia_papa, 10)),
            datos_base.bodeguero,
        )


def test_cambiar_las_horas_recalcula_los_totales_planificados(
    db, datos_base, orden_guardar, guardar_formula
):
    orden = servicio_ordenes.crear_orden(db, orden_guardar(), datos_base.supervisor)
    guardar_formula(orden)

    actualizada = servicio_ordenes.editar_orden(
        db, orden, orden_guardar(horas_produccion=3)
    )

    assert actualizada.referencias[0].bultos_planificados == 30
    assert actualizada.referencias[0].kg_crudos_planificados == Decimal("1500.00")
    assert actualizada.referencias[0].kg_fritos_estimados == Decimal("375.00")


def test_la_proyeccion_advierte_sobreproduccion_sin_bloquear(
    db, datos_base, orden_guardar
):
    orden = servicio_ordenes.crear_orden(db, orden_guardar(), datos_base.supervisor)

    salida = servicio_formula.proyectar(
        db,
        orden,
        FormulaProyeccionGuardar(
            referencias=[
                FormulaReferenciaGuardar(
                    referencia_papa_id=datos_base.referencia_papa.id,
                    bultos_por_tanda=10,
                )
            ]
        ),
    )

    assert salida.total_kg_fritos_estimados == Decimal("250.00")
    assert salida.diferencia_kg == Decimal("150.00")
    assert salida.factible is True
    assert "más de lo pedido" in (salida.mensaje or "").lower()


def test_la_proyeccion_bloquea_cuando_la_capacidad_fisica_no_alcanza(
    db, datos_base, orden_guardar
):
    orden = servicio_ordenes.crear_orden(
        db, orden_guardar(cantidad_kg=Decimal("5000.00")), datos_base.supervisor
    )

    salida = servicio_formula.proyectar(
        db,
        orden,
        FormulaProyeccionGuardar(
            referencias=[
                FormulaReferenciaGuardar(
                    referencia_papa_id=datos_base.referencia_papa.id,
                    bultos_por_tanda=1,
                )
            ]
        ),
    )

    assert salida.factible is False
    assert "capacidad máxima" in salida.mensaje


def test_tanda_multi_referencia_guarda_el_detalle_y_la_suma(
    db, datos_base, orden_guardar
):
    segunda = _segunda_referencia(db, datos_base)
    orden = servicio_ordenes.crear_orden(db, orden_guardar(), datos_base.supervisor)
    datos = _formula((datos_base.referencia_papa, 30), (segunda, 20))
    servicio_formula.guardar(db, orden, datos, datos_base.bodeguero)
    servicio_ordenes.iniciar_orden(db, orden)

    registro = servicio_horno.crear_registro(
        db,
        orden,
        _tanda(
            datos_base,
            referencias=[
                RegistroReferenciaGuardar(
                    referencia_papa_id=datos_base.referencia_papa.id,
                    cantidad_bultos=Decimal("30"),
                ),
                RegistroReferenciaGuardar(
                    referencia_papa_id=segunda.id,
                    cantidad_bultos=Decimal("20"),
                ),
            ],
        ),
        datos_base.operario_horno,
    )

    assert registro.cantidad_bultos == Decimal("50.00")
    assert registro.kg_crudos_calculados == Decimal("2300.00")
    assert registro.kg_fritos_estimados == Decimal("615.00")
    assert len(registro.referencias) == 2
    por_referencia = {
        fila.referencia_papa_id: fila for fila in registro.referencias
    }
    assert por_referencia[datos_base.referencia_papa.id].kg_crudos_calculados == Decimal(
        "1500.00"
    )
    assert por_referencia[segunda.id].kg_fritos_estimados == Decimal("240.00")

    formula = servicio_formula.obtener(db, orden)
    assert formula.total_bultos_producidos == Decimal("50")
    assert formula.avance_bultos_porcentaje == Decimal("50.00")


def test_la_tanda_no_puede_usar_una_referencia_fuera_de_la_formula(
    db, datos_base, orden_guardar
):
    segunda = _segunda_referencia(db, datos_base)
    orden = servicio_ordenes.crear_orden(db, orden_guardar(), datos_base.supervisor)
    servicio_formula.guardar(
        db, orden, _formula((datos_base.referencia_papa, 10)), datos_base.bodeguero
    )
    servicio_ordenes.iniciar_orden(db, orden)

    with pytest.raises(ErrorDeValidacion, match="no está en la fórmula"):
        servicio_horno.crear_registro(
            db,
            orden,
            _tanda(
                datos_base,
                referencias=[
                    RegistroReferenciaGuardar(
                        referencia_papa_id=segunda.id,
                        cantidad_bultos=Decimal("20"),
                    )
                ],
            ),
            datos_base.operario_horno,
        )


def test_la_tanda_no_supera_el_restante_planificado(
    db, datos_base, orden_guardar
):
    orden = servicio_ordenes.crear_orden(
        db, orden_guardar(horas_produccion=2), datos_base.supervisor
    )
    servicio_formula.guardar(
        db, orden, _formula((datos_base.referencia_papa, 10)), datos_base.bodeguero
    )
    servicio_ordenes.iniciar_orden(db, orden)

    servicio_horno.crear_registro(
        db,
        orden,
        _tanda(
            datos_base,
            referencias=[
                RegistroReferenciaGuardar(
                    referencia_papa_id=datos_base.referencia_papa.id,
                    cantidad_bultos=Decimal("15"),
                )
            ],
        ),
        datos_base.operario_horno,
    )

    with pytest.raises(ErrorDeValidacion, match="Solo quedan 5"):
        servicio_horno.crear_registro(
            db,
            orden,
            _tanda(
                datos_base,
                inicio=time(7, 0),
                fin=time(8, 0),
                referencias=[
                    RegistroReferenciaGuardar(
                        referencia_papa_id=datos_base.referencia_papa.id,
                        cantidad_bultos=Decimal("6"),
                    )
                ],
            ),
            datos_base.operario_horno,
        )


def test_la_tanda_no_supera_la_capacidad_del_horno(
    db, datos_base, orden_guardar
):
    orden = servicio_ordenes.crear_orden(db, orden_guardar(), datos_base.supervisor)
    servicio_formula.guardar(
        db, orden, _formula((datos_base.referencia_papa, 30)), datos_base.bodeguero
    )
    servicio_ordenes.iniciar_orden(db, orden)

    with pytest.raises(ErrorDeValidacion, match="admite máximo 50"):
        servicio_horno.crear_registro(
            db,
            orden,
            _tanda(
                datos_base,
                referencias=[
                    RegistroReferenciaGuardar(
                        referencia_papa_id=datos_base.referencia_papa.id,
                        cantidad_bultos=Decimal("51"),
                    )
                ],
            ),
            datos_base.operario_horno,
        )


def test_una_orden_de_n_horas_no_admite_la_tanda_n_mas_uno(
    db, datos_base, orden_guardar, guardar_formula
):
    orden = servicio_ordenes.crear_orden(
        db, orden_guardar(horas_produccion=2), datos_base.supervisor
    )
    # La mezcla planifica 60 bultos para que el tercer intento falle por el
    # conteo de tandas y no por bultos restantes.
    guardar_formula(orden, bultos_por_tanda=30)
    servicio_ordenes.iniciar_orden(db, orden)

    servicio_horno.crear_registro(
        db,
        orden,
        _tanda(datos_base, inicio=time(6, 0), fin=time(6, 30)),
        datos_base.operario_horno,
    )
    servicio_horno.crear_registro(
        db,
        orden,
        _tanda(datos_base, inicio=time(6, 30), fin=time(7, 0)),
        datos_base.operario_horno,
    )

    with pytest.raises(ErrorDeValidacion, match="ya registró 2 tandas"):
        servicio_horno.crear_registro(
            db,
            orden,
            _tanda(datos_base, inicio=time(7, 0), fin=time(7, 30)),
            datos_base.operario_horno,
        )


def test_la_formula_pasa_por_sus_estados_sin_perder_filas(
    db, datos_base, orden_guardar, guardar_formula
):
    orden = servicio_ordenes.crear_orden(db, orden_guardar(), datos_base.supervisor)
    assert orden.formula_estado == EstadoFormula.SIN_FORMULA

    guardar_formula(orden)
    assert orden.formula_estado == EstadoFormula.LISTA

    servicio_ordenes.iniciar_orden(db, orden)
    assert orden.formula_estado == EstadoOrden.EN_PRODUCCION

    servicio_ordenes.finalizar_orden(db, orden)
    assert orden.formula_estado == EstadoOrden.FINALIZADA

    cancelada = servicio_ordenes.crear_orden(
        db, orden_guardar(), datos_base.supervisor
    )
    guardar_formula(cancelada)
    servicio_ordenes.cancelar_orden(db, cancelada)
    assert cancelada.formula_estado == EstadoOrden.CANCELADA


def test_bandeja_de_bodega_filtra_pendientes_sin_formula(
    db, datos_base, orden_guardar, guardar_formula
):
    sin_formula = servicio_ordenes.crear_orden(
        db, orden_guardar(), datos_base.supervisor
    )
    con_formula = servicio_ordenes.crear_orden(
        db, orden_guardar(), datos_base.supervisor
    )
    guardar_formula(con_formula)

    pendientes = servicio_formula.listar_ordenes_bodega(
        db, solo_sin_formula=True
    )
    assert [orden.id for orden in pendientes] == [sin_formula.id]

    detalle = servicio_formula.detalle_bodega(db, con_formula)
    assert detalle.orden.id == con_formula.id
    assert detalle.orden.formula_estado == EstadoFormula.LISTA
    assert detalle.orden.total_bultos_planificados == 20
    assert detalle.orden.total_bultos_producidos == Decimal("0")
    assert detalle.orden.avance_bultos_porcentaje == Decimal("0.00")
    assert detalle.formula.total_bultos_por_tanda == 10
