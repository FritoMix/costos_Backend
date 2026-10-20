"""
Fixtures compartidas por las pruebas.

Las pruebas unitarias no necesitan base de datos y corren siempre.
Las de integracion se activan definiendo TEST_DATABASE_URL (ver
tests/integration/) y se omiten si la variable no existe.

Por seguridad, la URL debe apuntar a una base cuyo nombre termine en
"_test": el fixture borra y recrea el schema public antes de empezar.
"""

import os
from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from app.db.migraciones import aplicar_migraciones_pendientes

CARPETA_MIGRACIONES = Path(__file__).resolve().parents[1] / "migraciones"


def _url_de_pruebas() -> str:
    url = os.getenv("TEST_DATABASE_URL", "").strip()
    if not url:
        pytest.skip(
            "TEST_DATABASE_URL no está definida: se omiten las pruebas de integración. "
            "Ejemplo: postgresql+psycopg://test:test@localhost:5432/datacontrol_test"
        )

    # Los proveedores suelen entregar "postgresql://" sin driver; SQLAlchemy
    # intentaria usar psycopg2, que no esta instalado.
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]

    nombre_base = url.rsplit("/", 1)[-1].split("?", 1)[0]
    if not nombre_base.endswith("_test"):
        pytest.exit(
            "Por seguridad, TEST_DATABASE_URL debe apuntar a una base terminada en "
            f"'_test' (se recibió '{nombre_base}').",
            returncode=2,
        )
    return url


@pytest.fixture(scope="session")
def engine_integracion() -> Generator[Engine, None, None]:
    """Motor apuntando a una base de pruebas limpia y migrada."""
    engine = create_engine(_url_de_pruebas(), pool_pre_ping=True)

    with engine.begin() as conexion:
        conexion.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conexion.execute(text("CREATE SCHEMA public"))

    aplicar_migraciones_pendientes(engine, CARPETA_MIGRACIONES)
    yield engine
    engine.dispose()


@pytest.fixture
def db(engine_integracion: Engine) -> Generator[Session, None, None]:
    """
    Sesion dentro de una transaccion externa que se revierte al final.

    join_transaction_mode="create_savepoint" permite que los db.commit() del
    codigo de negocio no confirmen de verdad: solo liberan un savepoint.
    Asi cada prueba queda aislada y no hay que limpiar tablas a mano.
    """
    conexion = engine_integracion.connect()
    transaccion = conexion.begin()
    sesion = Session(bind=conexion, join_transaction_mode="create_savepoint")
    try:
        yield sesion
    finally:
        sesion.close()
        transaccion.rollback()
        conexion.close()
