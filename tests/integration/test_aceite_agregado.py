"""Aceite agregado en la tanda y catálogo de tipos de aceite (V18)."""

from datetime import timedelta
from decimal import Decimal

import pytest

from app.core.errores import ErrorDeValidacion
from app.modules.catalogos import service as catalogos
from app.modules.catalogos.schemas import TipoAceiteGuardar
from app.modules.produccion.schemas import RegistroHornoGuardar
from app.modules.produccion.servicios import horno as servicio_horno
from app.modules.produccion.servicios import ordenes as servicio_ordenes


def _tanda(datos_base, **cambios) -> RegistroHornoGuardar:
    base = dict(
        referencia_papa_id=datos_base.referencia_papa.id,
        cantidad_bultos=Decimal("10"),
        operarios_seleccion=2,
        operarios_horno=1,
        nivel_aceite_inicial_cm=Decimal("20"),
        nivel_aceite_final_cm=Decimal("18"),
        temperatura_aceite_c=Decimal("175"),
    )
    base.update(cambios)
    return RegistroHornoGuardar(**base)


def _orden(db, datos_base, orden_guardar, guardar_formula):
    orden = servicio_ordenes.crear_orden(db, orden_guardar(horas_produccion=2), datos_base.supervisor)
    guardar_formula(orden)
    servicio_ordenes.iniciar_orden(db, orden)
    orden.hora_inicio -= timedelta(hours=2)
    db.flush()
    return orden


def test_nivel_que_sube_exige_litros_agregados(db, datos_base, orden_guardar, guardar_formula):
    orden = _orden(db, datos_base, orden_guardar, guardar_formula)
    with pytest.raises(ValueError, match="indica cuántos litros"):
        _tanda(datos_base, nivel_aceite_final_cm=Decimal("25"))

    datos_base.horno.litros_por_cm_manual = Decimal("10")
    db.flush()
    # Subió 5 cm (50 L) pero se agregaron 80 L: consumo real 30 L.
    registro = servicio_horno.crear_registro(
        db,
        orden,
        _tanda(datos_base, nivel_aceite_final_cm=Decimal("25"), aceite_agregado_litros=Decimal("80")),
        datos_base.operario_horno,
    )
    assert registro.aceite_agregado_litros == Decimal("80")
    assert registro.volumen_aceite_litros == Decimal("30.00")


def test_consumo_negativo_se_rechaza(db, datos_base, orden_guardar, guardar_formula):
    orden = _orden(db, datos_base, orden_guardar, guardar_formula)
    datos_base.horno.litros_por_cm_manual = Decimal("10")
    db.flush()
    with pytest.raises(ErrorDeValidacion, match="da negativo"):
        servicio_horno.crear_registro(
            db,
            orden,
            _tanda(datos_base, nivel_aceite_final_cm=Decimal("25"), aceite_agregado_litros=Decimal("10")),
            datos_base.operario_horno,
        )


def test_densidad_del_catalogo_solo_sin_muestras(db, datos_base):
    aceite = catalogos.crear_aceite(
        db, TipoAceiteGuardar(nombre="Palma prueba", densidad_kg_por_litro=Decimal("0.91"), proveedor="X")
    )
    datos_base.horno.aceite_id = aceite.id
    db.flush()
    hoy = datos_base.horno and __import__("datetime").date.today()
    densidad = catalogos.obtener_densidad_vigente(db, datos_base.horno.id, hoy)
    # Si el horno ya tiene una muestra, manda la muestra; si no, el catálogo.
    muestras = catalogos.listar_muestras_densidad(db, datos_base.horno.id)
    if muestras:
        assert densidad == muestras[0].densidad_kg_por_litro
    else:
        assert densidad == Decimal("0.91")

    with pytest.raises(ErrorDeValidacion, match="un horno lo usa"):
        catalogos.eliminar_aceite(db, aceite.id)
