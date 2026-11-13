"""Operaciones simultáneas en conexiones y transacciones PostgreSQL independientes."""

from concurrent.futures import ThreadPoolExecutor
from datetime import time
from decimal import Decimal
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.core.errores import ErrorDeValidacion
from app.db.idempotencia import ejecutar
from app.db.migraciones import aplicar_migraciones_pendientes
from app.modules.bodega.models import ReferenciaPapa
from app.modules.catalogos.models import CategoriaProducto, Horno, Producto, Turno
from app.modules.identidad.models import Rol, Usuario
from app.modules.produccion.models import OrdenProduccion, RegistroHorno
from app.modules.produccion.schemas import (
    FormulaGuardar,
    FormulaReferenciaGuardar,
    OrdenGuardar,
    OrdenSalida,
    RegistroHornoGuardar,
)
from app.modules.produccion.servicios import formula, horno, ordenes


@pytest.fixture
def escenario(engine_integracion):
    nombre = f"prueba_fases_{uuid4().hex}"
    with engine_integracion.begin() as c:
        c.execute(text(f'CREATE SCHEMA "{nombre}"'))
    motor = create_engine(engine_integracion.url, connect_args={"options": f"-csearch_path={nombre},public"})
    try:
        aplicar_migraciones_pendientes(motor)
        with Session(motor) as db:
            categoria = db.scalar(select(CategoriaProducto).where(CategoriaProducto.nombre == "Papa Hojuela"))
            turno = db.scalar(select(Turno).order_by(Turno.id))
            rol = db.scalar(select(Rol).where(Rol.codigo == "admin"))
            usuario = Usuario(
                nombre_usuario="prueba",
                nombre_completo="Prueba simultánea",
                password_hash="sin-uso-http",
                rol_id=rol.id,
                activo=True,
            )
            equipo = Horno(
                nombre="Horno de concurrencia",
                activo=True,
                apto_exportacion=True,
                capacidad_bultos_hora=Decimal("50"),
                categorias=[categoria],
            )
            producto = Producto(
                nombre_comercial="Producto concurrente",
                activo=True,
                categoria_id=categoria.id,
                peso_estandar_canastilla_kg=Decimal("6"),
            )
            referencia = ReferenciaPapa(
                nombre="Referencia concurrente", activo=True, peso_promedio_bulto_kg=Decimal("50")
            )
            db.add_all([usuario, equipo, producto, referencia])
            db.commit()
            datos = OrdenGuardar(
                turno_id=turno.id,
                horno_id=equipo.id,
                categoria_id=categoria.id,
                producto_id=producto.id,
                cantidad_kg=Decimal("100"),
                horas_produccion=2,
            )
            actor_id, ref_id = usuario.id, referencia.id
        yield SimpleNamespace(engine=motor, datos=datos, actor_id=actor_id, ref_id=ref_id)
    finally:
        motor.dispose()
        with engine_integracion.begin() as c:
            c.execute(text(f'DROP SCHEMA "{nombre}" CASCADE'))


def preparar(escenario, *, iniciar=False):
    with Session(escenario.engine) as db:
        actor = db.get(Usuario, escenario.actor_id)
        orden = ordenes.crear_orden(db, escenario.datos, actor)
        formula.guardar(
            db,
            orden,
            FormulaGuardar(
                referencias=[
                    FormulaReferenciaGuardar(referencia_papa_id=escenario.ref_id, bultos_por_tanda=10)
                ]
            ),
            actor,
        )
        if iniciar:
            ordenes.iniciar_orden(db, orden, actor)
        return orden.id


def simultaneos(acciones):
    barrera = Barrier(len(acciones))

    def correr(accion):
        barrera.wait()
        try:
            return accion()
        except ErrorDeValidacion:
            return "rechazado"

    with ThreadPoolExecutor(max_workers=len(acciones)) as ejecutor:
        return list(ejecutor.map(correr, acciones))


def test_dos_inicios_del_mismo_horno_solo_admiten_una_orden(escenario):
    ids = [preparar(escenario), preparar(escenario)]

    def iniciar(identificador):
        def accion():
            with Session(escenario.engine) as db:
                orden = db.get(OrdenProduccion, identificador)
                ordenes.iniciar_orden(db, orden)
                return "iniciada"

        return accion

    resultados = simultaneos([iniciar(i) for i in ids])
    assert sorted(resultados) == ["iniciada", "rechazado"]
    with Session(escenario.engine) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(OrdenProduccion)
                .where(OrdenProduccion.estado == "en_produccion")
            )
            == 1
        )


def test_finalizar_y_cancelar_simultaneamente_no_se_sobrescriben(escenario):
    identificador = preparar(escenario, iniciar=True)

    def cambiar(funcion):
        def accion():
            with Session(escenario.engine) as db:
                funcion(db, db.get(OrdenProduccion, identificador))
                return "ok"

        return accion

    resultados = simultaneos([cambiar(ordenes.finalizar_orden), cambiar(ordenes.cancelar_orden)])
    assert sorted(resultados) == ["ok", "rechazado"]


def test_dos_tandas_simultaneas_no_duplican_horario(escenario):
    identificador = preparar(escenario, iniciar=True)

    def guardar():
        with Session(escenario.engine) as db:
            orden = db.get(OrdenProduccion, identificador)
            datos = RegistroHornoGuardar(
                hora_inicio=time(6),
                hora_fin=time(7),
                referencia_papa_id=escenario.ref_id,
                cantidad_bultos=Decimal("5"),
                operarios_seleccion=2,
                operarios_horno=1,
                nivel_aceite_inicial_cm=20,
                nivel_aceite_final_cm=18,
                temperatura_aceite_c=175,
            )
            horno.crear_registro(db, orden, datos, db.get(Usuario, escenario.actor_id))
            return "guardada"

    assert sorted(simultaneos([guardar, guardar])) == ["guardada", "rechazado"]
    with Session(escenario.engine) as db:
        assert db.scalar(select(func.count()).select_from(RegistroHorno)) == 1


def test_misma_clave_concurrente_crea_una_sola_orden(escenario):
    def crear():
        with Session(escenario.engine) as db:
            actor = db.get(Usuario, escenario.actor_id)
            respuesta = ejecutar(
                db,
                actor.id,
                "crear_orden",
                "clave-paralela-123456",
                escenario.datos,
                lambda: ordenes.crear_orden(db, escenario.datos, actor),
                OrdenSalida,
            )
            return respuesta["id"]

    resultados = simultaneos([crear, crear])
    assert resultados[0] == resultados[1]
    with Session(escenario.engine) as db:
        assert db.scalar(select(func.count()).select_from(OrdenProduccion)) == 1
