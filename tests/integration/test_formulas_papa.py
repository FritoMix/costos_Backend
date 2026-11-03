"""
Pruebas de integración de las fórmulas reutilizables por producto.

Cubren el ciclo completo: Bodega crea y activa una fórmula, el supervisor
crea la orden y la mezcla activa se copia; activaciones, reemplazos y
bloqueos; y los casos en los que la orden queda pendiente de Bodega.
"""

from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.errores import ErrorDeValidacion, RecursoNoEncontrado
from app.modules.bodega import service as servicio_bodega
from app.modules.bodega.models import ReferenciaPapa
from app.modules.catalogos.models import Producto
from app.modules.notificaciones.models import Notificacion, TipoNotificacion
from app.modules.produccion.schemas import (
    FormulaPapaGuardar,
    FormulaPapaReferenciaGuardar,
)
from app.modules.produccion.servicios import formulas_papa as servicio_plantillas
from app.modules.produccion.servicios import ordenes as servicio_ordenes


def _plantilla(
    datos_base,
    *filas: tuple[ReferenciaPapa, int],
    producto_id: int | None = None,
    nombre: str = "Fórmula de prueba",
    notas: str | None = None,
) -> FormulaPapaGuardar:
    if not filas:
        filas = ((datos_base.referencia_papa, 10),)
    return FormulaPapaGuardar(
        nombre=nombre,
        producto_id=producto_id or datos_base.producto.id,
        referencias=[
            FormulaPapaReferenciaGuardar(
                referencia_papa_id=referencia.id, bultos_por_tanda=bultos
            )
            for referencia, bultos in filas
        ],
        notas=notas,
    )


def _contar_avisos(db, orden_id: int, tipo: str) -> int:
    return db.scalar(
        select(func.count())
        .select_from(Notificacion)
        .where(Notificacion.orden_id == orden_id, Notificacion.tipo == tipo)
    ) or 0


def test_crear_activar_y_listar_plantillas(db, datos_base):
    creada = servicio_plantillas.crear(
        db, _plantilla(datos_base, notas="Mezcla estable"), datos_base.bodeguero
    )

    assert creada.activa is False
    assert creada.producto.id == datos_base.producto.id
    assert creada.total_bultos_por_tanda == 10
    assert creada.total_kg_crudos == Decimal("500.00")
    assert creada.total_kg_fritos_estimados == Decimal("125.00")
    assert creada.notas == "Mezcla estable"
    assert creada.creado_por.id == datos_base.bodeguero.id
    assert len(creada.referencias) == 1
    fila = creada.referencias[0]
    assert fila.porcentaje_produccion_pct == Decimal("100.0000")
    assert fila.kg_crudos_por_tanda == Decimal("500.00")
    assert fila.kg_fritos_por_tanda == Decimal("125.00")

    assert servicio_plantillas.listar(db, solo_activas=True) == []

    activada = servicio_plantillas.activar(
        db, servicio_plantillas.obtener(db, creada.id)
    )
    assert activada.activa is True
    activas = servicio_plantillas.listar(db, solo_activas=True)
    assert [formula.id for formula in activas] == [creada.id]


def test_activar_otra_desactiva_la_anterior_del_producto(db, datos_base):
    primera = servicio_plantillas.crear(
        db, _plantilla(datos_base, nombre="Primera"), datos_base.bodeguero
    )
    segunda = servicio_plantillas.crear(
        db, _plantilla(datos_base, nombre="Segunda"), datos_base.bodeguero
    )
    servicio_plantillas.activar(db, servicio_plantillas.obtener(db, primera.id))
    servicio_plantillas.activar(db, servicio_plantillas.obtener(db, segunda.id))

    activas = servicio_plantillas.listar(db, solo_activas=True)
    assert [formula.nombre for formula in activas] == ["Segunda"]
    assert servicio_plantillas.obtener(db, primera.id).activa is False


def test_dos_productos_pueden_tener_su_propia_activa(db, datos_base):
    otro = Producto(
        nombre_comercial="Producto Plátano",
        categoria_id=datos_base.categoria.id,
        activo=True,
        peso_estandar_canastilla_kg=Decimal("6.00"),
    )
    db.add(otro)
    db.flush()

    de_papa = servicio_plantillas.crear(
        db, _plantilla(datos_base, nombre="De papa"), datos_base.bodeguero
    )
    de_platano = servicio_plantillas.crear(
        db,
        _plantilla(datos_base, producto_id=otro.id, nombre="De plátano"),
        datos_base.bodeguero,
    )
    servicio_plantillas.activar(db, servicio_plantillas.obtener(db, de_papa.id))
    servicio_plantillas.activar(db, servicio_plantillas.obtener(db, de_platano.id))

    activas = servicio_plantillas.listar(db, solo_activas=True)
    assert sorted(formula.producto.id for formula in activas) == sorted(
        [datos_base.producto.id, otro.id]
    )


