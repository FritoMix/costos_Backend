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
    SmallInteger,
    String,
    Table,
    Time,
    func,
    select,
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


class Linea(Base):
    """
    Linea de produccion (V21): papa, platano, pellet, extruido, trocillo y
    nachos. Cada horno pertenece a una; la linea de la orden es la de su
    horno. Solo la papa usa Bodega.
    """

    __tablename__ = "lineas"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(20), unique=True)
    nombre: Mapped[str] = mapped_column(String(60))
    # Como entra la materia prima al horno: 'bultos' (papa) o 'kg'.
    unidad_materia_prima: Mapped[str] = mapped_column(String(10), default="kg")
    nombre_materia_prima: Mapped[str] = mapped_column(String(40))
    usa_bodega: Mapped[bool] = mapped_column(Boolean, default=False)
    pide_variedad: Mapped[bool] = mapped_column(Boolean, default=False)
    # Unidades en que el supervisor pide la orden, separadas por coma.
    unidades_orden_texto: Mapped[str] = mapped_column("unidades_orden", String(80), default="kg")
    orden: Mapped[int] = mapped_column(SmallInteger, default=0)
    activo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    @property
    def unidades_orden(self) -> list[str]:
        return [u.strip() for u in self.unidades_orden_texto.split(",") if u.strip()]

    @property
    def en_bultos(self) -> bool:
        return self.unidad_materia_prima == "bultos"

    @property
    def permite_canastillas(self) -> bool:
        return "canastillas" in self.unidades_orden

    def __repr__(self) -> str:
        return f"<Linea {self.codigo}>"


class Variedad(Base):
    """Variedad de la materia prima de una linea: Harton, FHIA 21 (V21)."""

    __tablename__ = "variedades"

    id: Mapped[int] = mapped_column(primary_key=True)
    linea_id: Mapped[int] = mapped_column(ForeignKey("lineas.id"))
    linea: Mapped["Linea"] = relationship(lazy="joined")
    nombre: Mapped[str] = mapped_column(String(80))
    activo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    def __repr__(self) -> str:
        return f"<Variedad {self.nombre}>"


class TipoAceite(Base):
    """Aceite de fritura con su densidad fija (kg/L) y su proveedor (V18)."""

    __tablename__ = "tipos_aceite"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(100), unique=True)
    densidad_kg_por_litro: Mapped[Decimal] = mapped_column(Numeric(6, 4))
    proveedor: Mapped[str | None] = mapped_column(String(150), nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    def __repr__(self) -> str:
        return f"<TipoAceite {self.nombre}>"


class Horno(Base):
    __tablename__ = "hornos"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(50), unique=True)
    activo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    # Informativo, para trazabilidad: que aceite usa este horno (ej: "LS").
    tipo_aceite: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Aceite del catalogo (V18). Su densidad solo se usa si el horno no
    # tiene muestras de densidad.
    aceite_id: Mapped[int | None] = mapped_column(ForeignKey("tipos_aceite.id"), nullable=True)

    # Linea del horno (V21). De aqui sale la linea de la orden.
    # Sin linea explicita, el horno queda de papa (como todos los existentes).
    linea_id: Mapped[int] = mapped_column(
        ForeignKey("lineas.id"),
        default=select(Linea.id).where(Linea.codigo == "papa").scalar_subquery(),
    )
    linea: Mapped["Linea"] = relationship(lazy="joined")
    aceite: Mapped["TipoAceite | None"] = relationship(lazy="selectin")

    # Cuantos bultos de papa cruda puede procesar en una hora. Se usa para
    # proyectar la distribucion entre referencias; NULL en hornos historicos
    # que todavia no tienen el dato confirmado por la planta.
    capacidad_bultos_hora: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 2), nullable=True
    )

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

    # Mercado del producto (V19): nacional, exportacion o ambos. Al crear la
    # orden solo se ofrecen los del destino elegido (o los de "ambos").
    destino: Mapped[str] = mapped_column(String(20), default="ambos", server_default="ambos")

    # Rango de % de sabor esperado (V21). Es un control, no un calculo.
    sabor_minimo_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    sabor_maximo_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)

    def sirve_para(self, destino_orden: str) -> bool:
        return self.destino in ("ambos", destino_orden)

    def fuera_de_rango_sabor(self, porcentaje: Decimal | None) -> str | None:
        """Texto del aviso si el % de sabor real queda fuera del rango."""
        if porcentaje is None:
            return None
        if self.sabor_minimo_pct is not None and porcentaje < self.sabor_minimo_pct:
            return (
                f"Sabor bajo: {porcentaje.normalize():f} % y el mínimo de "
                f"{self.nombre_comercial} es {self.sabor_minimo_pct.normalize():f} %"
            )
        if self.sabor_maximo_pct is not None and porcentaje > self.sabor_maximo_pct:
            return (
                f"Sabor alto: {porcentaje.normalize():f} % y el máximo de "
                f"{self.nombre_comercial} es {self.sabor_maximo_pct.normalize():f} %"
            )
        return None

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
