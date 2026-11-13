"""Historial de cambios de producción, confirmado en la misma transacción."""

import json
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, func, inspect
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.db.base import Base


class EventoOperacion(Base):
    __tablename__ = "auditoria_operaciones"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    recurso: Mapped[str] = mapped_column(String(40))
    recurso_id: Mapped[int]
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    accion: Mapped[str] = mapped_column(String(50))
    antes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    despues: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    fecha: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def registrar(
    db: Session,
    recurso: str,
    recurso_id: int,
    accion: str,
    usuario_id: int | None = None,
    antes=None,
    despues=None,
) -> None:
    def serializable(valor):
        return json.loads(json.dumps(valor, default=str)) if valor is not None else None

    db.add(
        EventoOperacion(
            recurso=recurso,
            recurso_id=recurso_id,
            accion=accion,
            usuario_id=usuario_id,
            antes=serializable(antes),
            despues=serializable(despues),
        )
    )


def estado_orden(orden) -> dict:
    return {
        campo: getattr(orden, campo)
        for campo in (
            "estado",
            "horno_id",
            "producto_id",
            "categoria_id",
            "cantidad_programada",
            "horas_produccion",
            "hora_inicio",
            "hora_fin",
            "eliminado",
        )
    }


def snapshot(entidad) -> dict:
    def columnas(objeto):
        return {columna.key: getattr(objeto, columna.key) for columna in inspect(type(objeto)).column_attrs}

    datos = columnas(entidad)
    relaciones = inspect(type(entidad)).relationships
    for nombre in ("canastillas", "desperdicios", "referencias"):
        if nombre in relaciones:
            datos[nombre] = [columnas(fila) for fila in getattr(entidad, nombre)]
    return datos
