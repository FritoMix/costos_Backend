"""
Logica del catalogo de referencias de papa.

Solo el Administrador y el Bodeguero pueden crear, corregir o eliminar.
Cualquier usuario conectado puede consultarlas porque el operario de horno
necesita elegir una al registrar la tanda.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errores import ErrorDeValidacion, RecursoNoEncontrado
from app.modules.bodega.models import ReferenciaPapa
from app.modules.bodega.schemas import ReferenciaPapaGuardar


def listar(db: Session, solo_activas: bool = False) -> list[ReferenciaPapa]:
    consulta = select(ReferenciaPapa).order_by(func.lower(ReferenciaPapa.nombre))
    if solo_activas:
        consulta = consulta.where(ReferenciaPapa.activo.is_(True))
    return list(db.scalars(consulta).all())


def obtener(db: Session, referencia_id: int) -> ReferenciaPapa:
    referencia = db.get(ReferenciaPapa, referencia_id)
    if referencia is None:
        raise RecursoNoEncontrado("Esa referencia de papa no existe.")
    return referencia


def _nombre_libre(db: Session, nombre: str, excluir_id: int | None) -> None:
    consulta = select(ReferenciaPapa.id).where(
        func.lower(ReferenciaPapa.nombre) == nombre.lower()
    )
    if excluir_id is not None:
        consulta = consulta.where(ReferenciaPapa.id != excluir_id)
    if db.scalar(consulta) is not None:
        raise ErrorDeValidacion(f'Ya existe una referencia de papa llamada "{nombre}".')


def _nombre_limpio(nombre: str) -> str:
    limpio = nombre.strip()
    if not limpio:
        raise ErrorDeValidacion("El nombre de la referencia de papa no puede estar vacío.")
    return limpio


def crear(db: Session, datos: ReferenciaPapaGuardar) -> ReferenciaPapa:
    nombre = _nombre_limpio(datos.nombre)
    _nombre_libre(db, nombre, None)
    referencia = ReferenciaPapa(
        nombre=nombre,
        peso_promedio_bulto_kg=datos.peso_promedio_bulto_kg,
        activo=datos.activo,
    )
    db.add(referencia)
    db.commit()
    db.refresh(referencia)
    return referencia


def actualizar(
    db: Session, referencia_id: int, datos: ReferenciaPapaGuardar
) -> ReferenciaPapa:
    referencia = obtener(db, referencia_id)
    nombre = _nombre_limpio(datos.nombre)
    _nombre_libre(db, nombre, referencia_id)
    referencia.nombre = nombre
    referencia.peso_promedio_bulto_kg = datos.peso_promedio_bulto_kg
    referencia.activo = datos.activo
    db.commit()
    db.refresh(referencia)
    return referencia


def eliminar(db: Session, referencia_id: int) -> None:
    from app.modules.produccion.models import RegistroHorno

    referencia = obtener(db, referencia_id)
    usada = db.scalar(
        select(RegistroHorno.id)
        .where(RegistroHorno.referencia_papa_id == referencia_id)
        .limit(1)
    )
    if usada is not None:
        raise ErrorDeValidacion(
            f'No se puede eliminar "{referencia.nombre}": ya tiene tandas de horno '
            "registradas. Puedes desactivarla en su lugar."
        )
    db.delete(referencia)
    db.commit()