def test_plantilla_rechaza_referencias_invalidas(db, datos_base):
    orden_ref = datos_base.referencia_papa

    with pytest.raises(ErrorDeValidacion, match="repetir"):
        servicio_plantillas.crear(
            db,
            _plantilla(datos_base, (orden_ref, 5), (orden_ref, 5)),
            datos_base.bodeguero,
        )

    orden_ref.activo = False
    db.flush()
    with pytest.raises(ErrorDeValidacion, match="inactiva"):
        servicio_plantillas.crear(
            db, _plantilla(datos_base, (orden_ref, 5)), datos_base.bodeguero
        )

    orden_ref.activo = True
    orden_ref.tipo = None
    db.flush()
    with pytest.raises(ErrorDeValidacion, match="incompleta"):
        servicio_plantillas.crear(
            db, _plantilla(datos_base, (orden_ref, 5)), datos_base.bodeguero
        )


def test_no_se_repite_el_nombre_en_el_mismo_producto(db, datos_base):
    servicio_plantillas.crear(db, _plantilla(datos_base), datos_base.bodeguero)

    with pytest.raises(ErrorDeValidacion, match="Ya existe"):
        servicio_plantillas.crear(db, _plantilla(datos_base), datos_base.bodeguero)


def test_listar_filtra_por_producto_y_valida_los_datos(db, datos_base):
    servicio_plantillas.crear(db, _plantilla(datos_base), datos_base.bodeguero)

    assert len(servicio_plantillas.listar(db, producto_id=datos_base.producto.id)) == 1
    assert servicio_plantillas.listar(db, producto_id=999999) == []

    with pytest.raises(ErrorDeValidacion, match="producto"):
        servicio_plantillas.crear(
            db, _plantilla(datos_base, producto_id=999999), datos_base.bodeguero
        )
    with pytest.raises(ErrorDeValidacion, match="nombre"):
        servicio_plantillas.crear(
            db, _plantilla(datos_base, nombre="   "), datos_base.bodeguero
        )


def test_crear_orden_aplica_la_formula_activa(db, datos_base, orden_guardar):
    plantilla = servicio_plantillas.crear(
        db, _plantilla(datos_base, notas="Directo de Bodega"), datos_base.bodeguero
    )
    servicio_plantillas.activar(db, servicio_plantillas.obtener(db, plantilla.id))

    orden = servicio_ordenes.crear_orden(db, orden_guardar(), datos_base.supervisor)

    assert orden.formula_estado == "lista"
    assert orden.formula_notas == "Directo de Bodega"
    assert orden.formula_papa_id == plantilla.id
    assert len(orden.referencias) == 1
    fila = orden.referencias[0]
    assert fila.bultos_por_tanda == 10
    assert fila.bultos_planificados == 20
    assert fila.kg_crudos_planificados == Decimal("1000.00")
    assert fila.kg_fritos_estimados == Decimal("250.00")

    # Horno y supervisor reciben el aviso de fórmula lista; Bodega no recibe
    # una orden pendiente porque la mezcla ya quedó aplicada.
    assert _contar_avisos(db, orden.id, TipoNotificacion.FORMULA_LISTA) == 2
    assert _contar_avisos(db, orden.id, TipoNotificacion.ORDEN_PARA_BODEGA) == 0

    # La orden puede iniciar de inmediato.
    servicio_ordenes.iniciar_orden(db, orden)
    assert orden.estado == "en_produccion"


def test_crear_orden_sin_activa_pide_a_bodega(db, datos_base, orden_guardar):
    servicio_plantillas.crear(db, _plantilla(datos_base), datos_base.bodeguero)

    orden = servicio_ordenes.crear_orden(db, orden_guardar(), datos_base.supervisor)

    assert orden.referencias == []
    assert orden.formula_estado == "sin_formula"
    assert _contar_avisos(db, orden.id, TipoNotificacion.ORDEN_PARA_BODEGA) == 1
    assert _contar_avisos(db, orden.id, TipoNotificacion.FORMULA_LISTA) == 0


