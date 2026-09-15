"""
Conexion a PostgreSQL.

- engine: el canal de comunicacion con la base de datos.
- SessionLocal: una sesion de trabajo por cada peticion HTTP.
- get_db(): dependencia de FastAPI que entrega esa sesion y la cierra al
  terminar, pase lo que pase.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,  # descarta conexiones muertas antes de usarlas
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_recycle=settings.db_pool_recycle_segundos,  # renueva conexiones viejas
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """Entrega una sesion de base de datos y la cierra al terminar."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
