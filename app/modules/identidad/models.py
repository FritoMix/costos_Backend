"""
Modulo Identidad - tablas: roles, usuarios.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class RolCodigo:
    """
    Codigos fijos de los cuatro roles. Se usan para verificar permisos, en
    vez de escribir el texto "admin" suelto por todo el codigo.
    """

    ADMIN = "admin"
    SUPERVISOR = "supervisor"
    OPERARIO_HORNO = "operario_horno"
    OPERARIO_SABORIZADO = "operario_saborizado"

    TODOS = (ADMIN, SUPERVISOR, OPERARIO_HORNO, OPERARIO_SABORIZADO)


class Rol(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    nombre: Mapped[str] = mapped_column(String(100))

    usuarios: Mapped[list["Usuario"]] = relationship(back_populates="rol")

    def __repr__(self) -> str:
        return f"<Rol {self.codigo}>"


class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre_completo: Mapped[str] = mapped_column(String(150))
    nombre_usuario: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))

    rol_id: Mapped[int] = mapped_column(ForeignKey("roles.id"))
    rol: Mapped["Rol"] = relationship(back_populates="usuarios", lazy="joined")

    activo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    fecha_creacion: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Borrado suave: un usuario eliminado no aparece en listas ni puede
    # entrar, pero sus ordenes y registros historicos siguen firmados por
    # el, para no perder la trazabilidad.
    eliminado: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    eliminado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    fecha_eliminacion: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    @property
    def puede_entrar(self) -> bool:
        return self.activo and not self.eliminado

    def __repr__(self) -> str:
        return f"<Usuario {self.nombre_usuario}>"
