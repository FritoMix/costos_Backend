"""Consecutivo diario PostgreSQL, dentro de la transacción de la operación llamadora."""

from datetime import date

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.modules.produccion.models import SecuenciaOrden


def generar_numero_orden(db: Session, fecha: date) -> str:
    """
    Siguiente numero del dia. Se usa una operacion atomica de PostgreSQL
    (INSERT ... ON CONFLICT DO UPDATE): si dos supervisores crean una orden
    en el mismo instante, cada uno recibe un numero distinto.
    """
    tabla = SecuenciaOrden.__table__
    sentencia = (
        insert(tabla)
        .values(fecha=fecha, ultimo_numero=1)
        .on_conflict_do_update(
            index_elements=[tabla.c.fecha],
            set_={"ultimo_numero": tabla.c.ultimo_numero + 1},
        )
        .returning(tabla.c.ultimo_numero)
    )
    consecutivo = db.execute(sentencia).scalar_one()
    return f"OP-{fecha:%Y%m%d}-{consecutivo:04d}"


