"""
Pruebas de las reglas de negocio de órdenes de producción.
"""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.core.errores import ErrorDeValidacion
from app.modules.catalogos.models import Horno, Producto
from app.modules.produccion.models import (
    DestinoOrden,
    EstadoOrden,
    UnidadSolicitada,
)
from app.modules.produccion.schemas import OrdenGuardar
from app.modules.produccion.servicios.ordenes import (
    _validar_catalogos,
    _validar_horas,
    calcular_cantidad_programada,
)


class MockSession:
    """Simulación ligera de sesión para probar validaciones de negocio puras."""

    def __init__(self, objetos: dict | None = None):
        self.objetos = objetos or {}

    def get(self, modelo, id_):
        return self.objetos.get((modelo, id_))


def test_orden_exportacion_requiere_horno_apto():
    horno = Horno()
    horno.id = 1
    horno.nombre = "Horno Convencional"
    horno.activo = True
    horno.apto_exportacion = False

    producto = Producto()
    producto.id = 1
    producto.nombre_comercial = "Papa Lisa 100g"
    producto.categoria_id = 1
    producto.activo = True

    db = MockSession({(Horno, 1): horno, (Producto, 1): producto})

    datos = OrdenGuardar(
        turno_id=1,
        horno_id=1,
        producto_id=1,
        categoria_id=1,
        destino=DestinoOrden.EXPORTACION,
        unidad_solicitada=UnidadSolicitada.KG,
        cantidad_kg=Decimal("1000.00"),
        horas_produccion=2,
    )

    with pytest.raises(ErrorDeValidacion, match="no está habilitado para órdenes de exportación"):
        _validar_catalogos(db, datos)


def test_calcular_cantidad_en_canastillas_usa_peso_producto():
    producto = Producto()
    producto.id = 1
    producto.peso_estandar_canastilla_kg = Decimal("6.50")

    datos = OrdenGuardar(
        turno_id=1,
        horno_id=1,
        producto_id=1,
        categoria_id=1,
        destino=DestinoOrden.NACIONAL,
        unidad_solicitada=UnidadSolicitada.CANASTILLAS,
        cantidad_canastillas=Decimal("10"),
    )

    db = MockSession()
    kg, canastillas = calcular_cantidad_programada(db, datos, producto)
    assert kg == Decimal("65.00")
    assert canastillas == Decimal("10")


def test_estados_y_destinos_constantes():
    assert EstadoOrden.PENDIENTE == "pendiente"
    assert EstadoOrden.EN_PRODUCCION == "en_produccion"
    assert EstadoOrden.FINALIZADA == "finalizada"
    assert EstadoOrden.CANCELADA == "cancelada"
    assert EstadoOrden.ACTIVOS == ("pendiente", "en_produccion")
    assert DestinoOrden.NACIONAL == "nacional"
    assert DestinoOrden.EXPORTACION == "exportacion"


def _orden_de_prueba(**cambios) -> OrdenGuardar:
    """Orden válida mínima; cada prueba cambia solo lo que quiere revisar."""
    base = dict(
        turno_id=1,
        horno_id=1,
        producto_id=1,
        categoria_id=1,
        destino=DestinoOrden.NACIONAL,
        unidad_solicitada=UnidadSolicitada.KG,
        cantidad_kg=Decimal("100.00"),
        horas_produccion=2,
    )
    base.update(cambios)
    return OrdenGuardar(**base)


def test_horas_de_produccion_son_obligatorias():
    with pytest.raises(ErrorDeValidacion, match="cuántas horas"):
        _validar_horas(_orden_de_prueba(horas_produccion=None))



def test_horas_de_produccion_no_admiten_medias_horas():
    """En planta no existen medias horas: 1.5 debe rechazarse en el schema."""
    with pytest.raises(ValidationError):
        _orden_de_prueba(horas_produccion=Decimal("1.5"))


def test_horas_de_produccion_validas_no_levantan_error():
    _validar_horas(_orden_de_prueba(horas_produccion=1))
    _validar_horas(_orden_de_prueba(horas_produccion=8))

def test_horas_de_produccion_minimo_una_en_el_schema():
    """Primera barrera: el schema no deja pasar 0 horas (ge=1)."""
    with pytest.raises(ValidationError):
        _orden_de_prueba(horas_produccion=0)


def test_horas_de_produccion_minimo_una_en_el_servicio():
    """
    Segunda barrera. Se salta el schema a proposito (model_construct) para
    comprobar que el servicio tampoco acepta menos de una hora, aunque el
    dato llegue por otro camino.
    """
    orden = OrdenGuardar.model_construct(horas_produccion=0)
    with pytest.raises(ErrorDeValidacion, match="al menos 1 hora"):
        _validar_horas(orden)
