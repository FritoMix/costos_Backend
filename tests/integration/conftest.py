"""
Datos de catalogo y usuarios para las pruebas de integracion.

Se apoyan en los datos iniciales de la migracion V2 (categorias, turnos,
hornos, configuracion). Los productos, sabores y usuarios se crean aqui
porque en produccion los administra el negocio.
"""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.catalogos.models import (
    CategoriaProducto,
    ConfiguracionPlanta,
    Horno,
    Producto,
    Sabor,
    TipoDesperdicio,
    Turno,
)
from app.modules.identidad.models import Rol, RolCodigo, Usuario
from app.modules.produccion.models import DestinoOrden, UnidadSolicitada
from app.modules.produccion.schemas import OrdenGuardar

HASH_DE_PRUEBA = "hash-de-prueba-sin-uso-en-login"


def _usuario(nombre: str, usuario: str, rol: Rol) -> Usuario:
    return Usuario(
        nombre_completo=nombre,
        nombre_usuario=usuario,
        password_hash=HASH_DE_PRUEBA,
        rol_id=rol.id,
        activo=True,
    )


@pytest.fixture
def datos_base(db: Session) -> SimpleNamespace:
    """Catalogos y usuarios minimos para operar una orden completa."""
    categoria = db.scalar(
        select(CategoriaProducto).where(CategoriaProducto.nombre == "Papa Hojuela")
    )
    turno = db.scalar(select(Turno).order_by(Turno.id))
    horno = db.scalar(select(Horno).where(Horno.nombre == "Horno 1"))
    tipo_desperdicio = db.scalar(
        select(TipoDesperdicio).where(TipoDesperdicio.nombre == "Papa quemada")
    )
    configuracion = db.get(ConfiguracionPlanta, 1)
    roles = {rol.codigo: rol for rol in db.scalars(select(Rol)).all()}

    producto = Producto(
        nombre_comercial="Papa Hojuela de Prueba",
        categoria_id=categoria.id,
        activo=True,
        peso_estandar_canastilla_kg=Decimal("6.00"),
    )
    sabor = Sabor(nombre="Natural de Prueba", activo=True)

    supervisor = _usuario("Supervisor de Prueba", "supervisor_prueba", roles[RolCodigo.SUPERVISOR])
    admin = _usuario("Admin de Prueba", "admin_prueba", roles[RolCodigo.ADMIN])
    operario_horno = _usuario(
        "Operario de Horno de Prueba",
        "operario_horno_prueba",
        roles[RolCodigo.OPERARIO_HORNO],
    )
    operario_saborizado = _usuario(
        "Operario de Saborizado de Prueba",
        "operario_saborizado_prueba",
        roles[RolCodigo.OPERARIO_SABORIZADO],
    )

    db.add_all([producto, sabor, supervisor, admin, operario_horno, operario_saborizado])
    db.flush()

    return SimpleNamespace(
        categoria=categoria,
        turno=turno,
        horno=horno,
        tipo_desperdicio=tipo_desperdicio,
        configuracion=configuracion,
        producto=producto,
        sabor=sabor,
        supervisor=supervisor,
        admin=admin,
        operario_horno=operario_horno,
        operario_saborizado=operario_saborizado,
    )


@pytest.fixture
def orden_guardar(datos_base: SimpleNamespace):
    """Fabrica de OrdenGuardar validas; cada prueba cambia solo lo que le importa."""

    def _crear(**cambios) -> OrdenGuardar:
        base = dict(
            turno_id=datos_base.turno.id,
            horno_id=datos_base.horno.id,
            categoria_id=datos_base.categoria.id,
            producto_id=datos_base.producto.id,
            destino=DestinoOrden.NACIONAL,
            unidad_solicitada=UnidadSolicitada.KG,
            cantidad_kg=Decimal("100.00"),
            horas_produccion=2,
        )
        base.update(cambios)
        return OrdenGuardar(**base)

    return _crear
