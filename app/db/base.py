"""
Clase base de la que heredan todos los modelos de SQLAlchemy.

IMPORTANTE: en esta version el esquema de la base de datos lo manda
Flyway (backend/migraciones/*.sql). Estos modelos solo describen las
tablas para poder leerlas y escribirlas desde Python: no se usa
`Base.metadata.create_all()` ni autogeneracion de migraciones. Si una
tabla cambia, primero se escribe la migracion SQL y despues se ajusta el
modelo.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
