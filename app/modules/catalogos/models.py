"""
Modulo Catalogos - tablas que el administrador mantiene:
categorias, turnos, hornos (con su calibracion de tanque), sabores,
productos, tipos de desperdicio, configuracion de planta y las muestras
de densidad de aceite.
"""

import math
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Table,
    Time,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# Tabla puente: que categorias puede producir cada horno. Lo configura el
# administrador; esta regla no esta escrita a mano en el codigo.
horno_categoria = Table(
    "horno_categoria",
    Base.metadata,
    Column("horno_id", ForeignKey("hornos.id"), primary_key=True),
    Column("categoria_id", ForeignKey("categorias_producto.id"), primary_key=True),
)


class CategoriaProducto(Base):
    __tablename__ = "categorias_producto"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(100), unique=True)
    activo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    productos: Mapped[list["Producto"]] = relationship(back_populates="categoria")

    def __repr__(self) -> str:
        return f"<CategoriaProducto {self.nombre}>"


class Turno(Base):
    __tablename__ = "turnos"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(50), unique=True)
    hora_inicio: Mapped[time] = mapped_column(Time)
    hora_fin: Mapped[time] = mapped_column(Time)
    cruza_medianoche: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    activo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    def contiene(self, hora: time) -> bool:
        """Si esta hora del reloj cae dentro del turno (contando la medianoche)."""
        if self.cruza_medianoche:
            return hora >= self.hora_inicio or hora < self.hora_fin
        return self.hora_inicio <= hora < self.hora_fin

    def __repr__(self) -> str:
        return f"<Turno {self.nombre}>"


class Horno(Base):
    __tablename__ = "hornos"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(50), unique=True)
    activo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    # Informativo, para trazabilidad: que aceite usa este horno (ej: "LS").
    tipo_aceite: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Si el horno esta habilitado para ordenes de exportacion. Cuando una
    # orden es de exportacion, el horno elegido debe tener esto en True,
    # sin importar la categoria.
    apto_exportacion: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    # Calibracion del tanque de aceite (convierte cm -> litros):
    #   1) tanque_diametro_cm: la app estima litros/cm asumiendo cilindro.
    #   2) litros_por_cm_manual: calibracion real medida a mano; si esta,
    #      SIEMPRE tiene prioridad sobre el diametro.
    # Si no hay ninguna, no se calculan litros ni kg de aceite.
    tanque_diametro_cm: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    litros_por_cm_manual: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)

    categorias: Mapped[list["CategoriaProducto"]] = relationship(secondary=horno_categoria)

    @property
    def litros_por_cm(self) -> Decimal | None:
        """
        Cuantos litros representa 1 cm de altura en este tanque.

        Con el diametro se asume un cilindro perfecto: area del circulo
        (pi * radio^2) convertida de cm3 a litros (1 litro = 1000 cm3).

        El tanque real tiene una base conica debajo del cilindro, pero se
        confirmo con la planta que el nivel medido en operacion siempre se
        mantiene dentro de la parte recta (el cono es solo para drenaje),
        asi que la formula simple es valida en el rango real de medicion.
        """
        if self.litros_por_cm_manual is not None:
            return self.litros_por_cm_manual
        if self.tanque_diametro_cm is None:
            return None
        radio_cm = float(self.tanque_diametro_cm) / 2
        litros = (math.pi * radio_cm**2) / 1000
        return Decimal(str(round(litros, 4)))

    def __repr__(self) -> str:
        return f"<Horno {self.nombre}>"


class Sabor(Base):
    __tablename__ = "sabores"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(100), unique=True)
    activo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    def __repr__(self) -> str:
        return f"<Sabor {self.nombre}>"


class Producto(Base):
    __tablename__ = "productos"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre_comercial: Mapped[str] = mapped_column(String(150), unique=True)

    categoria_id: Mapped[int] = mapped_column(ForeignKey("categorias_producto.id"))
    categoria: Mapped["CategoriaProducto"] = relationship(back_populates="productos", lazy="selectin")

    activo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    # Peso ESTIMADO de una canastilla de esta referencia (ej: cabello de
    # angel pesa mas que 6 kg). Solo sirve para que el supervisor convierta
    # "canastillas pedidas" a kg al programar; el peso real de cada
    # canastilla se sigue pesando en saborizado. Si esta vacio se usa el
    # valor general de Configuracion.
    peso_estandar_canastilla_kg: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 2), nullable=True
    )

    def __repr__(self) -> str:
        return f"<Producto {self.nombre_comercial}>"


class TipoDesperdicio(Base):
    __tablename__ = "tipos_desperdicio"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(100), unique=True)
    activo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    def __repr__(self) -> str:
        return f"<TipoDesperdicio {self.nombre}>"


class ConfiguracionPlanta(Base):
    """
    Tabla de una sola fila (siempre id = 1) con los valores generales de
    la planta. Los registros de horno copian el peso del bulto vigente al
    momento de crearse: si aqui cambia despues, el historico no se altera.
    """

    __tablename__ = "configuracion_planta"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)

    # None hasta que el administrador lo configure: no se inventa un valor.
    peso_estandar_bulto_kg: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    peso_estandar_canastilla_kg: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 2), nullable=True
    )

    def __repr__(self) -> str:
        return f"<ConfiguracionPlanta bulto={self.peso_estandar_bulto_kg}>"


class MuestraDensidadAceite(Base):
    """
    La densidad del aceite no es fija: se obtiene por muestreos periodicos
    y es distinta por horno (cada uno usa un aceite diferente). Cada
    registro de horno usa la muestra mas reciente disponible para ese
    horno en esa fecha.
    """

    __tablename__ = "muestras_densidad_aceite"

    id: Mapped[int] = mapped_column(primary_key=True)

    horno_id: Mapped[int] = mapped_column(ForeignKey("hornos.id"))
    horno: Mapped["Horno"] = relationship(lazy="selectin")

    fecha: Mapped[date] = mapped_column(Date)
    densidad_kg_por_litro: Mapped[Decimal] = mapped_column(Numeric(6, 4))

    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    fecha_creacion: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<MuestraDensidadAceite horno={self.horno_id} {self.fecha}>"
