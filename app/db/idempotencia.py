"""Reintentos de creaciones: resultado y efectos se confirman juntos."""

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel
from sqlalchemy import DateTime, ForeignKey, String, delete, func, select
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.errores import ConflictoDeDatos
from app.db.base import Base
from app.db.transacciones import atomica


class OperacionIdempotente(Base):
    __tablename__ = "operaciones_idempotentes"
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), primary_key=True)
    ambito: Mapped[str] = mapped_column(String(200), primary_key=True)
    clave: Mapped[str] = mapped_column(String(128), primary_key=True)
    solicitud_hash: Mapped[str] = mapped_column(String(64))
    respuesta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    creada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


@atomica
def ejecutar(
    db: Session,
    usuario_id: int,
    ambito: str,
    clave: str | None,
    datos: BaseModel,
    accion: Callable,
    salida: type[BaseModel],
) -> dict:
    if not clave:
        return salida.model_validate(accion()).model_dump(mode="json")
    cuerpo = json.dumps(datos.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    huella = hashlib.sha256(cuerpo.encode()).hexdigest()
    # Ventana de reintento: 24 h; fuera de ella la misma clave inicia otra operación.
    db.execute(
        delete(OperacionIdempotente).where(
            OperacionIdempotente.creada_en < datetime.now(UTC) - timedelta(hours=24)
        )
    )
    db.execute(
        insert(OperacionIdempotente)
        .values(
            usuario_id=usuario_id,
            ambito=ambito,
            clave=clave,
            solicitud_hash=huella,
        )
        .on_conflict_do_nothing()
    )
    registro = db.scalar(
        select(OperacionIdempotente)
        .where(
            OperacionIdempotente.usuario_id == usuario_id,
            OperacionIdempotente.ambito == ambito,
            OperacionIdempotente.clave == clave,
        )
        .with_for_update()
    )
    if registro.solicitud_hash != huella:
        raise ConflictoDeDatos("La clave de operación ya se utilizó con datos distintos.")
    if registro.respuesta is not None:
        return registro.respuesta
    registro.respuesta = salida.model_validate(accion()).model_dump(mode="json")
    db.flush()
    return registro.respuesta
