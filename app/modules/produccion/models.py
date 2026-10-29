"""
Modulo Produccion - tablas: ordenes de produccion, su consecutivo diario,
registro de horno (con desperdicios) y registro de saborizado (con las
canastillas pesadas una por una).
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
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
from app.modules.bodega.models import ReferenciaPapa  # noqa: F401  (relacion)
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


class EstadoFormula:
    """Estado de la formula, independiente del estado de la orden."""

    SIN_FORMULA = "sin_formula"
    LISTA = "lista"
    EN_PRODUCCION = "en_produccion"
    FINALIZADA = "finalizada"
    CANCELADA = "cancelada"
    NO_APLICA = "no_aplica"


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

    # Formula de produccion definida por Bodega. Las ordenes nuevas exigen
    # formula; las historicas (creadas antes de V10) no.
    formula_obligatoria: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )
    formula_notas: Mapped[str | None] = mapped_column(Text, nullable=True)
    formula_actualizada_por_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id"), nullable=True
    )
    formula_actualizada_por: Mapped[Usuario | None] = relationship(
        foreign_keys=[formula_actualizada_por_id], lazy="selectin"
    )
    formula_fecha_actualizacion: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    referencias: Mapped[list["OrdenReferencia"]] = relationship(
        back_populates="orden",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="OrdenReferencia.id",
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
    def formula_estado(self) -> str:
        """
        Estado de la FORMULA, no de la orden.

        Sin filas: no_aplica para historicas y sin_formula para las nuevas.
        Con filas: lista mientras la orden esta Pendiente y, despues, el
        estado de la orden (en_produccion, finalizada o cancelada).
        """
        if not self.referencias:
            return (
                EstadoFormula.NO_APLICA
                if not self.formula_obligatoria
                else EstadoFormula.SIN_FORMULA
            )
        if self.estado == EstadoOrden.PENDIENTE:
            return EstadoFormula.LISTA
        return self.estado

    @property
    def destino_etiqueta(self) -> str:
        return DESTINO_ETIQUETAS.get(self.destino, self.destino)

    def __repr__(self) -> str:
        return f"<OrdenProduccion {self.numero_orden}>"


class OrdenReferencia(Base):
    """
    Fila de la formula de una orden: cuantos bultos de esta referencia van
    en cada tanda. La misma mezcla se repite en todas las tandas de la orden.

    Peso, rendimiento y porcentaje se congelan al guardar la formula. Si
    Bodega corrige el catalogo despues, la formula y las tandas ya creadas
    conservan los valores con los que se planificaron.
    """

    __tablename__ = "orden_referencias"
    __table_args__ = (
        CheckConstraint("bultos_por_tanda > 0", name="ck_orden_ref_bultos_tanda"),
        CheckConstraint("bultos_planificados > 0", name="ck_orden_ref_bultos_planificados"),
        CheckConstraint(
            "porcentaje_produccion_pct > 0 AND porcentaje_produccion_pct <= 100",
            name="ck_orden_ref_pct",
        ),
        CheckConstraint("peso_promedio_bulto_kg > 0", name="ck_orden_ref_peso"),
        CheckConstraint(
            "rendimiento_fritura_pct > 0 AND rendimiento_fritura_pct <= 100",
            name="ck_orden_ref_rendimiento",
        ),
        CheckConstraint(
            "kg_crudos_por_tanda >= 0 AND kg_crudos_planificados >= 0",
            name="ck_orden_ref_kg_crudos",
        ),
        CheckConstraint(
            "kg_fritos_por_tanda >= 0 AND kg_fritos_estimados >= 0",
            name="ck_orden_ref_kg_fritos",
        ),
        Index("ix_orden_referencias_orden", "orden_id"),
        Index("ix_orden_referencias_referencia", "referencia_papa_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    orden_id: Mapped[int] = mapped_column(
        ForeignKey("ordenes_produccion.id", ondelete="CASCADE")
    )
    orden: Mapped["OrdenProduccion"] = relationship(back_populates="referencias")

    referencia_papa_id: Mapped[int] = mapped_column(ForeignKey("referencias_papa.id"))
    referencia_papa: Mapped[ReferenciaPapa] = relationship(lazy="selectin")

    bultos_por_tanda: Mapped[int] = mapped_column(Integer)
    bultos_planificados: Mapped[int] = mapped_column(Integer)
    porcentaje_produccion_pct: Mapped[Decimal] = mapped_column(Numeric(7, 4))
    peso_promedio_bulto_kg: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    rendimiento_fritura_pct: Mapped[Decimal] = mapped_column(Numeric(7, 4))
    kg_crudos_por_tanda: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    kg_fritos_por_tanda: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    kg_crudos_planificados: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    kg_fritos_estimados: Mapped[Decimal] = mapped_column(Numeric(12, 2))

    creado_por_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    creado_por: Mapped["Usuario"] = relationship(foreign_keys=[creado_por_id], lazy="selectin")
    fecha_creacion: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return (
            f"<OrdenReferencia orden={self.orden_id} "
            f"referencia={self.referencia_papa_id} bultos={self.bultos_por_tanda}>"
        )


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

    # Referencia de papa elegida por el operario. Puede quedar NULL solo en
    # registros historicos creados antes de existir el catalogo de bodega.
    referencia_papa_id: Mapped[int | None] = mapped_column(
        ForeignKey("referencias_papa.id"), nullable=True
    )
    referencia_papa: Mapped[ReferenciaPapa | None] = relationship(lazy="selectin")

    cantidad_bultos: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    # Copias congeladas de los parametros de la referencia al crear la tanda.
    # Si bodega corrige la referencia despues, el historico no cambia.
    # En tandas multi-referencia estas columnas del padre quedan NULL: el
    # detalle vive en registro_horno_referencias.
    peso_estandar_bulto_kg: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 2), nullable=True
    )
    rendimiento_fritura_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(7, 4), nullable=True
    )
    porcentaje_produccion_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(7, 4), nullable=True
    )
    kg_crudos_calculados: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    kg_fritos_estimados: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )

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

    referencias: Mapped[list["RegistroHornoReferencia"]] = relationship(
        back_populates="registro_horno",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="RegistroHornoReferencia.id",
    )

    desperdicios: Mapped[list["Desperdicio"]] = relationship(
        back_populates="registro_horno", lazy="selectin", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<RegistroHorno {self.id} orden={self.orden_id}>"


class RegistroHornoReferencia(Base):
    """Detalle por referencia de una tanda. La cabecera guarda la suma."""

    __tablename__ = "registro_horno_referencias"
    __table_args__ = (
        CheckConstraint("cantidad_bultos > 0", name="ck_registro_ref_bultos"),
        CheckConstraint("peso_estandar_bulto_kg > 0", name="ck_registro_ref_peso"),
        CheckConstraint(
            "rendimiento_fritura_pct IS NULL OR "
            "(rendimiento_fritura_pct > 0 AND rendimiento_fritura_pct <= 100)",
            name="ck_registro_ref_rendimiento",
        ),
        CheckConstraint(
            "porcentaje_produccion_pct IS NULL OR "
            "(porcentaje_produccion_pct >= 0 AND porcentaje_produccion_pct <= 100)",
            name="ck_registro_ref_participacion",
        ),
        CheckConstraint("kg_crudos_calculados >= 0", name="ck_registro_ref_kg_crudos"),
        CheckConstraint(
            "kg_fritos_estimados IS NULL OR kg_fritos_estimados >= 0",
            name="ck_registro_ref_kg_fritos",
        ),
        Index("ix_registro_ref_registro", "registro_horno_id"),
        Index("ix_registro_ref_referencia", "referencia_papa_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    registro_horno_id: Mapped[int] = mapped_column(
        ForeignKey("registro_horno.id", ondelete="CASCADE")
    )
    registro_horno: Mapped["RegistroHorno"] = relationship(back_populates="referencias")

    referencia_papa_id: Mapped[int] = mapped_column(ForeignKey("referencias_papa.id"))
    referencia_papa: Mapped[ReferenciaPapa] = relationship(lazy="selectin")

    cantidad_bultos: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    peso_estandar_bulto_kg: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    rendimiento_fritura_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(7, 4), nullable=True
    )
    porcentaje_produccion_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(7, 4), nullable=True
    )
    kg_crudos_calculados: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    kg_fritos_estimados: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )

    @property
    def nombre(self) -> str:
        return self.referencia_papa.nombre

    def __repr__(self) -> str:
        return (
            f"<RegistroHornoReferencia registro={self.registro_horno_id} "
            f"referencia={self.referencia_papa_id} bultos={self.cantidad_bultos}>"
        )


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
