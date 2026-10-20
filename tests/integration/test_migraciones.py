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
    assert roles == {"admin", "supervisor", "operario_horno", "operario_saborizado"}
    assert hornos == {"Horno 1", "Horno 2"}


def test_migraciones_son_idempotentes(engine_integracion):
    aplicadas = aplicar_migraciones_pendientes(engine_integracion, CARPETA_MIGRACIONES)

    assert aplicadas == 0
