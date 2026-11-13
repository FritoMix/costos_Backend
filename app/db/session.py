"""
Conexion a PostgreSQL.

- engine: el canal de comunicacion con la base de datos.
- SessionLocal: una sesion de trabajo por cada peticion HTTP.
- get_db(): dependencia de FastAPI que entrega esa sesion y la cierra al
  terminar, pase lo que pase.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


def argumentos_conexion() -> dict:
    opciones = str(make_url(settings.database_url).query.get("options", ""))
    opciones += (
        f" -c statement_timeout={settings.db_statement_timeout_ms}"
        f" -c lock_timeout={settings.db_lock_timeout_ms}"
        f" -c idle_in_transaction_session_timeout={settings.db_idle_transaction_timeout_ms}"
    )
    return {"connect_timeout": settings.db_connect_timeout_segundos, "options": opciones.strip()}


engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,  # descarta conexiones muertas antes de usarlas
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_recycle=settings.db_pool_recycle_segundos,  # renueva conexiones viejas
    pool_timeout=settings.db_pool_timeout_segundos,
    connect_args=argumentos_conexion(),
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """Entrega una sesion de base de datos y la cierra al terminar."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
