"""
Verifica que las migraciones dejen un esquema completo y que puedan
repetirse sin efectos secundarios (idempotencia).
"""

from pathlib import Path

from sqlalchemy import text

from app.db.migraciones import aplicar_migraciones_pendientes

CARPETA_MIGRACIONES = Path(__file__).resolve().parents[2] / "migraciones"

TABLAS_ESPERADAS = {
    "roles",
    "usuarios",
    "categorias_producto",
    "turnos",
    "hornos",
    "horno_categoria",
    "sabores",
    "productos",
    "tipos_desperdicio",
    "configuracion_planta",
    "muestras_densidad_aceite",
    "secuencia_ordenes",
    "ordenes_produccion",
    "registro_horno",
    "desperdicios",
    "registro_saborizado",
    "canastillas",
    "notificaciones",
    "referencias_papa",
    "orden_referencias",
    "registro_horno_referencias",
    "formulas_papa",
    "formula_papa_referencias",
}


def test_esquema_y_datos_iniciales(engine_integracion):
    with engine_integracion.connect() as conexion:
        tablas = set(
            conexion.scalars(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
        )
        roles = set(conexion.scalars(text("SELECT codigo FROM roles")))
        hornos = set(conexion.scalars(text("SELECT nombre FROM hornos")))

    assert TABLAS_ESPERADAS <= tablas
    assert roles == {
        "admin",
        "supervisor",
        "operario_horno",
        "operario_saborizado",
        "bodeguero",
    }
    assert hornos == {"Horno 1", "Horno 2"}


def test_migraciones_son_idempotentes(engine_integracion):
    aplicadas = aplicar_migraciones_pendientes(engine_integracion, CARPETA_MIGRACIONES)

    assert aplicadas == 0


def test_columnas_de_formula_y_tipos_de_aviso(engine_integracion):
    with engine_integracion.connect() as conexion:
        columnas = set(
            conexion.scalars(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'ordenes_produccion'"
                )
            )
        )
        permitidos = conexion.scalar(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'ck_notificacion_tipo_valido'"
            )
        )
        referencia_nullable = conexion.scalar(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name = 'registro_horno' "
                "AND column_name = 'referencia_papa_id'"
            )
        )

    assert {
        "formula_obligatoria",
        "formula_notas",
        "formula_actualizada_por_id",
        "formula_fecha_actualizacion",
    } <= columnas
    assert "orden_para_bodega" in permitidos
    assert "formula_lista" in permitidos
    assert "orden_creada" in permitidos
    assert referencia_nullable == "YES"


def test_rendimiento_y_kg_fritos_opcionales_en_la_formula(engine_integracion):
    with engine_integracion.connect() as conexion:
        nullable = dict(
            conexion.execute(
                text(
                    "SELECT column_name, is_nullable FROM information_schema.columns "
                    "WHERE table_name = 'orden_referencias' AND column_name IN "
                    "('rendimiento_fritura_pct', 'kg_fritos_por_tanda', 'kg_fritos_estimados')"
                )
            ).all()
        )

    # Bodega dejo de capturar el rendimiento: las formulas nuevas guardan
    # NULL y los kg fritos se estiman solo si el rendimiento existe.
    assert nullable == {
        "rendimiento_fritura_pct": "YES",
        "kg_fritos_por_tanda": "YES",
        "kg_fritos_estimados": "YES",
    }


def test_una_sola_formula_activa_por_producto(engine_integracion):
    with engine_integracion.connect() as conexion:
        definicion = conexion.scalar(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE indexname = 'ux_formula_papa_activa_por_producto'"
            )
        )
        columna = conexion.scalar(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'ordenes_produccion' "
                "AND column_name = 'formula_papa_id'"
            )
        )

    assert definicion is not None
    assert "UNIQUE" in definicion
    assert "WHERE activa" in definicion
    assert columna == "formula_papa_id"