def test_plantilla_que_no_cabe_en_el_horno_deja_la_orden_pendiente(
    db, datos_base, orden_guardar
):
    plantilla = servicio_plantillas.crear(
        db, _plantilla(datos_base, (datos_base.referencia_papa, 60)), datos_base.bodeguero
    )
    servicio_plantillas.activar(db, servicio_plantillas.obtener(db, plantilla.id))

    # El horno admite 50 bultos por hora: la orden nace sin fórmula y Bodega
    # recibe el aviso para ajustarla.
    orden = servicio_ordenes.crear_orden(db, orden_guardar(), datos_base.supervisor)

    assert orden.referencias == []
    assert orden.formula_estado == "sin_formula"
    assert _contar_avisos(db, orden.id, TipoNotificacion.ORDEN_PARA_BODEGA) == 1


def test_plantilla_que_no_alcanza_la_cantidad_deja_la_orden_pendiente(
    db, datos_base, orden_guardar
):
    plantilla = servicio_plantillas.crear(
        db, _plantilla(datos_base, (datos_base.referencia_papa, 1)), datos_base.bodeguero
    )
    servicio_plantillas.activar(db, servicio_plantillas.obtener(db, plantilla.id))

    orden = servicio_ordenes.crear_orden(
        db, orden_guardar(cantidad_kg=Decimal("5000.00")), datos_base.supervisor
    )

    assert orden.referencias == []
    assert _contar_avisos(db, orden.id, TipoNotificacion.ORDEN_PARA_BODEGA) == 1


def test_desactivar_la_plantilla_deja_de_aplicarse(db, datos_base, orden_guardar):
    plantilla = servicio_plantillas.crear(db, _plantilla(datos_base), datos_base.bodeguero)
    servicio_plantillas.activar(db, servicio_plantillas.obtener(db, plantilla.id))
    servicio_plantillas.desactivar(db, servicio_plantillas.obtener(db, plantilla.id))

    orden = servicio_ordenes.crear_orden(db, orden_guardar(), datos_base.supervisor)

    assert orden.referencias == []
    assert servicio_plantillas.activa_para_orden(
        db, producto_id=datos_base.producto.id
    ) is None


def test_eliminar_activa_se_bloquea_y_la_inactiva_se_borra(db, datos_base):
    activa = servicio_plantillas.crear(db, _plantilla(datos_base), datos_base.bodeguero)
    inactiva = servicio_plantillas.crear(
        db, _plantilla(datos_base, nombre="Otra"), datos_base.bodeguero
    )
    servicio_plantillas.activar(db, servicio_plantillas.obtener(db, activa.id))

    with pytest.raises(ErrorDeValidacion, match="activa"):
        servicio_plantillas.eliminar(
            db, servicio_plantillas.obtener(db, activa.id)
        )

    servicio_plantillas.eliminar(
        db, servicio_plantillas.obtener(db, inactiva.id)
    )
    with pytest.raises(RecursoNoEncontrado):
        servicio_plantillas.obtener(db, inactiva.id)


def test_editar_la_plantilla_cambia_las_ordenes_nuevas_no_las_anteriores(
    db, datos_base, orden_guardar
):
    plantilla = servicio_plantillas.crear(db, _plantilla(datos_base), datos_base.bodeguero)
    servicio_plantillas.activar(db, servicio_plantillas.obtener(db, plantilla.id))
    primera = servicio_ordenes.crear_orden(db, orden_guardar(), datos_base.supervisor)

    servicio_plantillas.actualizar(
        db,
        servicio_plantillas.obtener(db, plantilla.id),
        _plantilla(datos_base, (datos_base.referencia_papa, 5)),
    )
    segunda = servicio_ordenes.crear_orden(
        db, orden_guardar(cantidad_kg=Decimal("60.00")), datos_base.supervisor
    )

    assert primera.referencias[0].bultos_por_tanda == 10
    assert segunda.referencias[0].bultos_por_tanda == 5


def test_no_se_elimina_una_referencia_usada_en_una_plantilla(db, datos_base):
    servicio_plantillas.crear(db, _plantilla(datos_base), datos_base.bodeguero)

    with pytest.raises(ErrorDeValidacion, match="desactivarla"):
        servicio_bodega.eliminar(db, datos_base.referencia_papa.id)


def test_la_activa_para_orden_trae_los_totales_de_las_horas(db, datos_base):
    plantilla = servicio_plantillas.crear(db, _plantilla(datos_base), datos_base.bodeguero)
    servicio_plantillas.activar(db, servicio_plantillas.obtener(db, plantilla.id))

    activa = servicio_plantillas.activa_para_orden(
        db, producto_id=datos_base.producto.id, horas=3
    )

    assert activa is not None
    assert activa.horas == 3
    assert activa.total_bultos_planificados == 30
    assert activa.total_kg_crudos_planificados == Decimal("1500.00")
    assert activa.total_kg_fritos_planificados == Decimal("375.00")
