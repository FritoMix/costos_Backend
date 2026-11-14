from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.modules.produccion.schemas import FormulaPapaGuardar, FormulaReferenciaGuardar
from app.modules.produccion.servicios import formulas_papa, ordenes

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'limpiar_operaciones.sql'


def cuerpo():
    # La prueba ya tiene una transacción externa, que nunca se confirma.
    return '\n'.join(linea for linea in SCRIPT.read_text().splitlines()
                     if linea.strip() not in {'BEGIN;', 'COMMIT;'})


def test_limpieza_conserva_usuarios_catalogos_y_formulas_y_permite_nueva_orden(
    db, datos_base, orden_guardar,
):
    plantilla = formulas_papa.crear(db, FormulaPapaGuardar(
        nombre='Plantilla que debe conservarse', producto_id=datos_base.producto.id,
        referencias=[FormulaReferenciaGuardar(
            referencia_papa_id=datos_base.referencia_papa.id, bultos_por_tanda=10,
        )],
    ), datos_base.admin)
    orden = ordenes.crear_orden(db, orden_guardar(), datos_base.supervisor)
    numero_anterior = orden.numero_orden
    tablas = ('usuarios', 'roles', 'productos', 'hornos', 'referencias_papa',
              'formulas_papa', 'formula_papa_referencias', 'secuencia_ordenes')
    def contenido(tabla):
        return db.execute(text(f'SELECT to_jsonb(fila) FROM public.{tabla} fila')).scalars().all()
    antes = {tabla: contenido(tabla) for tabla in tablas}
    db.connection().exec_driver_sql(cuerpo())
    for tabla in tablas:
        assert contenido(tabla) == antes[tabla]
    for tabla in ('ordenes_produccion', 'orden_referencias', 'registro_horno',
                  'registro_saborizado', 'canastillas', 'desperdicios',
                  'notificaciones', 'operaciones_idempotentes'):
        assert db.scalar(text(f'SELECT count(*) FROM public.{tabla}')) == 0
    assert db.scalar(text("SELECT count(*) FROM auditoria_operaciones "
                          "WHERE accion='limpieza_operativa'")) == 1
    assert db.scalar(text('SELECT nombre FROM formulas_papa WHERE id=:id'),
                     {'id': plantilla.id}) == 'Plantilla que debe conservarse'
    nueva = ordenes.crear_orden(db, orden_guardar(), datos_base.supervisor)
    assert nueva.numero_orden != numero_anterior


def test_fallo_durante_limpieza_revierte_todo(db, datos_base, orden_guardar):
    orden = ordenes.crear_orden(db, orden_guardar(), datos_base.supervisor)
    orden_id = orden.id
    with pytest.raises(DBAPIError):
        with db.begin_nested():
            db.connection().exec_driver_sql(cuerpo() + '\nSELECT 1/0;')
    assert db.scalar(text('SELECT count(*) FROM ordenes_produccion WHERE id=:id'),
                     {'id': orden_id}) == 1
    assert db.scalar(text("SELECT count(*) FROM auditoria_operaciones "
                          "WHERE accion='limpieza_operativa'")) == 0
