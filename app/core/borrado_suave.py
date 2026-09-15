"""
Borrado suave reutilizable.

Convenio del proyecto: las entidades importantes nunca se borran de verdad,
sino que se marcan con `eliminado = True` y guardan quien y cuando lo hizo,
para poder auditar. Cada modelo tiene tres columnas:

  eliminado         bool
  eliminado_por_id  FK a usuarios (quien lo borro)
  fecha_eliminacion timestamp (cuando)

Este modulo centraliza los tres pasos (marcar, registrar quien/cuando,
commit) y el borrado en cascada para no repetirlo en cada servicio.
"""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.errores import ErrorDeValidacion


def marcar_eliminado(db: Session, entidad) -> None:
    """
    Marca una entidad individual como borrada (borrado suave) con su
    auditoria. El commit lo hace el llamador (o este, si va solo).

    `entidad` debe tener las tres columnas del convenio.
    """
    if getattr(entidad, "eliminado", False):
        raise ErrorDeValidacion("Este registro ya fue eliminado.")

    ahora = datetime.now(UTC)
    entidad.eliminado = True
    entidad.fecha_eliminacion = ahora

    # Marcar quien lo borro si la entidad soporta la columna y se sabe quien.
    eliminado_por = getattr(entidad, "eliminado_por_id", None)
    if eliminado_por is None:
        entidad.eliminado_por_id = None


def marcar_eliminado_por(db: Session, entidad, usuario) -> None:
    """
    Igual que `marcar_eliminado` pero registrando quien fue.
    `usuario` debe ser un objeto con `.id`.
    """
    if getattr(entidad, "eliminado", False):
        raise ErrorDeValidacion("Este registro ya fue eliminado.")

    entidad.eliminado = True
    entidad.eliminado_por_id = usuario.id
    entidad.fecha_eliminacion = datetime.now(UTC)


def borrar_en_cascada(db: Session, coleccion, usuario) -> int:
    """
    Marca como eliminados todos los elementos de `coleccion` (una consulta o
    lista de objetos con el convenio de borrado suave) y devuelve cuantos
    se marcaron. No hace commit: el llamador decide cuando.
    """
    arrastrados = 0
    ahora = datetime.now(UTC)

    try:
        elementos = list(coleccion)
    except TypeError:
        # Ya es una lista o iterable
        elementos = list(coleccion)

    for elemento in elementos:
        if getattr(elemento, "eliminado", False):
            continue
        elemento.eliminado = True
        elemento.eliminado_por_id = usuario.id
        elemento.fecha_eliminacion = ahora
        arrastrados += 1

    return arrastrados
