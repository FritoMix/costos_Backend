"""
Modulo Produccion - tablas: ordenes de produccion, su consecutivo diario,
registro de horno (con desperdicios) y registro de saborizado (con las
canastillas pesadas una por una).
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.modules.catalogos.models import (  # noqa: F401  (necesarios para las relaciones)
    CategoriaProducto,
    Horno,
    Producto,
    Sabor,
    TipoDesperdicio,
    Turno,
)
from app.modules.identidad.models import Usuario  # noqa: F401


class EstadoOrden:
    PENDIENTE = "pendiente"
    EN_PRODUCCION = "en_produccion"
    FINALIZADA = "finalizada"
    CANCELADA = "cancelada"

    ACTIVOS = (PENDIENTE, EN_PRODUCCION)


ESTADO_ETIQUETAS = {
    EstadoOrden.PENDIENTE: "Pendiente",
    EstadoOrden.EN_PRODUCCION: "En producción",
    EstadoOrden.FINALIZADA: "Finalizada",
    EstadoOrden.CANCELADA: "Cancelada",
}


class DestinoOrden:
    NACIONAL = "nacional"
    EXPORTACION = "exportacion"


DESTINO_ETIQUETAS = {
    DestinoOrden.NACIONAL: "Nacional",
    DestinoOrden.EXPORTACION: "Exportación",
}


class UnidadSolicitada:
    KG = "kg"
    CANASTILLAS = "canastillas"


class SecuenciaOrden(Base):
    """
    Ultimo consecutivo usado por fecha, para numerar las ordenes como
    OP-20260826-0001 reiniciando en 1 cada dia.
    """

    __tablename__ = "secuencia_ordenes"

    fecha: Mapped[date] = mapped_column(Date, primary_key=True)
    ultimo_numero: Mapped[int] = mapped_column(default=0, server_default="0")


class OrdenProduccion(Base):
    __tablename__ = "ordenes_produccion"
    __table_args__ = (
        CheckConstraint(
            "estado IN ('pendiente', 'en_produccion', 'finalizada', 'cancelada')",
            name="ck_orden_estado_valido",
        ),
        CheckConstraint("destino IN ('nacional', 'exportacion')", name="ck_orden_destino_valido"),
        CheckConstraint(
            "unidad_solicitada IN ('kg', 'canastillas')",
            name="ck_orden_unidad_solicitada_valida",
        ),
        # Un mismo horno NUNCA puede tener dos ordenes en produccion a la
        # vez. El indice unico parcial lo garantiza en la base de datos.
        Index(
            "ux_un_horno_en_produccion",
            "horno_id",
            unique=True,
            postgresql_where=text("estado = 'en_produccion'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    numero_orden: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    fecha: Mapped[date] = mapped_column(Date)

    supervisor_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    # foreign_keys explicito: eliminado_por_id es una SEGUNDA llave foranea
    # a usuarios en esta misma tabla y SQLAlchemy no puede adivinar cual usar.
    supervisor: Mapped["Usuario"] = relationship(foreign_keys=[supervisor_id], lazy="selectin")

    turno_id: Mapped[int] = mapped_column(ForeignKey("turnos.id"))
    turno: Mapped["Turno"] = relationship(lazy="selectin")

    horno_id: Mapped[int] = mapped_column(ForeignKey("hornos.id"))
    horno: Mapped["Horno"] = relationship(lazy="selectin")

    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id"))
    producto: Mapped["Producto"] = relationship(lazy="selectin")

    categoria_id: Mapped[int] = mapped_column(ForeignKey("categorias_producto.id"))
    categoria: Mapped["CategoriaProducto"] = relationship(lazy="selectin")

    # Siempre en kg: es lo que usa el resto del sistema. Si el pedido llego
    # en canastillas, aqui ya quedo convertido.
    cantidad_programada: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    unidad_solicitada: Mapped[str] = mapped_column(
        String(20), default=UnidadSolicitada.KG, server_default=UnidadSolicitada.KG
    )
    cantidad_canastillas_solicitadas: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )

    # Cuantas horas COMPLETAS se programa mantener la orden en produccion
    # (minimo 1): en la planta no existen medias horas de produccion.
    # Es NULL en las ordenes creadas antes de que existiera este dato.
    horas_produccion: Mapped[int | None] = mapped_column(Integer, nullable=True)

    destino: Mapped[str] = mapped_column(
        String(20), default=DestinoOrden.NACIONAL, server_default=DestinoOrden.NACIONAL
    )
    estado: Mapped[str] = mapped_column(
        String(20), default=EstadoOrden.PENDIENTE, server_default=EstadoOrden.PENDIENTE
    )

    hora_inicio: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hora_fin: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fecha_creacion: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Borrado suave: la orden eliminada desaparece de listas, Analisis y
    # exportaciones, pero sigue en la base de datos por si hay que auditar.
    eliminado: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    eliminado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    fecha_eliminacion: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    @property
    def estado_etiqueta(self) -> str:
        return ESTADO_ETIQUETAS.get(self.estado, self.estado)

    @property
    def destino_etiqueta(self) -> str:
        return DESTINO_ETIQUETAS.get(self.destino, self.destino)

    def __repr__(self) -> str:
        return f"<OrdenProduccion {self.numero_orden}>"


class RegistroHorno(Base):
    """
    Una tanda de fritura: bultos usados, personal, niveles de aceite y,
    opcionalmente, el desperdicio. El usuario, la fecha y la orden quedan
    registrados solos: nunca se le piden al operario.
    """

    __tablename__ = "registro_horno"

    id: Mapped[int] = mapped_column(primary_key=True)

    orden_id: Mapped[int] = mapped_column(ForeignKey("ordenes_produccion.id"))
    orden: Mapped["OrdenProduccion"] = relationship(lazy="selectin")

    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    usuario: Mapped["Usuario"] = relationship(foreign_keys=[usuario_id], lazy="selectin")

    hora_inicio: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    hora_fin: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    cantidad_bultos: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    # Copia del valor de configuracion vigente al crear el registro.
    peso_estandar_bulto_kg: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    kg_crudos_calculados: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    operarios_seleccion: Mapped[int] = mapped_column(SmallInteger)
    operarios_horno: Mapped[int] = mapped_column(SmallInteger)

    nivel_aceite_inicial_cm: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    nivel_aceite_final_cm: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    diferencia_aceite_cm: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    temperatura_aceite_c: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)

    # Conversion cm -> litros -> kg. Quedan en None si el horno todavia no
    # tiene calibracion o densidad: eso no impide guardar el registro.
    litros_por_cm_usado: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    volumen_aceite_litros: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    densidad_aceite_usada: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    kg_aceite_consumido: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)

    observaciones: Mapped[str | None] = mapped_column(Text, nullable=True)
    fecha_creacion: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    eliminado: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    eliminado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    fecha_eliminacion: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    desperdicios: Mapped[list["Desperdicio"]] = relationship(
        back_populates="registro_horno", lazy="selectin", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<RegistroHorno {self.id} orden={self.orden_id}>"


class Desperdicio(Base):
    """
    Desperdicio de una tanda. El tipo es un catalogo (no solo "papa
    quemada") para poder agregar otros mas adelante sin tocar el codigo.
    """

    __tablename__ = "desperdicios"

    id: Mapped[int] = mapped_column(primary_key=True)

    registro_horno_id: Mapped[int] = mapped_column(ForeignKey("registro_horno.id"))
    registro_horno: Mapped["RegistroHorno"] = relationship(back_populates="desperdicios")

    tipo_desperdicio_id: Mapped[int] = mapped_column(ForeignKey("tipos_desperdicio.id"))
    tipo_desperdicio: Mapped["TipoDesperdicio"] = relationship(lazy="selectin")

    cantidad_kg: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    observacion: Mapped[str | None] = mapped_column(Text, nullable=True)


class RegistroSaborizado(Base):
    """
    Una recepcion de saborizado. Una orden puede tener varias, cada una con
    su sabor, su cantidad de sabor y su grupo de canastillas pesadas.
    """

    __tablename__ = "registro_saborizado"

    id: Mapped[int] = mapped_column(primary_key=True)

    orden_id: Mapped[int] = mapped_column(ForeignKey("ordenes_produccion.id"))
    orden: Mapped["OrdenProduccion"] = relationship(lazy="selectin")

    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    usuario: Mapped["Usuario"] = relationship(foreign_keys=[usuario_id], lazy="selectin")

    # Detectado automaticamente segun la hora de inicio: no se le pide al
    # operario.
    turno_id: Mapped[int] = mapped_column(ForeignKey("turnos.id"))
    turno: Mapped["Turno"] = relationship(lazy="selectin")

    hora_inicio: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    hora_fin: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    sabor_id: Mapped[int] = mapped_column(ForeignKey("sabores.id"))
    sabor: Mapped["Sabor"] = relationship(lazy="selectin")
    cantidad_sabor_kg: Mapped[Decimal] = mapped_column(Numeric(8, 2))

    # Suma automatica de los pesos reales de las canastillas.
    kg_recibidos: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    fecha_creacion: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    eliminado: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    eliminado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    fecha_eliminacion: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    canastillas: Mapped[list["Canastilla"]] = relationship(
        back_populates="registro_saborizado",
        order_by="Canastilla.numero",
        lazy="selectin",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<RegistroSaborizado {self.id} orden={self.orden_id}>"


class Canastilla(Base):
    """
    Peso REAL de una canastilla, tal como la peso el operario. La planta
    tiene un peso aproximado por canastilla (ej: 6 kg), pero aqui nunca se
    guarda un valor asumido.
    """

    __tablename__ = "canastillas"

    id: Mapped[int] = mapped_column(primary_key=True)

    registro_saborizado_id: Mapped[int] = mapped_column(ForeignKey("registro_saborizado.id"))
    registro_saborizado: Mapped["RegistroSaborizado"] = relationship(back_populates="canastillas")

    numero: Mapped[int] = mapped_column(SmallInteger)
    peso_kg: Mapped[Decimal] = mapped_column(Numeric(6, 2))
