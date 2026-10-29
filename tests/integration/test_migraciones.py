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
