"""
Pruebas del guardado de avisos.

El indice unico de PostgreSQL evita duplicar el mismo aviso para la misma
persona, orden y tipo. Lo importante es que un duplicado no haga perder los
avisos de las demas personas que se estaban creando en el mismo lote.
"""

from datetime import UTC, datetime
from types import SimpleNamespace

from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint, create_engine
from sqlalchemy.orm import Session, declarative_base

from app.modules.notificaciones import service as servicio

Base = declarative_base()


class AvisoPrueba(Base):
    __tablename__ = "avisos_prueba"

    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, nullable=False)
    tipo = Column(String(40), nullable=False)
    titulo = Column(String(150), nullable=False)
    mensaje = Column(String, nullable=False)
    orden_id = Column(Integer, nullable=True)
    fecha_programada = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (UniqueConstraint("usuario_id", "orden_id", "tipo"),)


def test_un_duplicado_no_hace_perder_los_avisos_anteriores(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        # La persona 2 ya tenia este aviso (por ejemplo, de un reinicio).
        db.add(
            AvisoPrueba(
                usuario_id=2,
                tipo=servicio.TipoNotificacion.ORDEN_CREADA,
                titulo="previo",
                mensaje="previo",
                orden_id=10,
                fecha_programada=datetime.now(UTC),
            )
        )
        db.commit()

        # Se usa un modelo equivalente sobre SQLite para no depender de
        # PostgreSQL en una prueba unitaria.
        monkeypatch.setattr(servicio, "Notificacion", AvisoPrueba)

        creados = servicio._crear_para(
            db,
            usuarios=[SimpleNamespace(id=1), SimpleNamespace(id=2), SimpleNamespace(id=3)],
            tipo=servicio.TipoNotificacion.ORDEN_CREADA,
            titulo="Nueva orden",
            mensaje="Hay una orden nueva",
            orden_id=10,
        )
        db.commit()

        # La persona 2 choca con el indice unico; las personas 1 y 3 reciben
        # su aviso y no se pierden por el conflicto.
        assert creados == 2
        guardados = db.query(AvisoPrueba).all()
        assert len(guardados) == 3
        assert {aviso.usuario_id for aviso in guardados} == {1, 2, 3}
